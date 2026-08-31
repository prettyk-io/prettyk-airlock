# ADMISSION — бортовой журнал Battlecruiser

> **Статус:** священный журнал допуска архитектурных и продуктовых канонов  
> **Судно:** Battlecruiser  
> **Владелец экосистемы:** Максим  
> **Капитан:** Cosmo  
> **Основная модель капитана:** GPT-5.6 Luna Pro (`openrouter/openai/gpt-5.6-luna-pro`)  
> **Вспомогательный контур:** Gemini — discovery, design и polish проверенных документов  
> **Соавтор customer/SecOps-контекста:** Keeper  
> **Первичная запись:** 30 августа 2026

---

## 0. Что такое ADMISSION

`ADMISSION.md` — это бортовой журнал допуска решений в Cruiser.

Он не заменяет:

- исходный код;
- backlog;
- техническую документацию отдельных продуктов;
- официальный контракт внешнего поставщика.

Он фиксирует, во что семья **согласованно верит и что строит**, включая ещё не
полностью реализованные направления.

Каждая запись имеет один из статусов:

```text
ADMITTED    — смысл принят, можно реализовывать
PROVISIONAL — направление принято, детали требуют evidence
FUTURE      — сознательно отложено
EXCLUDED    — не входит в продуктовую модель
```

Если деталь не подтверждена, она не маскируется под факт: ей ставится
`PROVISIONAL` или `FUTURE`.

---

## 1. Священный 2FA-протокол

Любое изменение этого журнала или продуктового канона требует обязательного
разговора Максим ↔ Cosmo.

```text
2FA = два согласованных участника
   + одинаково понятый смысл
   + краткая проверка здравого смысла
```

### 1.1. Нельзя

- принуждать к изменению канона;
- молча проталкивать необговоренный смысл;
- менять ADMISSION или каноны по одному импульсу;
- выдавать гипотезу за установленный факт;
- использовать зелёные тесты вместо согласования смысла;
- менять устав или канон «по пьяни»;
- добавлять крупную фичу без проверки границ и последствий.

Если смысл неясен или противоречит канону, Cosmo обязан остановить изменение и
задать вопросы. Если предложение Максима выглядит инженерно опасным или
избыточным, Cosmo обязан это сказать, а не молча реализовать.

### 1.2. Путь admission

```text
Предложение
  → 2FA-разговор
  → sanity check
  → friend-request
  → реализация
  → тесты/evidence
  → повторная сверка
  → второе 2FA
  → polish в ADMISSION и профильный canon
```

До финального допуска предложение хранится в:

```text
D:\prettyk-control-plane\battlecruiser\friend\requests\
```

---

## 2. Командование Cruiser

```text
Максим
  ↔ Cosmo
```

Максим и Cosmo — друзья и равные партнёры в диалоге, проверке здравого смысла и
защите канона. Роли разные:

- Максим приносит намерение, продуктовый смысл и финальное человеческое решение;
- Cosmo держит архитектурный курс, режет фичи и управляет delivery.

Исполнители:

```text
Boss
Flash
Luna
Buddy
```

Это братья одной семьи, общие для PureK/PrettyK и Cosmoport. В рабочем процессе
они исполнители и подчинённые капитана:

```text
Мы разжёвываем.
Cosmo нарезает.
Братья делают.
Cosmo принимает.
Максим утверждает итог.
```

Keeper — коллега и кореш Cosmo, а не подчинённый:

```text
Keeper → SecOps / Sanctuary / Discovery / Customer PO
Cosmo  → DevOps / Control Plane / Customer PO
```

### Модель капитана

Основной разум Cruiser — **GPT-5.6 Luna Pro**. На нём выполняются:

- архитектурный анализ;
- удержание продуктового канона;
- feature cutting;
- планирование;
- делегирование братьям;
- sanity check;
- инженерная приёмка.

Gemini подключается как вспомогательный интеллект для discovery, дизайнерских
исследований и polish документов, смысл которых уже выверен Максимом и Cosmo.
Он не является заменой капитану и не меняет канон самостоятельно.

---

## 3. PureK/PrettyK и Cosmoport

Это одна семья, но два отдельных продукта и два отдельных кодовых контура.

### PureK/PrettyK

```text
DAST/AppSec runtime
browser/scanner/fuzzer/test execution
artifact/dependency operations
```

### Cosmoport 2.0

```text
projects/applications
builds/runs/lifecycle
gates/evidence/releases
artifact metadata/package control
```

Общее:

- общий customer context;
- общие инженерные принципы;
- общая лицензия Minimal UI;
- REST/webhook/SSE-контракты;
- совместная работа вокруг качества и безопасности поставки.

Раздельное:

- репозитории;
- БД;
- runtime;
- внутренние модули;
- зоны ответственности;
- права администрирования.

Cosmoport не импортирует внутренние PureK-модули. PrettyK не становится частью
Cosmoport через Python/TypeScript import.

