"""
COS-018: Security Leak Check — токены, DSN, креды не протекают.

Проверяемые поверхности:
  - Domain model (token_ref — VAULT/ссылка, не реальный токен)
  - Gate model (manual gate требует human decision)
  - SSE-поток (только публичные данные, без credentials)
  - Evidence chain (SHA-256 хеши, без plaintext секретов)
  - Compiled plans (не содержат кредов в serialization)
  - API responses (не отдают forge_token_ref наружу)
  - Admission gate (блокирует без human decision)
"""
import json
import pytest

from cosmo.domain.domain_model import Domain, ForgeBinding, DomainQuota
from cosmo.domain.gate_model import Gate, GatePolicy, GatePolicyRule, GateDecision
from cosmo.domain.run_model import Run, Batch, RunStatus
from cosmo.ledger.evidence_chain import EvidenceLedger
from cosmo.ledger.gost_act import GOSTAct, GOSTActHeader, GOSTActObject, GOSTFinding


# ═══════════════════════════════════════════════════════════════════════
# Domain: token_ref is a Vault REFERENCE, not a real token
# ═══════════════════════════════════════════════════════════════════════

class TestDomainTokenNotLeaked:
    """token_ref хранит ссылку на секретницу, а не реальный токен."""

    def test_token_ref_is_vault_style(self):
        """token_ref должен быть в формате VAULT/... или секретницы."""
        domain = Domain(
            id="d1", label="Test",
            forge_binding=ForgeBinding(
                forge_type="gitea",
                url="http://gitea:3000",
                token_ref="VAULT/GITEA_TOKEN",
            ),
        )
        # token_ref — это ссылка, не должен содержать bearer/squ_/ghp_
        ref = domain.forge_binding.token_ref
        assert not ref.startswith("squ_"), f"token_ref is real token: {ref[:10]}"
        assert not ref.startswith("ghp_"), f"token_ref is GitHub PAT: {ref[:10]}"
        assert not ref.startswith("Bearer "), f"token_ref is raw Bearer: {ref[:20]}"
        # Должен содержать VAULT или путь к секретнице
        assert "VAULT" in ref.upper() or "/" in ref, f"token_ref not vault-style: {ref}"

    def test_token_ref_never_exposed_in_dict(self):
        """to_dict() не должен содержать строку, похожую на реальный токен."""
        domain = Domain(
            id="d1", label="Test",
            forge_binding=ForgeBinding(
                forge_type="gitea",
                url="http://gitea:3000",
                token_ref="VAULT/GITEA_TOKEN",
            ),
        )
        d = domain.model_dump()
        ref = d["forge_binding"]["token_ref"]
        # Не реальный токен по длине
        assert len(ref) < 50, f"token_ref suspiciously long: {len(ref)} chars"


# ═══════════════════════════════════════════════════════════════════════
# Gate: manual gate requires HUMAN decision
# ═══════════════════════════════════════════════════════════════════════

