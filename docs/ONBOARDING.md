# Onboarding — Cosmoport 2.0 / Operator Control Plane

> Вопрос документа: **Как новому агенту или инженеру войти в контекст платформы Cosmoport 2.0 без распыления внимания?**

---

## Маршрут погружения (шаги 1–7)

### Шаг 1: Что мы строим (10 мин)
Прочитай [`docs/CONCEPT.md`](CONCEPT.md) — полный концепт:
- Cosmoport 2.0 — это **Sovereign Run Control Plane**, центр управления жизненным циклом и безопасностью разработки.
- **8 сущностей** вместо 80+ таблиц старого Rails-портала:
  `Domain → Pipeline → Compile → Run → Batch → Gate → Evidence`.
- **Две UI-поверхности в одном SPA**:
  - Surface A: Control Station (MUI + Data Grid, белая тема Meta Light по умолчанию, для операторов ИБ и релизников).
  - Surface B: Web IDE (Tailwind v4 + Radix + Monaco + xterm, тёмная тема по умолчанию, для инженеров безопасности и dev).

### Шаг 2: Откуда это взялось (15 мин)
Прочитай [`docs/DISCOVERY.md`](DISCOVERY.md) — выжимки из старого Cosmoport 1.0:
- Старый портал был паразитическим клеем над GitLab CI со статусами в Redis (терялись при рестарте).
- Мы сохранили доменную модель и статусную машину, но архитектуру строим с нуля:
  PostgreSQL 16 (durable state), собственный PlanCompiler + Batch DAG, строгие Security Gates и неизменяемый Evidence Ledger (SHA-256).

### Шаг 3: Стек и границы хранения (15 мин)
Прочитай [`docs/STACK.md`](STACK.md) и [`docs/PERSISTENCE.md`](PERSISTENCE.md):
- **Backend:** Python 3.12+ / FastAPI / Pydantic v2 / SQLAlchemy 2 Async.
- **Database:** PostgreSQL 16 (JSONB + GIN).
- **Queue/PubSub:** Valkey 8 (Streams для SSE backlog, PubSub для live telemetry).
- **Artifacts:** S3-контракт (MinIO / локальный FS в тестах).
- **Edge:** Caddy (:8180 prod edge) + Nginx (:5174 same-origin front door SPA+API).
- **Security:** Better Auth + OpenBao (Vault).
- **Запрещено:** React Admin, AntD, React Flow Pro, прямое импортирование модулей Коробки (Pure Box).

### Шаг 4: Текущий бэклог и приёмка (10 мин)
Прочитай [`docs/BACKLOG.md`](BACKLOG.md) и [`PROGRESS.md`](../PROGRESS.md):
- Рабочие карточки имеют статус `⬜ READY`, `🔄 IN PROGRESS`, `✅ DONE`.
- Формат диспетча строго одна строка: `Worker, COS-XXX, D:\prettyk-control-plane\docs\BACKLOG.md`.
- Каждый воркер начинает сессию с чтения `PROGRESS.md` и `git log --oneline -10`.

### Шаг 5: Связь с Коробкой (SecOps) и Хабом (QGFCS)
- **Коробка (`D:\prettyk-secops`):** DAST-сканирование, фаззер, браузерный рантайм Playwright, формирование первичных отчётов/актов.
- **Хаб (`D:\prettyk-qgfcs`):** Intake уязвимостей, триаж, вердикты Quality Gate.
- **Космопорт (`D:\prettyk-control-plane`):** Управление пайплайнами, запуск сборок/прогонов, оркестрация релизов и межзонный трансфер.
- Взаимодействие — **только по REST / Webhook / SSE**. Внутренние импорты запрещены.

### Шаг 6: Первоисточники Discovery (опционально)
Если требуется историческая глубина:
- `D:\cosmo\discovery-final-deliverable.md` — сводный каталог старых сущностей и ER-диаграмма.
- `D:\cosmo\cosmo-dump.sql` — схема БД старого портала.

### Шаг 7: Рабочий здравый смысл
1. Сначала читать текущий backlog и WIP, затем уточнять scope.
2. Принятый стек считать исходной точкой; отклонения поднимать на planning.
3. UI строить после понятного API/контракта.
4. Новые сущности вводить только после проверки границ существующей модели.
5. PO держит planning, backlog и acceptance; реализация принадлежит воркеру.

---

## Ключевые отличия от старого Cosmoport 1.0

| Старый (1.0) | Cosmoport 2.0 |
|---|---|
| Паразитический клей над GitLab CI | Суверенный Control Plane |
| Статусы в Redis (теряются при рестарте) | Статусы в PostgreSQL 16 (durable) |
| GitLab CI YAML как единственный движок | PlanCompiler + Batch DAG + State Machine |
| Нет встроенных Security Gates | Gates в PostgreSQL с историей решений |
| Нет Evidence Chain | SHA-256 цепочка доказательств с привязкой к Run |
| 80+ таблиц, 97 микросервисов | 8 чистых доменных сущностей (модульный монолит) |
| Ant Design + MobX | Dual-Surface: MUI (Light) + Tailwind (Dark) |