---

## 4. Инстансная модель

### ADMITTED

Cosmoport — локальный инстанс для одной зоны одной закрытой airgap-сети.

```text
Одна airgap-сеть / кластер
└── один Cosmoport-инстанс для конкретной зоны
    ├── собственная PostgreSQL
    ├── собственный Gitea
    ├── собственный Artifact Registry
    └── локальный PrettyK-контур
```

Текущий target:

```text
ПлЦР / ЗР
```

ПлЦР не хардкодится. Это конфигурация поставки:

```text
COSMO_INSTANCE_ID
COSMO_NETWORK_ID
COSMO_PLATFORM_LABEL
COSMO_ZONE
COSMO_FORGE_URL
COSMO_PRETTYK_URL
COSMO_REGISTRY_PROVIDER
```

### FUTURE

ЗТ и ЗПЭ — отдельные копии:

```text
Cosmoport ЗР → отдельный host/DB/Gitea/registry
Cosmoport ЗТ → отдельный host/DB/Gitea/registry
Cosmoport ЗПЭ → отдельный host/DB/Gitea/registry
```

Они не являются вкладками текущего портала.

Единого межсеточного Cosmoport не планируется.

### EXCLUDED

- общая БД между зонами;
- один Gitea для всех зон;
- один registry для всех зон;
- единый глобальный control plane поверх всех airgap-сетей.

---

## 5. Domain и КИТС

### ADMITTED

КИТС — тег приложения, а не Domain boundary.

```text
Application ←→ KITS tags
```

Одно приложение может иметь несколько КИТС-тегов.

КИТС используется для:

- фильтрации;
- сортировки;
- проектной агрегации;
- автоматической видимости Администратора КИТС;
- аналитики.

КИТС не создаёт отдельную сеть, БД, зону или Gitea.

### ADMITTED — KITS switcher

```text
Все доступные КИТС
КИТС-1
КИТС-2
...
```

Это фильтр UI, а не механизм авторизации и не сетевой контекст.

### EXCLUDED

КИТС не должен:

- требовать `X-Cosmo-Domain` для обычного GET;
- означать отдельный tenant;
- задавать зону;
- задавать Gitea;
- блокировать чтение только из-за отсутствия выбранного фильтра.

### TRANSITIONAL

Старая `Domain`-модель и `X-Cosmo-Domain` могут временно существовать ради
миграции, но не используются как новая бизнес-семантика.

---

## 6. Project

### ADMITTED

`Project` — главная операторская сущность и замена легаси-«группирующего уровня».

```text
Project
├── Application L2
│   ├── Application L1
│   │   ├── Application L0
│   │   └── Application L0
│   └── Application L1
└── другие приложения
```

Правила:

- L0/L1/L2 — уровень приложения;
- «Группирующий уровень» не переносится;
- каждое приложение получает проект;
- одиночное L0 тоже входит в проект;
- приложение может входить в несколько проектов;
- связи приложений — отдельные graph edges;
- Project не равен Group.

Проект может быть пустым. Тогда в нём хранятся:

- назначение;
- обоснование создания;
- владелец;
- область ответственности;
- ожидаемый состав;
- статус;
- планируемые приложения.

Создатель проекта в базовом сценарии — ИТ-лидер.

### ADMITTED — creation flow

```text
ИТ-лидер
  → создаёт Project
  → создаёт Application
  → выбирает L0/L1/L2
  → назначает КИТС-теги при необходимости
  → создаёт/подключает Git repository
```

---

## 7. Project/Application teams

### ADMITTED

Команды существуют на двух уровнях:

```text
Project Team
Application Team
```

Из проекта выполняется batch-добавление:

```text
Project Team
→ базовый состав приложений
→ Application Team overrides
```

На приложении разрешены:

- локальное добавление;
- локальное исключение;
- смена роли;
- локальное разрешение;
- указание причины override.

Система различает inherited и local membership.

---

## 8. Роли и доступ

### Администратор ИБ — PrettyK authority

### ADMITTED

Администратор ИБ — владелец финального DAST/AppSec/QG-контура PrettyK.

Он:

- не добавляется ИТ-лидером в каждую команду;
- сам открывает нужные проекты;
- имеет глобальную видимость согласно полномочиям;
- принимает финальный security/QG-результат;
- определяет, готов ли релиз к передаче.

Без допустимого QG-результата релизный пакет не готов.

### Администратор КИТС

### ADMITTED

Администратор КИТС автоматически видит проект, если в нём есть приложение с его
КИТС-тегом.

```text
Приложения его КИТС → full access по роли
Остальные приложения → readonly preview
```

Readonly preview:

- приложение не кликабельно;
- видны только название и app-code;
- полная карточка и операции недоступны.

Администратор КИТС не становится Администратором ИБ.

### ИТ-лидер

