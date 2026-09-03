# COS-101 — Мост Findings ↔ Quality Gates, SigV4 MinIO provisioning, OpenAPI контракт-тест

> Исполнитель: Apex. Дата: 2026-09-03. Зависимости: COS-097 (execution cycle), COS-055 (GatePolicyEngine/RCP), COS-093 (SigV4), COS-104 (FindingSearchEngine — канонический носитель).

## 1. Постановка

Диспетч Максима: закрыть COS-101 из BACKLOG — три части:

1. **Мост Findings ↔ Quality Gates**: gate-оценка на живых findings прогона вместо статических заглушек.
2. **Фикс SigV4 MinIO auto-provisioning** (`startup.py` использует Basic auth — MinIO отвергает).
3. **Исправление OpenAPI контракт-теста** (`test_no_raw_token_in_parameters` падает на легитимном auth-каноне COS-066/067/068).

## 2. Ключевые находки исследования

### 2.1. Канонический носитель findings — `runs.findings_refs`, не новая таблица

Карточка предполагала сущность `cosmo_findings`. Исследование показало:

- `Run.findings_refs` (JSONB, default `[]`) уже **канонический** носитель: его читают
  FindingSearchEngine (COS-104) и runs API; это задокументировано в моделях.
- **Никто не писал** в него в production — bridging-дыра.
- Отдельная таблица продублировала бы носитель и потребовала бы sync между
  двумя местами истины. Решение: писать в `runs.findings_refs`.

### 2.2. Точка hook'а — `ExecutionService.finalize_run`

- `GatePolicyEngine` (COS-055, `control_plane/gate_engine.py`) принимает findings
  аргументом: `evaluate_plan_gates(plan_id, findings, run_id=...)` → `{gate_id: decision}`.
- `RCP.set_gate_engine/set_findings_provider` существуют, но в production **никогда
  не вызывались** (только тесты с `lambda: []`); RCP в API не инстанцируется (COS-003).
- ExecutionService (COS-097) — единственный production-класс, который знает момент
  завершения прогона и имеет и async-, и sync-фабрики сессий.

### 2.3. Дефект MinIO — HTTP Basic против S3 API

`startup.py::_minio_client()` создавал httpx-клиент с `auth=(access_key, secret_key)`
— это HTTP Basic. MinIO/S3 API требует SigV4 и отвечает
`400: Please use AWS4-HMAC-SHA256`. Канонический подписант уже есть:
`s3_sigv4_headers(...)` в `ledger/evidence_anchor.py` (COS-093).

### 2.4. OpenAPI-тест — ложное срабатывание на auth-каноне

`test_no_raw_token_in_parameters` (COS-035) запрещал **любой** параметр с "token"
в имени. Спека содержит 130 `session_token` параметров, все `in: cookie` — легитимный
auth-канон COS-066/067/068 (cookie не утекает в URL/логи, в отличие от query).
Риск, от которого защищал тест, — token в **query** (дефолт OpenAPI-локация).

## 3. Реализация

### 3.1. `control_plane/findings_bridge.py` (новый)

- `normalize_severity` / `normalize_finding`: сканеры пишут в любом регистре
  ("critical", "CRITICAL", "High"); gate engine ожидает канон
  `Critical|High|Medium|Low|Info`. Нормализация на границе моста, вход не мутируется.
- `PgFindingsProvider(session_factory)`: async callable run_id → findings из
  `runs.findings_refs`; **fail-open** (ошибка чтения/ghost run → `[]`).
- `attach_findings(session_factory, run_id, findings)`: валидация (severity
  обязателен и канонизируем → ValueError; run отсутствует → LookupError),
  append + commit → total.

### 3.2. `execution_service.py` — gate hook в finalize

- `__init__(..., gate_bridge: bool | None = None)`: kill-switch, env
  `COSMO_GATE_BRIDGE_ENABLED` (default **on**; "0"/"false"/"no" — off).
- `_start_core()` авто-wiring: `GatePolicyEngine(self._sync_db)` +
  `PgFindingsProvider(self._sf)` в try/except — сбой wiring не роняет старт
  (fail-open, parity с контрактом bridge).
- `finalize_run()`: при `all_passed and not degraded_reason` →
  `gate_blocked = await self._gate_blocked(run_id, run_plan_id)`;
  verdict **block** → `run.status = "blocked"` (parity RCP COS-055: gate может
  заблокировать успешный прогон с Critical finding). Порядок честности COS-097
  сохранён: degraded → **failed** раньше gate-оценки.
