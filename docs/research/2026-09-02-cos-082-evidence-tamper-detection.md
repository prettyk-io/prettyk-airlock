# COS-082 — Honest tamper detection on the durable evidence ledger

Дата: 2026-09-02 · Воркер: Luna · Статус: DELIVERED
Задача: docs/BACKLOG.md (COS-082)

## Проблема

`verify_and_get` пересчитывал хеши записей **от текущих строк таблицы**.
Подмена любой строки (UPDATE content_hash / DELETE середины цепочки) делала
подделку «легальной головой»: verify честно пересчитывал хеши уже
мутированных данных и рапортовал `verified=True`. Детектора там не было —
была рекалькуляция.

Дополнительно: таблица `evidence_ledger` не хранила никаких якорей цепочки
(prev/hash) — проверить целостность по сохранённым данным было невозможно
в принципе.

## Дизайн

Миграционная цепочка заморожена (правило проекта) — **новых колонок нет**.
Якоря цепочки живут в существующем JSONB-поле `provenance_json`:

- `provenance_json["_chain_prev_hash"]` — хеш предыдущей записи;
- `provenance_json["_chain_hash"]` — хеш самой записи.

`GENESIS_HASH = "0" * 64`.

### Канонический снапшот записи (`entry_snapshot`)

Замороженный состав полей (исключая якоря):
`id, run_id, batch_id, type, content_ref, content_hash,
created_at.isoformat(), provenance` — сериализация
`json.dumps(..., sort_keys=True, ensure_ascii=False, default=str)`.

`compute_entry_hash` = `sha256` канонического JSON (hexdigest).

### Запечатывание (`seal_entry`)

`seal_entry(row, prev_hash)`: очищает якорные ключи из provenance_json,
считает хеш от чистого снапшота, затем добавляет якоря в тот же dict.

**Критичный порядок операций (баг найден при ревью):** seal требует
финальные `id`/`created_at`. Python-side дефолты ORM применяются на
flush, поэтому write-path — `session.add(entry)` → `await session.flush()`
→ `seal_entry(...)` → commit. Seal до flush подписывал `id=None`, все
якоря получались битыми. Изменение `provenance_json` после flush уходит
отдельным UPDATE на commit — в транзакции это атомарно.

### Верификация (`verify_rows` / `verify_and_get`)

Сверяется **сохранённый** якорь с **сохранённым** содержимым:

| Детект | Условие |
|---|---|
| `hash_mismatch` | пересчитанный хеш ≠ сохранённого `_chain_hash` (строку мутировали после запечатывания) |
| `broken_link` | `_chain_prev_hash[i] ≠ _chain_hash[i-1]` (для первой — genesis: строку удалили/вставили в середину) |
| `unsealed` | нет якорей в provenance_json (строка не прошла write-path) |
| `replay` | дубликат content-fingerprint (включая id) |

Полная переподпись суффикса цепочки недетектируема без внешнего якоря
головы (публикация last_hash вне БД) — вне scope карточки, задокументировано
как честная граница threat model.

### Ответ API (GET /api/v1/runs/{run_id}/evidence)

`chain` (entries/length/verified/last_hash), `verified`,
`integrity`: `"ok" | "tampered" | "unsealed"`,
`tampered_entries`, `tampered_details` (index/entry_id/reason/
stored_hash/recomputed_hash), `broken_links` (index/entry_id/
expected_prev_hash/stored_prev_hash), `unsealed_entries`,
`tampered_chain`, `replay_count`, `total_entries`.
Компат-ключи COS-064 сохранены.

## Изменения

- `orchestrator/cosmo/ledger/evidence_chain.py` — GENESIS_HASH,
  entry_snapshot, compute_entry_hash, seal_entry, verify_rows,
  переписанный verify_and_get. Исправлен баг классификации:
  broken_links раньше не учитывались в integrity (deleted-row тест
  давал 'ok').
- `orchestrator/cosmo/ledger/evidence_writer.py` — новый:
  `last_chain_hash` (порядок created_at desc, id desc; unsealed
  пропускаются; genesis для пустого run'а) и
  `append_evidence_entry` (add → flush → seal).
- `orchestrator/cosmo/api/routes/evidence.py` — docstring контракта
  ответа (результат возвращается как dict, новые поля текут сами).
- `orchestrator/tests/cosmo/test_evidence_verification.py` — юниты
  переведены на sealed-контракт (_sealed_rows helper), новые тесты:
  tamper content_ref/content_hash/provenance_json/type с указанием
  звена, DELETE середины → broken_link, unsealed-строка, replay.
- `orchestrator/tests/cosmo/integration/test_evidence_tamper_detection.py`
  — новый интеграционный сьют (8 тестов): sealed-цепочка ок (якоря
  проверяются в БД, genesis у головы), tamper каждого поля,
  DELETE средней строки, unsealed, детерминизм ×3 на трёх run'ах.
- `orchestrator/tests/cosmo/integration/test_steel_thread_integration.py`
  — `_add_evidence` переведён на `append_evidence_entry`; tamper-тест
  на новом контракте (integrity=="tampered", verified=False,
  tampered_entries==[0], reason=="hash_mismatch").

## Инфраструктурные находки (не по карточке, но важны)

1. **«Фантом 409» COS-080 разгадан.** Wipe-зонды (pre/post счётчики)
   доказали: wipe чистит (post=0), а 409 на создание домена был
   **дублем `_create_domain(h, DOM)` внутри одного теста** — скрипт
   унификации доменов превратил второй вызов `_create_domain(h,
   "it-neg2")` в DOM. В tamper-сьюте то же: детерминистический тест
   звал setup 3 раза в цикле. Фикс — идемпотентный `_ensure_domain`
   (201 или 409). Никакого ghost-стейта в PG не было.
2. **Гонка тестовых прогонов на общем :5433.** Параллельные pytest
   других воркеров вайпают те же таблицы посреди чужих тестов → FK
   violations / StaleDataError / случайные 409. Решение для acceptance:
   второй изолированный тестовый PG (`cosmo-test-pg-luna`, host :5434,
   та же postgres:16-alpine) + официальный override
   `COSMO_TEST_DATABASE_URL` (порт 5432 запрещён guard'ом, 5434 — нет).
   Код не менялся. Рекомендация в бэклог: per-worker test PG.
3. **Чужой WIP, не блокирующий интеграцию:** COS-081 (Boss) вынес gate
   decision trail на отдельный `GateTrailBase` — общий
   `CosmoBase.metadata.create_all` его не создаёт, а роут gates пишет
   туда на каждом решении. В integration conftest добавлен
   ImportError-safe create_all/wipe для trail-таблицы (аддитивно,
   помечено COS-081 WIP).

## Верификация

- Юнит `test_evidence_verification.py`: **24 passed** (стабильно).
- Интеграция (весь integration-сет, изолированный PG :5434): **20
  passed ×3** (10.3/10.4/13.1s) — 12 COS-080 + 8 COS-082.
- Параллельный прогон integration + миграционные (20 + 24): integration
  зелёный; миграционные 23/24 — `TestScratchHygiene::
  test_cycle_preserves_main_db` падает и соло (не моя параллель,
  не моя поверхность — мой diff не трогает миграции; воспроизводится
  на фоне активного WIP Boss по миграциям).
- Детерминизм tamper-детекта: 3 run'а в одном тесте, три полных
  прогона сьюта — результат стабилен.

## Out of scope

- Внешний якорь головы цепочки (публикация last_hash вне БД).
- Миграционные колонки (frozen chain — якоря в JSONB).