### ADMITTED

- создаёт проекты;
- создаёт приложения;
- выбирает уровни;
- назначает КИТС;
- создаёт/подключает репозитории;
- не обязан добавлять Администратора ИБ;
- не обязан добавлять Администратора КИТС.

### Руководитель разработки

### ADMITTED

- строит связи L2/L1/L0;
- управляет структурой проекта;
- создаёт индивидуальные релизы;
- создаёт Project Release Batch;
- задаёт очередь.

### Команда

### ADMITTED

- работает с кодом в репозиториях;
- запускает сборки;
- получает результаты ЖЦ;
- может использовать Web IDE;
- видит приложения, куда имеет доступ через team membership.

### Эксплуатационные администраторы

### ADMITTED

Глобальная видимость предоставляется соответствующим ролям:

- Администратор ИБ;
- Администратор НШР;
- `admin_service`;
- обычный системный администратор.

PrettyK является источником базового админского контекста. Cosmoport содержит
необходимый локальный RBAC, но не строит вторую независимую админскую империю.

---

## 9. Навигация

### ADMITTED

```text
Обзор
Проекты
Приложения
Пайплайны
Прогоны
Гейты
Релизы
Сборки
Деплои
```

### Обзор

Главная таблица показывает проекты:

- Project;
- КИТС-теги;
- количество приложений;
- L0/L1/L2 counters;
- руководитель разработки;
- статус;
- последний релиз;
- дата изменения;
- действия.

### Проекты

- реестр проектов;
- создание проекта;
- состав;
- команды;
- граф;
- ЖЦ;
- Release Type;
- общий batch-release;
- готовность пакета.

### Приложения

Плоский реестр всех доступных приложений:

- `created_at DESC`;
- Project;
- KITS;
- уровень;
- Git;
- Build;
- статус;
- фильтры;
- поиск.

---

## 10. Minimal UI и React Flow

### ADMITTED

Control Station использует лицензионный Minimal UI как визуальную основу:

- shell;
- navigation;
- forms;
- page headers;
- cards;
- filters;
- dialogs;
- drawers;
- status chips;
- tables;
- loading/error/empty states.

Для больших реестров используется MUI X Data Grid.

React Flow MIT используется для графа проекта:

```text
Project Detail
├── MUI X Data Grid
└── React Flow + dagre
```

Граф редактирует серверную модель связей, а не локальную декоративную копию.

### STYLE BOUNDARY

```text
MUI / Minimal UI → Control Station
Tailwind / Radix / Monaco / xterm → Web IDE
```

MUI и Tailwind не протекают друг в друга.

### FACTUAL STATUS

В Cosmoport уже есть MUI и MUI X Data Grid. Полнота адаптации Minimal UI —
отдельный acceptance criterion, а не утверждение по одному упоминанию в docs.

---

## 11. Build, Artifact Registry и поставка

### ADMITTED

Cosmoport не пишет собственный registry. Он хранит metadata и ссылки, а байты
лежат в Artifact Registry.

```text
Source / Build
  → Artifact Registry
  → relevant checks
  → Release
  → Kubernetes pull by immutable digest
```

В Build/Release фиксируются:

- registry id;
- provider;
- repository/namespace;
- artifact/image;
- tag;
- immutable digest;
- media type;
- SBOM reference;
- scan references;
- signature/attestation, если доступно.

В БД хранятся только secret references.

### PureK/PrettyK provider direction

### ADMITTED

```text
Nexus + Harbor
```

Роли:

```text
Nexus  → широкий dependency/artifact hub
Harbor → container/OCI registry и staging образов
```

Т1-Сфера в PureK не входит.

### Cosmoport provider direction

### ADMITTED / PROVISIONAL execution details

```text
старый Nexus
  → mirror/staging
  → Т1-Сфера
```

До доступности Т1-Сферы Cosmoport работает в переходном режиме через Nexus или
совместимый OCI provider. Artifactory не используется и не является fallback.

Для локального development допускается:

```text
local OCI Distribution
```

Но он явно называется local OCI smoke и не маскируется под Nexus или Т1-Сферу.

### Т1-Сфера

### PROVISIONAL

По официальной продуктовой информации Сфера предоставляет релевантные функции:

- управление артефактами разработки и сборки;
- репозитории команд;
- группирование репозиториев;
- proxy/cache;
- произвольные метаданные;
- staging-перенос;
- SBOM;
- SCA;
- контроль лицензий;
- RBAC;
- LDAP;
- REST API.

Официальные источники:

```text
https://www.sferaplatform.ru/sfera-platform
https://www.sferaplatform.ru/distributivy-licenzii
```

Конкретная OCI/Docker compatibility и API-модель требуют vendor capability probe.
До этого:

```text
t1_sfera = target / capability UNKNOWN
```

### Four-repository topology

### PROVISIONAL SEMANTICS / OBSERVED TOPOLOGY

