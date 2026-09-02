# -*- coding: utf-8 -*-
"""COS-065: Offline/diode recovery hardening tests.

Exhaustive DeliveryState transition matrix (positive + negative),
crash-recovery evidence, ACK semantics, checkpoint corruption handling,
vendor conformance kit validation, observability fields.

Полная матрица переходов — в docstring diode_adapter.py (COS-065).
"""
from __future__ import annotations

import json

import pytest

from orchestrator.cosmo.transfer.builder import PackageBuilder
from orchestrator.cosmo.transfer.contract import (
    ArtifactPlane,
    PackageMode,
    TransferFailureClass,
)
from orchestrator.cosmo.transfer.diode_adapter import (
    AckMode,
    CheckpointCorruptedError,
    DeliveryCheckpoint,
    DeliveryState,
    DiodeAdapter,
    DeliveryClosedError,
    TargetRejectError,
    TransportError,
)
from orchestrator.cosmo.transfer.link_conformance import (
    CapacityLimitedTransportLink,
    FlakyTransportLink,
    RecordingTransportLink,
    RejectingTransportLink,
    assert_link_conformance,
    run_link_conformance,
)
from orchestrator.cosmo.transfer.offline_importer import (
    CheckpointCorruptedError as ImporterCheckpointCorruptedError,
    ImportState,
    OfflineImporter,
)

PAYLOAD = b"hardening-payload-" + bytes(range(128)) * 40   # ~5.5 KB, > 1 chunk


# ══════════════════════════════════════════════════════════════════
# Fixtures/helpers
# ══════════════════════════════════════════════════════════════════

def make_item(release_id: str = "rel-hard") -> object:
    return PackageBuilder.build_item(
        item_id="i-hard",
        release_id=release_id,
        plan_id="plan-hard",
        artifact_plane=ArtifactPlane.SOURCE_CODE,
        package_mode=PackageMode.FULL_PACKAGE,
        transport_profile="one_way_diode_relay",
        payload_refs=["payload.bin"],
        source_ref="src://rel-hard",
        target_ref="landing://zpe/rel-hard",
    )