- `_gate_blocked()`: поддерживает и sync, и async provider (`asyncio.iscoroutine`);
  любая ошибка → fail-open (не блокирует прогон); block только при явном
  policy-вердикте.
- Порядок чтения колонок: `run_plan_id`/`run_domain_id` фиксируются сразу после
  fetch run (первая версия читала переменную до присваивания — поймано тестом
  `test_success_writes_real_evidence_and_finalizes`).

### 3.3. `routes/runs.py` — scan-сторона моста

`POST /api/v1/runs/{run_id}/findings` (201):

- `require_capability(Action.SCAN_START, domain_binding="identity")` — тот же
  write-паттерн, что commit-and-run; USER без SCAN_START → 403 до handler'а
  (регрессионный тест в auth-матрице).
- Run lookup → 404; ghost-404 для не-админа через собственный `run.domain_id`
  (verify_ownership).
- Body: `findings: list[dict]` (min_length 1); LookupError → 404, ValueError → 422.
- Через `attach_findings(get_sessionmaker(), ...)` + `loop_safe_engine_reset`
  в тестах (синглтон-фабрика привязана к event loop).

### 3.4. `startup.py` — SigV4 provisioning

- Basic-клиент удалён; `_minio_conf()` → `(endpoint, access_key, secret_key) | None`.
- Каждый запрос (HEAD exists / PUT create) подписывается `s3_sigv4_headers`
  (канон COS-093): `Authorization: AWS4-HMAC-SHA256 Credential=...`,
  `x-amz-date`, `x-amz-content-sha256`.
- `provision_minio_buckets(transport=None)` — точка внедрения httpx.MockTransport
  для тестов; отсутствие `PK_MINIO_URL` → ранний выход (noop).

### 3.5. `test_openapi_contract.py` — лок auth-канона

- `test_no_raw_token_in_parameters`: запрещает token/password/secret **только в
  query** (`in` отсутствует → трактуем как query — OpenAPI default); cookie/header
  разрешены.
- Новый `test_session_token_is_cookie_only`: все `session_token` параметры обязаны
  быть `in: cookie` (seen > 0) — лочит канон COS-066/067/068 от дрейфа.

## 4. Тесты (+26)

- `test_findings_bridge.py` (23): нормализация severity (канон/unknown/не-строка/
  не-мутирование входа); provider (чтение+нормализация/ghost fail-open/пусто/
  не-dict-записи); attach (append+total/bad severity/без severity/ghost/empty);
  gate hook на scratch-БД (Critical+block-политика → blocked; medium при
  High-политике → succeeded; нет gates → succeeded; сломанный engine → fail-open;
  bridge off конструктором → hook инертен; degraded → failed раньше gate);
  API ingest (201+персистенция+нормализация; 422 без записи; ghost 404).
- `test_startup_minio_sigv4.py` (2): MockTransport — Authorization
  `AWS4-HMAC-SHA256`, нет Basic, SignedHeaders=host;x-amz-content-sha256;x-amz-date;
  HEAD для существующих, PUT только для отсутствующих; без PK_MINIO_URL — noop.
- `test_surface_auth_regression.py` (+1): USER без SCAN_START → 403 на
  findings ingest.

Scratch-паттерн как в test_execution_service: module-фикстура `_scratch`
(DROP/CREATE БД через psycopg2 admin, create_all CosmoBase **и** ExecutionBase —
side-таблицы `cosmo_execution_*` живут в отдельном Base, `db/models_execution.py`),
`env` — async_sessionmaker с обязательным `bind=` (иначе `_ensure_tables` уходит
в dev stand :5432).

## 5. Результаты

- Полный сет: **2526 passed / 8 skipped / 0 failed** (7:21), против
  COS-097-бейслайна 2498/8/**1** (единственный фейл был OpenAPI-тестом — починен).
- Верификации в процессе: пойманы и исправлены (1) чтение `run_plan_id` до
  присваивания, (2) отсутствие ExecutionBase.create_all в scratch, (3)
  `async with maker` без вызова фабрики.

## 6. Открытые вопросы / follow-up

1. **ID-коллизия**: в `docs/cosmo-openapi.json/yaml` строка "SSE multiplexer:
   all run events for a KITS domain (COS-101)" из sse.py — ложная привязка к
   номеру этой карточки. Не трогал; решает Максим.
2. **SARIF-парсинг** отчётов Woodpecker-шагов — не входил: execution-адаптер
   отдаёт статусы, не отчёты; нужна отдельная карточка, когда появится требование
   на артефакты-отчёты.
3. **Точка вызова ingest** сканерами (Woodpecker plugin / webhook) — следующий
   связующий шаг; контракт API готов.
