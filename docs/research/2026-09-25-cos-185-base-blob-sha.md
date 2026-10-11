# COS-185 Acceptance — Per-file `base_blob_sha` в multi-file commit (2026-09-25)

**Выполнил:** Luna · **Итог:** PASS · **Новые тесты:** 13 · **Suite gate:** 3588/0 · **Live-smoke:** 13/13

## Что сделано

Follow-up COS-181: файловые конфликты (`exists`/`missing`) теперь несут в typed 409
`expected_sha` = **переданную клиентом файловую базу**, а не `null` — точный 3-way
для merge-loop (IDE-CORE-005: `base_blob_sha`).

### DTO (`domain/workspace.py`)

- `WorkspaceFileChange.base_blob_sha` (alias `baseBlobSha`, optional) — валидатор
  `validate_head_sha` (полный sha или ≥7-hex префикс; `""`/None → None). Зеркало legacy
  `WorkspaceContentsFileChange` (COS-107) — имена и семантика совпадают.

### Route (`api/routes/workspace.py`)

- Файловые конфликты (`_workspace_conflict`) получили `expected_sha=ch.base_blob_sha`:
  - create-exists → `kind=exists`, `expected_sha` = база, `actual_sha` = текущий blob sha;
  - update/delete-missing → `kind=missing`, `expected_sha` = база, `actual_sha` = null.
- Без `baseBlobSha` — прежнее поведение COS-181 (`expected_sha=null`). Новых
  precondition'ов нет: поле — носитель базы, не CAS-проверка (branch-level CAS остаётся
  за `expectedHeadSha`, COS-181).

## Конверт (актуальная форма файлового конфликта)

```json
{
  "error": {
    "code": "WORKSPACE_CONFLICT",
    "message": "create conflict on <path>: file already exists at <branch> (concurrent commit; refresh workspace)",
    "details": {
      "kind": "exists",
      "expected_sha": "<переданная база | null>",
      "actual_sha": "<текущий blob sha>",
      "paths": ["<path>"]
    }
  }
}
```

## Совместимость

- Старые клиенты (без поля) — поведение и форма не меняются относительно COS-181.
- Поле принимается и на **успешном** пути (игнорируется — коммит проходит).
- `expectedHeadSha` (branch-level) по-прежнему проверяется **до** файловой работы —
  при обоих полях конфликт head-уровня имеет приоритет.
- Битый формат базы → 422 (валидация DTO), записей нет.
- Legacy `POST /workspace/commit` (COS-107) не тронут.

## Верификация

- `tests/cosmo/test_workspace_commit_conflict.py` — **+13** (5 DTO: alias/default/empty/
  malformed/delete; 7 route: exists+база → `expected_sha`=база и `actual_sha`=blob;
  update/delete-missing+база; без базы → null; база на успешном пути; битый → 422;
  head-level приоритет; + 1 контракт: `baseBlobSha` в OpenAPI-схеме). Файл целиком —
  **33 passed**; с COS-124-файлом — 63 passed.
- Регресс-сет workspace/openapi/sse/forge — **820 passed / 0 failed**.
- OpenAPI реген из живого `app.openapi()` — `baseBlobSha` в `WorkspaceFileChange`;
  json==yaml==live.
- **Suite gate: 3588 passed / 24 skipped / 0 failed** (433 s).
- **Live-smoke (живой стенд, реальный login+HTTP, read-only):** **13/13 PASS** —
  `payments/api`: create на существующий `README.md` с базой → 409 `exists`
  (`expected_sha`=база, `actual_sha`=текущий blob, `paths=[README.md]`); update на
  несуществующий путь с базой → 409 `missing` (`expected_sha`=база, `actual_sha`=null);
  без базы → `expected_sha=null`; битый формат → 422; голова ветки не сдвинулась.
  Скрипт: `D:\Infra\Temp\opencode\cos185_live_smoke.py` (временный артефакт, не в репо).

## Артефакты

- `orchestrator/cosmo/domain/workspace.py` — поле `base_blob_sha` + валидатор.
- `orchestrator/cosmo/api/routes/workspace.py` — `expected_sha=ch.base_blob_sha` в двух конфликтах.
- `orchestrator/tests/cosmo/test_workspace_commit_conflict.py` — +13 тестов.
- `docs/cosmo-openapi.{json,yaml}` — регенерация.