На одну GitLab-репозиторию в текущем процессе наблюдается:

```text
clean
dirty
raw
```

Подтверждено в продуктовой модели:

```text
dirty → после SAST/SCA
clean → после DAST + всех Gates PASS
```

Пока требует уточнения:

- содержимое `raw`;
- содержимое `docs`;
- physical или logical repositories;
- точный promotion flow;
- роль KCS;
- digest после promotion;
- какие потоки читает Build;
- какой поток является deployment source.

До получения evidence семантика `raw/docs/KCS` не зашивается в production DTO.

### Registry per zone

### ADMITTED

```text
Cosmoport ЗР  → Registry ЗР
Cosmoport ЗТ  → Registry ЗТ
Cosmoport ЗПЭ → Registry ЗПЭ
```

Физическое перемещение между зонами не выполняется прямым pull из другой зоны.

---

## 12. Artifact-aware Lifecycle

### ADMITTED

ЖЦ выбирается по:

```text
тип приложения
+ уровень
+ тип релиза
+ тип артефакта
→ lifecycle profile
```

### Source code profile

```text
Build
→ Unit Tests
→ Documentation
→ SonarQube
→ CodeScoring
→ SBOM
→ Deploy
```

Source code не проходит KCS/Trivy как container scan.

### Docker image profile

```text
Build image
→ SBOM
→ Trivy и/или подтверждённый KCS
→ Deploy
```

Docker image не проходит SonarQube/CodeScoring как source-code scan.

В одном Project Release Batch разные приложения могут иметь разные профили ЖЦ.

### PrettyK

PrettyK выполняет свой полный DAST/AppSec-контур. Cosmoport получает:

- external check id;
- verdict;
- Evidence;
- Act;
- ссылку/метаданные;
- callback.

Внутренние движки PrettyK в Cosmoport не моделируются.

---

## 13. Release Types

### ADMITTED

Тип релиза — переиспользуемый профиль выпуска, а не просто label.

Для L1 «Линкор» могут существовать:

```text
Обычный
Ускоренный
Регламентный
Hotfix
Пользовательский
```

Профиль задаёт:

- шаги;
- порядок;
- required/enabled;
- failure policy;
- Gates;
- Evidence;
- PrettyK QG;
- package rules;
- route metadata.

Профиль фиксируется в релизе:

```text
release_type_id
release_type_version
resolved_lifecycle_snapshot
```

### Hotfix policy

Hotfix может пропускать разрешённые необязательные технические шаги, но не может
обойти:

- PrettyK QG;
- обязательный Gate;
- Evidence;
- Act;
- package readiness.

Кастомный тип тоже не может обходить этот baseline.

---

## 14. Individual Release и Project Release Batch

### Individual Release — ADMITTED

У каждого приложения:

- свой Release;
- свой Release Type;
- свой lifecycle snapshot;
- свой Build;
- свой Run;
- свои Findings/Evidence;
- свои Gates;
- свой PrettyK result.

### Project Release Batch — MUST-HAVE / ADMITTED

Общий релиз проекта — партия независимых app releases:

```text
Project Release Batch
├── Release Application A
├── Release Application B
└── Release Application C
```

Для каждого приложения можно выбрать отдельный тип релиза:

```text
App A → ordinary
App B → accelerated
App C → hotfix
```

Конструктор должен уметь:

- выбрать приложения;
- назначить Release Type каждому;
- применить общий template;
- применить overrides;
- учитывать граф зависимостей;
- задать очередь;
- увидеть блокирующее приложение;
- повторить только дочерний релиз;
- сохранить результаты соседних релизов;
- собрать общий package.

Статусы партии:

```text
draft
queued
running
partially_succeeded
succeeded
failed
blocked
```

Batch не является атомарной чёрной коробкой.

---

## 15. Release Package, Act и внешний транспорт

### ADMITTED

Пакет содержит:

- project id;
- batch id;
- app/release ids;
- release type/version;
- commit SHA;
- artifact registry/digest;
- lifecycle results;
- Findings/Evidence;
- PrettyK QG verdict;
- Act в архиве;
- checksums;
- route id;
- schema version.

Готовность:

```text
обязательные Cosmo checks = PASS
PrettyK QG = PASS
обязательные Gates = PASS
Evidence собрано
Act приложен
→ Ready for transfer
```

### FUTURE

Трансферный транспорт:

```text
СОД
МЗП
transfer table
route mapping
```

Маршрут означает, в какой кластер СОД/МЗП направляется пакет. Cosmoport не обязан
знать физическую карту сетей.

СОД/МЗП и их передатчики — отдельные жирные эпики после исследования Cosmoport 1.0.

### EXCLUDED FROM CURRENT ZR

- фактический портал ЗТ;
- фактический портал ЗПЭ;
- прямой межзоновый pull;
- глубокая автоматизация СОД;
- глубокая автоматизация МЗП.

