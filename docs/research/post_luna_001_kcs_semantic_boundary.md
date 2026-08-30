# POST-LUNA-001: KCS Semantics & Semantic Boundary — Confirmed / Observed / Unknown

## Источники исследования

| Источник | Путь | Что получено |
|---|---|---|
| Cosmoport 1.0 Release Model | `cosmo/cosmoport/backend/app/models/project/release.rb` | 19 статусов, release_type_id, extra_tag, repeat_transfer |
| Cosmoport 1.0 Transfer Table | `cosmo/cosmoport/backend/db/schema.rb` (lines 1308-1333) | release_routes, release_transfer_histories, sod_code, mzp_url |
| Cosmoport 1.0 Release Schema | `cosmo/cosmoport/backend/public/resources/schema/release_schema.yml` | Поля release: tag, commit, notes, guide, domain, extra_tag |
| Cosmoport 2.0 Models | `orchestrator/cosmo/domain/release_model.py`, `release_type_model.py` | ReleaseBatch, ReleaseType, TransferRecord, ArtifactRecord |
| Provider Adapters | `orchestrator/cosmo/adapters/artifact_registry.py`, `oci_registry.py`, `registry_per_zone.py` | local-oci/nexus/t1_sfera provider path |

---

## 1. CONFIRMED (подтверждено кодом, схемой и тестами)

### Release Core
| Поле | Тип | Источник | Cosmoport 2.0 статус |
|---|---|---|---|
| `id` | UUID | schema.rb:1019 | ✅ `ReleaseModel.id` |
| `tag` | string(33), semver | release.rb:83-84 | ✅ `ReleaseModel.version` |
| `commit` / `commit_sha` | string | release.rb:83 | ✅ `Build.commit_sha` |
| `status` | integer enum (19 значений) | release.rb:12-30,88 | ✅ `ReleaseModel.status` (7 статусов) |
| `project_id` | UUID FK | schema.rb:1026 | ✅ `ReleaseBatch.project_id` |
| `release_type_id` | UUID FK | schema.rb:1039 | ✅ `ReleaseType.id` |
| `notes` / `changelog` | text | release.rb:83 | ✅ `ReleaseModel.changelog` |
| `extra_tag` | string (внеочередной) | release.rb:238 | ✅ `ReleaseMetadata.emergency` computational |

### Provider Path
| Провайдер | Зона | Тип артефактов | Статус |
|---|---|---|---|
| `local-oci` | ЗР (Dev) | raw build outputs | ✅ `RegistryProvider.provider_type="local-oci"` |
| `nexus` | ЗТ (Staging) | dirty (после SAST) | ✅ `RegistryProvider.provider_type="nexus"` |
| `t1_sfera` | ЗПЭ (Production) | clean (все gates PASS) | ✅ `RegistryProvider.provider_type="t1_sfera"` |

### KITS Classification
| Компонент | Статус |
|---|---|
| `KitsTag` — domain-free DTO | ✅ |
| M:N `ApplicationKitTag` join table | ✅ |
| Единый `GET /api/v1/kits` endpoint | ✅ |
| Фильтрация приложений по `kits` параметру | ✅ |

### Project/Application связь
| Компонент | Статус |
|---|---|
| `ProjectApplication` M:N join table | ✅ POST-LUNA-001 |
| `project_id` backfill из `projects.application_ids` JSON | ✅ Alembic migration |
| Multi-project applications | ✅ |

---

## 2. OBSERVED (наблюдается в Cosmoport 1.0 или инфраструктуре, но не зафиксировано как production contract)

### KCS (Классификатор Среды / Environment Classifier)
```
raw   — CI build output, ЗР only. Соответствует stage "before any scanning".
dirty — После SAST/SCA (sonarqube, dependency-check). Артефакт просканирован, но DAST ещё не пройден.
clean — После DAST + все gates PASS. Допущен к трансферу в ЗПЭ.
docs  — SBOM, GOST-Act, evidence. Не артефакт выполнения, а доказательная цепочка.
```

**Promotion path**: `raw (ЗР) → dirty (ЗТ, after SAST) → clean (ЗТ, after DAST+gates) → ЗПЭ transfer`

