"""
COS-109: Tests for Cross-Zone Digital Envelope Signer (DigitalReleaseEnvelope).

Тестирует:
  1. Запечатывание конверта (seal_envelope) с манифестом, артефактами и ГОСТ-актом.
  2. Валидацию подписи (verify_envelope / verify_envelope_body).
  3. Обнаружение любых модификаций (tamper detection):
     - изменение коммитов, узлов, рёбер, гейтов в манифесте
     - изменение дайджестов артефактов (SBOM, SARIF, binary)
     - изменение вердикта или подписи ГОСТ-акта
     - изменение метаданных (версия, домен, зоны, changelog, signer)
  4. Детерминированность канонического JSON.
  5. Round-trip сериализацию: Envelope -> Dict/JSON -> Envelope -> verify.
  6. Межзонный сценарий трансфера (ЗР -> ЗТ -> ЗПЭ).
  7. API эндпоинты GET /{id}/envelope и POST /envelope/verify.
"""
import copy
import hashlib
import json
import pytest
from cosmo.domain.rbac import PrincipalContext, Role
from cosmo.ledger.release_envelope import (
    DigitalReleaseEnvelope,
    EnvelopeArtifactDigest,
    EnvelopeManifest,
    GOSTActSummary,
    ReleaseEnvelopeService,
    seal_envelope,
    verify_envelope,
    verify_envelope_body,
)


def test_seal_envelope_basic():
    """Базовое запечатывание конверта."""
    env = seal_envelope(
        release_id="rel-101",
        signer="sec_officer_ivanov",
        version="1.2.0",
        domain_id="dom-secops",
        source_zone="zr",
        target_zone="zt",
        run_ids=["run-1", "run-2"],
        changelog="Security fixes and DAST compliance",
    )

    assert env.release_id == "rel-101"
    assert env.version == "1.2.0"
    assert env.domain_id == "dom-secops"
    assert env.source_zone == "zr"
    assert env.target_zone == "zt"
    assert env.sealed_by == "sec_officer_ivanov"
    assert len(env.envelope_signature) == 64  # SHA-256 hex
    assert env.manifest.run_ids == ["run-1", "run-2"]
    assert env.gost_act_summary.verdict == "PASS"
    assert env.verify() is True


def test_verify_envelope_valid():
    """Валидный конверт успешно проходит верификацию."""
    env = seal_envelope(
        release_id="rel-001",
        signer="officer_1",
        version="2.0.0",
        domain_id="dom-1",
        run_ids=["r1"],
        pipeline_hash="abcd1234efgh5678",
    )
    assert verify_envelope(env) is True


def test_tamper_manifest_run_ids():
    """Подделка run_ids ломает подпись конверта."""
    env = seal_envelope(
        release_id="rel-002",
        signer="officer_1",
        run_ids=["run-alpha", "run-beta"],
    )
    assert env.verify() is True

    # Злоумышленник подменил список прогонов
    env.manifest.run_ids.append("run-unverified-backdoor")
    assert env.verify() is False


def test_tamper_manifest_commits():
    """Подделка commit SHA ломает подпись конверта."""
    env = seal_envelope(
        release_id="rel-003",
        signer="officer_1",
        commit_shas={"run-1": "e4d909c290d0fb1ca068ffaddf22cbd0adddef11"},
    )
    assert env.verify() is True

    # Подмена коммита
    env.manifest.commit_shas["run-1"] = "0000000000000000000000000000000000000000"
    assert env.verify() is False


def test_tamper_manifest_pipeline_hash():
    """Подделка pipeline_hash ломает подпись."""
    env = seal_envelope(
        release_id="rel-004",
        signer="officer_1",
        pipeline_hash="hash_orig_12345",
    )
    assert env.verify() is True

    env.manifest.pipeline_hash = "hash_tampered_67890"
    assert env.verify() is False


