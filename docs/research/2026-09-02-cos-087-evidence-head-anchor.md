# COS-087 — External append-only head anchor + conftest advisory lock + contract test

Дата: 2026-09-02 · Воркер: Luna · Статус: DELIVERED
Задача: docs/BACKLOG.md (COS-087) · Зависимости: COS-082 ✅, COS-083 ✅

## 1. Внешний append-only якорь головы (head_mismatch)

### Граница, которую закрывает карточка

COS-082 честно задокументировала принципиальный предел: атакующий с полным
доступом на запись в PG может пере-подписать весь суффикс цепочки (payload
+ якоря тем же каноническим алгоритмом) — internal verify от сохранённых
якорей пройдёт чистым. Без внешнего доказательства головы это
недетектируемо в принципе.

### Решение: anchor sink (audit-file, без новых сервисов)

`orchestrator/cosmo/ledger/evidence_anchor.py` — append-only JSONL sink,
путь из env `COSMO_EVIDENCE_ANCHOR_FILE` (env читается на каждый вызов;
не задан → anchoring disabled, честный no-op). Файл только дозаписывается,
никогда не rewrite; одна строка на публикацию:
`{"ts", "run_id", "chain_hash", "entry_id"}` + fsync.

Ключевой инвариант: `chain_hash` — **СОХРАНЁННЫЙ** `_chain_hash` последней
запечатанной строки (тот же hash, что пишет write-path), НЕ hash
rebuild-вида chain API (у rebuild другой канонический состав — сверка
была бы всегда ложной).

### Write-path

`evidence_writer.commit_evidence_entry(session, entry)` — канонический
путь: append → flush → seal → **commit** → `publish_head`. Якорь
публикуется только после commit (sink пополняется только durable-головами);
фейл публикации → исключение (fail visible: якорь — часть контракта
записи). Интеграционный хелпер `_add_evidence` переведён на него.

### Read-side (verify_and_get)

- `computed_head` = последний непустой stored `_chain_hash` по порядку
  строк (genesis, если пусто);
- сверка с внешним якорем → `anchor: {enabled, status, anchored_head,
  computed_head, anchored_at, detail}` + `head_mismatch: bool`;
- **integrity расширено четвёртым статусом**: `"ok" | "tampered" |
  "unsealed" | "head_mismatch"`. Приоритет: internal-доказательства
  (tampered/unsealed) доминируют; head_mismatch — когда internal чист,
  но внешнее доказательство расходится;
- `verified` при head_mismatch → False;
- **честный unknown_anchor**: sink сконфигурирован, но файл отсутствует /
  нечитаем / нет записи для run → `anchor.status="unknown_anchor"` с
  detail; internal вердикт не притворяется внешне подтверждённым.

### Тесты

- Юниты `tests/cosmo/test_evidence_anchor.py` (11): sink-контракт
  (disabled no-op, publish/read, last-wins + физическая append-only,
  unknown при отсутствии записи/файла, fail-visible при невозможности
  записи), anchored-режим verify_and_get (ok / suffix re-sign →
  head_mismatch при ЧИСТОМ internal verify / head loss → head_mismatch /
  честный unknown / disabled — поведение COS-082 как было).
- Интеграция `tests/cosmo/integration/test_evidence_tamper_detection.py`
  (+5 тестов, всего 13): `test_suffix_resign_detected_by_external_anchor`
  — флагман: canonical write → якорь сходится → атака
  (`_resign_suffix`: подмена payload всех строк + корректная переподпись
  всей цепочки) → integrity=head_mismatch, tampered_entries=[] (internal
  чист!), verified=False; head loss (DELETE головы) → head_mismatch;
  unknown_anchor; disabled-режим; **детерминизм ×3**.

## 2. Advisory lock в integration/conftest

Причина: параллельные pytest-процессы на общем :5433 сталкиваются в
create_all/wipe (каталожкие гонки pg_type_typname_nsp_index при
конкурентном DDL; изолированный PG :5434 — временный хак приёмки COS-082).

- `pg_advisory_xact_lock(0x434F534D /* 'COSM' */)` первым statement'ом
  в транзакции: create_all (один tx движка) и wipe (весь wipe собран в
  одну транзакцию сессии) сериализуются между процессами, lock живёт до
  commit;
- возврат на общий :5433 (COSMO_TEST_DATABASE_URL не требуется);
- попутно: wipe-зонд COS-082 (pre/post print) убран;
- созданный для COS-082 контейнер `cosmo-test-pg-luna` (:5434) удалён.

## 3. test_final_luna_001 → caller_domain

Зависимость COS-083 принята: домен-free старая семантика больше не канон.
Проверка: тест `test_project_endpoints_domain_free` уже переписан в
fallout COS-083 (caller_domain разрешён как ОПЦИОНАЛЬНЫЙ заголовок,
обязательным быть не должен), Header→str баг `domain_guard.py` закрыт
Apex'ом. Верифицировано: test_final_luna_001 + test_nx_luna_integration +
test_post_luna_001_semantic_boundary + test_lr_persist_api_visiblity —
**119 passed**. X-Cosmo-Domain в seed'ах интеграционного сьюта присутствует
с COS-080 (`_H()`).

## Верификация

- Юниты: test_evidence_anchor (11) + test_evidence_verification (24) —
  **35 passed**.
- Интеграция: **25 passed ×3** (11.9/12.0/11.5s) на общем :5433.
- Параллель integration + миграции на :5433: **25 passed** + **27 passed**
  — каталожких гонок нет.
- Полный снапшот `tests/cosmo`: **2265 passed, 2 skipped, 0 failed,
  0 errors** (135s) — чисто по всей поверхности.

## Out of scope

- Object-store ref (S3/MinIO) вместо audit-file — тот же контракт sink,
  отдельная карточка.
- Single-writer assumption sink-файла (один экземпляр API) — задокументировано.
- Advisory lock только в integration conftest (карточка), не в родительском.
