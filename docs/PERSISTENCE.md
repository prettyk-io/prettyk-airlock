# Persistence Boundary — переход от Live к MinIO

> Полный документ: `D:\prettyk-dev\sanctuary\cosmoport2\persistence-and-minio.md`

## Короткий ответ

**MinIO пора интегрировать.** Но он не заменяет Live и не является базой сущностей.

```text
PostgreSQL  — сущности, состояния, индексы, аудит
MinIO/S3    — большие неизменяемые бинарные артефакты
Valkey      — ephemeral queue/pubsub/live transport
API/SSE     — новая поверхность чтения и live-доставки
Live :8767  — временный compatibility facade → удаляется
```

## Что Live хранит сейчас (в prettyk-dev)

| Текущий объект | Где | Целевой владелец |
|---|---|---|
| checks_registry.json | reports/live/ | PostgreSQL checks/pipelines |
| runs_index.ndjson | reports/live/ | PostgreSQL runs + projections |
| diary.ndjson | reports/live/ | PostgreSQL run_events + Valkey fan-out |
| run_summary.json | reports/live/ | PostgreSQL run_summaries |
| artifact_index.json | reports/live/ | PostgreSQL artifacts + retention |
| discovery_*.json | reports/live/ | PostgreSQL discovery + MinIO object |
| reports/runs/<id>/ | local fs | PG metadata + MinIO objects |
| reports/video/ | local fs | MinIO object |

## ArtifactStore contract (единый интерфейс)

```text
ArtifactStore.put(stream, key, content_type, metadata) → ArtifactRef
ArtifactStore.get(key) → stream/bytes
ArtifactStore.head(key) → ArtifactMetadata
ArtifactStore.delete(key) → result
ArtifactStore.verify(ref) → bool
```

Реализации:
- `LocalArtifactStore` — Pure Box / тесты / airgap
- `S3ArtifactStore` — Enterprise / MinIO / Ceph

## Порядок интеграции

1. Persistence inventory + contract freeze
2. ArtifactStore с Local backend
3. MinIO в Enterprise-профиль
4. Backfill существующих artifacts
5. Durable records в PostgreSQL
6. Control API и SSE
7. **Только после этого** — удалить Live UI/server

## Приёмочные gates

- После рестарта исчезновение Valkey не удаляет run/status/evidence
- API восстанавливает run history из PostgreSQL
- Каждый бинарный artifact имеет PG record + checksum + object key
- Pure Box работает на LocalArtifactStore без MinIO
- Live UI выключен, но все старые сущности доступны через новый API
- **Никакого флуда микро-событиями в Valkey/SSE:** фаззинг передаёт только агрегированные события, тики прогресса ≤2 Гц, сырой дамп в MinIO