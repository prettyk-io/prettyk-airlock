# COS-077 — Transfer Durable Repo Wiring: research & acceptance

- **Карточка:** COS-077 — READY · TRANSFER DURABLE REPO WIRING (Apex, P1, 20–24h)
- **Дата:** 2026-09-02
- **Исполнитель:** Apex (worker Cosmo)
- **Зависимости:** COS-067 (guard), COS-070 (durable repo), COS-074 (lease semantics) — все приняты ранее.

## 1. Scope (по карточке)

1. Подключить `PgTransferRegistryRepository` в `routes/transfer.py` вместо in-memory registry.
2. API-путь честного терминального `TRANSFER_FAILED` + `GatewayLeaseRegistry`
   (missing/expired/revoked → контрактная ошибка API).
3. Интеграционные тесты на тестовом PG (`_testpg.py`, :5433/cosmo_test).
4. Flake `test_transfer_security_matrix.py` (×4 в run1, зелёный изолированно) —
   найти и устранить корень межфайлового состояния, не маскировать.

Out of scope: `db/session.py` + `alembic/env.py` (Boss COS-078), notification
surfaces (Flash COS-079), миграционная цепочка (frozen), Steel Thread (Luna COS-080).

## 2. Что сделано

### 2.1 Репозиторий: persist-методы для маршрутов

`orchestrator/cosmo/db/transfer_registry_repo.py` — расширены 2 методами
(kernel-поверхность `registry.py` не тронута):

- `save_item(item)` — persist status/revision_key/retry_count/payload.
- `save_plan(plan)` — persist status + payload (items исключены).

Мотивация: durable-методы (`record_transfer_failed`, `record_transfer_retryable`,
`transition_landing`) мутируют только строки БД; in-memory item/SM у маршрута
устаревает. Маршрут зеркалирует поля в локальный объект и persist'ит через
`save_*`, чтобы последующая запись не затёрла kernel-записи устаревшим payload.

### 2.2 Маршруты: durable wiring

`orchestrator/cosmo/api/routes/transfer.py`:

- **DI:** все handlers получили `registry: TransferRegistryRepository = Depends(get_transfer_repository)`.
  Протокол `TransferRegistryRepository` — hermetic-тесты подменяют зависимость
  in-memory двойником, боевой путь — PG-репозиторий.
- **Ленивый синглтон:** `_transfer_repo` + `get_transfer_repository()` —
  `PgTransferRegistryRepository(get_sync_url())` конструируется при первом вызове,
  никогда на импорте (паритет с COS-078 lazy URL resolution).
- **`_persist_state(registry, entry, item, sm)`** — duck-typed persist
  (`save_landing_state`/`save_item`/`save_plan` через getattr, no-op для
  in-memory тестовых двойников). Вызывается после каждого успешного перехода.
- **`mark_transfer_failed`:** ветка в `landing_transition`; вызывает
  `registry.record_transfer_failed(...)`, зеркалирует failure-поля в in-memory
  item только когда `prev_state is not TRANSFER_FAILED` (честная идемпотентность),
  обновляет SM из `registry.get_landing_state` (PG-репозиторий мутирует только БД).
  Checksum-mismatch путь persist'ит состояние ДО raise 409.
- **`_ITEM_STATUS_BY_LANDING[TRANSFER_FAILED] = TransferItemStatus.FAILED`** —
  вью item отражает терминальный провал.
- **Контракт ошибки:** `TransferErrorCode.GATEWAY_LEASE_REQUIRED`; маппинг
  `LeaseRequiredError` → HTTP 423 LOCKED с details `{revision_key, reason}`.

### 2.3 Новые эндпоинты (lease + dispatch)

| Метод | Путь | Семантика |
|---|---|---|
| POST | `/items/{item_id}/lease` | issue lease (`ttl_seconds` 0<ttl≤86400, `gateway_id`), `LeaseView` |
| DELETE | `/items/{item_id}/lease` | revoke, идемпотентный `RevokeView` |
| POST | `/items/{item_id}/dispatch` | dispatch c lease-гейтом, `DispatchView` |

- Lease-гейт — ТОЛЬКО для `TransportProfile.CONTROLLED_GATEWAY_RELAY`
  (`direct_authenticated_api` не гейтится) — паритет kernel `diode_adapter.py`.
- Гейт валидируется ДО любой мутации (включая simulate transport_failure) —
  паритет kernel-порядку.
- Re-dispatch → 409 CONFLICT; dispatch при недопустимом статусе → 409.
- simulate.transport_failure → `record_transfer_retryable` (retry_count+1,
  зеркалится в item) → состояние `transport_failed_retryable`.

### 2.4 Герметичность: корень flake

Исторический flake security_matrix («×4 в run1, зелёный изолированно») —
межфайловое состояние in-memory синглтона `TransferRegistry` + неявная
зависимость от порядка файлов. Устранено явно:

- `test_transfer_api.py`, `test_transfer_security_matrix.py`: autouse-фикстура
  `_clean_registry` теперь выставляет
  `app.dependency_overrides[get_transfer_repository] = get_transfer_registry`
  на setup, снимает на teardown, реcетит registry с обеих сторон.
