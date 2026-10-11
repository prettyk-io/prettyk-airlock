# COS-189 — PTY-контур: research/дизайн (wire `runnerTty`, сэндбокс, безопасность)

> **Статус:** research DONE · дизайн-предложение к согласованию · 2026-09-25 · Luna (Airlock).
> **Карточка:** COS-189 (P2, зависимость IDE-CORE-023 — клиент готов и принят).
> **Канон:** `orchestrator/cosmo/capability/BAN.md` (Pure Box boundary), `docs/ARCHITECTURE-DIRECTION.md`
> (§9 execution providers, VM/host collector как отдельная capability), BACKLOG «трактование раннера»
> (сканы — subprocess в `cosmo-api`; отдельный security-runner контейнер не заводим — это был scope-выбор
> для сканов, не индульгенция для интерактивного shell).
> **Канон Web IDE (Vector):** `void-core/web-ide/THREAT-MODEL.md` — «arbitrary command execution: no
> interactive shell in MVP; future shell requires **expiring capability, allowlist, quotas and audit**»;
> `void-core/web-ide/ARCHITECTURE.md` — «Web IDE is … not a runner», «interactive runner shell is not
> an MVP capability». Дизайн ниже обязан удовлетворять этим четырём требованиям; **free-shell — не цель**.
> **Реализация — отдельными карточками после согласования wire с Vector (через Максима).**

## 1. Зачем

IDE-клиент (IDE-CORE-023) построил интерактивную TTY-поверхность (xterm stdin/resize/ANSI) и
**честно деградирует** в read-only, пока сервер не эмитит `pty_open`. Серверной половины нет:
gutter-run пишет «runner не подключён (PTY epic)». Нужен безопасный дизайн интерактивного exec и
согласованный wire — до любой реализации.

## 2. Что уже есть

### 2.1 Клиентский контракт (canonical, Vector — реализован и принят)

- **Output (server→client):** именованные SSE-события на **существующем** потоке
  `GET /api/v1/runs/{run_id}/logs/stream` (COS-109/COS-180):
  - `pty_open` — payload `{run_id, cols, rows}` (geometry; отсутствие → 0);
  - `pty_data` — payload `{data}` — **сырые байты терминала** (ANSI passthrough, строка UTF-8);
  - `pty_close` — payload игнорируется.
- **Input (client→server):** `POST /api/v1/repos/workspace/runs/{run_id}/tty?repo=<owner/name>`
  с JSON `{"kind":"data","data":...}` | `{"kind":"resize","cols":N,"rows":N}` — **только после
  `pty_open`**; 404/405 поглощаются вызывающим (нет PTY → тихо read-only).
- **Дисциплина non-drift:** input/resize инертны до `open`; `data`-фреймы доставляются подписчику
  только пока PTY открыт; `reset()` на run-trigger/rerun шлёт синтетический `close`.
- **Фреймы едут тем же resume/dedupe-потоком**, что и логи: `id` из backlog (COS-180) защищает
  повторные байты при replay; keepalive-активность расширена на `pty_*`.
- **Контрактный пробел (к согласованию):** клиент **не имеет запроса «открой сессию»** — он ждёт
  `pty_open` от сервера. Кто и когда открывает PTY — открытый вопрос (см. §7).

### 2.2 Контур Airlock (что рядом)

- Run: `POST /workspace/run` (COS-108) → Woodpecker pipeline; `cosmo_workspace_runs` хранит
  `repo_owner/repo_name/branch/commit_sha/wp_number/status` — контекст для сэндбокса есть.
- Лог-стрим: COS-109 (деривация шагов из Woodpecker) + COS-180 (SSE `id` + backlog replay,
  kind `runlog`, TTL 900 c, MAXLEN ≈2000).
- Auth: `require_principal` + ownership домена; SSE — short-TTL ticket (COS-079).
- Аудит: `cosmo_audit_events` (`record_system_event`).
- «Раннер» в Airlock сегодня: **Woodpecker agent** (CI: docker build+push; шаги — контейнеры,
  монтирует `docker.sock` — это его рабочая модель) и **subprocess-сканы в `cosmo-api`**
  (trivy/syft — scope-решение для сканов). Интерактивного exec нет.

## 3. Wire `runnerTty` — серверная половина (предложение)

