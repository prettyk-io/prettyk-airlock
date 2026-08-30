"""
COS-127: Tests for Event Sourcing & Audit Trail Engine.

Проверяет:
  1. Вычисление before/after JSON diff (added, removed, changed).
  2. Запись событий аудита с криптографической цепочкой хэшей SHA-256.
  3. Проверку целостности цепочки (verify_chain_integrity).
  4. Обнаружение подделки любого исторического события или разрыва цепочки (tamper detection).
  5. Реконструкцию состояния сущности (Event Sourcing replay_entity_state).
  6. Фильтрацию и пагинацию запросов к журналу аудита.
"""
import pytest
from cosmo.ledger.audit_trail import (
    AuditEvent,
    AuditTrailEngine,
    compute_json_diff,
)


def test_compute_json_diff():
    """Проверка корректности вычисления дельты JSON."""
    before = {
        "status": "draft",
        "version": "1.0.0",
        "obsolete_field": "to_remove",
        "tags": ["alpha"],
    }
    after = {
        "status": "approved",
        "version": "1.0.0",
        "tags": ["alpha", "beta"],
        "new_field": "added_value",
    }

    diff = compute_json_diff(before, after)

    assert diff["added"] == {"new_field": "added_value"}
    assert diff["removed"] == {"obsolete_field": "to_remove"}
    assert diff["changed"]["status"] == {"old": "draft", "new": "approved"}
    assert diff["changed"]["tags"] == {"old": ["alpha"], "new": ["alpha", "beta"]}
    assert "version" not in diff["changed"]


def test_audit_event_hash_and_verification():
    """Одиночное событие аудита корректно вычисляет хэш и валидируется."""
    event = AuditEvent(
        event_id="aud-001",
        entity_type="release",
        entity_id="rel-100",
        action="approve",
        actor_id="sec_officer_1",
        domain_id="dom-banking",
        zone="zt",
        timestamp="2026-08-29T12:00:00Z",
        before_state={"status": "pending_review"},
        after_state={"status": "approved"},
    )
    event.sign_and_seal(prev_hash="0" * 64)

    assert len(event.event_hash) == 64
    assert event.verify_hash() is True

    # Модификация поля ломает хэш
    event.action = "delete"
    assert event.verify_hash() is False


def test_audit_trail_chain_integrity():
    """Цепочка из нескольких событий успешно проходит проверку целостности."""
    engine = AuditTrailEngine()

    # Событие 1: Создание релиза
    engine.record_event(
        entity_type="release",
        entity_id="rel-200",
        action="create",
        actor_id="dev_lead",
        domain_id="dom-core",
        before_state=None,
        after_state={"id": "rel-200", "status": "draft", "version": "1.0.0"},
        zone="zr",
    )

    # Событие 2: Отправка на ревью
    engine.record_event(
        entity_type="release",
        entity_id="rel-200",
        action="submit",
        actor_id="dev_lead",
        domain_id="dom-core",
        before_state={"id": "rel-200", "status": "draft", "version": "1.0.0"},
        after_state={"id": "rel-200", "status": "pending_review", "version": "1.0.0"},
        zone="zr",
    )

    # Событие 3: Утверждение офицером ИБ
    engine.record_event(
        entity_type="release",
        entity_id="rel-200",
        action="approve",
        actor_id="sec_officer",
        domain_id="dom-core",
        before_state={"id": "rel-200", "status": "pending_review", "version": "1.0.0"},
        after_state={"id": "rel-200", "status": "approved", "version": "1.0.0"},
        zone="zr",
    )

    valid, count, errors = engine.verify_chain_integrity()
    assert valid is True
    assert count == 3
    assert errors == []


def test_tamper_detection_in_chain():
    """Обнаружение подмены данных в цепочке аудита."""
    engine = AuditTrailEngine()

    engine.record_event(
        entity_type="release",
        entity_id="rel-300",
        action="create",
        actor_id="dev_1",
        domain_id="dom-1",
        after_state={"status": "draft"},
    )
    engine.record_event(
        entity_type="release",
        entity_id="rel-300",
        action="approve",
        actor_id="officer_1",
        domain_id="dom-1",
        after_state={"status": "approved"},
    )

    # Злоумышленник изменил actor_id в первом событии
    engine._events[0].actor_id = "imposter_actor"

    valid, count, errors = engine.verify_chain_integrity()
    assert valid is False
    assert any("Tampered content" in e for e in errors)


def test_event_sourcing_replay_state():
    """Event Sourcing: реконструкция полного состояния сущности по событиям."""
    engine = AuditTrailEngine()

    t1 = "2026-08-29T10:00:00Z"
    t2 = "2026-08-29T11:00:00Z"
    t3 = "2026-08-29T12:00:00Z"

    engine.record_event(
        entity_type="run",
        entity_id="run-500",
        action="create",
        actor_id="system",
        domain_id="dom-1",
        after_state={"run_id": "run-500", "status": "running", "findings_count": 0},
        timestamp=t1,
    )
    engine.record_event(
        entity_type="run",
        entity_id="run-500",
        action="finding_added",
        actor_id="scanner_zap",
        domain_id="dom-1",
        after_state={"run_id": "run-500", "status": "running", "findings_count": 3},
        timestamp=t2,
    )
    engine.record_event(
        entity_type="run",
        entity_id="run-500",
        action="complete",
        actor_id="system",
        domain_id="dom-1",
        after_state={"run_id": "run-500", "status": "passed", "findings_count": 3},
        timestamp=t3,
    )

    # Реконструкция на момент времени t2
    state_at_t2 = engine.replay_entity_state("run", "run-500", target_timestamp=t2)
    assert state_at_t2["status"] == "running"
    assert state_at_t2["findings_count"] == 3

    # Финальное состояние
    final_state = engine.replay_entity_state("run", "run-500")
    assert final_state["status"] == "passed"


def test_query_events_filtering_and_pagination():
    """Проверка фильтрации и пагинации в AuditTrailEngine."""
    engine = AuditTrailEngine()

    engine.record_event("release", "rel-1", "create", "actor_a", "dom-1")
    engine.record_event("release", "rel-2", "create", "actor_b", "dom-2")
    engine.record_event("run", "run-1", "start", "actor_a", "dom-1")
    engine.record_event("release", "rel-1", "approve", "actor_a", "dom-1")

    # Фильтр по domain_id
    dom1_events = engine.query_events(domain_id="dom-1")
    assert len(dom1_events) == 3

    # Фильтр по entity_type
    run_events = engine.query_events(entity_type="run")
    assert len(run_events) == 1
    assert run_events[0].entity_id == "run-1"

    # Пагинация
    paged = engine.query_events(domain_id="dom-1", limit=2, offset=1)
    assert len(paged) == 2
