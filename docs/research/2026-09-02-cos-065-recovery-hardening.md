# COS-065 — Offline Transfer Recovery Hardening: Acceptance

Дата: 2026-09-02
Worker: Boss
Зависимости: accepted COS-050, COS-053, COS-054

## Что сделано

Contract audit `OfflineImporter` + `DiodeAdapter`, укрепление recovery
contract, vendor conformance kit, exhaustive transition tests.

## Найденные и исправленные дефекты контракта (audit)

1. **`dispatch()` после terminal failure перезаписывал delivery** — создавал
   новый checkpoint с тем же `delivery_id` (нарушение "terminal требует
   новую revision"). Fix: `DeliveryClosedError` при dispatch/retry по
   terminal/delivered delivery; recovery = `rebuild_with_revision` →
   новый revision_key → новая delivery.
2. **Явный NACK (`ok=false`) через ACK channel игнорировался** — delivery
   оставалась retryable навсегда. Fix: NACK → terminal `LANDING_REJECTED`,
   `same_revision=False`, recovery `new_revision` (в `_resume` и `poll_status`).
3. **`max_attempts` не enforcement'ился.** Fix: `retry()` при
   `attempts >= max_attempts` → `FAILED_TERMINAL`, identity сохранена.
4. **OfflineImporter: crash между promote и register** → повторный импорт
   падал с ложным `CHECKSUM_MISMATCH`. Fix: crash-gap recovery —
   существующий landing верифицируется; целый → idempotent duplicate;
   битый → `IDEMPOTENCY_CONFLICT` (quarantine, не перезаписывается).
5. **`cleanup_staging` блокировался любым активным checkpoint глобально.**
   Fix: scoped policy — блокируется только staging, на который указывает
   активный checkpoint; чужие завершённые staging чистятся.
6. **Verify-hook получал `revision_key` вместо expected sha.** Fix:
   `_target_verify(revision_key, manifest_sha256)`; `manifest_sha256`
   зафиксирован в `DeliveryCheckpoint`.
7. **`load_checkpoint` молча глотал corruption.** Fix: `load_checkpoint`
   остаётся soft (None → verify с нуля — silent success невозможен, т.к.
   promote всегда после полной checksum verification), добавлен
   `load_checkpoint_strict` → `CheckpointCorruptedError` + schema-валидация.

## Переходы/инварианты (зафиксированы в docstring diode_adapter.py)

Полная transition matrix (PENDING→IN_FLIGHT→CHECKPOINTED→{ASSUMED_DELIVERED |
DELIVERED | FAILED_RETRYABLE | FAILED_TERMINAL}, absorbing-состояния) и
оба delivery profile — `strict_one_way` (никогда DELIVERED, ACK-канал
игнорируется даже если сконфигурирован) и `ack_channel` (DELIVERED только
по явному ACK; NACK terminal; отсутствие ACK — retryable).

## Recovery behavior

- Crash между flush и state-transition: checkpoint `CHECKPOINTED` c
  `chunks_sent == chunks_total` → restore → re-dispatch → только flush →
  `ASSUMED_DELIVERED`; буфер target без дублей/дыр (тест).
- Crash mid-chunks: restore → resume с `chunks_sent` → completion,
  reassembly == payload, каждый чанк ровно один раз (тест).
- Restore-валидация: schema/state mismatch, chunks_sent/last_chunk_index
  out-of-range, duplicate restore с другим содержимым →
  `CheckpointCorruptedError` (silent success невозможен). Тот же контент —
  идемпотентно.
- Pre-send checksum guard: payload, мутировавший между plan и отправкой →
  `FAILED_TERMINAL CHECKSUM_MISMATCH`, в канал не уходит ничего.

## Vendor seam

`orchestrator/cosmo/transfer/link_conformance.py` — conformance kit:
канонические фейки (`RecordingTransportLink`, `FlakyTransportLink`,
`RejectingTransportLink`, `CapacityLimitedTransportLink`) + `run_link_conformance()`
/ `assert_link_conformance()` для vendor TransportLink до подключения.
Vendor-протокол остаётся снаружи kernel (protocol-only seam).

## Observability

`DispatchResult`: delivery_id, revision_key, state, chunks_total/sent,
last_chunk_index, attempts, failure_class, failure_detail, same_revision,
recovery_requirement (`none` | `resume_same_revision` | `new_revision`).
`ImportReport`: + recovery_requirement, resumed, duplicate, promoted_to.

## Физические assumptions (открытые)

1. flush() идемпотентность — ответственность vendor link (kernel вызывает
   повторно при resume).
2. Target-буфер персистентен между попытками (retransmit вне diode-канала).
3. Capacity-классификация по маркеру в сообщении TransportError.
4. ACK-транспорт (TCP/TLS/API) — вне адаптера.

## Тесты

```
python -m pytest test_offline_recovery_hardening.py --noconftest -q   → 41 passed
python -m pytest <13 focused files> --noconftest -q                   → 442 passed
python -m pytest orchestrator/tests/cosmo -q                          → 1943 passed,
                                                                        6 pre-existing fails
                                                                        (вне scope)
```

COS-054 тест `test_cleanup_does_not_remove_active_transfer` обновлён под
scoped cleanup policy (семантика acceptance "cleanup does not remove an
active/recoverable transfer" сохранена — для СВОЕГО staging).

## Blockers

Нет.
