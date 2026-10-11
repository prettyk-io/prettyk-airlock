# COS-190 — Source-SAST: research/дизайн (SonarQube / CodeScoring)

> **Статус:** research DONE · дизайн-предложение к решению владельца · 2026-09-25 · Luna (Airlock).
> **Карточка:** COS-190 (P2, SOURCE_AUDIT-кандидат; зависимости нет).
> **Канон:** `docs/CANONICAL_KINDS_AND_LC_STEPS.md` (шаги 1.4 SonarQube / 1.6 CodeScoring),
> `docs/COSMOPORT2-CANONICAL-MONOLITH.md` §8.3-8.5 (source- vs container-профили),
> `control_plane/build_modes.py` (политики PUREK/SECURITY_COSMO), `capability/BAN.md`
> (Cosmo не управляет процессами локально), `docs/ARCHITECTURE-DIRECTION.md` §9.
> **Реализация — отдельными карточками после решения владельца.**

## 1. Зачем

SOURCE_AUDIT — последний крупный непочатый кандидат: гейты закрывают container/artifact
(trivy/syft/grype приняты), исходники — нет. Канон УЖЕ описывает шаги 1.4 (SonarQube, опциональный,
`TERMINATE_ON_ERROR`) и 1.6 (CodeScoring, опциональный, `CONTINUE`), но в Airlock-2 они не подключены.
Нужен дизайн: варианты, где живёт сканер, связь с evidence/SARIF, границы.

## 2. Что уже есть (факты репо)

### 2.1 Канон (уже написан)

- **LC-шаги**: 1.4 SonarQube (SAST & Quality), 1.6 CodeScoring (SCA & Licenses), 1.7 KCS.
- **Профили**: source-код → SonarQube + CodeScoring (+CodeQL в PUREK/SECURITY_COSMO по
  `build_modes.py`); контейнер → Trivy/KCS, **без** SonarQube; «не гонять образ через source-проверки».
- **BrickType** уже содержит `"sast"`/`"sca"` (`domain/pipeline_brick.py`, пример образа —
  `sonarsource/sonar-scanner-cli:latest`), E2E-харнесс (`services/scripts/run-e2e-pipeline.ps1`)
  уже собирает «Sonar SAST»-кирпич как **шаг Woodpecker**.

### 2.2 Живая принимающая машинерия (wired)

- **Findings-мост COS-101**: `POST /api/v1/runs/{run_id}/findings` (capability `SCAN_START` +
  ownership) → `attach_findings` → канонический носитель **`runs.findings_refs`** (JSONB) с
  нормализацией severity (`findings_bridge.normalize_severity`).
- **Гейт**: `GatePolicyEngine` (Critical→BLOCK, High→WARN с порогом) на финализации прогона;
  `FindingSearchEngine`/`GET /api/v1/findings/search` (GIN); Evidence Ledger живой.
- **Contour артефактов**: artifact capture → MinIO/Evidence (принято COS-161..170).

### 2.3 Legacy-бlueprint SONAR-POOL (код есть, в рантайм НЕ подключён; тесты зелёные)

Проверено `git grep`: модули ниже используются только собой/тестами/`chaos_runner` — **wiring отсутствует**.

- `capability/sonar_pool.py` — пул эфемерных CE-воркеров (sonar-scanner-cli контейнеры, port leases,
  readiness по `ceTaskId`, `reconcile_orphans`).
- `ledger/sarif_merger.py` — `StreamingSarifMerger` (50 шардов → 1 SARIF, O(1) память, дедуп правил).
- `ledger/minio_buffer.py` — `MinIOBufferSink` (S3 `cosmo-evidence` + Valkey `sonar.ingest`, MAXLEN 10000).
- `capability/ingest_controller.py` — `IngestTokenBucket` (плавная подача 1-2 задачи/цикл с backoff).
- `ledger/fast_ingest.py` — `FastEvidenceIngest`: SARIF 2.1.0 → findings (severity map, CWE, dedupe
  по composite key) — **целевая таблица `cosmo_findings` в Airlock-2 НЕ существует**
  (проверено: таблицы нет; finding-носитель сейчас `runs.findings_refs`).
- `capability/chaos_runner.py` — 7 негативных сценариев (outage/overload/timeout).
- Источник дизайна — боевой Cosmoport-1 («50 параллельных run: воркеры отработали, центральный
  сервер захлебнулся» → пул+буферизация); архивный хэндофф: `prettyk-secops/docs/archive/handoffs-2026-08/COPYPASTA-COSMO-SONAR-WORKER-POOL.md`.