**Статус в Cosmoport 2.0**: KCS НЕ хранится как поле в БД. Вычисляется динамически из статусов гейтов и зоны трансфера. Это **наблюдаемая** семантика — подтверждена исследованием Cosmoport 1.0, но НЕ зашита в `ReleaseBatch.status` или `ArtifactRecord`.

### Т1-Сфера
- **Observed**: capability probe. Т1-Сфера поддерживает OCI V2 протокол.
- **Не confirmed**: полная совместимость со всеми API Cosmoport 2.0.
- **Статус в коде**: зарегистрирован как `RegistryProvider.T1_SFERA` с `UNKNOWN capability`.

### Transfer queue / PackageTransfer
- **Observed в Cosmoport 1.0**: `ReleaseRoute::PackageTransfer`, статусы `pending/in_progress/success/failed/canceled`.
- **НЕ перенесено в Cosmoport 2.0**: текущая реализация `transfer-v2` — атомарный вызов без очереди.

---

## 3. UNKNOWN (не подтверждено, не зашито в код, помечено future)

### СОД / МЗП (Separation of Duties / Межзоновое Перемещение)
| Поле | Cosmoport 1.0 | Cosmoport 2.0 |
|---|---|---|
| `sod_code` | `release_routes.sod_code` | ❌ НЕ в active модели |
| `mzp_url` | `release_routes.mzp_url` | ❌ НЕ в active модели |
| `sod?` / `mzp?` | `release_route.rb:16-22` | ❌ НЕ реализовано |

**Причина**: СОД/МЗП — специфичные для конкретной организации протоколы. Не являются частью универсального контракта Cosmoport 2.0.

### Т1-Сфера capability matrix
- Полная матрица возможностей Т1-Сфера (manifest put, tag list, blob push, signature verify) — **UNKNOWN**.
- Будет определена через capability probe при первом подключении к реальному реестру.

### KCS роль в promotion dirty → clean
- Является ли KCS **требованием** для трансфера (т.е. только clean артефакты допускаются к ЗПЭ), или **рекомендацией** — **observed, но не confirmed**.
- В Cosmoport 2.0 трансфер ограничен статусами гейтов, а не KCS.

### Domain migration path
- Старые таблицы `domains` **НЕ мигрируются** в новую проектную модель.
- `domain_project_mapping` — **read-only VIEW**, не production contract.
- Полный отказ от Domain как tenant boundary — confirmed.

---

## 4. Semantic Boundary (Граница семантического контракта)

```
            CONFIRMED (production contract)
           ╔══════════════════════════════════╗
           ║  ReleaseBatch.status            ║
           ║  TransferRecord (ЗР→ЗТ→ЗПЭ)     ║
           ║  ArtifactRecord.digest_sha256   ║
           ║  ProjectApplication M:N         ║
           ║  KitsTag → ApplicationKitTag    ║
           ║  local-oci → nexus → t1_sfera   ║
           ╚══════════════════════════════════╝
                          │
           ───────────────┼──────────────────
                          │
           OBSERVED (research, not in contract)
           ╔══════════════════════════════════╗
           ║  KCS: raw/dirty/clean/docs      ║
           ║  Т1-Сфера capability probe      ║
           ║  Transfer queue (future)         ║
           ║  domain_project_mapping (VIEW)   ║
           ╚══════════════════════════════════╝
                          │
           ───────────────┼──────────────────
                          │
           UNKNOWN (future, не зашито)
           ╔══════════════════════════════════╗
           ║  СОД (sod_code)                 ║
           ║  МЗП (mzp_url)                  ║
           ║  Т1-Сфера full capability       ║
           ║  KCS enforcement policy         ║
           ╚══════════════════════════════════╝
```

---

## 5. Project ID backfill & validation policy

- **Источник**: `projects.application_ids` (JSON array) → `project_applications` (M:N table).
- **Миграция**: `93d4e5f6a7b8` автоматически бэкфиллит все существующие записи.
- **Валидация**: при создании `ProjectApplication` проверяется существование `project_id` и `app_id`.
- **Политика**: новые приложения НЕ создаются через `projects.application_ids` — только через `POST /api/v1/projects/{id}/apps`.