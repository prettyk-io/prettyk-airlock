# COS-060: Capability evidence & adapter hardening notes

> **Дата:** 1 сентября 2026. **Исполнитель:** Luna.
> **Контекст:** conformance suite поверх принятых COS-051 + COS-052.

## 1. Epistemic statuses — что означает каждый

| Status | Значение | Поведение операций |
|---|---|---|
| `CONFIRMED` | Проверено contract tests / live | Операции реализованы и покрыты |
| `DOCUMENTED` | Заявлено спекой/легаси-клиентом, live не проверено | Операции реализованы; live-семантика может отличаться |
| `NOT_SUPPORTED` | Провайдер не поддерживает по своей природе | Операции возвращают `UNSUPPORTED`, никогда fake success |
| `UNKNOWN` | Нет подтверждённого контракта | Операции возвращают `UNSUPPORTED` до появления evidence |
| `BLOCKED` | Нет доступа проверить | Аналогично UNKNOWN |

Инвариант conformance: `UNKNOWN`, `NOT_SUPPORTED`, `BLOCKED` **никогда не дают
`ok=True`** (battery B в `test_provider_conformance.py`).

## 2. Digest identity rules

1. Server digest (Docker-Content-Digest / ETag) сохраняется verbatim.
2. Если сервер молчит и adapter вычисляет sha256 от payload — в
   `OpResult.raw["digest_source"]` ставится `computed_payload`; server digest
   всегда имеет `digest_source=server`.
3. Отсутствие digest не превращается в подтверждение целостности.
4. Provider location_ref (area keys, repo paths) — НЕ PureK canonical identity;
   canonical — immutable `sha256` digest + `PackageRevision` (COS-050).

## 3. Error/retry mapping (OpStatus → kernel)

| OpStatus | TransferItemStatus | TransferFailureClass | Retryable |
|---|---|---|---|
| OK | DISPATCHED | — | нет |
| TRANSIENT_FAILURE | RETRY_SCHEDULED | TRANSPORT_FAILURE | **да** |
| VALIDATION_FAILURE | FAILED | VALIDATION_FAILURE | нет |
| AUTH_FAILURE | FAILED | TRANSPORT_FAILURE | нет |
| QUOTA_FAILURE | FAILED | CAPACITY_QUOTA_FAILURE | нет |
| CONFLICT | FAILED | IDEMPOTENCY_CONFLICT | нет |
| NOT_FOUND | FAILED | PACKAGE_NOT_READY | нет |
| UNSUPPORTED | FAILED | **None** (см. §4) | нет |
| ERROR | FAILED | TRANSPORT_FAILURE | нет |

Terminal ошибки никогда не уходят в silent retry (battery F).

## 4. Known gap: kernel не имеет класса UNSUPPORTED

`TransferFailureClass` (COS-050) не содержит UNSUPPORTED/CONFIGURATION_FAILURE.
Нормализация (`provider_result_mapping.to_transfer_outcome`) возвращает для
UNSUPPORTED `FAILED` c `failure_class=None` + пометку в detail — kernel-семантика
не искажается. Если позже понадобится отдельный класс — это изменение kernel
контракта (отдельная карточка, не COS-060).

## 5. TLS/mTLS verification

`adapters/tls_config.py`:
- `TLSConfig` — только ссылки (`vault:secret/...`, `openbao:secret/...`,
  `file:/path`), плейтекст-материал запрещён;
- `tls_verify=False` без `allow_insecure=True` → INVALID (молчаливый downgrade
  отказан); с allow → `INSECURE_EXPLICIT` (dev-only, zpe запрещено);
- mTLS требует ОБА `client_cert_ref` и `client_key_ref`;
- `to_logsafe_dict()` — в логах только схема + 8-символьный отпечаток ссылки;
- `SferaProviderConfig.tls` — опциональный seam (back-compat, None допустим);
  `RegistryConfig` (BRG-001) маппится через `tls_config_from_registry`.

Live TLS/mTLS против реального private CA — НЕ проверялся (нет доступа к
живому Sfera/Harbor с CA); зафиксировано в follow-up.

## 6. Sfera: confirmed vs unsupported

**Реализовано (легаси evidence §7.1 research doc):**
raw push/pull (`PUT <repo_url>/raw/...`), OCI push/pull (`/v2/` blobs+manifest),
health (auth + `/v2/` ping), bearer через token_provider.

**UNSUPPORTED до подтверждённого OpenAPI (COS-049):**
area/repository creation (формат операций есть, точные маршруты — нет),
exists/HEAD, tag→digest resolve, copy/promotion, quota, signatures/SBOM,
job/status lifecycle, pagination.

**Правило:** endpoint не добавляется без evidence — сипы `areas_path` /
`repositories_path` в конфиге принимают маршрут только после подтверждения.

## 7. Follow-ups (зафиксированы, НЕ чинились в этом пакете)

1. **Stale table-count assertions** — 4 теста (`test_cbr_luna_001_matrix`,
   `test_final_luna_001`, `test_int_012_013_016_steel_thread`,
   `test_post_luna_001_semantic_boundary`) ждут 27/24/23 таблиц, в реестре 31
   после COS-055 notification-схем. Владелец фикса — Flash (COS-055) или
   отдельный follow-up.
2. **Caddy encoding failure** — `test_int_registry_smoke.py::
   test_caddy_uses_8180_not_8080` падает на `read_text()` без encoding
   (Windows cp1251, не-ASCII compose). Фикс тривиален (`encoding="utf-8"`),
   вне скоупа COS-060.
3. COS-049: Sfera CORE OpenAPI export — разблокирует provisioning routes и
   exists/resolve/promote/quota.
4. Live TLS/private CA/mTLS проверка на реальном контуре.
