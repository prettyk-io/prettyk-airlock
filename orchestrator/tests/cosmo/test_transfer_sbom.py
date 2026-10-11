# -*- coding: utf-8 -*-
"""COS-099: SBOM & vulnerability report in release bundle.

Покрывает:
  1. Генерация SBOM: syft wrapper (инъекция runner'а) + internal fallback
     parser (requirements/pyproject/package.json, prune node_modules).
  2. Grype vulnerability report: offline env (GRYPE_DB_AUTO_UPDATE=false),
     честный source="none" при отсутствии инструмента.
  3. Digest pinning: manifest.security.{sbom,vulnerability_report}.sha256,
     покрыт PackageRevision checksum; tamper-отклонение.
  4. PreTransferValidator: modified SBOM bytes → CHECKSUM_MISMATCH;
     missing payload; ref-not-in-payload; envelope cross-check (COS-126).
  5. LandingStateMachine.receive_and_verify: modified SBOM →
     CHECKSUM_MISMATCH (requires new revision), success → VERIFIED.
  6. Airgap roundtrip: seal_envelope + AirgapReleaseBundle export/import —
     tampered SBOM bytes отвергаются bundle-верификацией.

100% offline: ни один путь не делает сетевых вызовов; syft/grype —
инъекция fake-runner'ов (на стенде бинарников нет → fallback/none).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_repo = Path(__file__).resolve().parents[3]
_orch = Path(__file__).resolve().parents[2]
for p in (str(_repo), str(_orch)):
    if p not in sys.path:
        sys.path.insert(0, p)

from orchestrator.cosmo.transfer.builder import PackageBuilder, PreTransferValidator  # noqa: E402
from orchestrator.cosmo.transfer.contract import (  # noqa: E402
    ArtifactPlane,
    PackageMode,
    TransferFailureClass,
)
from orchestrator.cosmo.transfer.landing import (  # noqa: E402
    LandingState,
    LandingStateError,
    LandingStateMachine,
)
from orchestrator.cosmo.transfer.sbom import (  # noqa: E402
    canonical_json_bytes,
    envelope_artifacts_from_security,
    generate_sbom,
    generate_vuln_report,
    build_secured_package,
    extract_security,
)
from orchestrator.cosmo.ledger.release_envelope import (  # noqa: E402
    export_airgap_bundle,
    import_and_verify_airgap_bundle,
    seal_envelope,
)

SBOM_REF = "sbom/cdx.json"
VULN_REF = "sbom/grype.json"


# ── Fixtures / fakes ──


@pytest.fixture()
def repo_dir(tmp_path: Path) -> Path:
    """Мини-репо с тремя экосистемами + шум (node_modules — prune)."""
    (tmp_path / "requirements.txt").write_text(
        "flask==2.3.0\nrequests>=2.31.0\n# comment\n-r other.txt\n",
        encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\ndependencies = ["uvicorn>=0.29.0", "pydantic"]\n'
        '[tool.poetry.dependencies]\npython = "^3.12"\nhttpx = "^0.27.0"\n',
        encoding="utf-8")
    (tmp_path / "package.json").write_text(json.dumps({
        "name": "app", "version": "1.0.0",
        "dependencies": {"left-pad": "^1.3.0"},
        "devDependencies": {"vitest": "1.2.3"},
    }), encoding="utf-8")
    nm = tmp_path / "node_modules" / "junk"
    nm.mkdir(parents=True)
    (nm / "package.json").write_text(
        json.dumps({"dependencies": {"evil": "9.9.9"}}), encoding="utf-8")
    return tmp_path


class _FakeProc:
    def __init__(self, stdout: str = "", stderr: str = "", returncode: int = 0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def _syft_runner(components: list[dict], calls: list):
    """Fake syft: возвращает валидный CycloneDX на stdout, пишет вызовы."""
    doc = {
        "bomFormat": "CycloneDX", "specVersion": "1.5",
        "serialNumber": "urn:uuid:syft", "version": 1,
        "metadata": {"component": {"type": "application", "name": "x"}},
        "components": components,
    }

    def _run(cmd, **kwargs):
        calls.append({"cmd": cmd, "kwargs": kwargs})
        return _FakeProc(stdout=json.dumps(doc))

    return _run


# ── 1. Internal fallback parser ──


class TestInternalSBOM:
    def test_cyclonedx_schema_valid(self, repo_dir: Path):
        res = generate_sbom(repo_dir)
        doc = res.document
        assert res.source == "internal"
        assert doc["bomFormat"] == "CycloneDX"
        assert doc["specVersion"] == "1.5"
        assert doc["serialNumber"].startswith("urn:uuid:")
        assert doc["metadata"]["component"]["name"] == repo_dir.name
        assert isinstance(doc["components"], list)
        for c in doc["components"]:
            assert {"type", "name", "version", "purl"} <= set(c)
            assert c["purl"].startswith(("pkg:pypi/", "pkg:npm/"))

    def test_three_ecosystems_collected(self, repo_dir: Path):
        res = generate_sbom(repo_dir)
        purls = {c["purl"] for c in res.document["components"]}
        assert "pkg:pypi/flask@2.3.0" in purls
        assert "pkg:pypi/requests@2.31.0" in purls
        assert "pkg:pypi/httpx@0.27.0" in purls          # poetry table
        assert "pkg:npm/left-pad@1.3.0" in purls
        assert "pkg:npm/vitest@1.2.3" in purls

    def test_node_modules_pruned_and_dedup(self, repo_dir: Path):
        res = generate_sbom(repo_dir)
        names = [c["name"] for c in res.document["components"]]
        assert "evil" not in names                       # prune сработал
        assert len(names) == len(set(names))             # дедуп по (eco, name)

    def test_digest_is_sha256_of_canonical_json(self, repo_dir: Path):
        res = generate_sbom(repo_dir)
        import hashlib
        expected = hashlib.sha256(
            canonical_json_bytes(res.document)).hexdigest()
        assert res.sha256 == expected

    def test_single_manifest_file_target(self, tmp_path: Path):
        f = tmp_path / "requirements.txt"
        f.write_text("gunicorn==21.2.0\n", encoding="utf-8")
        res = generate_sbom(f)
        assert [c["purl"] for c in res.document["components"]] == [
            "pkg:pypi/gunicorn@21.2.0"]

    def test_empty_dir_yields_empty_components(self, tmp_path: Path):
        res = generate_sbom(tmp_path)
        assert res.document["components"] == []


# ── 2. syft wrapper ──


class TestSyftWrapper:
    def test_syft_used_when_runner_provided(self, repo_dir: Path):
        calls: list = []
        runner = _syft_runner([{"type": "library", "name": "syft-found",
                                "version": "1.0", "purl": "pkg:generic/x"}],
                              calls)
        res = generate_sbom(repo_dir, runner=runner)
        assert res.source == "syft"
        assert res.document["components"][0]["name"] == "syft-found"
        assert len(calls) == 1
        cmd = calls[0]["cmd"]
        assert cmd[0] == "syft"
        assert str(repo_dir) in cmd
        assert "cyclonedx-json" in cmd

    def test_syft_failure_falls_back_internal(self, repo_dir: Path):
        def _run(cmd, **kwargs):
            return _FakeProc(returncode=2, stderr="boom: unsupported format")

        res = generate_sbom(repo_dir, runner=_run)
        assert res.source == "internal"
        assert any("syft failed" in w for w in res.warnings)
        # fallback собрал реальные зависимости
        assert any(c["name"] == "flask" for c in res.document["components"])

    def test_syft_oserror_falls_back(self, repo_dir: Path):
        def _run(cmd, **kwargs):
            raise FileNotFoundError("syft.exe not found")

        res = generate_sbom(repo_dir, runner=_run)
        assert res.source == "internal"
        assert any("syft unavailable" in w for w in res.warnings)

    def test_syft_non_cyclonedx_output_falls_back(self, repo_dir: Path):
        def _run(cmd, **kwargs):
            return _FakeProc(stdout=json.dumps({"not": "sbom"}))

        res = generate_sbom(repo_dir, runner=_run)
        assert res.source == "internal"

    def test_no_binary_no_runner_uses_internal(self, repo_dir: Path, monkeypatch):
        monkeypatch.setattr("shutil.which", lambda name: None)
        res = generate_sbom(repo_dir)
        assert res.source == "internal"
        assert any("not found" in w for w in res.warnings)


# ── 3. grype vulnerability report ──


class TestGrypeReport:
    def test_grype_offline_env_enforced(self, repo_dir, tmp_path):
        sbom = generate_sbom(repo_dir)
        captured: list = []

        def _run(cmd, **kwargs):
            captured.append({"cmd": cmd, "kwargs": kwargs})
            return _FakeProc(stdout=json.dumps({"matches": [], "source": {}}))

        res = generate_vuln_report(sbom.document, runner=_run,
                                   db_dir=str(tmp_path / "grypedb"))
        assert res.source == "grype"
        env = captured[0]["kwargs"]["env"]
        assert env["GRYPE_DB_AUTO_UPDATE"] == "false"
        assert env["GRYPE_DB_VALIDATE_AGE"] == "false"
        assert env["GRYPE_DB_CACHE_DIR"] == str(tmp_path / "grypedb")
        assert captured[0]["cmd"][1].startswith("sbom:")

    def test_grype_env_inherits_cache_dir_from_environment(self, repo_dir, monkeypatch):
        """COS-183: без db_dir grype использует GRYPE_DB_CACHE_DIR из окружения
        (в контейнере — ENV образа /var/lib/grype; тут env наследуется как есть)."""
        sbom = generate_sbom(repo_dir)
        monkeypatch.setenv("GRYPE_DB_CACHE_DIR", "/var/lib/grype")
        captured: list = []

        def _run(cmd, **kwargs):
            captured.append({"cmd": cmd, "kwargs": kwargs})
            return _FakeProc(stdout=json.dumps({"matches": []}))

        res = generate_vuln_report(sbom.document, runner=_run)
        assert res.source == "grype"
        env = captured[0]["kwargs"]["env"]
        assert env["GRYPE_DB_CACHE_DIR"] == "/var/lib/grype"
        assert env["GRYPE_DB_AUTO_UPDATE"] == "false"

    def test_grype_missing_is_honest_none(self, repo_dir, monkeypatch):
        sbom = generate_sbom(repo_dir)
        monkeypatch.setattr("shutil.which", lambda name: None)
        res = generate_vuln_report(sbom.document)
        assert res.source == "none"
        assert "not found" in res.reason
        assert res.report["status"] == "unavailable"
        # Честный pin: source=none, без digest
        pin = res.pin()
        assert pin.source == "none" and pin.sha256 == "" and pin.ref == ""

    def test_grype_failure_is_honest_none(self, repo_dir):
        sbom = generate_sbom(repo_dir)

        def _run(cmd, **kwargs):
            return _FakeProc(returncode=1, stderr="no database found at cache")

        res = generate_vuln_report(sbom.document, runner=_run)
        assert res.source == "none"
        assert "no database" in res.reason

    def test_pin_of_successful_scan(self, repo_dir, tmp_path):
        sbom = generate_sbom(repo_dir)

        def _run(cmd, **kwargs):
            return _FakeProc(stdout=json.dumps(
                {"matches": [{"vulnerability": {"id": "CVE-2026-0001"}}]}))

        res = generate_vuln_report(sbom.document, runner=_run)
        pin = res.pin(ref=VULN_REF)
        assert pin.source == "grype"
        assert len(pin.sha256) == 64
        assert pin.ref == VULN_REF


# ── 4. Digest pinning + PreTransferValidator ──


class TestPinningAndValidator:
    def _secured(self, repo_dir):
        item, sbom, vuln = build_secured_package(
            "it-sbom-1", "rel-1", "plan-1", repo_dir,
            source_ref="git::gitea/app@abc", target_ref="diode://zt/inbox")
        payload = canonical_json_bytes(sbom.document)
        return item, sbom, vuln, {SBOM_REF: payload}

    def test_manifest_pins_digest_and_validates(self, repo_dir):
        item, sbom, _v, payload = self._secured(repo_dir)
        sec = extract_security(item.manifest)
        assert sec is not None
        assert sec.sbom.sha256 == sbom.sha256
        assert sec.sbom.ref == SBOM_REF
        assert sec.sbom.source == "internal"
        assert SBOM_REF in item.payload_refs
        result = PreTransferValidator.validate(item)
        assert result.passed, result.error_codes
        assert item.artifact_plane == ArtifactPlane.SBOM
        assert item.package_mode == PackageMode.FULL_PACKAGE

    def test_revision_checksum_covers_security(self, repo_dir):
        """Tamper manifest.security → существующий checksum-контоль ловит."""
        item, _sbom, _v, _p = self._secured(repo_dir)
        original = item.package_revision.manifest_sha256
        item.manifest["security"]["sbom"]["sha256"] = "f" * 64
        recomputed = PackageBuilder.build_manifest  # noqa: F841 — читаемость
        from orchestrator.cosmo.transfer.contract import PackageRevision
        assert PackageRevision.compute_manifest_sha256(
            item.manifest) != original

    def test_modified_sbom_bytes_rejected(self, repo_dir):
        item, _sbom, _v, _p = self._secured(repo_dir)
        result = PreTransferValidator.validate_with_artifacts(
            item, {SBOM_REF: b'{"bomFormat": "CycloneDX", "tampered": true}'})
        assert not result.passed
        assert "SECURITY_PAYLOAD_DIGEST_MISMATCH" in result.error_codes
        issue = next(i for i in result.issues
                     if i.code == "SECURITY_PAYLOAD_DIGEST_MISMATCH")
        assert issue.failure_class == TransferFailureClass.CHECKSUM_MISMATCH

    def test_valid_bytes_pass(self, repo_dir):
        item, sbom, _v, payload = self._secured(repo_dir)
        result = PreTransferValidator.validate_with_artifacts(item, payload)
        assert result.passed, result.error_codes

    def test_missing_payload_rejected(self, repo_dir):
        item, _sbom, _v, _p = self._secured(repo_dir)
        result = PreTransferValidator.validate_with_artifacts(item, {})
        assert "SECURITY_PAYLOAD_MISSING" in result.error_codes

    def test_pinned_ref_must_be_in_payload_refs(self, repo_dir):
        item, sbom, _v, _p = self._secured(repo_dir)
        item.payload_refs = []          # сломали payload без пересборки
        result = PreTransferValidator.validate(item)
        assert not result.passed
        assert "SECURITY_REF_NOT_IN_PAYLOAD" in result.error_codes

    def test_malformed_digest_rejected(self, repo_dir):
        item, _sbom, _v, _p = self._secured(repo_dir)
        item.manifest["security"]["sbom"]["sha256"] = "zz-not-hex"
        result = PreTransferValidator.validate(item)
        assert "SECURITY_DIGEST_MALFORMED" in result.error_codes

    def test_envelope_digest_crosscheck(self, repo_dir):
        """Тройная tamper-evidence: manifest ↔ bytes ↔ envelope artifacts."""
        item, sbom, _v, payload = self._secured(repo_dir)
        sec = extract_security(item.manifest)
        arts = envelope_artifacts_from_security(sec, payload)
        assert len(arts) == 1
        assert arts[0]["artifact_type"] == "sbom"
        assert arts[0]["sha256"] == sbom.sha256

        ok = PreTransferValidator.validate_with_artifacts(
            item, payload, envelope_artifacts=arts)
        assert ok.passed

        bad = PreTransferValidator.validate_with_artifacts(
            item, payload, envelope_artifacts=[])
        assert "SECURITY_ENVELOPE_DIGEST_MISMATCH" in bad.error_codes


# ── 5. Landing: target-side tamper-evidence ──


class TestLandingVerification:
    def _secured(self, repo_dir):
        item, sbom, _v = build_secured_package(
            "it-sbom-2", "rel-2", "plan-2", repo_dir,
            source_ref="git::gitea/app@abc", target_ref="diode://zt/inbox")
        payload = canonical_json_bytes(sbom.document)
        return item, {SBOM_REF: payload}

    def test_success_transitions_to_verified(self, repo_dir):
        item, payload = self._secured(repo_dir)
        sm = LandingStateMachine(item)
        report = sm.receive_and_verify(payload)
        assert report.passed
        assert report.state == LandingState.VERIFIED
        checks = {c["check"]: c["passed"] for c in report.checks}
        assert checks["manifest_checksum"] and checks["sbom_digest"]

    def test_modified_sbom_rejected_at_landing(self, repo_dir):
        item, _payload = self._secured(repo_dir)
        sm = LandingStateMachine(item)
        report = sm.receive_and_verify({SBOM_REF: b"tampered-bytes"})
        assert not report.passed
        assert report.state == LandingState.CHECKSUM_MISMATCH
        assert report.failure_class == TransferFailureClass.CHECKSUM_MISMATCH
        assert sm.requires_new_revision()
        failed = [c["check"] for c in report.checks if not c["passed"]]
        assert "sbom_digest" in failed
        assert "modified SBOM" in " ".join(report.reasons)

    def test_missing_sbom_payload_rejected(self, repo_dir):
        item, _payload = self._secured(repo_dir)
        sm = LandingStateMachine(item)
        report = sm.receive_and_verify({})
        assert not report.passed
        assert "sbom_payload_present" in [
            c["check"] for c in report.checks if not c["passed"]]

    def test_double_receive_raises(self, repo_dir):
        item, payload = self._secured(repo_dir)
        sm = LandingStateMachine(item)
        sm.receive_and_verify(payload)
        with pytest.raises(LandingStateError):
            sm.receive_and_verify(payload)

    def test_manifest_tamper_caught_at_landing(self, repo_dir):
        item, payload = self._secured(repo_dir)
        item.manifest["payload_refs"].append("evil/extra.bin")  # ломает checksum
        sm = LandingStateMachine(item)
        report = sm.receive_and_verify(payload)
        assert not report.passed
        assert "manifest_checksum" in [
            c["check"] for c in report.checks if not c["passed"]]


# ── 6. Envelope / Airgap roundtrip (COS-126 интеграция) ──


class TestAirgapRoundtrip:
    def _bundle(self, repo_dir, grype_runner=None):
        item, sbom, vuln = build_secured_package(
            "it-sbom-3", "rel-3", "plan-3", repo_dir,
            source_ref="git::gitea/app@abc", target_ref="diode://zt/inbox",
            grype_path="grype" if grype_runner else None,
            runner=grype_runner)
        payload = {SBOM_REF: canonical_json_bytes(sbom.document)}
        sec = extract_security(item.manifest)
        if sec.vulnerability_report and sec.vulnerability_report.source == "grype":
            payload[VULN_REF] = canonical_json_bytes(vuln.report)
        arts = envelope_artifacts_from_security(sec, payload)
        envelope = seal_envelope("rel-3", "cosmo", artifacts=arts)
        bundle = export_airgap_bundle(envelope, payload)
        return bundle, envelope, payload

    def test_bundle_import_verifies_intact_sbom(self, repo_dir):
        bundle, _env, _p = self._bundle(repo_dir)
        ok, envelope, errors = import_and_verify_airgap_bundle(bundle)
        assert ok, errors
        assert envelope.release_id == "rel-3"
        assert not errors

    def test_tampered_sbom_rejected_by_bundle(self, repo_dir):
        bundle, envelope, payload = self._bundle(repo_dir)
        # Подменяем SBOM-байты в бандле (signature конверта осталась прежней)
        import io
        import zipfile
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("envelope.json",
                        json.dumps(envelope.to_dict(), ensure_ascii=False))
            for name, data in payload.items():
                if name == SBOM_REF:
                    data = b'{"bomFormat": "CycloneDX", "evil": true}'
                zf.writestr(f"artifacts/{name}", data)
        ok, _env, errors = import_and_verify_airgap_bundle(buf.getvalue())
        assert not ok
        assert any("checksum mismatch" in e for e in errors)


# ── 7. rebuild_with_revision сохраняет security ──


class TestRebuildPreservesSecurity:
    def test_rebuild_keeps_pins_and_recomputes_checksum(self, repo_dir):
        item, sbom, _v = build_secured_package(
            "it-sbom-4", "rel-4", "plan-4", repo_dir,
            source_ref="git::gitea/app@abc", target_ref="diode://zt/inbox")
        old_sec = item.manifest["security"]
        PackageBuilder.rebuild_with_revision(item, 2)
        assert item.package_revision.revision == 2
        assert item.manifest["security"] == old_sec
        from orchestrator.cosmo.transfer.contract import PackageRevision
        assert item.package_revision.manifest_sha256 == \
            PackageRevision.compute_manifest_sha256(item.manifest)
        result = PreTransferValidator.validate(item)
        assert result.passed


# ── 8. Оффлайн-гигиена ──


class TestOfflineHygiene:
    def test_module_has_no_network_imports(self):
        """SBOM-модуль не тянет сетевые библиотеки (airgap-канон)."""
        import orchestrator.cosmo.transfer.sbom as m
        src = Path(m.__file__).read_text(encoding="utf-8")
        for banned in ("urllib.request", "requests.", "httpx", "socket."):
            assert banned not in src, f"network dependency found: {banned}"

    def test_syft_timeout_handled(self, repo_dir):
        def _run(cmd, **kwargs):
            raise subprocess.TimeoutExpired(cmd, 300)

        res = generate_sbom(repo_dir, runner=_run)
        assert res.source == "internal"
        assert any("unavailable" in w for w in res.warnings)