def test_tamper_manifest_gate_decisions():
    """Подделка решения гейта (fail -> pass) ломает подпись."""
    env = seal_envelope(
        release_id="rel-005",
        signer="officer_1",
        gate_decisions={"gate-dast": "pass", "gate-sast": "pass"},
    )
    assert env.verify() is True

    # Подмена статуса гейта
    env.manifest.gate_decisions["gate-sast"] = "blocked"
    assert env.verify() is False


def test_tamper_artifacts_digest():
    """Подделка хэша бинарника или SARIF отчета ломает подпись."""
    artifacts = [
        {"name": "app.tar.gz", "type": "binary", "sha256": "11112222333344445555666677778888", "size_bytes": 1024000},
        {"name": "report.sarif", "type": "sarif", "sha256": "aaaabbbbccccddddeeeeffff00001111", "size_bytes": 45000},
    ]
    env = seal_envelope(
        release_id="rel-006",
        signer="officer_1",
        artifacts=artifacts,
    )
    assert env.verify() is True
    assert len(env.artifacts_digest) == 2

    # Подделка хэша отчета
    env.artifacts_digest[1].sha256 = "ffffffffffffffffffffffffffffffff"
    assert env.verify() is False


def test_tamper_gost_act_summary():
    """Подделка ГОСТ-вердикта или заключение офицера ИБ ломает подпись."""
    env = seal_envelope(
        release_id="rel-007",
        signer="officer_1",
        gost_verdict="PASS",
        gost_profile="gost_56939_2016",
        gost_conclusion="Соответствует требованиям безопасности",
    )
    assert env.verify() is True

    # Злоумышленник изменил вердикт
    env.gost_act_summary.verdict = "FAIL"
    assert env.verify() is False


def test_tamper_metadata():
    """Подделка метаданных (версия, домен, changelog, signer) ломает подпись."""
    env = seal_envelope(
        release_id="rel-008",
        signer="officer_1",
        version="1.0.0",
        domain_id="dom-kits",
        source_zone="zr",
        target_zone="zt",
        changelog="Initial secure release",
    )
    assert env.verify() is True

    # Изменение версии
    env_copy = copy.deepcopy(env)
    env_copy.version = "1.0.1"
    assert env_copy.verify() is False

    # Изменение целевой зоны (попытка в обход ЗТ сразу в ЗПЭ)
    env_copy2 = copy.deepcopy(env)
    env_copy2.target_zone = "zpe"
    assert env_copy2.verify() is False

    # Изменение подписывающего
    env_copy3 = copy.deepcopy(env)
    env_copy3.sealed_by = "officer_imposter"
    assert env_copy3.verify() is False


def test_canonical_json_determinism():
    """Канонический JSON детерминирован независимо от порядка ключей и элементов."""
    gost = GOSTActSummary(
        profile="gost_56939_2016",
        verdict="PASS",
        conclusion="Audit passed",
        signed_by="officer_1",
        signed_at="2026-08-29T12:00:00Z",
        signature="fixed_sig_123",
    )
    env1 = seal_envelope(
        release_id="rel-009",
        signer="officer_1",
        run_ids=["run-b", "run-a"],
        gate_decisions={"gate-2": "pass", "gate-1": "pass"},
        gost_act_summary=gost,
    )
    # Формируем аналогичный конверт с переставленными элементами
    env2 = seal_envelope(
        release_id="rel-009",
        signer="officer_1",
        run_ids=["run-a", "run-b"],
        gate_decisions={"gate-1": "pass", "gate-2": "pass"},
        gost_act_summary=gost,
    )
    # Синхронизируем sealed_at для сравнения канонического хеша
    env2.sealed_at = env1.sealed_at
    env2.sign("officer_1")

    assert env1.canonical_json() == env2.canonical_json()
    assert env1.envelope_signature == env2.envelope_signature


