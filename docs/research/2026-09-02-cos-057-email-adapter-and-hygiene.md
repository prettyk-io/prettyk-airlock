# COS-057: Email provider adapter + provider surface offline hygiene

> **Дата:** 2 сентября 2026. **Исполнитель:** Luna.
> **Scope:** email adapter против provider-neutral seam COS-055; offline hygiene
> принятых файлов (provider_capability, sfera_provider, tls_config,
> provider_result_mapping); live-gap checklist. Вне scope: manager.py, routes,
> api.ts, AlertHUD, TransferRegistry/миграции, инфраструктура.

## 1. Что сделано

### 1.1 Новый модуль `orchestrator/cosmo/notifications/email_adapter.py`

Реализация `EmailProvider` Protocol (COS-055) без изменения seam и manager:

- `TransportOutcome(code, message)` + `EmailTransport` Protocol — офлайн seam
  для транспорта (production SMTP подключается отдельной карточкой, эндпоинты
  не выдуманы);
- `SmtpEmailProvider` — классификация SMTP-исходов + redaction;
- `FakeEmailProvider` — детерминированный fake (скрипт исходов, in-memory call
  log) для тестов и ops-проверок.

Классификация (честная, документирована в докстринге):

| Исход | Результат | Следствие в manager (COS-055) |
|---|---|---|
| 2xx | accepted | sent |
| 3xx / 4xx | transient | retryable_failure → backoff → DLQ при исчерпании |
| 5xx | permanent | failed → DLQ-видимость |
| exception транспорта | transient | retry (сеть/timeout) |
| code=None (нет SMTP-кода) | transient | retry; письмо не теряется молча |
| невалидный адрес (adapter-гвардия) | permanent | terminal, транспорт не дёргается |

### 1.2 Redaction-контракт адаптера

- Адреса получателей вычищаются из error-строк (`[recipient]`): error может
  попасть в произвольные лог-sinks через last_error; durable source of truth —
  `notification_inbox.recipient_id`, дублирование не нужно.
- Логи адаптера — только `safe_log_line` с subject_len/body_len/code; ни
  получателей, ни секретов.
- **Найденный hygiene-gap в redaction.py (COS-055, НЕ правил):** `redact_text`
  маскирует только КЛЮЧ (`token=x` → `[sensitive]=x`) — значение остаётся.
  Обход в своём модуле: `safe_error_text` дополнительно вычищает значения
  key=value паттерном → `token=[REDACTED]`, затем поверх — `redact_text`.
  Рекомендация Flash: усилить `redact_text` в источнике (отдельный follow-up).
- **Наблюдение (дизайн COS-055, вне scope):** manager.py намеренно логирует
  `recipient_id` в `[EMAIL:failed→DLQ]` (manager.py:396) и в delivery-логах.
  Это идентификатор адресата (не секрет из payload), но критерий
  «redaction не утекает получатели в логи» формально нарушается на уровне
  manager. Решение за владельцем COS-055.

### 1.3 Offline hygiene принятых файлов

Новых изменений кода в 4 файлах НЕ потребовалось — edge-поведение честное,
закреплено тестами (см. §2): PEM-материал в refs → INVALID, insecure без
allow_insecure → INVALID, mTLS cert/key парность, logsafe-отпечатки,
UNSUPPORTED → FAILED + failure_class=None, неизвестный статус → FAILED +
TRANSPORT_FAILURE + detail (не маскировка), digest/location_ref verbatim.

## 2. Тесты: `orchestrator/tests/cosmo/test_email_adapter.py` — 33 passed

Unit (без PG): классификация 250/451/354/550/999/None/exception; invalid
recipient → permanent + транспорт не вызывается; recipient/secret scrub в
error; truncation 500; логи без получателя/секрета (caplog); FakeEmailProvider
(скрипт/исключение/default/call log); TLS-edges (PEM, insecure, cert без key,
logsafe, system trust note); mapping-edges (UNSUPPORTED/unmapped/verbatim).

Integration (PG, auto-skip, паттерн notif_db COS-055) — adapter через живого
NotificationManager:
- 451 → retryable_failure → retry по backoff → sent;
- 550 → failed/DLQ-видимость, last_error содержит 550, но НЕ адресата;
- невалидный адрес: manager гейтит email-канал (`looks_like_email`,
  manager.py:270) — email-строка не создаётся, транспорт не дёргается;
  adapter-гвардия проверена прямым вызовом (contract-level safety net);
- логи адаптера без адресата при живой доставке.

Регрессия: `test_notification_manager` + provider-тесты — 205 passed / 9
skipped. Полный снапшот `orchestrator/tests` — 2063 passed / 37 skipped /
**14 failed — все вне scope пакета**, см. §4.

## 3. Live-gap checklist (требования к будущей верификации; НЕ реализация)

| Gap | Что нужно для верификации | Блокер |
|---|---|---|
| Sfera CORE OpenAPI | Экспорт OpenAPI (COS-049): подтверждение точных маршрутов areas/repositories, exists/HEAD, tag→digest resolve, promotion/copy, quota, signatures/attestations, job lifecycle, pagination | доступ к живому Sfera + export |
| private CA / mTLS | Живой контур: real CA, выданные cert/key (vault-refs), сервер с TLS + mutual auth; проверка `verify_tls_config` против реальных цепочек и refusal-семантики 4xx/5xx live-сервера | стенд с private CA |
| Live SMTP | Реальный SMTP-сервер: подтверждение классификации 2xx/4xx/5xx на живых ответах (451/55x), поведение при connection drop/timeout, TLS-SMTP (STARTTLS) при необходимости | SMTP-аккаунт/relay в контуре |
| redact_text values | Усиление `redact_text` (маскировать значения, не только ключи) — follow-up к COS-055 | владелец COS-055 |

## 4. Полный снапшот — атрибуция 14 падений (все вне scope)

- 7× `AttributeError: 'Depends' object has no attribute 'is_system_admin'`
  (`test_release_envelope`, `test_sod_and_transfer_linear` ×6) — COS-067
  domain-binding в `routes/releases.py`/`gates.py`/`domain_guard.py` в полёте
  у параллельного worker'а; мок-тесты передают `Depends(...)` вместо
  PrincipalContext. Не мои файлы.
- 5× stale table-count (`test_cbr_luna_001_matrix`, `test_final_luna_001`,
  `test_int_012_013_016_steel_thread`, `test_post_luna_001_semantic_boundary`)
  — ждут 27 таблиц, в реестре 31 (эволюция схемы; известный follow-up §7
  COS-060-дока; владелец — Flash).
- 1× `test_deps_guard_regression` ×2 (считать как 2 из 14) — dev-БД загрязнена
  доменом `test` («Domain test not found» вместо 400/404) — тестовые данные
  параллельной работы.
- 1× `test_int_registry_smoke` cp1251 UnicodeDecodeError — известный
  encoding-флейк (COS-060 §7.2).

Мой след в снапшоте: 0 падений. Notification/provider/adapter-тесты зелёные.
