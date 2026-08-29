# Стек Cosmoport 2.0 — утверждён

> **Не перерешивать.** 2FA sealed 28 авг 2026.

| Слой | Выбор | Запрещено |
|---|---|---|
| **Backend Core** | Python 3.12+ / FastAPI / Pydantic v2 / SQLAlchemy 2 Async | Rails, Node.js, Go |
| **Durable Truth** | PostgreSQL 16 (JSONB + GIN) | MongoDB, Redis как SoT |
| **Queue/Transport** | Valkey 8 (Streams + PubSub) | RabbitMQ, Kafka, Celery |
| **Artifact Storage** | S3-контракт (MinIO / Local FS) | BLOB в PostgreSQL |
| **Edge** | Caddy | Nginx, Traefik |
| **Surface A (Control Station)** | React 18 + TS + Vite + MUI Core + MUI X Data Grid, **Meta Light default** | React Admin как shell, AntD |
| **Inline Editor** | Monaco + Tailwind (внутри Control Station, только по deep-link) | MUI, AntD |
| **Pipeline Graph** | @xyflow/react (MIT, бесплатный) + dagre | React Flow Pro |
| **Execution Runtime** | Playwright + scanner Demon + Fuzzer + Woodpecker | Selenium, GitLab CI (только адаптер) |
| **Auth/KMS** | Better Auth + OpenBao | Keycloak, Blitz OIDC |

## Surface A: Control Station

- MUI Minimal UI template (куплен, лицензия общая с Pure Box Admin)
- Белая тема Meta Light — **default**
- Meta Dark — опциональный переключатель
- MUI X Data Grid с Tree Data и Master-Detail
- @xyflow/react + dagre для Pipeline DAG
- Zustand для локального UI-state

## Inline Code Editor

- Monaco + Tailwind — встроенный редактор, открывается только по deep-link из Security Gate / Finding
- НЕ отдельная поверхность, НЕ на лендинге, НЕ замена VS Code
- Используется для быстрой правки .yaml/.wire/.json конфигов

## Стилевая изоляция

- Tailwind Preflight: изолирован внутри `.cosmo-ide-root`
- MUI CssBaseline: изолирован внутри `.cosmo-control-station`
- Единые CSS-переменные: `--pk-status-*`, `--pk-bg-*`, `--pk-border-*`