### 2.4 Lab-инстанс (Keeper, внешняя зависимость)

- `prettyk-secops/services/docker-compose.sonarqube.yml` — SonarQube CE + PG, UI `:9000`, сеть
  `pk-net`, НЕ в обязательном lab_up; канон `prettyk-secops/docs/sonar-lab.md`, локальный доступ
  `sonar-access.md` (не в git).
- Тулинг Keeper: `sonar_scan.ps1`, `sonar_pipeline.ps1`, `sonar_check.py`, `sonar_export_issues.py`,
  `sonar_pk_profiles.py` (PrettyK-профили), `sonar_coverage_prep.py`.
- В стенде Airlock SonarQube **нет**.

## 3. Варианты

| # | Вариант | Оценка |
|---|---|---|
| **A** | **SAST как шаг пайплайна** (brick `sast`, Woodpecker, `sonar-scanner-cli`) + ingest отчёта в findings через живой мост COS-101 | ✅ **Рекомендация (Phase 1).** Максимально переиспользует принятый steel thread (brick/CI/artifacts/evidence) и живой findings-мост; не требует локального управления процессами (BAN.md); E2E-харнесс уже моделирует такой кирпич |
| **B** | **Standalone SonarQube + оркестратор** (legacy SONAR-POOL: пул воркеров, merger, buffer, token bucket) | 🟡 **Phase 2 при подтверждённом масштабе.** Бlueprint боевой и покрыт тестами, но это существенно больше поверхностей; включать только под реальную нагрузку (много параллельных run) |
| **C** | **CodeScoring** (SCA & Licenses, шаг 1.6) | 🟡 Отдельный трек: продукт/лицензия/доступность в контуре — решение владельца; в `build_modes` уже помечен как «bridge позже». Дизайн закладывает точку подключения, реализация — отдельно |
| **D** | Только `workspace/gate-scan` (COS-132: rule-based скан + SARIF) | ❌ Не закрывает SOURCE_AUDIT: это полезная дешёвая проверка (secrets/patterns), но не SAST-движок |
| **E** | Внешний провайдер (Pure-Box-подобный: Cosmo триггерит сессию, получает результат) | ✅ Совместим с BAN.md; фактически форма варианта A/B (сканер — не в процессе Cosmo). В Phase 1 роль провайдера играет CI-шаг |

## 4. Механика Phase 1 (рекомендация)

```text
Run (COS-108..) → batch[pipeline_brick type=sast, executor=woodpecker,
                       image=sonarsource/sonar-scanner-cli]
  → шаг сканирует checkout рана (repo@commit_sha) против SonarQube-хоста
    (SONAR_HOST_URL + токен из секретницы; projectKey по конвенции)
  → отчёт (SARIF 2.1.0; при CE — конверсия из api/issues/search, ср. legacy-конвертер)
  → artifact capture (MinIO/Evidence, как у trivy/syft)
  → findings нормализуются и уходят в ЖИВОЙ мост:
       POST /api/v1/runs/{run_id}/findings  (tool="sonarqube", severity-канон)
  → GatePolicyEngine на финализации прогона (Critical→BLOCK / High→WARN-порог;
    политика профиля: 1.4 = TERMINATE_ON_ERROR — см. §7)
  → Evidence Ledger + Findings Search + Hub (Contract A)
```

- **Хост SonarQube**: Phase 1 подключается к CE-инстансу; варианты: (а) сервис в стенде Airlock
  (зеркало compose Keeper, `:9000`, CE+PG, ~4 GB) — самодостаточность; (б) lab-инстанс Keeper —
  кросс-продуктовая зависимость (см. §7). Код Cosmo от этого не зависит — только конфиг.
- **Ingest-адаптер**: SARIF 2.1.0 → findings-json. Бlueprint `fast_ingest` переиспользуется
  **с ретаргетингом** на канонический носитель (`runs.findings_refs` через мост; `cosmo_findings`
  не существует); либо конверсия в build-шаге. Дедуп — composite key (path+rule+line), как в legacy.
- **Что НЕ строим в Phase 1**: пул воркеров, rate-limited standalone-инжест, SARIF-mеrger — это B (Phase 2).

## 5. Границы

- **Не трогаем**: container/artifact-сканы (приняты COS-171/172/168), DAST (Коробка), promotion.
- **BAN.md**: никакого локального управления процессами в Cosmo — сканер исполняется CI-шагом
  или внешним сервисом; Cosmo оркестрирует и принимает результат.