- Каждому transfer-тестовому файлу — свой явный registry, никакого shared state.

### 2.5 Durable integration suite

Новый `orchestrator/tests/cosmo/test_transfer_durable_api.py` — 14 тестов,
боевой путь (БЕЗ override репозитория) на тестовом PG :5433/cosmo_test:

- **TestRestartSurvival** — план/items/landing/received-revision видны через
  свежий экземпляр репозитория (симуляция рестарта); валидация persist'ится
  через `save_item`; DuplicateRevisionError переживает рестарт.
- **TestTransferFailedViaAPI** — достижимость + идемпотентность через API;
  recovery view (`transport_failure`, failure_detail); после RECEIVED —
  409 INVALID_TRANSITION (from_state=received) с сохранением состояния;
  item FAILED + failure_class TRANSPORT_FAILURE persist'ятся.
- **TestLeaseAndDispatch** — 423 no-lease/revoked/expired (ttl=1s, sleep 1.2);
  dispatch → persisted → re-dispatch 409; reissue вытесняет предыдущий lease
  (single-active); ghost item 404; foreign domain → 404 anti-disclosure
  (guard require_domain + anti-spoofing X-Cosmo-Domain).

## 3. Evidence

| Прогон | Результат |
|---|---|
| `test_transfer_security_matrix.py` ×3 подряд (целевые) | 26 passed ×3 |
| Периметр 5 transfer-файлов ×3 | 100 passed ×3 (плюс 2 зелёных ранее) |
| Полный сет на тестовом PG, прогон A (чистое окно) | **2274 passed / 2 skipped / 0 failed** (128s) |
| Полный сет на тестовом PG, прогон B (чистое окно) | **2274 passed / 2 skipped / 0 failed** (149s) |

Итог по flake-критерию: security_matrix зелёный в **3 полных прогонах подряд**
(A, B + промежуточный полный) и 3 целевых прогонах подряд.

Примечания к evidence:

- Первый полный прогон после wiring (24F/3E) и периметр-блиц (1F) пришлись на
  окно активной параллельной работы других worker-сессий в том же workspace
  (хронология WIP: Luna `test_steel_thread_integration.py` 12:50, Flash
  `test_notification_ops.py` 13:01) — два pytest на общем test-PG дают ровно
  такую картину (IntegrityError на дубликатах, плавающие наборы падений).
  Это задокументированный паттерн (COS-073/076: mitigation — scratch-DB per run).
  В чистом окне сет полностью зелёный; чужие падения (steel_thread NameError,
  notification log-hygiene) воспроизвелись только в момент чужого WIP и были
  закрыты их владельцами.
- Единственный невоспроизведённый блиц периметра (1F → 5 зелёных подряд):
  остаточное состояние общего test-PG, не transfer-логика; в корневом
  lastfailed-кэше десятки аналогичных исторических one-off по разным файлам.

## 4. Acceptance по карточке

| Критерий | Статус |
|---|---|
| Рестарт не теряет revisions/states | ✅ TestRestartSurvival |
| TRANSFER_FAILED достижимость через API + идемпотентность | ✅ TestTransferFailedViaAPI |
| Lease-нарушения → 409/423 контракт | ✅ TestLeaseAndDispatch |
| Интеграционные тесты на тестовом PG | ✅ 14/14, боевой путь без override |
| Полный сет на тестовом PG без новых падений | ✅ 2274/2/0 |
| security_matrix стабильно зелёный ×3 | ✅ 26×3 |

## 5. Находки и follow-up (для Cosmo)

1. **Backlog hygiene fork:** follow-up-строка COS-067 назначает «Pass 2
   (capability-гранулярность builds/deployments/projects, доменный scoping
   read-списков) → COS-077», но карточка COS-077 этого не включает. Карточка —
   источник истины; Pass 2 требует собственной карточки либо снятия устаревшего
   указателя.
2. **conftest `_wipe` не чистит transfer-таблицы:** `delete_order` в
   `pg_client` не включает `transfer_*` (отдельный `TransferRegistryBase`).
   Сегодня мой autouse-фикстура чистит их в своём файле; риск — durable-остатки
   из других файлов. Предложение: дополнить delete_order в пакете Boss COS-078.
3. **Параллельные worker-сессии на общем test-PG** — системный источник
   one-off падений. Scratch-DB паттерн (`_testpg.scratch_name`) уже есть и
   используется Luna; предложить закрепить как норму для новых integration
   suites и/или отдельную карточку на per-worker изоляцию схем.
4. **Sync-репозиторий в sync-обработчиках** — консистентно (FastAPI крутит `def`
   handlers в threadpool); при росте нагрузки пересмотреть на async-движок.
   Решение сознательное, в рамках стека.

## 6. Не тронуто

Kernel (`transfer/registry.py`, `landing.py`, `gateway_lease.py`,
`contract.py`, `diode_adapter.py`), `db/session.py`, alembic-цепочка,
notifications, Steel Thread — без изменений.