| Аспект | Решение |
|---|---|
| **Транспорт** | **SSE (output) + POST (input)** — как в клиенте. WS отклонён: дублировал бы resume/dedupe/ticket-машинерию COS-180, потребовал бы нового клиента (зона Vector) и второго канала прав. POST для stdin — низкочастотный (нажатия/вставки), батчинг возможен без смены протокола |
| **Envelope** | payload'ы несут `run_id` (как лог-события); `pty_data.data` — UTF-8-строка; не-UTF8/бинарные потоки — вне скоупа (при нужде — base64-расширение, отдельное согласование) |
| **Id/order** | фреймы публикуются в **тот же backlog `runlog:<run_id>`**, что и логи → порядок log↔pty сохраняется при replay; курсоры лог-стрима pty-фреймы **не** сдвигают (не `_LOG_ID_EVENTS`) |
| **Reconnect** | SSE-обрыв не убивает PTY: процесс живёт в сэндбоксе, output реплеится из backlog по `last_event_id`; при реконнекте сервер может пере-эмитить `pty_open` (свежий id) для восстановления геометрии |
| **Auth** | POST — обычный bearer (`require_principal`) + ownership домена + привязка к run; SSE — как сегодня (ticket). Отдельных «pty-токенов» не вводим |
| **Capability (канон)** | открытие сессии — по **expiring capability** (короткий TTL, scope: principal+repo+run, single-use при open / refresh при re-attach), а не только по bearer — требование threat-model. Хранение — Valkey (паттерн `sse_tickets` `ot1`); отзыв — kill-switch |
| **Ошибки (typed)** | нет сессии/не открыт → `409 PTY_NOT_OPEN`; фича выключена/сэндбокс недоступен → `503 PTY_UNAVAILABLE`; чужой run → 404 (anti-enumeration); input сверх лимита → `413/429`. Форма — единый конверт COS-058 |
| **Lifetime** | сессия привязана к `(repo, run_id)` + principal; **single-flight** (одна сессия на run); idle-TTL (напр. 15 мин) + hard-TTL (напр. 60 мин); kill при `run_finish`/cancel/rerun; явный `pty_close` при выходе процесса |
| **Открытие сессии** | **Открытый вопрос** (§7): (a) client `open`-frame; (b) opt-in флаг на `POST /workspace/run`; (c) авто-открытие — отклоняем (неявный exec) |

## 4. Модель сэндбокса (варианты)

| Вариант | Оценка |
|---|---|
| **A. Subprocess в `cosmo-api`** (как сканы) | ❌ **Отклонён.** Интерактивный shell в control plane = RCE-эквивалент при компромате API: в контейнере — DB-DSN, vault-креды, сеть ко всем сервисам. Сканы — детерминированные бинари с фиксированным argv; shell — произвольный ввод |
| **B. Ephemeral-контейнер на сессию (отдельный sandbox-сервис)** | ✅ **Рекомендация.** Одноразовый контейнер: workdir = checkout `commit_sha` (read-only копия/tmpfs), изоляция по профилю §5, kill по TTL/lifecycle. Требует **нового сервиса** — инфра-решение владельца (ср. «отдельный security-runner не заводим» — там scope сканов; здесь риск-профиль иной, trade-off явный) |
| **C. Woodpecker как транспорт (интерактивный шаг)** | ❌ Отклонён: у Woodpecker нет интерактивного exec-API; связывать CI-агент (docker.sock) с пользовательскими сессиями — расширение blast radius |

> **Канон-фильтр (Vector, THREAT-MODEL):** сессия обязана нести **expiring capability, allowlist,
> quotas, audit**. Значит рекомендуемая форма — **команд-скоупная сессия**: allowlist-энтрипоинт в
> сэндбоксе (объявленные инструменты/шаги репозитория), а не unrestricted `/bin/bash`. Free-shell
> потребовал бы снять allowlist — противоречит канону, в дизайн не берём.

## 5. Профиль изоляции (sandbox, рекомендация B)

- non-root user; `cap-drop ALL`; `no-new-privileges`; runtime seccomp-дефолт;
- **allowlist-энтрипоинт:** сессия стартует объявленную команду/инструмент из allowlist образа
  сэндбокса, а не произвольный shell (требование threat-model);
- **expiring capability:** TTL-капабилити на open/input, scope principal+repo+run; отзыв и
  операторский kill-switch;
- rootfs **read-only** + `tmpfs` на `/workspace` и `/tmp`;
- **без** `docker.sock`, **без** host-mount'ов, **без** доступа к внутренним сервисам
  (DB/OpenBao/MinIO/registry) — сеть: `none` по умолчанию (egress к forge — только если
  подтвердится сценарий; тогда allowlist, как в §9 ARCHITECTURE-DIRECTION про VM/host collector);
- лимиты: cpu/mem/pids/fs-size; TTL idle+hard; максимум сессий на principal/стенд;
- секреты в сэндбокс **не** прокидываются; checkout — публичный код репозитория на `commit_sha`;
- запись в репозиторий из PTY невозможна by construction (read-only workdir; коммит — только через
  CAS-ручки workspace).

## 6. Границы безопасности (канон)

- **PTY ≠ замена безопасному runner'у (стоп-линия roadmap).** Гейты/сканы/CI остаются
  единственным путём «верифицированного» исполнения; PTY — интерактивное исследование. Канон
  Vector: Web IDE — «not a runner», interactive shell — не MVP-капабилити.