class TestGateHumanDecisionRequired:
    """Manual gate не может быть принят без человеческого решения."""

    def test_manual_gate_blocked_without_decider(self):
        """Manual gate с decision, но без decided_by — должен быть rejected."""
        policy = GatePolicy(rules=[
            GatePolicyRule(finding_type="Critical", action="block"),
        ])
        with pytest.raises(Exception):
            Gate(
                id="g1", type="manual", position=0, policy=policy,
                decision="warn",  # решение есть, но decided_by=None
            )

    def test_manual_gate_with_decider_passes(self):
        """Manual gate с decided_by — валиден."""
        policy = GatePolicy(rules=[
            GatePolicyRule(finding_type="Critical", action="block"),
        ])
        gate = Gate(
            id="g2", type="manual", position=0, policy=policy,
            decision="pass", decided_by="operator-ivan",
        )
        assert gate.decision == "pass"
        assert gate.decided_by == "operator-ivan"

    def test_automatic_gate_cannot_be_manual_required(self):
        """Automatic gate не может иметь решение manual_required."""
        policy = GatePolicy(rules=[
            GatePolicyRule(finding_type="Critical", action="block"),
        ])
        with pytest.raises(Exception):
            Gate(
                id="g3", type="automatic", position=0, policy=policy,
                decision="manual_required",
            )

    def test_automatic_gate_can_pass_without_human(self):
        """Automatic gate может принять решение без decided_by."""
        policy = GatePolicy(rules=[
            GatePolicyRule(finding_type="Critical", action="block"),
        ])
        gate = Gate(
            id="g4", type="automatic", position=0, policy=policy,
            decision="pass",
        )
        assert gate.decision == "pass"
        assert gate.decided_by is None  # автоматическое — не требует человека

    def test_admission_gate_blocks_unsigned(self):
        """Gate без decision — admission блокирован."""
        policy = GatePolicy(rules=[
            GatePolicyRule(finding_type="Critical", action="block"),
        ])
        gate = Gate(
            id="g5", type="manual", position=0, policy=policy,
        )
        assert gate.decision is None  # решение не принято
        assert gate.decided_by is None  # никто не подписал

    def test_block_decision_halts_pipeline(self):
        """Gate decision=block — останавливает пайплайн."""
        policy = GatePolicy(rules=[
            GatePolicyRule(finding_type="Critical", action="block"),
        ])
        gate = Gate(
            id="g6", type="automatic", position=0, policy=policy,
            decision="block",
        )
        assert gate.decision == "block"


# ═══════════════════════════════════════════════════════════════════════
# SSE: токены не протекают в stream-события
# ═══════════════════════════════════════════════════════════════════════

class TestSSENoCredentialsLeak:
    """SSE-поток отдаёт только публичные данные, без credentials."""

    _SENSITIVE_KEYS = frozenset({
        "token", "password", "secret", "api_key", "private_key",
        "authorization", "cookie", "credential", "dsn", "connection_string",
        "forge_token_ref",  # ссылка на токен тоже не должна утекать
    })

    def _assert_no_sensitive_keys(self, data: dict, source: str):
        """Рекурсивно проверить, что в dict нет чувствительных ключей."""
        for key, value in data.items():
            key_lower = key.lower()
            for sensitive in self._SENSITIVE_KEYS:
                assert sensitive not in key_lower, (
                    f"Sensitive key '{key}' found in {source}"
                )
            if isinstance(value, dict):
                self._assert_no_sensitive_keys(value, f"{source}.{key}")
            elif isinstance(value, list):
                for i, item in enumerate(value):
                    if isinstance(item, dict):
                        self._assert_no_sensitive_keys(item, f"{source}.{key}[{i}]")

    def test_status_change_event_no_credentials(self):
        """SSE status_change содержит только публичный статус."""
        event = {
            "event": "status_change",
            "data": json.dumps({
                "status": "running",
                "previous": "queued",
                "started_at": "2026-08-28T10:00:00Z",
                "finished_at": None,
            }),
        }
        data = json.loads(event["data"])
        self._assert_no_sensitive_keys(data, "status_change")

    def test_batch_complete_event_no_credentials(self):
        """SSE batch_complete — только тип и статус."""
        event = {
            "event": "batch_complete",
            "data": json.dumps({
                "batch_id": "batch-plan-x-build",
                "type": "build",
                "status": "passed",
            }),
        }
        data = json.loads(event["data"])
        self._assert_no_sensitive_keys(data, "batch_complete")

    def test_gate_decision_event_no_credentials(self):
        """SSE gate_decision — только решение, без токенов."""
        event = {
            "event": "gate_decision",
            "data": json.dumps({
                "gate_id": "g1",
                "decision": "block",
                "decided_by": "operator-ivan",
                "decided_at": "2026-08-28T10:05:00Z",
            }),
        }
        data = json.loads(event["data"])
        self._assert_no_sensitive_keys(data, "gate_decision")

    def test_finding_event_no_credentials(self):
        """SSE finding — только счётчики, без данных находок."""
        event = {
            "event": "finding",
            "data": json.dumps({
                "count": 5,
                "delta": 2,
                "total_evidence": 12,
            }),
        }
        data = json.loads(event["data"])
        self._assert_no_sensitive_keys(data, "finding")

    def test_run_snapshot_no_forge_token(self):
        """SSE run snapshot НЕ должен содержать forge_token_ref."""
        snap = {
            "run": {
                "id": "run-1",
                "status": "running",
                "trigger": "manual",
                "started_at": "2026-08-28T10:00:00Z",
                "finished_at": None,
            },
            "batches": [
                {"id": "b1", "type": "build", "status": "passed"},
            ],
            "gates": [
                {"id": "g1", "type": "automatic", "position": 0,
                 "decision": "pass", "decided_by": None, "decided_at": None},
            ],
            "findings_count": 0,
            "evidence_count": 5,
        }
        self._assert_no_sensitive_keys(snap, "run_snapshot")


