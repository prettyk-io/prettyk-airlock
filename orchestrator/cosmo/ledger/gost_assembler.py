# -*- coding: utf-8 -*-
"""COS-069: GOST-Act Auto Generation & Report Assembly.

GOSTActAssembler:
  - assemble_act(run_id) → GOSTAct — полная сборка акта из метаданных прогона,
    нормализованных находок, решений гейтов и подписей.
  - generate_html_report(run_id) → str — HTML для печати/просмотра.
  - save_act_to_artifacts(run_id) → ArtifactRef — сохранение JSON + HTML в ArtifactStore.

Заключение: Passed (без блокировок) / Blocked (гейты заблокировали).
Нормативная база: ГОСТ Р 56939, Положение 683-П / 757-П.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from orchestrator.cosmo.ledger.artifact_store import ArtifactRef, ArtifactStore
from orchestrator.cosmo.ledger.gost_act import (
    GOSTAct,
    GOSTActHeader,
    GOSTActObject,
    GOSTFinding,
    GOSTSignature,
)
from orchestrator.cosmo.ledger.gost_renderer import render_gost_act_html

logger = logging.getLogger("cosmoport.gost_assembler")


class GOSTActAssembler:
    """Сборщик ГОСТ-Акта по результатам завершённого прогона."""

    def __init__(
        self,
        db_session_factory: Any | None = None,
        store: ArtifactStore | None = None,
    ) -> None:
        self._db_session_factory = db_session_factory
        self._store = store or ArtifactStore(base_dir="cosmo-artifacts")

    # ── Public API ──

    def assemble_act(
        self,
        run_id: str,
        findings: list[dict[str, Any]] | None = None,
        gate_decisions: dict[str, str] | None = None,
    ) -> GOSTAct:
        """Собрать ГОСТ-Акт по run_id.

        Args:
            run_id: ID прогона.
            findings: опционально — нормализованные находки (dict с severity, title, description, cwe).
            gate_decisions: опционально — {gate_id: decision} из GatePolicyEngine.

        Returns: GOSTAct.
        """
        # Load run metadata
        run_meta = self._load_run_meta(run_id)
        project_name = run_meta.get("project_name") or run_meta.get("plan_id", run_id)
        domain_name = run_meta.get("domain_id", "")
        commit_sha = run_meta.get("commit_sha", "")
        run_status = run_meta.get("status", "completed")

        # Header
        header = GOSTActHeader(
            project_name=project_name,
            act_number=f"ACT-{run_id[-8:].upper()}",
            organization="Центральный Банк РФ",
        )

        # Object
        obj = GOSTActObject(
            name=project_name,
            url=f"https://cosmoport.local/runs/{run_id}",
            domain=domain_name,
        )

        # Findings table
        gost_findings = self._to_gost_findings(findings or [])

        # Signatures from gate decisions
        signatures = self._build_signatures(gate_decisions or {}, run_meta)

        # Verdict
        verdict = self._compute_verdict(run_status, gate_decisions or {})
        recommendation = self._build_recommendation(verdict, len(gost_findings))

        # Add verdict as a synthetic finding row (last row)
        gost_findings.insert(0, GOSTFinding(
            severity="Info",
            title=f"Заключение: {verdict}",
            description=recommendation,
            cwe="",
            evidence_refs=[run_id],
            recommendation=(
                "Нормативная база: ГОСТ Р 56939 (разработка безопасного ПО), "
                "Положение ЦБ РФ 683-П / 757-П (управление операционным риском)"
            ),
        ))

        return GOSTAct(
            header=header,
            object=obj,
            findings_table=gost_findings,
            signatures=signatures,
        )

    def generate_html_report(self, run_id: str, **kwargs: Any) -> str:
        """Сгенерировать HTML-отчёт."""
        act = self.assemble_act(run_id, **kwargs)
        return render_gost_act_html(act)

    def save_act_to_artifacts(
        self,
        run_id: str,
        **kwargs: Any,
    ) -> ArtifactRef:
        """Собрать акт, сгенерировать HTML и JSON, сохранить в ArtifactStore.

        Returns: ArtifactRef для JSON-файла.
        """
        act = self.assemble_act(run_id, **kwargs)

        # JSON
        act_json = act.model_dump(mode="json")
        json_bytes = json.dumps(act_json, ensure_ascii=False, indent=2).encode("utf-8")
        json_sha = hashlib.sha256(json_bytes).hexdigest()

        # HTML
        html_str = render_gost_act_html(act)
        html_bytes = html_str.encode("utf-8")

        # Write both to ArtifactStore
        base = Path(self._store._base) / "gost" / run_id
        base.mkdir(parents=True, exist_ok=True)

        json_path = base / "act.json"
        json_path.write_bytes(json_bytes)

        html_path = base / "act.html"
        html_path.write_bytes(html_bytes)

        return ArtifactRef(
            ref_id=json_sha[:16],
            path=f"gost/{run_id}/act.json",
            content_type="gost-act",
            size_bytes=len(json_bytes),
            sha256=json_sha,
            provenance=f"{run_id}/gost-act",
        )

    # ── Internal ──

    def _load_run_meta(self, run_id: str) -> dict[str, Any]:
        """Загрузить метаданные прогона из PG."""
        if self._db_session_factory is None:
            return {"run_id": run_id, "status": "completed"}

        s = self._db_session_factory()
        try:
            from orchestrator.cosmo.db.models import Run as RunModel
            orm = s.query(RunModel).filter(RunModel.id == run_id).first()
            if orm is None:
                return {"run_id": run_id, "status": "unknown"}
            return {
                "run_id": orm.id,
                "plan_id": orm.plan_id or "",
                "domain_id": orm.domain_id or "",
                "status": orm.status or "completed",
                "created_at": str(orm.created_at) if orm.created_at else "",
                "trigger": orm.trigger or "manual",
            }
        finally:
            s.close()

    @staticmethod
    def _to_gost_findings(raw_findings: list[dict[str, Any]]) -> list[GOSTFinding]:
        """Конвертировать сырые находки в GOSTFinding."""
        result: list[GOSTFinding] = []
        for f in raw_findings:
            sev = f.get("severity", "Medium")
            if sev not in {"Critical", "High", "Medium", "Low", "Info"}:
                sev = "Medium"

            cwe = ""
            cwe_list = f.get("cwe_ids", [])
            if cwe_list:
                cwe = cwe_list[0] if isinstance(cwe_list[0], str) else str(cwe_list[0])

            result.append(GOSTFinding(
                severity=sev,  # type: ignore[arg-type]
                title=f.get("title") or f.get("message") or f.get("rule_name", "Находка"),
                description=f.get("description") or f.get("message", ""),
                cwe=cwe,
                evidence_refs=f.get("evidence_refs", []),
                recommendation=f.get("recommendation") or _default_recommendation(sev),
            ))
        return result

    @staticmethod
    def _build_signatures(
        gate_decisions: dict[str, str],
        run_meta: dict[str, Any],
    ) -> list[GOSTSignature]:
        """Построить подписи на основе решений гейтов."""
        sigs: list[GOSTSignature] = []

        for gate_id, decision in gate_decisions.items():
            if decision in ("pass", "block"):
                sigs.append(GOSTSignature(
                    role=f"Gate {gate_id[-8:]}" if len(gate_id) > 8 else gate_id,
                    name="Система автоматического контроля",
                    date=datetime.now(tz=timezone.utc).isoformat()[:10],
                    status="signed" if decision == "pass" else "unsigned",
                ))

        # Default signature if no gates
        if not sigs:
            sigs.append(GOSTSignature(
                role="Руководитель тестирования",
                name="Cosmoport Control Plane",
                date=datetime.now(tz=timezone.utc).isoformat()[:10],
                status="signed",
            ))

        return sigs

    @staticmethod
    def _compute_verdict(
        run_status: str,
        gate_decisions: dict[str, str],
    ) -> str:
        """Вычислить заключение."""
        if any(d == "block" for d in gate_decisions.values()):
            return "Blocked — имеются критические находки, релиз не допущен"
        if run_status in ("succeeded", "pass", "completed"):
            return "Passed — контроль пройден, релиз допущен к внедрению"
        if run_status in ("blocked", "failed"):
            return "Blocked — прогон завершён с ошибками"
        return "Incomplete — прогон не завершён"

    @staticmethod
    def _build_recommendation(verdict: str, finding_count: int) -> str:
        """Построить рекомендацию."""
        if "Passed" in verdict:
            return (
                f"Всего находок: {finding_count}. "
                "Критических блокировок нет. "
                "Рекомендуется плановая передача в промышленную эксплуатацию."
            )
        if "Blocked" in verdict:
            return (
                f"Всего находок: {finding_count}. "
                "Обнаружены блокирующие находки / гейты. "
                "Требуется устранение до повторного тестирования."
            )
        return f"Всего находок: {finding_count}. Прогон не завершён — требуется повторный запуск."


def _default_recommendation(severity: str) -> str:
    """Стандартная рекомендация по severity."""
    recs = {
        "Critical": "Немедленно устранить. Релиз блокирован до исправления.",
        "High": "Устранить до следующего релиза.",
        "Medium": "Запланировать исправление в ближайшем спринте.",
        "Low": "Исправить при возможности.",
        "Info": "Ознакомиться.",
    }
    return recs.get(severity, "Проверить и принять решение.")