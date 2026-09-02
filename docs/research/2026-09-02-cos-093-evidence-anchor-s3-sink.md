# COS-093 — Evidence Anchor: object-store (S3/MinIO) sink

> Luna, 2 сентября 2026. Follow-up COS-087. Статус: DELIVERED, ждёт приёмки.
> Контракт publish/verify НЕ менялся; добавлен второй бэкенд за тем же
> интерфейсом, выбор — конфиг, не код.

## Что сделано

### 1. Backend dispatch — `COSMO_EVIDENCE_ANCHOR_BACKEND=file|s3`

`orchestrator/cosmo/ledger/evidence_anchor.py` сохраняет публичный контракт
COS-087 байт-в-байт (`sink_path`, `is_enabled`, `publish_head`, `read_head`)
и диспетчирует по env:

- **file** (default, unset) — audit-file JSONL, append-only, Pure Box /
  airgap. Поведение COS-087 не тронуто (11 старых юнитов зелёные без правок).
- **s3** — object-store (S3/MinIO): ключ `{prefix}{run_id}.jsonl`, публикация
  = GET текущего тела → append строки → PUT. Конфиг — конвенции startup.py:
  `PK_MINIO_URL` / `PK_MINIO_ACCESS_KEY` / `PK_MINIO_SECRET_KEY` +
  `COSMO_EVIDENCE_ANCHOR_S3_BUCKET` (default `cosmo-evidence`) +
  `COSMO_EVIDENCE_ANCHOR_S3_PREFIX` (default `evidence-anchor/`) +
  `COSMO_EVIDENCE_ANCHOR_S3_REGION` (default `us-east-1`).

### 2. Append-only замена: S3-версионирование

Файл дописывается; S3-объект переписывается целиком — append-only
гарантию берёт на себя **версионирование бакета**: каждый PUT создаёт новую
immutable-версию, история версий = журнал голов. Sink при первой публикации
включает versioning best-effort (идемпотентный `PUT /bucket?versioning`,
фейл → warning, не блокирует publish: жёсткая гарантия лежит на bucket
policy — разворачивается в deploy-профиле Enterprise). Single-writer
задокументирован: GET-modify-PUT без CAS, два райтера контракт не покрывают
(как и file-бэкенд).

### 3. Честные read-статусы — без изменений

`read_head` в s3-режиме возвращает те же формы: `ok` / `unknown_anchor`
(объекта нет → `no anchor object in bucket for run`; недоступен → `anchor
sink unreadable: ...`; HTTP≠200 → `anchor sink HTTP NNN`; битый JSONL →
`anchor object corrupt: ...`; не сконфигурирован → `anchor sink not
configured`). Verify-сторона (evidence_chain) НЕ менялась ни строкой —
head_mismatch/unknown_anchor语义 работают как в COS-087. Publish фейл →
RuntimeError (fail visible), включая misconfig `backend=s3` без
`PK_MINIO_URL`.

### 4. SigV4 на stdlib

MinIO **отклоняет HTTP Basic auth** для S3 API ("Please use
AWS4-HMAC-SHA256") — в репо нет boto3/minio SDK, поэтому подписант
`evidence_anchor.s3_sigv4_headers()` написан на stdlib (hmac/hashlib),
path-style, service=s3, ~60 строк. Используется sink'ом, health-пробой и
тестовой фикстурой.

⚠️ **Грабля, которая стоила половины карточки:** `httpx.URL(...).netloc`
в httpx 0.28.1 возвращает **bytes** — `b'127.0.0.1:9100'` в canonical
headers SigV4 даёт детерминированный `SignatureDoesNotMatch` при
валидной подписи. Симптом маскировался под «инфра-флейк» (часть тестов
с захардкоженным str-хостом проходила в те же минуты). Канон: для
извлечения host использовать `urllib.parse.urlsplit(...).netloc` (str);
в MinIOAdmin (тестовая фикстура) зафиксировано комментарием.

⚠️ **Чужая поверхность, найдена по пути:** `orchestrator/cosmo/api/
startup.py::_bucket_exists/_create_bucket` ходит в MinIO с Basic auth —
против реального MinIO это даёт 400 «authorization mechanism not
supported», т.е. автопровижининг бакетов при старте API, вероятно, молча
не работает (не блокирует старт по дизайну). Surface Apex/Boss; я не
трогал. Health-проба anchor'а в моём PR переведена на SigV4.

## Тесты

| Слой | Файл | Статус |
|---|---|---|
| Юнит: file-бэкенд (регресс COS-087) | tests/cosmo/test_evidence_anchor.py | 11 passed, без правок |
| Юнит: S3 sink (fake S3 на httpx.MockTransport) | там же, TestS3* | 16 новых: publish/read статусы, last-wins JSONL, versioning×1, fail-visible publish, honest unknown (404/500/drop/corrupt), backend dispatch, сквозной head_mismatch через якорь |
| E2E: живой MinIO :9100 + тестовый PG :5433 | tests/cosmo/integration/test_evidence_anchor_s3.py | 5 passed ×2: publish→verify ok (объект = накопленный JSONL, 3 публикации = 3 строки), **подмена якорного объекта в MinIO → head_mismatch** (флагман), suffix-resign через S3-якорь → head_mismatch, head loss → head_mismatch, мёртвый endpoint → честный unknown_anchor |
| Линия целиком | anchor + verification + tamper + s3 | 69 passed |
| Полный сет | tests/cosmo | 2366 passed / 3 failed / 3 skipped и 2355 / 13 / 1 в двух прогонах подряд; все failed — чужие поверхности (batch_executor, deps_guard_regression, gate_trail, notification_triggers, openapi_contract), разброс между прогонами + подтверждённый параллельный pytest другого воркера (PID 26736) = интерференция на общем test PG :5433, не мои файлы |

МинIO после прогонов вычищен: все debug-бакеты удалены (второй проход
листинга — 0 кандидатов), штатные бакеты стека не тронуты. E2E-фикстура
создаёт свой `cosmo-evidence-anchor-test-<pid>` и сносит его в teardown.

## Инфра-заметки

- Тесты e2e требуют живой cosmo-minio (host-канон **9100**, креды
  compose: cosmo / cosmo-minio-dev); при недоступности — честный skip.
- Версионирование бакета в e2e включается фикстурой; в проде — bucket
  policy (KMS/подписи якоря — out of scope карточки).

## Out of scope (как в карточке)

KMS/подписи якоря, миграционная цепочка, чужие поверхности
(startup.py-провижининг — флагнуто).
