# Build + Deploy основным стеком: Gitea + Woodpecker

> **Дата:** 23 сентября 2026. **Режим:** Cosmo (Strategy). **Статус:** ✅ ПОЛНЫЙ CYCLE ЗАКРЫТ.
> **Директив Максима:** «Для Airlock топим сперва build + deploy основным стеком — gitea + woodpecker».
> **Итог:** все этапы Э1-Э5 реализованы и live-верифицированы (COS-161…COS-170).
> Полный Steel Thread: Domain → Gitea → Woodpecker build → Registry (canonical digest)
> → capture → SBOM + trivy gate → deploy materialize → promotion ЗР→ЗТ→ЗПЭ.
> Suite gate 3607/0/16. Остаточные follow-ups: trivy-бинарь в раннере, боевой syft.

---

## 1. Что уже есть (не начинаем с нуля)

| Слой | Файл | Статус |
|---|---|---|
| Source | `adapters/forge_gitea.py` | ✅ repo, webhook HMAC, read_file, commit, tree |
| CI | `adapters/execution_woodpecker.py` | ✅ v3.5 submit/status/logs/cancel, repo_id lookup, gen pipeline |
| Release-оркестрация | `control_plane/release_orchestration.py` (NX-BOSS-01..04) | ✅ Artifact Truth Table SOURCE(7)/DOCKER(4), Project Graph L0/L1/L2, Release Type engine |
| Registry | `adapters/oci_registry.py`, `sfera_provider.py`, `registry_audit.py` | ✅ OCI V2, push=Basic, Evidence chain на push/pull/health, GAP-режим |
| Transfer | `transfer/*` (COS-136-148) | ✅ package builder/landing/offline_importer/diode/gateway_lease/sbom |
| Deploy route | `api/routes/releases.py` | ✅ `deploy_release` (статусный), `transfer_release` ЗР→ЗТ→ЗПЭ, gates |
| Digest-pin канон | COS-142 | ✅ canonical tag `slug/semver/sha256`, детерминированный digest_pin |

## 2. Гэп (куда топим)

1. **Build не first-class.** `generate_pipeline_yaml` рождает только generic container
   steps (`image` + `commands`). Нет канонического шага `docker build → push в registry`
   с deterministic digest-тагом `<name>:<version>@sha256:<digest>`.
2. **Build→Registry не замкнут.** Собранный образ должен лечь в OCI (зона), digest +
   manifest + SBOM — в PostgreSQL + Evidence Ledger, оттуда забрать deploy. Концы не
   соединены в один поток; нет durable-схемы artifact digest.
3. **Deploy = статусный переход.** `deploy_release` лишь `approved → deploying`
   (status flip), без фактического `pull image → run`. Это оставляем как есть в заходе 1;
   materialize + promotion — следующий заход.

## 3. Целевой поток (Steel Thread)

```
Gitea (source, webhook HMAC)
  → Woodpecker pipeline (docker build + sbom + trivy)
  → OCI registry (canonical digest tag, Evidence push)
  → PostgreSQL (digest/manifest/SBOM durable) + Evidence Ledger
  → deploy_release (статусный, заход 1) / → materialize + promotion ЗР→ЗТ→ЗПЭ (заход 2+)
```

Тестовым target-приложением (dogfooding) служит отдельное несложное приложение —
авторизация + один простой функционал, deployable docker-сервис (пишет Luna).

## 4. Карточки захода 1

| ID | Кто | Зависимость | Что |
|---|---|---|---|
| COS-161 | Luna | — | Тестовое приложение: авторизация + несложный функционал, deployable docker-сервис |
| COS-162 | Boss | COS-161, COS-142 | Build first-class: docker build + push в OCI с canonical digest tag, Evidence push |
| COS-163 | Luna | COS-162 | Build→Registry wiring: durable digest/manifest/SBOM в PG + Evidence, GAP-режим |

Порядок: COS-161 и COS-162 параллельны (161 — target, 162 — механизм); COS-163 строго
после COS-162 (контракт возврата digest). Все три — независимые write-поверхности
(новое приложение / pipeline-gen / schema+evidence), пересечений файлов нет.

## 5. Следующий заход (зафиксировано, не сейчас)

- **Э3** deploy materialize: `deploy_release` из статусного → реальный pull (по digest) + run.
- **Э4** release lifecycle DOCKER_AUDIT (build_image → sbom → trivy → deploy) как честный pipeline.
- **Э5** transfer promotion ЗР→ЗТ→ЗПЭ (offline importer / diode, digest matching, gates pass).

## 6. Риски

- **Woodpecker runner-возможности**: docker build внутри pipeline требует `docker.sock`
  mount или kaniko/podman в executor'е — проверить в COS-162 live, не выдумывать support.
- **Registry provider зоны ЗР**: какой из (local-oci/distribution/sfera) реально поднят —
  определить в COS-162; GAP-режим (push только локальный) уже enforce в registry_audit.
- **Digest канон**: опираемся на COS-142 (`slug/semver/sha256`, no-latest) — не переносим
  логику, ссылаемся.