def stage(spool, subdir, payload: bytes = PAYLOAD, corrupt: bool = False,
          release_id: str = "rel-hard") -> None:
    import hashlib
    staging = spool / subdir
    staging.mkdir(parents=True, exist_ok=True)
    data = payload
    if corrupt:
        data = payload[:-1] + bytes([payload[-1] ^ 0xFF])
    (staging / "payload.bin").write_bytes(data)
    manifest = {
        "release_id": release_id, "revision": 1,
        "payload_files": [{"name": "payload.bin",
                           "sha256": hashlib.sha256(payload).hexdigest()}],
    }
    (staging / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


class LateAckChannel:
    """Control/ACK channel: статусы назначаются test'ом напрямую."""

    def __init__(self):
        self.status: dict[str, dict] = {}
        self.polls = 0

    def send_ack(self, revision_key: str, ok: bool, detail: str = "") -> None:
        self.status[revision_key] = {"ok": ok, "detail": detail}

    def poll_status(self, revision_key: str):
        self.polls += 1
        return self.status.get(revision_key)


# ══════════════════════════════════════════════════════════════════
# Vendor conformance kit
# ══════════════════════════════════════════════════════════════════

class TestVendorConformanceKit:
    def test_recording_link_conforms(self):
        assert run_link_conformance(RecordingTransportLink()) == []

    def test_flaky_link_conforms(self):
        # TransportError — валидный failure mode, не violation
        assert run_link_conformance(FlakyTransportLink(fail_after=2)) == []

    def test_rejecting_link_conforms(self):
        assert run_link_conformance(RejectingTransportLink()) == []

    def test_capacity_link_conforms(self):
        assert run_link_conformance(CapacityLimitedTransportLink()) == []

    def test_arbitrary_exception_is_violation(self):
        class BadLink(RecordingTransportLink):
            def write_chunk(self, chunk, ref):
                raise RuntimeError("vendor bug: wrong exception type")

        violations = run_link_conformance(BadLink())
        assert violations
        assert any("RuntimeError" in v for v in violations)

    def test_missing_flush_is_violation(self):
        class NoFlush:
            def write_chunk(self, chunk, ref):
                pass

        violations = run_link_conformance(NoFlush())
        assert any("flush" in v for v in violations)

    def test_gappy_buffer_is_violation(self):
        class GappyLink(RecordingTransportLink):
            def write_chunk(self, chunk, ref):
                if ref.index == 1:
                    return  # потеряли чанк 1
                super().write_chunk(chunk, ref)

        violations = run_link_conformance(GappyLink())
        assert any("coverage" in v for v in violations)

    def test_assert_helper_raises(self):
        class BadLink(RecordingTransportLink):
            def write_chunk(self, chunk, ref):
                raise ValueError("no")

        try:
            assert_link_conformance(BadLink())
        except AssertionError as exc:
            assert "conformance failed" in str(exc)
        else:
            pytest_fail = True
            assert not pytest_fail, "expected AssertionError"

    def test_canonical_fakes_integrate_with_adapter(self):
        # Все канонические фейки работают с DiodeAdapter end-to-end
        item = make_item()
        r = DiodeAdapter(RecordingTransportLink()).dispatch(item, PAYLOAD)
        assert r.ok
        r = DiodeAdapter(FlakyTransportLink(fail_after=1), chunk_size=1024).dispatch(item, PAYLOAD)
        assert r.state == DeliveryState.FAILED_RETRYABLE
        r = DiodeAdapter(RejectingTransportLink()).dispatch(item, PAYLOAD)
        assert r.state == DeliveryState.FAILED_TERMINAL
        r = DiodeAdapter(CapacityLimitedTransportLink()).dispatch(item, PAYLOAD)
        assert r.failure_class == TransferFailureClass.CAPACITY_QUOTA_FAILURE


# ══════════════════════════════════════════════════════════════════
# State transition matrix — positive & negative
# ══════════════════════════════════════════════════════════════════

class TestStateTransitionMatrix:
    def test_pending_to_in_flight_to_checkpointed_to_failed_retryable(self):
        link = FlakyTransportLink(fail_after=2)
        adapter = DiodeAdapter(link, chunk_size=1024)
        item = make_item()
        result = adapter.dispatch(item, PAYLOAD, "p.bin")
        assert result.state == DeliveryState.FAILED_RETRYABLE
        assert result.chunks_sent == 2
        assert result.last_chunk_index == 1
        assert result.attempts == 1
        assert result.failure_class == TransferFailureClass.TRANSPORT_FAILURE
        cp = adapter.get_checkpoint(result.delivery_id)
        assert cp.chunks_sent == 2 and cp.chunks_total > 2

    def test_retryable_resumes_to_assumed_delivered(self):
        link = FlakyTransportLink(fail_after=2)
        adapter = DiodeAdapter(link, chunk_size=1024)
        item = make_item()
        adapter.dispatch(item, PAYLOAD, "p.bin")
        result = adapter.retry(item, PAYLOAD, "p.bin")
        assert result.state == DeliveryState.ASSUMED_DELIVERED
        assert result.attempts == 2
        assert result.same_revision
        # буфер без дыр и дублей
        assert link.reassemble() == PAYLOAD
        assert sorted(link.received) == list(range(len(link.received)))

    def test_retryable_never_delivered_without_ack(self):
        ack = LateAckChannel()
        adapter = DiodeAdapter(RecordingTransportLink(), chunk_size=1024,
                               ack_mode=AckMode.ACK_CHANNEL, ack_channel=ack)
        item = make_item()
        result = adapter.dispatch(item, PAYLOAD)
        assert result.state == DeliveryState.FAILED_RETRYABLE
        assert result.state != DeliveryState.DELIVERED

    def test_failed_terminal_is_absorbing(self):
        adapter = DiodeAdapter(RejectingTransportLink())
        item = make_item()
        adapter.dispatch(item, PAYLOAD)
        # retry по terminal → DeliveryClosedError (identity не переиспользуется)
        try:
            adapter.retry(item, PAYLOAD)
            raised = False
        except DeliveryClosedError:
            raised = True
        assert raised
        # dispatch по terminal → тоже DeliveryClosedError
        try:
            adapter.dispatch(item, PAYLOAD)
            raised = False
        except DeliveryClosedError:
            raised = True
        assert raised

    def test_delivered_is_absorbing(self):
        ack = LateAckChannel()
        adapter = DiodeAdapter(RecordingTransportLink(), chunk_size=1024,
                               ack_mode=AckMode.ACK_CHANNEL, ack_channel=ack)
        item = make_item()
        ack.send_ack(item.package_revision.revision_key, ok=True)
        result = adapter.dispatch(item, PAYLOAD)
        assert result.state == DeliveryState.DELIVERED
        # повторный poll не меняет состояние и не инкрементит attempts
        cp1 = adapter.poll_status(result.delivery_id)
        cp2 = adapter.poll_status(result.delivery_id)
        assert cp1.state == DeliveryState.DELIVERED
        assert cp2.state == DeliveryState.DELIVERED
        assert cp2.attempts == cp1.attempts
        # retry по DELIVERED → DeliveryClosedError
        try:
            adapter.retry(item, PAYLOAD)
            raised = False
        except DeliveryClosedError:
            raised = True
        assert raised

    def test_assumed_delivered_redispatch_is_idempotent(self):
        link = RecordingTransportLink()
        adapter = DiodeAdapter(link, chunk_size=1024)
        item = make_item()
        r1 = adapter.dispatch(item, PAYLOAD)
        assert r1.state == DeliveryState.ASSUMED_DELIVERED
        received_before = dict(link.received)
        r2 = adapter.dispatch(item, PAYLOAD)
        assert r2.delivery_id == r1.delivery_id
        assert r2.revision_key == r1.revision_key
        assert r2.state == DeliveryState.ASSUMED_DELIVERED
        assert r2.attempts == 2
        # ни одного нового чанка в буфер
        assert link.received == received_before

    def test_max_attempts_exhausted_is_terminal(self):
        link = FlakyTransportLink(fail_after=1)
        adapter = DiodeAdapter(link, chunk_size=1024, max_attempts=1)
        item = make_item()
        r1 = adapter.dispatch(item, PAYLOAD)          # attempt 1 → retryable
        assert r1.state == DeliveryState.FAILED_RETRYABLE
        r2 = adapter.retry(item, PAYLOAD)             # attempts(1) >= max(1) → terminal
        assert r2.state == DeliveryState.FAILED_TERMINAL
        assert "max attempts (1)" in r2.failure_detail
        assert r2.same_revision   # identity сохранена, но нужна новая revision
        assert r2.recovery_requirement == "new_revision"

    def test_recovery_requirement_mapping(self):
        item = make_item()
        rk = item.package_revision.revision_key
        # retryable
        r = DiodeAdapter(FlakyTransportLink(fail_after=1), chunk_size=1024).dispatch(item, PAYLOAD)
        assert r.recovery_requirement == "resume_same_revision"
        # terminal
        r = DiodeAdapter(RejectingTransportLink()).dispatch(item, PAYLOAD)
        assert r.recovery_requirement == "new_revision"
        # assumed
        r = DiodeAdapter(RecordingTransportLink()).dispatch(item, PAYLOAD)
        assert r.recovery_requirement == "none"
        assert r.revision_key == rk

    def test_dispatch_requires_revision(self):
        item = make_item()
        item.package_revision = None
        with pytest.raises(ValueError):
            DiodeAdapter(RecordingTransportLink()).dispatch(item, PAYLOAD)


class TestStrictOneWayGuarantees:
    def test_strict_ignores_configured_ack_channel(self):
        # ACK-канал говорит ok, но strict mode физически не может ему верить
        ack = LateAckChannel()
        link = RecordingTransportLink()
        adapter = DiodeAdapter(link, chunk_size=1024,
                               ack_mode=AckMode.STRICT_ONE_WAY, ack_channel=ack)
        item = make_item()
        ack.send_ack(item.package_revision.revision_key, ok=True)
        result = adapter.dispatch(item, PAYLOAD)
        assert result.state == DeliveryState.ASSUMED_DELIVERED
        assert result.state != DeliveryState.DELIVERED
        assert ack.polls == 0   # strict не опрашивает канал вообще

    def test_strict_poll_never_upgrades(self):
        adapter = DiodeAdapter(RecordingTransportLink(), chunk_size=1024)
        item = make_item()
        result = adapter.dispatch(item, PAYLOAD)
        cp = adapter.poll_status(result.delivery_id)
        assert cp.state == DeliveryState.ASSUMED_DELIVERED

    def test_empty_payload_strict_assumed_not_delivered(self):
        adapter = DiodeAdapter(RecordingTransportLink(), chunk_size=1024)
        item = make_item()
        result = adapter.dispatch(item, b"")
        assert result.ok
        assert result.state == DeliveryState.ASSUMED_DELIVERED


# ══════════════════════════════════════════════════════════════════
# ACK channel semantics: NACK, late ACK, duplicate ACK
# ══════════════════════════════════════════════════════════════════

class TestAckSemantics:
    def test_explicit_nack_is_terminal_new_revision(self):
        ack = LateAckChannel()
        adapter = DiodeAdapter(RecordingTransportLink(), chunk_size=1024,
                               ack_mode=AckMode.ACK_CHANNEL, ack_channel=ack)
        item = make_item()
        ack.send_ack(item.package_revision.revision_key, ok=False,
                     detail="quarantine: policy violation")
        result = adapter.dispatch(item, PAYLOAD)
        assert result.state == DeliveryState.FAILED_TERMINAL
        assert result.failure_class == TransferFailureClass.LANDING_REJECTED
        assert "policy violation" in result.failure_detail
        assert result.same_revision is False
        assert result.recovery_requirement == "new_revision"

    def test_nack_via_poll_terminal(self):
        ack = LateAckChannel()
        adapter = DiodeAdapter(RecordingTransportLink(), chunk_size=1024,
                               ack_mode=AckMode.ACK_CHANNEL, ack_channel=ack)
        item = make_item()
        result = adapter.dispatch(item, PAYLOAD)
        assert result.state == DeliveryState.FAILED_RETRYABLE  # ACK ещё нет

        ack.send_ack(item.package_revision.revision_key, ok=False)
        cp = adapter.poll_status(result.delivery_id)
        assert cp.state == DeliveryState.FAILED_TERMINAL
        assert cp.failure_class == TransferFailureClass.LANDING_REJECTED

    def test_late_ack_upgrades_to_delivered(self):
        ack = LateAckChannel()
        adapter = DiodeAdapter(RecordingTransportLink(), chunk_size=1024,
                               ack_mode=AckMode.ACK_CHANNEL, ack_channel=ack)
        item = make_item()
        result = adapter.dispatch(item, PAYLOAD)
        assert result.state == DeliveryState.FAILED_RETRYABLE

        ack.send_ack(item.package_revision.revision_key, ok=True)
        cp = adapter.poll_status(result.delivery_id)
        assert cp.state == DeliveryState.DELIVERED
        # retry после DELIVERED закрыт
        try:
            adapter.retry(item, PAYLOAD)
            raised = False
        except DeliveryClosedError:
            raised = True
        assert raised

    def test_duplicate_ack_is_idempotent(self):
        ack = LateAckChannel()
        adapter = DiodeAdapter(RecordingTransportLink(), chunk_size=1024,
                               ack_mode=AckMode.ACK_CHANNEL, ack_channel=ack)
        item = make_item()
        ack.send_ack(item.package_revision.revision_key, ok=True)
        r1 = adapter.dispatch(item, PAYLOAD)
        assert r1.state == DeliveryState.DELIVERED
        ack.send_ack(item.package_revision.revision_key, ok=True)  # duplicate ACK
        cp = adapter.poll_status(r1.delivery_id)
        assert cp.state == DeliveryState.DELIVERED
        assert cp.attempts == 1   # duplicate ACK не инкрементит attempts
        # poll снова — стабильно
        assert adapter.poll_status(r1.delivery_id).state == DeliveryState.DELIVERED


# ══════════════════════════════════════════════════════════════════
# Crash recovery (diode): checkpoint restore + crash-gap evidence
# ══════════════════════════════════════════════════════════════════

class TestCrashRecoveryDiode:
    def test_crash_between_flush_and_state_transition(self):
        """Crash после flush, до сохранения ASSUMED_DELIVERED.

        Восстановление: checkpoint с state=CHECKPOINTED, chunks_sent==total
        → re-dispatch → flush → ASSUMED_DELIVERED. Буфер без дублей/дыр.
        """
        link = RecordingTransportLink()
        adapter_a = DiodeAdapter(link, chunk_size=1024)
        item = make_item()
        r1 = adapter_a.dispatch(item, PAYLOAD)
        total = r1.chunks_total

        # "crash": снимок checkpoint в момент после flush, до перехода
        cp_dict = adapter_a.get_checkpoint(r1.delivery_id).model_dump()
        cp_dict["state"] = DeliveryState.CHECKPOINTED.value
        cp_dict["chunks_sent"] = total
        cp_dict["last_chunk_index"] = total - 1

        received_before = dict(link.received)
        # restart: свежий adapter, тот же target-буфер (target-стейт persists)
        adapter_b = DiodeAdapter(link, chunk_size=1024)
        adapter_b.restore_checkpoint(cp_dict)
        r2 = adapter_b.dispatch(item, PAYLOAD)

        assert r2.state == DeliveryState.ASSUMED_DELIVERED
        assert r2.delivery_id == r1.delivery_id
        assert r2.same_revision
        assert link.received == received_before      # ни одного нового чанка
        assert sorted(link.received) == list(range(total))
        assert link.reassemble() == PAYLOAD

    def test_crash_mid_chunks_resume_no_gap_no_duplicate(self):
        # target-буфер один на оба adapter'а (target-стейт персистентен)
        link = FlakyTransportLink(fail_after=3)
        adapter_a = DiodeAdapter(link, chunk_size=1024)
        item = make_item()
        r1 = adapter_a.dispatch(item, PAYLOAD)
        assert r1.state == DeliveryState.FAILED_RETRYABLE
        assert r1.chunks_sent == 3

        cp_dict = adapter_a.get_checkpoint(r1.delivery_id).model_dump()
        adapter_b = DiodeAdapter(link, chunk_size=1024)   # restart
        adapter_b.restore_checkpoint(cp_dict)
        r2 = adapter_b.dispatch(item, PAYLOAD)

        assert r2.state == DeliveryState.ASSUMED_DELIVERED
        assert link.reassemble() == PAYLOAD
        assert sorted(link.received) == list(range(len(link.received)))
        # каждый чанк записан ровно один раз
        assert len(link.received) == len(set(link.received))

    def test_restore_checkpoint_validates_schema(self):
        adapter = DiodeAdapter(RecordingTransportLink())
        base = {
            "delivery_id": "dl-x", "revision_key": "rel-x:1",
            "item_id": "i-x", "chunks_total": 4, "chunks_sent": 2,
            "last_chunk_index": 1, "state": "checkpointed",
        }
        # valid restore
        cp = adapter.restore_checkpoint(dict(base))
        assert cp.chunks_sent == 2

        # invalid state value
        bad = dict(base, delivery_id="dl-bad1", state="flying_to_the_moon")
        try:
            adapter.restore_checkpoint(bad)
            assert False, "expected CheckpointCorruptedError"
        except CheckpointCorruptedError:
            pass

        # chunks_sent out of range
        bad = dict(base, delivery_id="dl-bad2", chunks_sent=9)
        try:
            adapter.restore_checkpoint(bad)
            assert False, "expected CheckpointCorruptedError"
        except CheckpointCorruptedError:
            pass

        # negative chunks_total
        bad = dict(base, delivery_id="dl-bad3", chunks_total=-1)
        try:
            adapter.restore_checkpoint(bad)
            assert False, "expected CheckpointCorruptedError"
        except CheckpointCorruptedError:
            pass

        # missing required field
        bad = {k: v for k, v in base.items() if k != "item_id"}
        try:
            adapter.restore_checkpoint(bad)
            assert False, "expected CheckpointCorruptedError"
        except CheckpointCorruptedError:
            pass

    def test_duplicate_restore_same_content_idempotent(self):
        adapter = DiodeAdapter(RecordingTransportLink())
        data = {
            "delivery_id": "dl-x", "revision_key": "rel-x:1", "item_id": "i-x",
            "chunks_total": 4, "chunks_sent": 2, "last_chunk_index": 1,
            "state": "checkpointed",
        }
        cp1 = adapter.restore_checkpoint(dict(data))
        cp2 = adapter.restore_checkpoint(dict(data))
        assert cp1 is cp2

    def test_duplicate_restore_different_content_rejected(self):
        adapter = DiodeAdapter(RecordingTransportLink())
        data = {
            "delivery_id": "dl-x", "revision_key": "rel-x:1", "item_id": "i-x",
            "chunks_total": 4, "chunks_sent": 2, "last_chunk_index": 1,
            "state": "checkpointed",
        }
        adapter.restore_checkpoint(dict(data))
        tampered = dict(data, chunks_sent=3)
        try:
            adapter.restore_checkpoint(tampered)
            assert False, "expected CheckpointCorruptedError"
        except CheckpointCorruptedError:
            pass

    def test_presend_checksum_guard_terminal(self):
        # Payload мутирует между chunk-plan и отправкой (mutable buffer,
        # гонка потоков) → pre-send guard: chunk sha mismatch →
        # FAILED_TERMINAL, в канал не уходит ничего.
        link = RecordingTransportLink()

        class StalePlanAdapter(DiodeAdapter):
            """Chunk plan по snapshot, slice по фактическому payload."""
            snapshot = PAYLOAD

            def make_chunks(self, file_name, payload):
                return super().make_chunks(file_name, self.snapshot)

        adapter = StalePlanAdapter(link, chunk_size=1024)
        item = make_item()

        result = adapter.dispatch(item, b"Different payload entirely" * 50)
        assert result.state == DeliveryState.FAILED_TERMINAL
        assert result.failure_class == TransferFailureClass.CHECKSUM_MISMATCH
        assert "corrupted before send" in result.failure_detail
        assert link.received == {}   # ничего не ушло в канал

    def test_delivery_closed_error_preserves_identity(self):
        adapter = DiodeAdapter(RejectingTransportLink())
        item = make_item()
        rk = item.package_revision.revision_key
        r1 = adapter.dispatch(item, PAYLOAD)   # → FAILED_TERMINAL (reject)
        assert r1.state == DeliveryState.FAILED_TERMINAL
        try:
            adapter.retry(item, PAYLOAD)
            assert False, "expected DeliveryClosedError"
        except DeliveryClosedError as exc:
            msg = str(exc)
            assert r1.delivery_id in msg
            assert rk in msg


# ══════════════════════════════════════════════════════════════════
# Importer hardening: identity, crash-gap, checkpoint corruption, cleanup
# ══════════════════════════════════════════════════════════════════

class TestImporterIdentityCrossCheck:
    def test_manifest_identity_mismatch_rejected(self, tmp_path):
        imp = OfflineImporter(tmp_path / "spool", tmp_path / "landing")
        stage(tmp_path / "spool", "pkg-1", release_id="rel-OTHER")
        item = make_item()
        report = imp.import_package(item, "pkg-1")
        assert report.state == ImportState.MANIFEST_INVALID
        assert not report.passed
        assert report.requires_new_revision
        assert not (tmp_path / "landing").exists() or \
            list((tmp_path / "landing").iterdir()) == []


class TestImporterCrashGap:
    def test_crash_between_promote_and_register_is_idempotent(self, tmp_path):
        imp1 = OfflineImporter(tmp_path / "spool", tmp_path / "landing")
        stage(tmp_path / "spool", "pkg-1")
        item = make_item()
        r1 = imp1.import_package(item, "pkg-1")
        assert r1.passed and not r1.duplicate

        # "crash": новый importer-инстанс (рестарт процесса), регистр пуст
        imp2 = OfflineImporter(tmp_path / "spool", tmp_path / "landing")
        stage(tmp_path / "spool", "pkg-2")   # тот же revision на новом носителе
        r2 = imp2.import_package(item, "pkg-2")
        assert r2.passed
        assert r2.duplicate
        assert r2.recovery_requirement == "none"
        # landing ровно один, не задвоен
        assert len(list((tmp_path / "landing").iterdir())) == 1

    def test_crash_gap_with_corrupted_landing_is_conflict(self, tmp_path):
        imp1 = OfflineImporter(tmp_path / "spool", tmp_path / "landing")
        stage(tmp_path / "spool", "pkg-1")
        item = make_item()
        r1 = imp1.import_package(item, "pkg-1")
        assert r1.passed
        landing = next((tmp_path / "landing").iterdir())
        good_content = (landing / "payload.bin").read_bytes()

        # рестарт + порча существующего landing (crash-gap с битым dir)
        (landing / "payload.bin").write_bytes(b"corrupted-landing-content")
        imp2 = OfflineImporter(tmp_path / "spool", tmp_path / "landing")
        stage(tmp_path / "spool", "pkg-3")   # валидная копия той же revision
        r2 = imp2.import_package(item, "pkg-3")
        assert not r2.passed
        assert r2.failure_class == TransferFailureClass.IDEMPOTENCY_CONFLICT
        assert r2.requires_new_revision
        # импортёр НЕ перезаписал битый landing (quarantine до ручного разбора)
        assert (landing / "payload.bin").read_bytes() == b"corrupted-landing-content"


class TestImporterCheckpointCorruption:
    def test_strict_load_raises_on_corruption(self, tmp_path):
        imp = OfflineImporter(tmp_path / "spool", tmp_path / "landing")
        cp_path = tmp_path / "spool" / ".checkpoint_i-1.json"
        cp_path.write_text("{broken json", encoding="utf-8")
        try:
            imp.load_checkpoint_strict("i-1")
            assert False, "expected CheckpointCorruptedError"
        except ImporterCheckpointCorruptedError:
            pass
        # soft load: None (проверка с нуля)
        assert imp.load_checkpoint("i-1") is None

    def test_schema_invalid_checkpoint_detected(self, tmp_path):
        imp = OfflineImporter(tmp_path / "spool", tmp_path / "landing")
        (tmp_path / "spool" / ".checkpoint_i-2.json").write_text(
            json.dumps({"item_id": "i-2", "revision_key": "rk",
                        "staging_path": "s", "state": "flying"}),
            encoding="utf-8")
        try:
            imp.load_checkpoint_strict("i-2")
            assert False, "expected CheckpointCorruptedError"
        except ImporterCheckpointCorruptedError:
            pass

    def test_corrupt_checkpoint_no_silent_success(self, tmp_path):
        imp = OfflineImporter(tmp_path / "spool", tmp_path / "landing")
        stage(tmp_path / "spool", "pkg-1", corrupt=True)   # битый payload
        cp_path = tmp_path / "spool" / ".checkpoint_i-1.json"
        cp_path.write_text("{{{{corrupt", encoding="utf-8")
        item = make_item()
        report = imp.import_package(item, "pkg-1")
        # corrupt checkpoint не даёт silent success: битый payload отвергнут
        assert report.state == ImportState.CHECKSUM_MISMATCH
        assert not report.passed
        assert not (tmp_path / "landing").exists() or \
            list((tmp_path / "landing").iterdir()) == []


class TestCleanupScoped:
    def test_active_checkpoint_blocks_only_its_own_staging(self, tmp_path):
        from orchestrator.cosmo.transfer.offline_importer import SpoolEntry
        imp = OfflineImporter(tmp_path / "spool", tmp_path / "landing")
        active = SpoolEntry(item_id="i-live", revision_key="rk-live",
                            staging_path="pkg-live",
                            state=ImportState.VERIFYING)
        imp.checkpoint(active)
        stage(tmp_path / "spool", "pkg-done")

        # чужой staging чистится свободно
        assert imp.cleanup_staging("pkg-done") is True
        # свой активный staging заблокирован
        stage(tmp_path / "spool", "pkg-live")
        assert imp.cleanup_staging("pkg-live") is False
        assert (tmp_path / "spool" / "pkg-live").exists()


# ══════════════════════════════════════════════════════════════════
# Observability fields
# ══════════════════════════════════════════════════════════════════

class TestObservability:
    def test_dispatch_result_observability_on_failure(self):
        link = FlakyTransportLink(fail_after=2)
        adapter = DiodeAdapter(link, chunk_size=1024)
        item = make_item()
        result = adapter.dispatch(item, PAYLOAD)
        assert result.delivery_id.startswith("dl-")
        assert result.revision_key
        assert result.last_chunk_index == 1
        assert result.attempts == 1
        assert result.failure_class == TransferFailureClass.TRANSPORT_FAILURE
        assert result.recovery_requirement == "resume_same_revision"

    def test_import_report_observability(self, tmp_path):
        imp = OfflineImporter(tmp_path / "spool", tmp_path / "landing")
        item = make_item()
        # partial
        stage(tmp_path / "spool", "pkg-1", payload=PAYLOAD)
        (tmp_path / "spool" / "pkg-1" / "payload.bin").unlink()
        r1 = imp.import_package(item, "pkg-1")
        assert r1.recovery_requirement == "resume_same_revision"
        # checksum
        stage(tmp_path / "spool", "pkg-2", corrupt=True)
        r2 = imp.import_package(item, "pkg-2")
        assert r2.recovery_requirement == "new_revision"
        # promoted
        stage(tmp_path / "spool", "pkg-3")
        r3 = imp.import_package(item, "pkg-3")
        assert r3.recovery_requirement == "none"
        assert r3.promoted_to


import pytest  # noqa: E402  (используется в TestVendorConformanceKit)