- **CodeQL**: отложен (PUREK-политика/`bridge` по `build_modes.py`) — вне этого дизайна.
- **Секреты**: SONAR-токен — только через секретницу/CI-env, не в DTO/логах (канон zero-plaintext).
- **CE-ограничения (проверить при реализации):** Community Edition не поддерживает branch analysis —
  при сканировании веток нужна конвенция projectKey (repo+branch) или community-плагин; ресурсы
  CE ~4 GB; QG в CE есть, branch-QG — нет. Это влияет на per-branch дизайн ключей.

## 6. Предложение эпик-нарезки (после решения владельца)

| # | Карточка (предложение) | Кто | h | Зависит |
|---|---|---|---:|---|
| 1 | **SAST-STEP-1** — SAST-кирпич пайплайна: brick-def (`type=sast`, woodpecker, scanner-image), конфиг скана (host/projectKey/token-ref), артефакт-отчёт, live-прогон на стенде | инфра/Boss | 6-8 | решение о хосте CE |
| 2 | **SAST-INGEST-2** — отчёт → findings: конвертер (SARIF/CE-API) + вызов живого моста (`POST /runs/{id}/findings`, `tool=sonarqube`), дедуп, тесты | Luna | 4-6 | 1 |
| 3 | **SAST-GATE-3** — evidence + гейт: политика (маппинг severity/порогов, TERMINATE_ON_ERROR vs CONTINUE), финализация прогона, Hub-проводка, UI-visibility | Luna | 4-6 | 2 |
| 4 | **SAST-STAND-4** — стенд: SonarQube CE сервис (зеркало Keeper compose) + идемпотентный сид (projectKey/token/quality-profile) + live-smoke end-to-end (repo→run→scan→findings→verdict) | инфра/Boss | 4-6 | 1-3 |
| 5 | **SAST-SCALE-5** — SONAR-POOL legacy revival (pool+merger+buffer+token-bucket, ретаргетинг на текущий носитель) | Luna | 8-12 | подтверждённый масштаб |
| 6 | **SCA-CODESCORING-6** — CodeScoring-трек (шаг 1.6): интеграция/лицензия/API-контракт | ? | ? | решение владельца |

Порядок: 1 → 2 → 3 → 4 (одна поверхность) → 5/6 по решению.

## 7. Открытые вопросы (решение владельца / Keeper)

1. **Чей SonarQube-хост**: свой сервис в стенде Airlock (самодостаточность, +4GB) или lab-инстанс
   Keeper (кросс-продуктовая зависимость, `pk-net`/сеть между стендами)?
2. **Семантика гейта**: шаг 1.4 канона — `TERMINATE_ON_ERROR`; текущий GatePolicyEngine —
   severity-политика (Critical→BLOCK/High→WARN). Что из этого — источник истины для source-SAST
   (или комбинация: ошибка сканера = terminate, findings = severity-политика)?
3. **Quality/coverage**: используем ли Quality Gate/coverage SonarQube (шаг называется «SAST &
   Quality») или только security-findings?
4. **Ветки/ключи**: конвенция projectKey (repo / repo+branch / commit) с учётом CE-ограничения.
5. **CodeScoring**: есть ли доступ/лицензия в контуре (иначе шаг 1.6 остаётся bridge-заглушкой).
6. **Масштаб**: закладывать ли Phase 2 (пул) сразу или по факту нагрузки.

## 8. Риски

- **Возврат legacy-кода в рантайм** (A/B): модули покрыты тестами, но 1.5-летней давности —
  ретаргетинг на текущие модели обязателен; не тащить `cosmo_findings` как есть.
- **CE-ограничения** (ветки/QG) — проверить до нарезки, влияет на ключи и UX.
- **Ресурсы стенда**: CE ~4 GB — учесть в бюджете (стенд уже тяжёлый).
- **Airgap**: образы scanner/CE — в бандл/registry-контур (как trivy/syft в COS-171/172).
- **Ложный SOURCE_AUDIT**: не подменять дизайн «дешёвым» gate-scan'ом; честно: SAST = движок.

## 9. Артефакты

- Этот док; факты wiring/legacy — проверены `git grep` + живой ПГ (таблицы `cosmo_findings` нет).
- Точки подключения: `POST /api/v1/runs/{run_id}/findings` (мост), `GatePolicyEngine`,
  brick `type=sast`, `run-e2e-pipeline.ps1` (образец кирпича).
