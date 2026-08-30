# NX-LUNA-01/02: Cosmoport 1.0 Release & Transfer Research

## Источники
- `D:\cosmo\cosmoport\backend\app\models\project\release.rb` — модель Project::Release
- `D:\cosmo\cosmoport\backend\app\models\release_type.rb` — ReleaseType
- `D:\cosmo\cosmoport\backend\app\models\release_route.rb` — ReleaseRoute (маршруты)
- `D:\cosmo\cosmoport\backend\app\models\release_transfer_history.rb` — ReleaseTransferHistory
- `D:\cosmo\cosmoport\backend\db\schema.rb` (lines 1019–1045, 1308–1344)
- `D:\cosmo\cosmoport\backend\public\resources\schema\release_schema.yml`

---

## NX-LUNA-01: Реальные поля Release (Cosmoport 1.0 → 2.0 mapping)

### Статусы (DB: `status` integer enum, 19 значений)
```text
draft developing developed testing tested testing_failed production archived
build_deploy_failed_dev build_deploy_failed_test build_deploy_failed_prod
canceled transferred_to_test transferred_to_prod deleting build_failed_dev canary_production
```
**Ключевые группы:**
- `ACTIVE_STATUSES`: transferred_to_test, testing, tested, transferred_to_prod, production, build_deploy_failed_test, build_deploy_failed_prod, canary_production
- `PRODUCTION_STATUSES`: production, archived, build_deploy_failed_prod, transferred_to_prod, canary_production

### Поля (DB колонки)
| Поле | Тип | Назначение |
|---|---|---|
| `tag` | string(33) | Название/версия релиза (semver validated) |
| `commit` | string | Git-коммит |
| `notes` | text | Описание |
| `guide` | text | Инструкции |
| `release_date` | datetime | Дата выпуска |
| `project_id` | UUID FK | Приложение-владелец |
| `user_id` | bigint FK | Инициатор |
| `release_type_id` | UUID FK | Тип релиза |
| `domain` | string(10) | Semver-домен (для L0) |
| `abac` | string | ABAC-домен |
| `resources` | jsonb | Подключённые ресурсы |
| `deps` | jsonb | Деплои в других зонах |
| `extra_tag` | string | Внеочередной релиз |
| `repeat_transfer` | boolean | Повторный перенос |
| `page_id` | string | Confluence page ID |

### Связи
- `belongs_to :project` (приложение)
- `belongs_to :release_type`
- `has_one :build` (Project::Build)
- `has_many :packages`
- `has_many :child_project_releases` / `has_many :parent_project_releases`
- `has_many :attachments`

### Выявлено для Cosmoport 2.0
- **Уже есть**: `ReleaseModel` (domain/release_model.py): statuses `draft..rollback`, zones `zr/zt/zpe`, transfer_history
- **Нужно добавить**: `domain` (semver), `extra_tag` (внеочередной), `repeat_transfer` (повторный), `guide`, `abac`
- **СОД/МЗП**: помечены как `future` — поля `sod_code`, `mzp_url`

---

## NX-LUNA-02: Transfer Table & Routes

### ReleaseRoute (DB: `release_routes`)
| Поле | Тип | Назначение |
|---|---|---|
| `its_complex` | string | Комплекс ИТС |
| `segment` | string | Сегмент |
| `zone` | string | Зона (dev/test/prod) |
| `contour` | string | Контур |
| `transport_name` | string | Имя транспорта (СОД/МЗП) |
| `sod_code` | string | Код СОД — **future** |
| `mzp_url` | string | URL МЗП — **future** |
| `route_name` | string | Человекочитаемый ID |
| `enabled` | boolean | Доступность |

**Инвариант**: `route_id = "#{its_complex}_#{segment}_#{zone}_#{contour}_#{transport_name}"`

### ReleaseTransferHistory (DB: `release_transfer_histories`)
| `status` | integer | Статус переноса |
| `release_route_package_transfer_id` | UUID FK | Попытка переноса |
| `user_id` | bigint FK | Кто выполнил |
| `transfer_start_date` | datetime | Начало |
| `change_status_date` | datetime | Изменение статуса |
| `comment` | string(1024) | Комментарий |

### Package transfers (очередь)
- `ReleaseRoute::PackageTransfer` — пакет для переноса
- Статусы: `pending, in_progress, success, failed, canceled`

### Для Cosmoport 2.0
- **Уже есть**: `transfer-v2` (линейный ЗР→ЗТ→ЗПЭ), `TransferRecord`, `ReleaseBatch`
- **future**: СОД/МЗП поля (`sod_code`, `mzp_url`) — помечены в моделях как `Optional[str] = None`