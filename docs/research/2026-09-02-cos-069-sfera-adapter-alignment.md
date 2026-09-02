# COS-069 — Sfera adapter offline alignment с legacy contract map + micro-PR матрицы

> **Дата:** 2 сентября 2026. **Исполнитель:** Luna.
> **Карточка:** BACKLOG.md COS-069 (зависимости COS-068 + COS-060).
> **SoT контракта:** `docs/research/2026-09-02-legacy-sfera-contract-map.md` (COS-068, принят).
> **Правило сохранено:** ни одного нового эндпоинта; каждое изменение — ссылка
> на карту (файл:строка legacy). Live-верификация (COS-049) остаётся гейтом
> для CONFIRMED.

## 1. Что сделано

### 1.1 Micro-PR матрицы (`adapters/provider_matrices.py::sfera_matrix`)

Вердикты §8 карты применены:

| Capability | Было | Стало | Обоснование |
|---|---|---|---|
| LIST | UNKNOWN | **DOCUMENTED** | docker/raw tree listing код-подтверждён (client.rb:123–149, parentId-пагинация); фильтры/totals/сортировки остаются UNKNOWN до OpenAPI (COS-049) |
| GET_CHECKSUM | DOCUMENTED, без уточнения | note: «legacy предпочитает sha1 (`fileInfo['sha1'] \|\| sha256`); наш adapter sha256-only — sha1 не identity» | get_docker_image_checksums.rb:20–23; карта §6 |
| OCI_PUSH / OCI_PULL | notes без auth-факта | notes: push = **Basic** (pusher:51–57), pull = **Bearer** + Range-resume/retry ×5 (fetcher:171–181) | карта §2, §4 |
| HEALTH | «auth login + /v2/ ping» | note уточнён: login подтверждён (client.rb:47–57); отдельного /v2/ ping в legacy нет — живость /v2/ подтверждена HEAD/GET в push/fetch; auth split-факт | карта §2 |

### 1.2 Adapter (`adapters/sfera_provider.py`) — пять пунктов выравнивания

1. **Auth split (карта §2):**
   - конфиг: `SferaProviderConfig.basic_auth_provider: Optional[Callable[[], Awaitable[tuple[str, str]]]]` — секреты только через callable, без plaintext;
   - `_request(auth=...)` принимает `True` (Bearer) / `False` / `"basic"`; фактический режим резолвится `_resolve_auth_mode()` — без basic-провайдера честный fallback на Bearer/anonymous;
   - `oci_push`: POST uploads / PUT blob / PUT manifest → `auth="basic"` (весь registry push-путь, pusher:51–57); режим фиксируется в `raw["registry_auth_mode"]` (basic | bearer | anonymous) — fallback не маскируется;
   - `oci_blob_pull`: `auth=True` (Bearer, fetcher:171–181; анонимный конфиг остаётся анонимным).
2. **Клиентский digest на push (карта §4, pusher:120–121):** `oci_push` считает
   identity = `sha256` от отправленных байтов манифеста (`digest_source=computed_payload`);
   серверный Docker-Content-Digest не identity, записывается в
   `raw["server_digest_header"]` для сверки на live.
3. **Naming + repo options (карта §5, concern:8–50):** константы
   `SFERA_REPO_KINDS` (дословная калька `REPO_CONFIGS`), `REPO_NAME_SUFFIX`,
   функции `repo_name_for_project(code, kind)` → `{code}|{code}-dirty|{code}-raw|{code}-docs`
   (чужой kind → ValueError) и `repo_configs_for_project(code)`.
4. **ALREADY_EXISTS idempotent-семантика (карта §3, establish_sfera.rb:125,160):**
   `_result_from_response(..., idempotent_conflict=True)` для `provision_area` /
   `provision_repository`: HTTP 409 с `ALREADY_EXISTS_ERROR`/`already exists` в
   теле → `OpStatus.OK` + `raw["idempotent_already_exists"]=True`; 409 с другим
   телом остаётся честным `CONFLICT`.