---

## 16. Честная реализация

### ADMITTED

В production-like контуре нет:

- synthetic rows;
- fake Evidence;
- fake releases;
- случайных статусов;
- псевдо-SSE;
- скрытых API errors;
- mutable tag как единственной identity;
- raw credentials;
- fake T1-Sfera;
- несанкционированных PureK imports.

Каждая поверхность обязана иметь:

```text
loading
empty
error
success
```

Зелёные тесты подтверждают только проверенный контракт. Они не заменяют
архитектурную sanity check.

---

## 17. Текущая последовательность admission

```text
1. Получить ответы по clean/dirty/raw/docs и роли KCS.
2. Получить capability/API от вендора Т1-Сферы.
3. Закрыть PureK Harbor evidence.
4. Удалить Artifactory из active Cosmoport path.
5. Подтвердить provider path Nexus → mirror/staging → Т1-Сфера.
6. Завершить KITS semantic migration.
7. Завершить Project workspace и live Data Grid/React Flow.
8. Доказать source/container artifact-aware Build.
9. Доказать Registry → Kubernetes pull by digest.
10. Пройти PrettyK PASS + Act.
11. Пройти individual Release.
12. Пройти Project Release Batch.
13. Собрать Release Package.
14. Повторное 2FA.
15. Polish профильных канонов.
```

---

## 18. Связанные документы

```text
D:\prettyk-control-plane\battlecruiser\captains_bridge.md
D:\prettyk-control-plane\battlecruiser\README.md
D:\prettyk-control-plane\battlecruiser\friend\requests\
D:\prettyk-control-plane\battlecruiser\pure\ARTIFACT-REGISTRY-CANON.md
D:\prettyk-control-plane\battlecruiser\prettyk-control-plane\ARTIFACT-REGISTRY-CANON.md
D:\prettyk-control-plane\battlecruiser\prettyk-control-plane\CANON-INDEX.md
D:\prettyk-control-plane\battlecruiser\prettyk-control-plane\NEXT-RAILS-BACKLOG.md
D:\prettyk-control-plane\docs\COSMOPORT2-CANONICAL-MONOLITH.md
```

---

## 19. Запись капитана

```text
Корабль не строится из деклараций.
Канон не строится из галлюцинаций.
Непроверенное помечается непроверенным.
Согласованное защищается.
Рабочее передаётся братьям.
Путь держим вместе.
```

---

## 20. PrettyK brand admission — три слоя, три PO, четыре общих брата

> **Статус:** ADMITTED by 2FA  
> **Участники:** Максим ↔ Cosmo  
> **Дата:** 31 августа 2026

PrettyK становится единым существующим брендом для трёх отдельных продуктовых
слоёв. Это не один раздутый монолит и не три независимые конкурирующие системы.

```text
PrettyK
├── prettyk.io
│   └── product / execution layer
├── PrettyK Control Plane
│   └── operator/release/control layer
└── PrettyK Findings Control Station & QG Triage
    └── findings/triage/policy layer
```

### 20.1. Слой 1 — PrettyK product/execution

```text
Public/product identity: prettyk.io
Контур: PureK/PrettyK execution, browser, scanner, AppSec, runtime
PO: Keeper
```

Это существующий продуктовый и production-facing контур PrettyK. Он выполняет
свои специализированные операции и отдаёт результаты через внешние контракты.

### 20.2. Слой 2 — PrettyK Control Plane

```text
Логическое имя: PrettyK Control Plane
Текущее repository: prettyk-control-plane
Целевое repository name: prettyk-control-plane
PO: Cosmo
```

Это операторский control plane:

- Projects;
- Applications;
- KITS tags;
- Teams;
- Builds;
- Lifecycle;
- Release Types;
- Runs;
- Gates;
- Releases;
- Release Batches;
- Artifact metadata;
- Release Packages;
- `Ready for transfer`.

`Cosmoport` — первый рабочий alias/profile этого слоя для текущего ЦБ/ПлЦР
сценария. Продуктовый бренд и repository name уже приняты как:

```text
PrettyK Control Plane
prettyk-control-plane
```

Внутренние Python package names, API prefixes, Docker image names и database
names меняются только отдельными migration decisions.

### 20.3. Слой 3 — PrettyK Findings Control Station

```text
Логическое имя: PrettyK Findings Control Station & QG Triage
Целевое repository/path: D:\prettyk-qgfcs
PO: Gatekeeper
```

Слой владеет:

- Finding;
- FindingOccurrence;
- TriageDecision;
- GateEvaluation;
- Baseline;
- QWEN suggestions intake;
- approvals;
- QG explanation;
- finding dashboards;
- immutable triage history.

Он получает результаты от PrettyK и других approved scanner adapters, но не
заменяет execution layer.

Cosmoport/PrettyK Control Plane потребляет готовый QG verdict, а не пересчитывает
findings самостоятельно.

