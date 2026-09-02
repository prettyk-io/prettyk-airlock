# COS-074 — Acceptance: transfer_failed terminal path + gateway lease/TTL

Дата: 2026-09-02 · Worker: Dev (pool) · Status: implemented, focused suite 202/202

## Что сделано

### 1. Честный терминал `TRANSFER_FAILED` (landing.py)
- `LandingState.TRANSFER_FAILED` — терминал транспортного провала: пакет НЕ доехал
  до target (диода умерла навсегда: FAILED_TERMINAL, max_attempts).
- Переход `NOT_RECEIVED → TRANSFER_FAILED` (единственный вход); выходов нет.
- `check_report()`: `failure_class = TRANSPORT_FAILURE`, check `transfer_failed: false`.
- `is_terminal()` включает TRANSFER_FAILED; не recoverable, не требует новую revision
  (контент не виноват — recovery = свежий dispatch, новая SM).
- Честность: после `RECEIVED` переход запрещён (`LandingStateError`) — target что-то
  получил, «транспортный провал» лгать не может.

### 2. In-memory registry (registry.py)
- `record_transfer_retryable(item_id, failure_class, detail) -> retry_count`:
  retry_count+1 + failure-поля на item, состояние НЕ меняется.
- `record_transfer_failed(...) -> LandingState`: терминальный переход; идемпотентный
  no-op если уже TRANSFER_FAILED (без события и мутаций); LandingStateError на
  невалидных переходах; KeyError на неизвестном item.
- `transfer_events(item_id?)` — runtime failure log (event/from/to/failure_class/timestamp).

### 3. Durable mirror (transfer_registry_repo.py)
- Protocol + `PgTransferRegistryRepository`: `record_transfer_retryable` /
  `record_transfer_failed` — то же поведение на PG.
- Терминал персистентен: `transfer_landing_states.state='transfer_failed'`, история
  перехода (from/to/reason/timestamp), failure-поля в payload item'а.
  Restart-survival: новый инстанс репо восстанавливает SM и `check_report()`.

### 4. Gateway lease/TTL (gateway_lease.py — новый)
- `GatewayLease` (lease_id/revision_key/item_id/gateway_id/issued_at/ttl/expires_at/state),
  `GatewayLeaseRegistry`: issue / validate / revoke / get.
- Инвариант single-active на revision_key (новый issue отзывает предыдущий).
- Детерминированное истечение через инъекцию clock; граница `now >= expires_at`.
- Ошибки: `LeaseRequiredError` (missing/expired/revoked — reason различает).

### 5. DiodeAdapter lease gate (diode_adapter.py)
- Опциональный `gateway_leases` параметр; enforced только для
  `CONTROLLED_GATEWAY_RELAY`; отсутствие реестра = старое поведение.
- Проверка в `dispatch()` ДО любых мутаций: чанки не пишутся, checkpoint не
  создаётся, attempts не растут. Другие профили не затронуты.

## Верификация

- `test_transfer_failed_gateway_lease.py` — 27 тестов: landing unit, registry parity,
  lease-семантика (single-active, expiry boundary, revoke idempotent), adapter gate
  (no-lease/expired/revoked отказ без записи; active-lease проходит; прочие профили
  не затронуты), durable PG: терминал в transfer_landing_states, идемпотентность
  (без доп. истории), invalid-after-received, restart-survival, KeyError.
- Focused-набор (kernel+offline+recovery+durable+migrations+reconciliation+cos074):
  **202 passed**. (Флапы в двух промежуточных прогонах — каталожная гонка
  `pg_type_typname_nsp_index` при конкурентных pytest на стенде; соло и повтор
  зелёные, к коду отношения не имеют.)
- Dev-БД повторно на head `e4f5a6b7c8d9` (после рестарта контейнера 07:58Z откатилась
  к d2e3f4a5b6c7; только upgrade, downgrade запрещён).

## Out of scope (по карточке)
- routes/transfer.py (окно Apex, COS-067), notifications (Flash, COS-072), инфра,
  физические транспорты. Lease-реестр сознательно in-memory: durable-требование —
  только transfer_failed-терминал.
