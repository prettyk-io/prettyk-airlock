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
D:\cosmoport2\battlecruiser\friend\requests\
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
D:\cosmoport2\battlecruiser\captains_bridge.md
D:\cosmoport2\battlecruiser\README.md
D:\cosmoport2\battlecruiser\friend\requests\
D:\cosmoport2\battlecruiser\pure\ARTIFACT-REGISTRY-CANON.md
D:\cosmoport2\battlecruiser\cosmoport2\ARTIFACT-REGISTRY-CANON.md
D:\cosmoport2\battlecruiser\cosmoport2\CANON-INDEX.md
D:\cosmoport2\battlecruiser\cosmoport2\NEXT-RAILS-BACKLOG.md
D:\cosmoport2\docs\COSMOPORT2-CANONICAL-MONOLITH.md
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