- **Fail-closed:** фича по умолчанию **выключена** (`PK_PTY_ENABLED=false`); нет сэндбокса →
  `pty_*` не эмитятся, `POST /tty` → typed 503; клиент честно остаётся read-only (non-drift уже
  реализован). Input без открытой сессии → typed 409 (сервер не доверяет клиентскому гейту).
- **Аудит:** `pty_open`/`pty_close`/отказы/лимиты — в `cosmo_audit_events`
  (кто, repo, commit_sha, run_id, session_id, exit); без silent exec.
- **Лимиты:** bytes/sec и max-frame на input; max sessions; kill-switch (оператор может погасить
  все сессии); запрещено всё из BAN.md (control plane не управляет процессами локально — exec
  делегируется сэндбокс-провайдеру).
- **PTY-сессии не дают доступа к секретам контура** и не могут эскалировать в API-поверхности.

## 7. Открытые вопросы для согласования с Vector

1. **Открытие сессии:** client `open`-frame (`{kind:'open', cols, rows}`) vs opt-in флаг на run
   (`POST /workspace/run {interactive: true}`) vs иное. Рекомендация: **opt-in на run** — сессия
   рождается из намерения прогона, клиент не меняет словарь фреймов; но решение — Vector.
2. **`pty_close`:** добавить ли `exit_code`/`reason` (текущий клиент игнорирует extras — расширение
   безопасно)? Нужно ли отдельное событие `pty_exit`?
3. **Envelope:** подтвердить `run_id` в payload'ах `pty_*` (как в лог-событиях).
4. **Батчинг stdin:** допустим ли серверный coalescing (склейка нажатий в окне ~16 мс) без смены
   клиента — влияет на latency/нагрузку.
5. **Геометрия:** минимальные значения (клиент шлёт cols≥2, rows≥1); что считать валидным на сервере.
6. **Allowlist:** что в allowlist первой версии — инструменты образа сэндбокса (git/ls/cat/…) vs
   объявленные шаги пайплайна репозитория vs оба; кто владеет списком (Vector / владелец продукта)?
7. **Capability-выдача:** где выпускается expiring capability (endpoint рядом с ticket-выдачей?) и
   её формат; re-attach без повторной выдачи или с refresh.

## 8. Предложение эпик-нарезки (после согласования)

| # | Карточка (предложение) | Кто | h | Зависит |
|---|---|---|---:|---|
| 1 | **PTY-SANDBOX-1** — sandbox-сервис: образ с инструментами, allowlist-энтрипоинт, профиль изоляции §5, lifecycle API, smoke изоляции (negative: нет сети/docker.sock/host FS) | инфра/Boss | 8-12 | решение владельца о новом сервисе |
| 2 | **PTY-SERVER-2** — session manager в `cosmo-api`: registry (run→session), single-flight, TTL/kill, аудит, права, capability-выдача (expiring, scoped), `POST /tty` + typed ошибки, feature-flag default-off | Luna | 6-8 | 1 |
| 3 | **PTY-STREAM-3** — эмиссия `pty_open/pty_data/pty_close` на лог-стрим через backlog `runlog` (ids/replay COS-180), interplay с курсорами, reconnect | Luna | 3-4 | 1,2 |
| 4 | **PTY-HARDEN-4** — security-матрица (fail-closed, лимиты, отказы, kill-switch), live-смоук (реальная сессия: echo/ls/resize/exit), аудит-проверки | Luna | 4-6 | 3 |
| 5 | **PTY-FE-5** — открытие сессии из drawer (после п.7.1), gutter-run `.wire` через PTY-исполнитель (если решим), UX-баннеры | Flash | 4-6 | 1-4 + решение Vector |

Порядок: 1 → 2 → 3 → 4 (жёсткая цепочка, одна поверхность) → 5 параллельно после 3.

## 9. Риски

- **Новый сервис** — инфра-расширение (ср. канон «не заводим» для сканов): нужно явное решение
  владельца; альтернатива (subprocess в API) отклонена по §4.
- **Интерактивный exec — самая рискованная поверхность продукта**: без полного профиля §5 не
  реализовывать; поэтапно: сначала sandbox + harden, только потом UX.
- **Контрактный пробел open-intent** — без решения клиент навсегда останется read-only (безопасно,
  но фича не работает).
- **Нагрузка stdin-POST** — при агрессивном вводе; митигация: coalescing (п.7.4) + лимиты.

## 10. Согласование и дальше

- Wire-предложение (§3, §7) готово к передаче **Vector** через Максима; после согласования —
  нарезка карточек эпика (§8) и реализация.
- До согласования серверная половина не начинается; клиент уже безопасно деградирует.
