# Project composition, optional project manifest и равноправные applications

> **Статус:** friend-request / first 2FA agreed / awaiting implementation acceptance  
> **Дата:** 30 августа 2026  
> **Участники:** Максим ↔ Cosmo  
> **Связанные направления:** Project, KITS, Project Graph, ReleaseType, ReleaseBatch

---

## 1. Решение

В Cosmoport не переносим легаси-«группирующий второй уровень» и не используем
его как замену проекту.

```text
Project
├── optional Project Manifest card/repository
├── Application A → Repository A
├── Application B → Repository B
└── Application N → Repository N
```

Все приложения равноправны по умолчанию. Их роль в конкретной композиции задаётся
связями, типом артефакта и выбранным профилем ЖЦ, а не обязательным L0/L1/L2.

---

## 2. Project Manifest

### Предлагаемое имя

```text
UI label: Project Manifest
code: project_manifest
```

`Project Manifest` — отдельный тип project-level карточки и репозитория. Это не
обычное приложение и не новый «группирующий уровень».

Назначение:

- хранить manifest проекта;
- описывать состав;
- хранить зависимости и связи;
- задавать общий контекст сборки;
- быть координатором project batch;
- при необходимости иметь собственный Build/Deploy.

По умолчанию Build/Deploy для `project_manifest` выключены или не требуются.
Если manifest реально производит deployable artifact, это должно быть явно
включено его профилем, а не следовать из самого факта существования карточки.

### Создание

В диалоге «Создать проект»:

```text
[✓] Создать Project Manifest repository
```

Предлагаемое поведение — переключатель включён по умолчанию, но его можно
отключить для простого проекта.

Если включён:

```text
1 Project
1 Project Manifest card
1 Project Manifest repository
N Applications
N Application repositories
```

Если выключен:

```text
1 Project
N Applications
N Application repositories
```

Проект без manifest repository остаётся полноценным проектом: его граф, состав,
команды и batch-release не исчезают.

### Legacy mapping

```text
Cosmoport 1.0 meta_project
  → Cosmoport 2.0 Project
  + optional project_manifest
```

`meta_project` не переносится как имя и не становится уровнем приложения.

---

## 3. Drag-and-drop composition

Главный project-flow:

```text
Создать проект
  → drag-and-drop N folders
  → система предлагает N applications
  → показывает proposed graph
  → оператор настраивает KITS/team/settings
  → выбирает Project Manifest on/off
  → проходит validation
  → нажимает «Создать проект»
```

До подтверждения система должна показать:

- список будущих приложений;
- app-code и названия;
- предполагаемый artifact kind;
- зависимости;
- KITS tags;
- Project Team;
- root manifest toggle;
- будущие repository names/URLs;
- Build/Deploy applicability;
- ошибки валидации.

Нельзя сначала создать половину репозиториев, а потом выяснять, что схема
невалидна.

### Materialization

После валидной схемы:

```text
Project
→ optional Project Manifest
→ N equal Applications
→ N repositories
→ graph edges
→ KITS tags
→ Project Team
```

Создание должно быть атомарным с точки зрения результата или явно показывать
partial failure и состояние восстановления. Молчаливого частичного успеха нет.

---

## 4. Equal Applications

### Базовая модель

```text
Application
├── one own repository
├── own Build
├── own Deploy policy
├── own Lifecycle profile
├── own Release
└── own Team overrides
```

L0/L1/L2 не являются обязательными operational roles.

Legacy level/kind допускается хранить как migration metadata, но он не должен
определять:

- возможность Build;
- возможность Deploy;
- права;
- наличие проекта;
- тип registry scan;
- возможность Release.

### Application без проекта

В диалоге:

```text
Создать приложение
```

создаётся:

```text
1 Application
1 Repository
```

Приложение может жить без Project и позднее подключаться к нескольким проектам:

```text
Application X
  ↳ Project A
  ↳ Project B
  ↳ Project C
```

При подключении:

- репозиторий не копируется;
- новый репозиторий не создаётся;
- application identity сохраняется;
- проект получает ссылку на существующее приложение;
- граф каждого проекта может быть своим.

---

## 5. Libraries as reusable bricks

Библиотека — это профиль использования и visibility, а не обязательный уровень.

```text
Public Library
  → read/build/deploy: всем разрешённым потребителям
  → commit/write/settings: только Application Team
```

Одна библиотека может использоваться в нескольких проектах и приложениях:

```text
shared-crypto-lib
  ↳ Project A / auth-service
  ↳ Project B / payment-api
  ↳ Project C / reporting
```

Связь выражается графом зависимости:

```text
consumer → dependency
```

Порядок сборки строится топологически. Если библиотека изменилась, система может
показать затронутых потребителей, но не превращает библиотеку в особый L0-класс.

---

## 6. Artifact-aware build/deploy

Каждое равноправное приложение получает профиль по фактическому артефакту:

```text
source code
  → source lifecycle

Docker image
  → container lifecycle

package/config/documentation
  → соответствующий профиль
```

В одном проекте и batch допускаются разные профили:

```text
app-a → source → SonarQube/CodeScoring/SBOM
app-b → image  → SBOM/Trivy и/или подтверждённый KCS
app-c → library → library profile
```

---

## 7. Release model

У каждого Application собственный Release и собственный ReleaseType.

На уровне Project создаётся партия:

```text
Project Release Batch
├── Application Release A
├── Application Release B
└── Application Release C
```

`Project Manifest` может участвовать как координатор, но не превращает дочерние
приложения в один общий неразличимый релиз.

---

## 8. Acceptance scenarios

### Project with root manifest

```text
Given: N=3 folders
When: Project Manifest включён
Then:
  1 Project
  1 project_manifest card/repository
  3 Applications
  3 Application repositories
  graph valid
```

### Project without root manifest

```text
Given: N=3 folders
When: Project Manifest выключен
Then:
  1 Project
  3 Applications
  3 Application repositories
  project remains usable
```

### Standalone application reuse

```text
Given: создано standalone Application X с одной репой
When: X добавляют в два проекта
Then:
  repo остаётся один
  app identity остаётся одна
  обе композиции видят X
  graph/team/release context не смешиваются автоматически
```

### Reusable library

```text
Given: public library L
When: два проекта используют L
Then:
  оба могут читать/build/deploy L по policy
  commit/settings доступны только Library Team
  dependency edges видны в графах
```

### Invalid composition

```text
Given: drag-and-drop предложил cycle или битый repository URL
When: оператор доходит до validation
Then:
  Create Project disabled
  причина показана
  репозитории не создаются
```

---

## 9. Open details

До второго 2FA нужно подтвердить:

1. `Project Manifest` — финальное имя или нужен другой label/code.
2. Включён ли root manifest по умолчанию или выключен.
3. Может ли один Project Manifest ссылаться на приложения из нескольких проектов.
4. Как разводятся Project Team и Application Team при повторном подключении приложения.
5. Может ли один проект иметь несколько manifest repositories.
6. Какие форматы принимает drag-and-drop: папки, архивы, существующие репозитории.

До подтверждения решение имеет статус `friend-request / implementation candidate`.
