# COS-114 Acceptance — Workspace Search & Code Grep (2026-09-06)

> Исполнитель: Luna. Зависимость: COS-103 (done). Suite gate: 2713/0.

## Что построено

| Компонент | Файл | Что |
|---|---|---|
| DTO ×2 | `domain/workspace.py` | `WorkspaceSearchMatch` (path, lineNumber, lineContent, matchStart, matchEnd), `WorkspaceSearchResponse` (query, matches, totalMatches, scannedFiles, hasMore) — camelCase, extra="forbid" |
| Маршрут | `routes/workspace.py` | `GET /workspace/search?repo=&q=&branch=&path_prefix=&caseSensitive=&isRegex=&limit=` |

## Механизм поиска

1. `_binding_for_repo` — ownership check (ghost 404)
2. `get_tree(recursive=True)` — полное дерево blob-ов
3. Фильтр бинарных расширений: `_BINARY_EXTENSIONS` (30+ типов: .png/.jpg/.zip/.exe/.ttf/...)
4. `read_file(ref=head_ref)` — чтение каждого текстового файла
5. `pattern.finditer(line)` — построчный regex-матчинг с нумерацией строк
6. Сбор до `limit` с флагом `hasMore`

## ReDoS-защита

- Cap длины паттерна: 1000 символов → 400
- `re.error` catch для инвалидного regex → 400
- Regex-матчинг внутри цикла файлов — не блокирует event loop (FastAPI thread pool)

## Тесты

20/20 в `test_workspace_search.py`:
- 7 DTO: search match, response, camelCase dump, extra forbid
- 13 route: happy path (hello search, regex, case sensitive, path_prefix, no matches, limit, binary skip), ghost 404, anonymous 401, bad repo 400/422, short query 422, invalid regex 400, tree error 502/503

## Edge cases

- Бинарные файлы: отфильтрованы по расширению до read_file, плюс `ValueError` от read_file для непредвиденных бинарных
- `LookupError` от read_file (файл исчез между get_tree и read_file) — молча пропускается
- Transient errors (ConnectionError) — 502/503 через `forge_http_error`
- Пустой репозиторий: 200 с `totalMatches=0, scannedFiles=0`