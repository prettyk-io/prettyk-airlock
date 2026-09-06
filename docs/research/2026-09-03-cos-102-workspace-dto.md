# COS-102 — Workspace DTO (acceptance)

Дата: 2026-09-03 · Worker: Dev · Статус: готово к приёмке

## Что требовалось (карточка Boss, 8-12h, P1, dep COS-100)

Pydantic v2 DTO в `orchestrator/cosmo/domain/workspace.py`:
Bootstrap/Tree/Blob Request+Response, CAS `base_blob_sha`, path traversal
guard, head_sha обязателен для CAS-операций, unit-тесты валидности и
ригидности. DTO десериализуются из типов `prettyk-ide`
(`src/workspace/types.ts`). Реализация роутов — NOT in scope (COS-103
Luna), contract-тесты/OpenAPI — COS-104 Flash.

## Решения

1. **camelCase-контракт через алиасы, не через имена полей.** Канон —
   `types.ts` (headSha). Python-поля snake_case + явные
   `Field(alias="headSha"/"baseBlobSha")`:
   `model_dump_json(by_alias=True)` даёт ровно ключи TS-интерфейсов,
   `model_validate_json` ест TS-пейлоады. `populate_by_name=True` —
   snake_case тоже принимается (роутам COS-103 удобно).
2. **Ригидность: `extra="forbid"`** на всех 6 DTO + TreeEntry —
   незнакомое поле = ValidationError, драйф FE/BE ловится на границе,
   не тишиной.
3. **Traversal guard на уровне Pydantic** (`validate_repo/branch/
   head_sha/tree_path` + `WorkspaceContractError`): `..`, `.`, пустые
   сегменты, абсолютные пути, backslash, drive-буквы (":"), NUL,
   whitespace-края — reject до ForgeAdapter. head_sha: 7..64 hex
   (сокращённые и uppercase ок). repo строго "owner/repo".
4. **CAS**: `head_sha` обязателен в Tree/Blob запросах (bootstrap —
   нет, там branch опционален → default branch резолвит COS-103);
   `WorkspaceBlobResponse.base_blob_sha` обязателен — DTO не даёт
   забыть базу черновика. `encoding` Literal["utf-8"], capabilities
   Literal["read","draft","commit","run"], entry status M|U|D,
   authorization allow|deny — зеркально types.ts.

## Файлы

- `orchestrator/cosmo/domain/workspace.py` — новый (DTO + guard-функции).
- `orchestrator/tests/cosmo/test_workspace_dto.py` — новый, 75 тестов:
  happy-пути всех DTO, extra="forbid" на каждом, traversal-матрица
  (path ×15 reject / ×5 accept, repo ×9, branch ×7, head_sha ×6),
  CAS-требования (head_sha missing → reject; base_blob_sha missing →
  reject), литералы, camelCase round-trip.
- **Чужие поверхности не тронуты**: repos.py (mock substrate — COS-103),
  routes, openapi, contract-тесты — по границам карточки.

## Верификация

| Проверка | Результат |
|---|---|
| `test_workspace_dto.py` | **75/75** |
| TS-контракт: литералы и ключи сверены с живым `D:\prettyk-ide\src\workspace\types.ts` | mirror-тест зелёный (skip, если чекаута нет на машине) |
| Импорт приложения целиком | `from orchestrator.cosmo.api.main import app` OK |
| **Suite gate** | **PASS: 2518 passed / 8 skipped / 0 failed** |

## Примечания для COS-103 (Luna) / COS-104 (Flash)

- Роуты берут DTO из `orchestrator.cosmo.domain.workspace`; ошибки
  `WorkspaceContractError` (ValueError) внутри Pydantic-валидации
  превращаются в 422 автоматически; при ручном вызове guard-функций —
  мапить в 400.
- FE types.ts пока НЕ содержит `baseBlobSha` и request-типы — добавить
  на стороне prettyk-ide при интеграции (COS-104/FE follow-up); BE уже
  отдаёт `baseBlobSha` в by_alias-дампе.
- `WorkspaceTreeResponse.entries` — плоское рекурсивное дерево; если
  Luna решит отдавать неплоско — сначала согласовать изменение types.ts.