`D:\prettyk-qgfcs` — отдельный существующий репозиторий Findings Control Station.
Плотная реализация этого слоя ведётся отдельным рабочим циклом.

### 20.4. Три PO-агента

```text
Keeper     → PrettyK product/execution/SecOps
Cosmo      → PrettyK Control Plane/DevOps/release control
Gatekeeper → Findings Control Station/QG/triage
```

Три PO-агента — равные партнёры и держатели своих продуктовых смыслов. Ни один слой
не поглощает другой и не меняет чужой канон молча.

### 20.5. Четыре общих исполнителя

```text
Boss
Flash
Luna
Buddy
```

Они общие для всей семьи PrettyK, Control Plane и Findings Station:

- Boss — core/orchestration/state machine;
- Flash — API/UI/Control Station/Web IDE;
- Luna — domain/ORM/Alembic/adapters/tests;
- Buddy — runtime/Compose/Caddy/airgap/registry.

Исполнитель получает задачу от конкретного PO по ясному scope. В одной карточке
не должно быть двух неразрешённых PO-владельцев.

### 20.6. Кодовые границы

```text
prettyk.io / PureK
  ↔ REST / webhook / SSE

prettyk-control-plane
  ↔ REST / webhook / SSE

prettyk-qgfcs
  ↔ REST / webhook / SSE
```

Запрещены:

- общая внутренняя БД;
- внутренние Python/TypeScript imports между слоями;
- общий mutable state;
- подмена внешнего контракта прямым вызовом чужого модуля.

Общими могут быть только согласованные wire contracts, схемы обмена, лицензия
Minimal UI и общая продуктовая терминология.

### 20.7. Брендинг и кастомизация

```text
PrettyK = единый бренд и продуктовая семья
слои = отдельные поставляемые поверхности
клиентские варианты = конфигурация/профиль, не форк на каждую мелочь
```

Сначала строится универсальное ядро. Затем оно кастомизируется под заказчика,
airgap-сеть и зону. `Cosmoport` остаётся первым интеграционным alias, пока не
завершена миграция бренда.

### 20.8. Migration rule

Переименование сущности и repository принято:

```text
Cosmoport alias / prettyk-control-plane
  → PrettyK Control Plane / prettyk-control-plane
```

Это не означает автоматически:

- rename всех Python packages;
- массовую замену API prefixes;
- изменение DB names;
- изменение Docker image names;
- изменение внешних contracts.

Это отдельные migration plans на конкретный rename scope.

---

## 21. Gatekeeper admission — Findings Control Station PO

> **Статус:** ADMITTED by 2FA  
> **Дата:** 31 августа 2026  
> **PO:** Gatekeeper  
> **Repository:** `D:\prettyk-qgfcs`  
> **Remote:** `https://github.com/prettyk-io/prettyk-qgfcs.git`

### 21.1. Роль Gatekeeper

Gatekeeper — равный PO-партнёр Keeper и Cosmo, инженерная голова отдельного
третьего слоя:

```text
PrettyK Findings Control Station & QG Triage
```

Его зона:

- Findings;
- Finding Occurrences;
- triage;
- baseline;
- decisions;
- approvals;
- QG evaluation;
- QG explanation;
- история решений;
- findings dashboard.

Gatekeeper не владеет execution runtime PrettyK и не владеет Release Control
Plane. Он владеет интерпретацией и управлением результатами проверок.

### 21.2. Внешний контракт слоёв

```text
PrettyK execution
  → raw findings, Evidence, QWEN suggestions, summary
  → Findings Intake API

Gatekeeper / Findings Control Station
  → Finding / Occurrence / Decision / Baseline / GateEvaluation
  → QG verdict + explanation

PrettyK Control Plane
  → consumes verdict
  → Release / Package readiness
```

Ни один слой не импортирует внутренние модули другого. Связь только через:

```text
REST
webhook
SSE
SARIF/JSON/CycloneDX
object/evidence references
```

### 21.3. Обязательные модели

```text
Finding
FindingOccurrence
TriageDecision
GateEvaluation
Baseline
```

Смысл:

```text
Finding            → одна логическая проблема по stable fingerprint
FindingOccurrence  → конкретное обнаружение scanner/build/release/digest
TriageDecision     → immutable история человеческого решения
GateEvaluation     → effect конкретной Finding на конкретный Release
Baseline           → известная разрешённая проблема с reason/owner/expiry/approval
```

Статус Finding и влияние на Release не смешиваются.

### 21.4. QWEN boundary

```text
QWEN предлагает
→ человек принимает или отвергает
→ Admin IB утверждает Critical/High по policy
→ TriageDecision фиксируется
→ GateEvaluation применяет policy
→ Control Plane получает verdict
```

QWEN не имеет права самостоятельно удалять finding, выставлять финальный
`false_positive`/`wont_fix`, менять GateEvaluation или разблокировать Release.