def test_round_trip_dict_and_json():
    """Сериализация в dict / JSON и восстановление сохраняет валидность."""
    artifacts = [
        EnvelopeArtifactDigest(name="sbom.json", artifact_type="sbom", sha256="abc12345", size_bytes=1200),
    ]
    env = seal_envelope(
        release_id="rel-010",
        signer="officer_security",
        version="3.1.4",
        domain_id="dom-banking",
        source_zone="zt",
        target_zone="zpe",
        run_ids=["run-bank-1"],
        artifacts=artifacts,
        gost_verdict="PASS",
        changelog="Banking appsec audit passed",
    )

    d = env.to_dict()
    assert "envelope_signature" in d
    assert d["envelope_id"] == "rel-010"

    # Десериализация из dict
    restored = DigitalReleaseEnvelope.from_dict(d)
    assert restored.verify() is True
    assert restored.release_id == env.release_id
    assert restored.artifacts_digest[0].name == "sbom.json"

    # Проверка через verify_envelope_body
    assert verify_envelope_body(d) is True

    # JSON round-trip
    json_str = json.dumps(d)
    parsed = json.loads(json_str)
    assert verify_envelope_body(parsed) is True


def test_verify_envelope_body_tampered():
    """verify_envelope_body возвращает False при модификации JSON-тела."""
    env = seal_envelope(
        release_id="rel-011",
        signer="officer_1",
        version="1.0.0",
    )
    d = env.to_dict()
    assert verify_envelope_body(d) is True

    # Подделка поля в словаре
    d["version"] = "9.9.9"
    assert verify_envelope_body(d) is False

    # Поврежденная подпись
    d["version"] = "1.0.0"
    d["envelope_signature"] = "deadbeef" * 8
    assert verify_envelope_body(d) is False


def test_verify_envelope_corrupted_structure():
    """verify_envelope_body безопасно обрабатывает битые структуры без падений."""
    assert verify_envelope_body({}) is False
    assert verify_envelope_body({"release_id": "r1"}) is False
    assert verify_envelope_body({"envelope_signature": "bad"}) is False
    assert verify_envelope_body(None) is False  # type: ignore


def test_cross_zone_transfer_lifecycle():
    """Полный жизненный цикл трансфера: ЗР -> ЗТ -> ЗПЭ с конвертами."""
    # 1. Зона разработки (ЗР): подготовка релиза к переносу на ЗТ
    env_zr_to_zt = seal_envelope(
        release_id="rel-prod-2026",
        signer="dev_lead_petrov",
        version="1.0.0",
        domain_id="dom-core",
        source_zone="zr",
        target_zone="zt",
        run_ids=["run-build-1", "run-unit-1"],
        pipeline_hash="plan_hash_zr_100",
        gost_verdict="PASS",
        changelog="Release ready for test zone verification",
    )
    assert env_zr_to_zt.verify() is True
    assert env_zr_to_zt.source_zone == "zr"
    assert env_zr_to_zt.target_zone == "zt"

    # 2. Передача в Зону Тестирования (ЗТ) и верификация
    envelope_data_zt = env_zr_to_zt.to_dict()
    assert verify_envelope_body(envelope_data_zt) is True

    # 3. В ЗТ пройдены DAST/SAST проверки, запечатывается конверт для ЗПЭ
    env_zt_to_zpe = seal_envelope(
        release_id="rel-prod-2026",
        signer="sec_officer_sidorov",
        version="1.0.0",
        domain_id="dom-core",
        source_zone="zt",
        target_zone="zpe",
        run_ids=["run-build-1", "run-dast-secops", "run-sast-sonar"],
        pipeline_hash="plan_hash_zt_200",
        artifacts=[
            {"name": "security_report.sarif", "type": "sarif", "sha256": "sarif_hash_999", "size_bytes": 105000},
            {"name": "app_container.tar", "type": "image", "sha256": "image_sha256_777", "size_bytes": 500000000},
        ],
        gost_verdict="PASS",
        gost_profile="gost_56939_2016",
        gost_conclusion="Уязвимости критического и высокого уровня отсутствуют. Допуск к ЗПЭ разрешен.",
        approvals_count=2,
        transfer_history_count=1,
    )
    assert env_zt_to_zpe.verify() is True
    assert env_zt_to_zpe.source_zone == "zt"
    assert env_zt_to_zpe.target_zone == "zpe"

    # 4. Приём в Зоне Промышленной Эксплуатации (ЗПЭ)
    envelope_data_zpe = env_zt_to_zpe.to_dict()
    assert verify_envelope_body(envelope_data_zpe) is True
    assert envelope_data_zpe["gost_act_summary"]["verdict"] == "PASS"


