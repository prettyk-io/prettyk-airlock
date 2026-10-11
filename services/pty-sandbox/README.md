# PTY sandbox — сервис изолированных сессий (PTY-SANDBOX-1 / 1.1)

> **Статус:** шаги 1 и 1.1 PTY-эпика (§8 дизайна `docs/research/2026-09-25-cos-189-pty-contour-design.md`).
> **Default-off:** сервис поднимается только с compose-профилем `pty`.
> **Границы:** команд-скоупная сессия (не free-shell); PTY ≠ замена безопасному runner'у.

## Что это

Внутренний сервис для `cosmo-api`: создаёт **ephemeral-контейнер на сессию** из
образа с allowlist-инструментами и управляет lifecycle (create/stop/status/touch),
**attach-каналом** (stdin/stdout/resize) и **доставкой workspace** (tar → `/workspace`,
read-only для процесса).

- allowlist-энтрипоинт (`sandbox-run`): сессия стартует только объявленный
  инструмент, не произвольный shell;
- non-root, `cap-drop ALL`, `no-new-privileges`, read-only rootfs + tmpfs
  (`/workspace` — read-only для процесса, `/tmp` — скретч), `network none`,
  без docker.sock/host-mount'ов;
- лимиты cpu/mem/pids/fs; TTL idle+hard; аудит open/exit/kill/deny/attach/delivery (JSONL).

## Запуск

```powershell
# 1. Образ сессии (allowlist-инструменты)
docker build -t pty-sandbox-base:local services/pty-sandbox/image

# 2. Сервис (default-off: только с профилем pty)
docker compose -f services/docker-compose.yml --profile pty up -d pty-sandbox

# 3. Live-smoke (сам гоняет build+up+cleanup)
python services/scripts/smoke-pty-sandbox.py           # шаг 1: изоляция/TTL/аудит
python services/scripts/smoke-pty-sandbox-attach.py    # шаг 1.1: attach + delivery
```

API — внутренний (`cosmo-net`), публикация только `127.0.0.1:8190` для диагностики.

## API (внутренняя граница)

Lifecycle:

```bash
curl -X POST http://127.0.0.1:8190/sessions -H "Content-Type: application/json" -d '{
  "run_id": "run-1", "principal": "operator", "repo": "cosmo/pipeline-fixture",
  "commit_sha": "deadbeef", "tool": "cat", "ttl_s": 60 }'

curl http://127.0.0.1:8190/sessions/<sid>          # статус (exit_code после выхода)
curl http://127.0.0.1:8190/sessions
curl -X DELETE http://127.0.0.1:8190/sessions/<sid>
curl -X POST http://127.0.0.1:8190/sessions/<sid>/touch
```

### Attach (решение 1.1: HTTP-chunked, не WS)

Выбор транспорта зафиксирован: **HTTP-chunked** — нулевые новые зависимости
(Starlette на выдаче; у cosmo-api — httpx) и та же модель «out-стрим + POST на
вход», что в дизайне COS-189 для IDE. WS отклонён осознанно (дуплекс не нужен,
а лишние зависимости — нужны).

```bash
# out: сырой PTY-поток (octet-stream, live-only: история вывода — ответственность
# потребителя SERVER-2/STREAM-3); заканчивается при выходе процесса или обрыве клиента
curl -N http://127.0.0.1:8190/sessions/<sid>/attach

# in: stdin — chunked body; конец тела = отключение канала
# (EOF процессу docker 7.2 не доставляет — завершение сессии через stop/TTL)
curl -X POST --data-binary @- -H "Transfer-Encoding: chunked" \
  http://127.0.0.1:8190/sessions/<sid>/stdin

# resize (клампится: rows<=500, cols<=1000; нечисло/<=0 → 422)
curl -X POST http://127.0.0.1:8190/sessions/<sid>/resize \
  -H "Content-Type: application/json" -d '{"rows": 40, "cols": 120}'
```

- exit-code наружу: после конца out-потока — `GET /sessions/<sid>` → `exit_code`;
- один активный stdin-стрим на сессию (второй → 409);
- ввод/вывод/resize продлевают idle-TTL;
- обрыв клиента → аудит `attach_close` (`client_disconnect`).

### Доставка workspace (checkout)

```bash
# raw tar (application/x-tar) → /workspace, read-only для процесса
curl -X POST --data-binary @checkout.tar -H "Content-Type: application/x-tar" \
  http://127.0.0.1:8190/sessions/<sid>/workspace
```

Политика (fail-closed): только regular files и каталоги; относительные безопасные
имена (без `/`, `..`, `\`, дисков); владелец root:root, файлы 0644, каталоги 0755 —
доставленный код **read-only для процесса сессии** (uid 1000, скретч — `/tmp`).
Лимиты: размер архива, число записей, распакованный объём (env ниже).
Идемпотентность: повторная доставка **заменяет** содержимое (wipe + relayout) — без дублей.
Ответ: `{files, dirs, bytes, delivered_at}`; последняя доставка видна в
`GET /sessions/<sid>` → `workspace_delivery`.
Механика: exec `head -c N | tar -x` — ro-rootfs контейнера блокирует docker
`put_archive` (daemon: "rootfs is marked read-only"); head читает ровно объём
архива и завершается сам.

## Конфиг (env сервиса)

| Env | Default | Значение |
|---|---|---|
| `PTY_SANDBOX_IMAGE` | `pty-sandbox-base:local` | образ сессии |
| `PTY_SANDBOX_IDLE_TTL_S` | `900` | idle-TTL (touch/ввод/вывод продлевают) |
| `PTY_SANDBOX_HARD_TTL_S` | `3600` | hard-TTL сессии |
| `PTY_SANDBOX_MAX_SESSIONS` | `4` | максимум одновременных |
| `PTY_SANDBOX_AUDIT_LOG` | `/var/log/pty-sandbox/audit.jsonl` | аудит (volume) |
| `PTY_SANDBOX_ATTACH_CHUNK` | `65536` | размер читаемого PTY-чанка |
| `PTY_SANDBOX_MAX_DELIVERY_MB` | `32` | лимит размера tar-архива |
| `PTY_SANDBOX_MAX_DELIVERY_FILES` | `2000` | лимит числа записей архива |
| `PTY_SANDBOX_MAX_UNPACKED_MB` | `48` | лимит распакованного объёма |
| `PTY_SANDBOX_DEBUG` | `0` | debug-логи attach-чтений/stdin-записей (шов, для отладки) |

## Аудит (JSONL)

`session_create/exit/kill/denied`, `attach_open/close/denied`,
`attach_stdin_open/close`, `delivery_ok/denied` — session/run/tool, причины
отказов (allowlist, лимиты, пути, тип архива). Интеграция с
`cosmo_audit_events` — PTY-SERVER-2.

## Границы (швы следующих карточек)

- Session manager в `cosmo-api` + wire `runnerTty` — **PTY-SERVER-2** (Luna;
  ждёт согласования с Vector).
- Наполнение allowlist — открытый вопрос §7.6 дизайна (владелец: Vector/PO);
  v1 — read-only набор (git/ls/cat/grep/find/head/tail/wc).
- Replay истории PTY-вывода — ответственность SERVER-2/STREAM-3; attach отдаёт
  live-поток с момента подключения (без `logs`).