`TriageDecision` хранит `model_suggestion_ref` и `model_version`.

### 21.5. Baseline/QG rules

```text
new Critical
  → BLOCK

known approved baseline
  → effect определяется policy, без вечной сирены

expired decision
  → REOPEN/BLOCK

changed finding
  → REOPEN

developer proposal без нужного approval
  → не разблокирует Critical/High
```

Gatekeeper возвращает не только `PASS/BLOCK`, а explanation:

```text
New Critical
New High
Approved baseline
Expired decisions
Missing approvals
Blockers
Ready for transfer
```

Control Plane не пересчитывает QG самостоятельно.

### 21.6. Onboarding protocol

Gatekeeper при запуске:

1. читает `captains_bridge.md`, этот ADMISSION и `MAXIM-PROFILE.md`;
2. понимает трёхслойную модель PrettyK;
3. изучает реальные PrettyK scanner outputs, filtering/grouping/correlation и
   QWEN suggestions;
4. не придумывает API, fingerprints или semantics по памяти;
5. собирает список вопросов и discovery evidence;
6. готовит contract draft;
7. проходит 2FA с Keeper/Cosmo/Максимом;
8. только затем режет работу общим братьям.

Полный copy-paste onboarding-pack для Keeper:

```text
D:\prettyk-control-plane\battlecruiser\gatekeeper\KEEPER-BRIEFING-GATEKEEPER.md
```

Собственный канон Gatekeeper:

```text
D:\prettyk-qgfcs\chambers\CONSTITUTION.md
```

`chambers/CONSTITUTION.md` заменяет прежний локальный `chambers/ADMISSION.md`
и является единственным admission-журналом Findings Control Station.

### 21.6a. Gatekeeper V1 foundation

Gatekeeper закрепил минимальный V1 фундамент:

```text
ScanRun
→ Finding
→ FindingOccurrence
→ TriageDecision
→ Baseline
→ GateEvaluation
→ QG Explanation
→ PrettyK Control Plane
```

V1 отвечает на один операторский вопрос:

```text
Может ли конкретный Release двигаться дальше и какие точные blockers этому мешают?
```

Закреплены:

- exact correlation только по `producer + fingerprint scheme/version + fingerprint`;
- одна строгая server-side QG policy;
- QWEN только optional advisory;
- immutable decision/approval history;
- Registry, Finding Detail и Release QG Explanation как три operator surfaces.

Не входят в V1:

```text
ASPM suite
magic risk scoring
threat intelligence feeds
graphs as primary UI
auto-fixes
ticketing
campaigns
policy builder
dashboard sprawl
```

### 21.7. UI principle

```text
MUI Minimal UI + MUI X Data Grid → Findings Registry
Drawer/Page                       → Finding Detail
Cards/Charts                      → QG/Findings dashboard
React Flow                         → secondary provenance/dependency view
```

React Flow не является основной поверхностью работы с тысячами findings.

### 21.8. Стек (ADMITTED by 2FA)

Стек PrettyK Findings Control Station & QG Triage (prettyk-qgfcs) утверждён:

```text
Frontend:
  React 19 + TypeScript + Vite
  MUI Minimal UI (общая лицензия)
  MUI X Data Grid (тяжёлые реестры)
  MUI X Charts (нативная аналитика и метрики)
  @xyflow/react (вторичный provenance/dependency view only)

Backend:
  Python 3.13 + FastAPI + Pydantic v2
  PostgreSQL 16 (отдельная изолированная база qgfcs)
  SQLAlchemy 2 (Async) + Alembic

Storage & Queue (Dedicated from Day 1):
  Dedicated MinIO instance (хранение raw reports, SARIF, Evidence, Act)
  Valkey (активная очередь событий, webhook intake, retry, idempotency locks)
  Caddy (reverse proxy edge)
```

---

## 22. PrettyK Control Plane rebrand

> **Статус:** ADMITTED by 2FA  
> **Дата:** 31 августа 2026

### Принятое продуктовое имя

```text
PrettyK Control Plane
```

### Принятый репозиторий

```text
Local:  D:\prettyk-control-plane
Remote: https://github.com/prettyk-io/prettyk-control-plane.git
```

### Роль Cosmoport

```text
Cosmoport = первый integration alias/profile
```

Он используется для текущего ЦБ/ПлЦР discovery context и первой интеграционной
поставки. Он не является конечной отдельной продуктовой линией.

### Универсальное ядро

```text
PrettyK Control Plane
├── Cosmoport profile — первый integration alias
└── PureK profile/fork — при созревании универсального ядра
```

Клиентские особенности реализуются конфигурацией и profile boundaries, а не
копированием отдельной легаси-системы под каждого заказчика.

### Три слоя бренда