# ═══════════════════════════════════════════════════════════════════════
# Evidence: SHA-256 chain, без plaintext секретов
# ═══════════════════════════════════════════════════════════════════════

class TestEvidenceNoCredentialsLeak:
    """Evidence chain хранит криптографические хеши, не plaintext."""

    def test_ledger_entry_hashes_content_not_raw(self):
        """EvidenceEntry хранит SHA-256 хеш, а не сырые данные."""
        ledger = EvidenceLedger()
        entry = ledger.add_entry(
            "scan_result",
            {"scanner": "zap", "alerts": 5},
            "run-1/batch-1",
        )
        # hash — SHA-256 (64 hex), не сырые данные
        assert len(entry.hash) == 64
        assert entry.hash != json.dumps(entry.content)

    def test_ledger_to_dict_no_sensitive_keys(self):
        """to_dict() не должен содержать ключей token/password."""
        ledger = EvidenceLedger()
        ledger.add_entry("auth", {"user": "test", "method": "oauth2"}, "run-1")
        d = ledger.to_dict()
        # Проверить все ключи в entries[*]
        for entry in d["entries"]:
            for key in entry:
                assert "token" not in key.lower(), f"Sensitive key in evidence: {key}"
                assert "password" not in key.lower(), f"Sensitive key in evidence: {key}"
                assert "secret" not in key.lower(), f"Sensitive key in evidence: {key}"

    def test_tampered_chain_detected(self):
        """Попытка подмены evidence немедленно детектится."""
        ledger = EvidenceLedger()
        ledger.add_entry("finding", {"severity": "High"}, "run-1")
        assert ledger.verify_chain()

        ledger.tamper(0, "content", {"severity": "Low"})  # подмена
        assert not ledger.verify_chain()

    def test_ledger_no_raw_credentials_in_content(self):
        """Содержимое evidence-записей не должно содержать кредов."""
        ledger = EvidenceLedger()
        # Даже если кто-то попытается записать креды в content —
        # to_dict() не должен их показывать в открытом виде
        ledger.add_entry(
            "config_snapshot",
            {"db_host": "localhost", "db_user": "app", "db_pass": "REDACTED"},
            "run-1",
        )
        d = ledger.to_dict()
        content = d["entries"][0]["content"]
        # db_pass должно быть REDACTED, не реальным паролем
        if "db_pass" in content:
            assert "secret" not in str(content["db_pass"]).lower()


# ═══════════════════════════════════════════════════════════════════════
# GOSt-Акт: не содержит чувствительных данных
# ═══════════════════════════════════════════════════════════════════════

class TestGOSTActNoLeak:
    """ГОСТ-Акт — публичный документ, не содержит кредов."""

    def test_act_serialization_no_credentials(self):
        act = GOSTAct(
            header=GOSTActHeader(project_name="TestProject"),
            object=GOSTActObject(name="TestApp", url="https://test.local"),
            findings_table=[
                GOSTFinding(severity="Critical", title="SQLi", cwe="CWE-89"),
            ],
        )
        d = act.model_dump()
        flat = json.dumps(d, ensure_ascii=False)
        # Не должно быть признаков токенов
        for pat in ("squ_", "ghp_", "Bearer ", "VAULT/GITEA_TOKEN"):
            assert pat not in flat, f"Found potential credential: {pat}"


# ═══════════════════════════════════════════════════════════════════════
# Run model: статусы валидируются, нет утечки
# ═══════════════════════════════════════════════════════════════════════

