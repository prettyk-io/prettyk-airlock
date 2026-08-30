# OWN-LUNA-001: KCS, Artifact Provider Path, and Clean/Dirty/Raw Research

## 1. KCS (Классификатор Среды Среды / Environment Classifier) Role

### Определение
**KCS** — механизм классификации артефактов и образов контейнеров по степени готовности к развертыванию в зонах безопасности:

| Состояние | Значение | Зона | Что хранит | Пример |
|---|---|---|---|---|
| **raw** | Сырой артефакт из CI | Только ЗР | build output без проверок | `oci://nexus.corp/cosmoport/auth:dev-a1b2c3d4` |
| **dirty** | Артефакт прошел SAST/SCA, но не прошел DAST | ЗР / ЗТ | отсканированный, но не финальный | `oci://nexus.corp/cosmoport/auth:staging-v1.2.3` |
| **clean** | Полностью проверенный артефакт (все gates PASS) | ЗТ / ЗПЭ | готов к production deploy | `oci://harbor.corp/cosmoport/auth:prod-v1.2.3` |
| **docs** | Артефакт документации / SBOM / GOST-Act | Все зоны | evidence chain | `vault:secret/cosmo/docs/release-2026-act` |

### Promotion Path: dirty → clean
```
   CI Build (raw)
      │
      ▼
   Статический анализ (SAST/SCA) ──► dirty
      │
      ▼
   Динамический анализ (DAST/Fuzzer) ──► clean
      │
      ▼
   Security Gates (все PASS)
      │
      ▼
   Transfer ZT → ЗПЭ (clean only!)
```

**Источники**:
- `cosmo\cosmoport\backend\app\models\project\release.rb` — поле `extra_tag` (внеочередной), `repeat_transfer`
- `cosmo\cosmoport\backend\app\models\release_route.rb` — маршруты с `its_complex`, `segment`, `zone`, `contour`
- `cosmo\cosmoport\backend\db\schema.rb` — таблица `release_routes` с `zone`, `segment`, `contour`

**Зафиксировано для Cosmoport 2.0**:
- **clean/dirty/raw** не хранятся в релизе — вычисляются динамически из статусов гейтов
- **Promotion** ограничен через линейную зону: ЗР → ЗТ → ЗПЭ (transfer-v2)
- **KCS** является вычисляемым полем, не хранится в БД (`derived`)

---

## 2. Provider Path: Nexus → Mirror/Staging → Т1-Сфера

### Архитектура провайдеров артефактов

```
[Старый Nexus / OCI Registry]
        │
        │  push raw артефактов (CI)
        ▼
[Mirror / Staging Registry]   ←── SAST/SCA сканирование
        │
        │  promotion dirty → clean (DAST + gates)
        ▼
[Т1-Сфера (Trusted Registry)]  ←── Только clean артефакты
        │
        │  pull для развертывания в ЗТ / ЗПЭ
        ▼
[Kubernetes Runtime / Envoy Mesh]
```

### Конфигурация провайдеров в InstanceConfiguration

```python
# Старый Nexus — только для push из CI (raw/dirty)
registry_nexus = RegistryProvider(
    provider_type="oci",
    endpoint_url="https://nexus.internal.corp",
    namespace="cosmoport",
    auth_ref="vault:secret/cosmo/registry/nexus",
)

# Mirror/Staging — промежуточный реестр
registry_staging = RegistryProvider(
    provider_type="harbor",
    endpoint_url="https://harbor-staging.corp",
    namespace="cosmoport-staging",
    auth_ref="vault:secret/cosmo/registry/staging",
)

# Т1-Сфера — доверенный production реестр (clean only)
registry_t1_sfera = RegistryProvider(
    provider_type="harbor",
    endpoint_url="https://t1-sfera.bank.corp",
    namespace="cosmoport-prod",
    auth_ref="vault:secret/cosmo/registry/t1-sfera",
)
```

**Важно**: Artifactory не используется. Только OCI/Harbor/Nexus.

---

## 3. Remove Domain Semantics — Verification

### Проверено: новые DTO не содержат Domain-семантики

| Файл | Domain-free |
|---|---|
| `cosmo/domain/project_model.py` | ✅ `KitsTag` — "независимая от Domain семантическая метка" |
| `cosmo/domain/project_model.py` | ✅ `Project` — собственный `project_id`, нет `domain_id` |
| `cosmo/domain/instance_config.py` | ✅ `InstanceConfiguration` — `instance_id`, `network_id` |
| `cosmo/domain/release_type_model.py` | ✅ `ArtifactRecord` — `app_id`/`build_id`, без `domain_id` |
| `cosmo/domain/release_type_model.py` | ✅ `ReleaseBatch` — `project_id`, без `domain_id` |
| `cosmo/api/routes/projects.py` | ✅ Нет `require_domain`, `verify_ownership`, `X-Cosmo-Domain` |

### API без обязательного domain context

GET-эндпоинты, работающие без `X-Cosmo-Domain` заголовка:
- `GET /api/v1/projects` — список проектов
- `GET /api/v1/kits` / `GET /api/v1/kits/tags` — теги КИТС
- `GET /api/v1/release-types` — профили типов релизов
- `GET /api/v1/apps?kits=...&level=...` — фильтрация без domain

**Visibility policy**:
- Без токена → 401
- С токеном USER → read-only по всем проектам
- С токеном DEVELOPER → проекты своей команды
- С токеном SECURITY_OFFICER → все проекты + security gates