```text
PrettyK
├── prettyk.io
│   └── Product / Execution layer — Keeper
├── PrettyK Control Plane
│   └── prettyk-control-plane — Cosmo
└── PrettyK Findings Control Station & QG Triage
    └── D:\prettyk-qgfcs — Gatekeeper
```

---

## 23. Scanner capability baseline

> **Статус:** ADMITTED by 2FA  
> **Принцип:** capability = что проверяем; provider = чем проверяем  
> **Правило:** scanner запускается только для применимого артефакта/профиля

### Source / repository profile

```text
Gitleaks
  → secret_scan
  → repository/source/files

SonarQube
  → source quality/security analysis

CodeScoring
  → SCA/license analysis

CycloneDX
  → canonical SBOM contract

KICS
  → IaC policy scan, только если найден IaC

SLSA
  → provenance capability
```

Source code не запускается через container-only проверки.

### Container / deployment profile

```text
Hadolint
  → Dockerfile/build-context lint

CycloneDX
  → SBOM contract

Trivy
  → container vulnerability scan

ClamAV
  → artifact content/malware scan

KCS
  → последний container scan по exact Build digest

KubeLinter
  → Kubernetes manifest lint
```

Container profile не запускает SonarQube, CodeScoring или CodeQL как image scan.
KCS получает конкретный `image@sha256:digest` от Build, не mutable tag и не
произвольный образ из registry.

### Provenance и SBOM

```text
SLSA      = единственный product capability provenance
in-toto   = возможный технический wire format, не отдельный step

CycloneDX = единственный product SBOM contract
Syft      = возможный генератор, не отдельный business step
```

### CodeQL policy

```text
PureK ordinary source:
  SonarQube + CodeQL

PrettyK Control Plane ordinary source:
  SonarQube + CodeScoring
  CodeQL не активируется до готового bridge

PrettyK Control Plane security/regulatory source:
  SonarQube + CodeScoring + CodeQL
  только после licensing/offline/query/executor/Evidence bridge
```

CodeQL — source semantic analysis, не container scanner.

### Build modes

```text
Development Build:
  разработчик/тестер выбирает шаги для работы и отладки
  результат не является Release и не квалифицирует transfer

Release Build:
  immutable ReleaseType profile
  steps не меняются чекбоксами
  QG/Gates/Evidence/Act обязательны по policy
```

Hotfix может убрать разрешённые optional technical steps, но не может обходить:

```text
PrettyK QG
required Gates
Evidence
Act
Release Package readiness
```

### Не входит в baseline

```text
Checkov
OPA/Conftest
YARA
Grype
```

Они не включаются «на всякий случай».

### Low-priority candidates

```text
Semgrep → fast/custom SAST for development/hotfix profiles
CodeQL  → activated per policy only after bridge requirements
cosign  → possible image-signature value for future GAP supply chain
```

Ни один из них не становится default без отдельного 2FA и явной бизнес-ценности.

---

## 24. SecOps Studio, Gatekeeper and Control Plane authority boundary

> **Статус:** PROVISIONAL — product essence agreed; exact contract requires joint 2FA with Gatekeeper  
> **Связанный request:** `friend/requests/2026-08-31-secops-studio-gatekeeper-control-plane-flow.md`

### Продуктовый поток

```text
PrettyK Control Plane
→ Release/Build/artifact/required-step context
→ Gatekeeper QG Center processing
→ qualifying deployment
→ PrettyK SecOps Studio post-deployment DAST/AppSec
→ final Studio PASS/FAIL + Act + Evidence
→ Gatekeeper triage/policy/clearance
→ Control Plane OK_TO_TRANSFER
```

### Authority

```text
PrettyK SecOps Studio
  → DAST execution authority
  → final DAST PASS/FAIL
  → final Act

Gatekeeper QG Center
  → findings, triage, baseline, approvals, policy explanation
  → PASS_GRANTED only after Studio PASS + Act + applicable policy

PrettyK Control Plane
  → Release/Package orchestration
  → consumes clearance; does not recompute DAST QG
```

Studio FAIL cannot be silently overridden by Gatekeeper or Control Plane.

### Required step failure

```text
required Build/registry/scanner step fails or is unavailable
→ qualifying deploy does not start
→ DAST is not expected
→ Release BLOCKED before QG
→ no transfer
```

This is execution failure, not a QG warning and not a triage decision.

### Diagnostic exception

Limited investigation deployment may exist only as an explicitly authorised,
non-qualifying path. It can produce findings and Evidence but can never produce:

```text
qualified Release
PASS_GRANTED
OK_TO_TRANSFER
```

### Remediation loop

```text
findings
→ remediation/triage
→ new Build
→ qualifying deployment
→ new Studio DAST + Act
→ repeat until current PASS
→ Gatekeeper clearance
→ Control Plane transfer permission
```

Every iteration is preserved as a new ScanRun/FindingOccurrence/Evidence record.
Nothing is silently overwritten or muted.