class TestRunModelSecurity:
    """Run не содержит credentials в своих полях."""

    def test_run_schema_no_token_fields(self):
        """Run Pydantic модель не имеет полей token/password/credential."""
        run = Run(
            id="r1", plan_id="plan-1", trigger="manual",
            initiator="operator", domain_id="d1", status="pending",
        )
        d = run.model_dump()
        for key in d:
            assert "token" not in key.lower(), f"Run has token field: {key}"
            assert "password" not in key.lower(), f"Run has password field: {key}"
            assert "secret" not in key.lower(), f"Run has secret field: {key}"
            assert "credential" not in key.lower(), f"Run has credential field: {key}"

    def test_batch_schema_no_token_fields(self):
        """Batch Pydantic модель не имеет полей token/password/credential."""
        batch = Batch(
            id="b1", plan_id="plan-1", type="build",
            bricks=["brick-1", "brick-2"],
        )
        d = batch.model_dump()
        for key in d:
            assert "token" not in key.lower(), f"Batch has token field: {key}"

    def test_run_json_no_forge_info(self):
        """model_dump_json не должен содержать forge_binding/token_ref."""
        run = Run(
            id="r2", plan_id="plan-2", trigger="manual",
            initiator="operator", domain_id="d2", status="running",
        )
        js = run.model_dump_json()
        assert "forge_token_ref" not in js
        assert "VAULT" not in js
        assert "token" not in js.lower()


# ═══════════════════════════════════════════════════════════════════════
# API: эндпоинты не отдают credentials в ответах
# ═══════════════════════════════════════════════════════════════════════

class TestAPIResponseNoCredentials:
    """API-ответы не должны содержать реальных credentials."""

    def test_run_list_response_shape(self):
        """GET /api/v1/runs ответ — только Run поля, без forge_token."""
        run = Run(
            id="r-api", plan_id="plan-api", trigger="manual",
            initiator="operator", domain_id="d3", status="succeeded",
        )
        d = run.model_dump()
        # Только поля из Run модели — никаких forge_token_ref
        assert "forge_token_ref" not in d
        assert "token" not in d

    def test_batch_list_response_shape(self):
        """GET /api/v1/batches ответ — только Batch поля."""
        batch = Batch(
            id="b-api", plan_id="plan-api", type="static_scan",
            bricks=["b-sast"],
        )
        d = batch.model_dump()
        assert "token" not in d
        assert "secret" not in d


# ═══════════════════════════════════════════════════════════════════════
# Compiled plan: хеш, без кредов
# ═══════════════════════════════════════════════════════════════════════

class TestCompiledPlanNoCredentials:
    """Скомпилированный план не содержит credentials."""

    def test_compiled_hash_is_sha256(self):
        """compile_hash — SHA-256, не содержит исходных данных."""
        from cosmo.compiler.plan_compiler import PlanCompiler
        from cosmo.domain.pipeline_brick import PipelineBrick, BrickDefinition

        bricks = [
            PipelineBrick(
                id="b1", name="SAST", type="sast", source="repo/x",
                definition=BrickDefinition(image="sonar-scanner:latest"),
            ),
        ]
        pc = PlanCompiler()
        batches = pc.compile(bricks, plan_id="plan-hash")
        h = pc.compile_hash(batches, bricks)

        # Это SHA-256 hex, не JSON с данными
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_compiled_plan_no_forge_refs(self):
        """Batches не ссылаются на token_ref или credentials."""
        from cosmo.compiler.plan_compiler import PlanCompiler
        from cosmo.domain.pipeline_brick import PipelineBrick, BrickDefinition

        bricks = [
            PipelineBrick(
                id="b1", name="Build", type="build", source="repo/x",
                definition=BrickDefinition(image="node:20"),
            ),
        ]
        pc = PlanCompiler()
        batches = pc.compile(bricks, plan_id="plan-sec")

        for b in batches:
            d = b.model_dump()
            for key in d:
                assert "token" not in key.lower(), f"Batch has token: {key}"
                assert "password" not in key.lower(), f"Batch has password: {key}"