5. **Таймаут-профиль legacy (карта §2, client.rb:28–30, pusher:58–59):**
   константа `LEGACY_TIMEOUT_PROFILE = {open 10s, read 30s, upload_read 200s,
   registry 3600s, registry_open 600s}`; расхождение с нашим единым
   `timeout_seconds=30.0` (= legacy read) зафиксировано документированно,
   upload/registry-профили НЕ смоделированы до live-профиля.

Модульный docstring дополнен разделом COS-069 со ссылками на карту.
Доказательство-запрет соблюдён: **ни одного нового эндпоинта**, exists/resolve/
promote/quota остались UNSUPPORTED (COS-049).

## 2. Тесты (`tests/cosmo/test_sfera_adapter.py`)

- обновлён `test_oci_push_*_server_digest` → `test_oci_push_digest_computed_client_side_server_header_recorded`:
  сервер вернул «не согласный» digest → identity всё равно клиентский sha256,
  серверный заголовок записан и не использован;
- `TestRegistryAuthSplit` (3 теста): push = Basic (все 3 registry-вызова, точный
  base64-заголовок, `registry_auth_mode=="basic"`); fallback→Bearer виден в raw;
  pull (manifest+blob) = Bearer, ни одного Basic;
- `TestLegacyContractAlignment` (6 тестов): naming/options дословно vs concern;
  409+ALREADY_EXISTS → OK идемпотентно (JSON и текстовый body); 409 чужой → CONFLICT;
  timeout-профиль констант + расхождение;
- `TestMatrixMicroPR` (4 теста): LIST→DOCUMENTED + `client.rb:123` в evidence;
  GET_CHECKSUM note с sha1-фактом; OCI notes с Basic/Bearer; HEALTH evidence.

**Фокуснутый сет:** `test_sfera_adapter.py + test_provider_conformance.py +
test_provider_capability.py + test_tls_config.py` → **234 passed** (было 205 до
COS-069: +12 новых, 1 переписан, −конфликтов нет).

## 3. Полный снапшот (2 сентября, после правок)

**2200 passed / 16 failed / 2 skipped** (83s). Бухгалтерия фейлов — все вне scope:

| Файл | Кол-во | Зона | Причина |
|---|---|---|---|
| test_migrations.py | 5 | Boss WIP | psycopg2 scratch auth (базлайн) |
| test_migration_reconciliation.py | 3 | Boss WIP (нов. файл) | scratch `cosmo_mig_recon` не создан + localhost/`::1`-ловушка |
| test_notification_worker.py | 2 | notification-зона | `events_processed == 0` (worker tick) |
| test_notification_triggers.py | 2 | notification-зона | PG-race семейство (базлайн имел 1) |
| test_sod_and_transfer_linear.py | 2 | COS-067 (базлайн) | `'Depends' is_system_admin` 403 |
| test_transfer_security_matrix.py | 1 | COS-067 семейство | тот же 403 «System administrator role required» на `_ensure_domain` — с базлайна зона COS-067 расползлась |
| test_int_registry_smoke.py (Caddy) | 1 | Buddy | cp1251 (базлайн) |

Верификация «не моё»: failing-файлы не импортируют `sfera_provider` /
`provider_matrices`; фокуснутый Sfera/provider сет зелёный. **Новых падений в
scope: 0** (DoD выполнен).

## 4. Что осталось (не в COS-069)

- CONFIRMED-статусы — только после live-верификации: OpenAPI export (COS-049),
  идемпотентность create_area/create_repository на живом инстансе (карта §9#2),
  подтверждение Basic-vs-Bearer на живом push (§9#4);
- upload/registry таймаут-профили adapter'а — при live-профиле;
- registry_auth_mode для live-профиля обязан быть `basic` (fallback → Bearer
  не принимать как CONFIRMED).