def test_envelope_service_facade():
    """ReleaseEnvelopeService методы работают аналогично прямым функциям."""
    env = ReleaseEnvelopeService.seal_envelope(
        release_id="rel-srv-01",
        signer="officer_test",
        version="1.0.0",
    )
    assert ReleaseEnvelopeService.verify_envelope(env) is True
    assert ReleaseEnvelopeService.verify_envelope_body(env.to_dict()) is True


@pytest.mark.asyncio
async def test_api_verify_route_valid():
    """POST /api/v1/releases/envelope/verify возвращает verified=True."""
    from cosmo.api.routes.releases import verify_release_envelope, VerifyEnvelopeResponse

    env = seal_envelope(
        release_id="rel-api-01",
        signer="sec_lead",
        version="1.5.0",
        domain_id="dom-sec",
    )
    body = env.to_dict()

    res = await verify_release_envelope(body)
    assert isinstance(res, VerifyEnvelopeResponse)
    assert res.verified is True
    assert res.release_id == "rel-api-01"
    assert res.error is None


@pytest.mark.asyncio
async def test_api_verify_route_tampered():
    """POST /api/v1/releases/envelope/verify возвращает verified=False при подмене."""
    from cosmo.api.routes.releases import verify_release_envelope, VerifyEnvelopeResponse

    env = seal_envelope(
        release_id="rel-api-02",
        signer="sec_lead",
        version="1.5.0",
    )
    body = env.to_dict()
    body["version"] = "2.0.0"  # tamper

    res = await verify_release_envelope(body)
    assert isinstance(res, VerifyEnvelopeResponse)
    assert res.verified is False
    assert res.error is not None


@pytest.mark.asyncio
async def test_api_get_envelope_route():
    """GET /api/v1/releases/{id}/envelope формирует и запечатывает конверт."""
    from unittest.mock import AsyncMock, MagicMock
    from cosmo.api.routes.releases import get_release_envelope

    mock_db = AsyncMock()
    mock_rel = MagicMock()
    mock_rel.id = "rel-api-03"
    mock_rel.domain_id = "dom-corp"
    mock_rel.plan_id = "plan-1"
    mock_rel.run_ids = ["run-10", "run-20"]
    mock_rel.version = "2.1.0"
    mock_rel.changelog = "Prod release ready"
    mock_rel.status = "approved"
    mock_rel.current_zone = "zr"
    mock_rel.approvals = []
    mock_rel.transfer_history = []
    mock_db.get = AsyncMock(return_value=mock_rel)

    envelope_dict = await get_release_envelope(
        release_id="rel-api-03",
        signer="officer_alex",
        caller_domain="dom-corp",
        # COS-067: хендлер резолвит caller через principal (identity-путь)
        principal=PrincipalContext(
            user_id="unit_officer",
            roles=[Role.ADMIN_SEC],
            domain_id="dom-corp",
            zone="zr",
            is_authenticated=True,
            is_system_admin=False,
        ),
        db=mock_db,
    )

    assert envelope_dict["release_id"] == "rel-api-03"
    assert envelope_dict["version"] == "2.1.0"
    assert envelope_dict["domain_id"] == "dom-corp"
    assert envelope_dict["source_zone"] == "zr"
    assert envelope_dict["target_zone"] == "zt"
    assert envelope_dict["sealed_by"] == "officer_alex"
    assert len(envelope_dict["envelope_signature"]) == 64

    # Проверяем, что созданный через эндпоинт конверт валиден
    assert verify_envelope_body(envelope_dict) is True


# ═══════════════════════════════════════════════════════════════════════
# COS-126: Airgap Release Bundle & Cryptography Tests
# ═══════════════════════════════════════════════════════════════════════

def test_airgap_bundle_export_import_success():
    """Успешный экспорт и импорт Airgap бандла с бинарниками и отчетом."""
    from cosmo.ledger.release_envelope import (
        AirgapReleaseBundle,
        EnvelopeArtifactDigest,
        export_airgap_bundle,
        import_and_verify_airgap_bundle,
    )

    binary_data = b"BINARY_EXECUTABLE_CONTENT_V2"
    sarif_data = b'{"version": "2.1.0", "runs": []}'

    binary_sha = hashlib.sha256(binary_data).hexdigest()
    sarif_sha = hashlib.sha256(sarif_data).hexdigest()

    artifacts = [
        EnvelopeArtifactDigest(name="app_bin", artifact_type="binary", sha256=binary_sha, size_bytes=len(binary_data)),
        EnvelopeArtifactDigest(name="report.sarif", artifact_type="sarif", sha256=sarif_sha, size_bytes=len(sarif_data)),
    ]

    envelope = seal_envelope(
        release_id="rel-airgap-100",
        signer="officer_crypto",
        version="2.0.0",
        domain_id="dom-banking",
        source_zone="zr",
        target_zone="zt",
        artifacts=artifacts,
    )

    bundle_bytes = export_airgap_bundle(
        envelope=envelope,
        artifacts_data={
            "app_bin": binary_data,
            "report.sarif": sarif_data,
        },
    )

    assert len(bundle_bytes) > 0

    # Импорт в ЗТ (целевая зона)
    ok, imported_env, errors = import_and_verify_airgap_bundle(bundle_bytes, destination_zone="zt")
    assert ok is True
    assert errors == []
    assert imported_env is not None
    assert imported_env.release_id == "rel-airgap-100"


def test_airgap_bundle_tampered_binary_rejected():
    """Подмена бинарного файла в архиве отклоняется при импорте."""
    import io
    import zipfile
    from cosmo.ledger.release_envelope import (
        EnvelopeArtifactDigest,
        export_airgap_bundle,
        import_and_verify_airgap_bundle,
    )

    raw_data = b"ORIGINAL_CLEAN_CODE"
    raw_sha = hashlib.sha256(raw_data).hexdigest()

    envelope = seal_envelope(
        release_id="rel-airgap-200",
        signer="officer_crypto",
        artifacts=[EnvelopeArtifactDigest(name="lib.so", artifact_type="binary", sha256=raw_sha, size_bytes=len(raw_data))],
        source_zone="zr",
        target_zone="zt",
    )

    valid_bundle = export_airgap_bundle(envelope, {"lib.so": raw_data})

    # Злоумышленник подменил lib.so внутри ZIP архива
    tampered_buf = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(valid_bundle), "r") as zin:
        with zipfile.ZipFile(tampered_buf, "w") as zout:
            for item in zin.infolist():
                if item.filename == "artifacts/lib.so":
                    zout.writestr(item.filename, b"MALICIOUS_INJECTED_CODE")
                else:
                    zout.writestr(item.filename, zin.read(item.filename))

    ok, imported_env, errors = import_and_verify_airgap_bundle(tampered_buf.getvalue(), destination_zone="zt")
    assert ok is False
    assert any("Artifact checksum mismatch" in e for e in errors)


def test_airgap_bundle_zone_mismatch_rejected():
    """Попытка импортировать бандл ЗР->ЗТ сразу в ЗПЭ отклоняется."""
    from cosmo.ledger.release_envelope import export_airgap_bundle, import_and_verify_airgap_bundle

    envelope = seal_envelope(
        release_id="rel-airgap-300",
        signer="officer_crypto",
        source_zone="zr",
        target_zone="zt",
    )
    bundle_bytes = export_airgap_bundle(envelope, {})

    # Попытка импорта в ЗПЭ вместо ЗТ
    ok, imported_env, errors = import_and_verify_airgap_bundle(bundle_bytes, destination_zone="zpe")
    assert ok is False
    assert any("Zone mismatch" in e for e in errors)

