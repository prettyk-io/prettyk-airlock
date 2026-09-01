# Inspection: legacy release package `20260819183846278`

> **Дата:** 1 сентября 2026 года.
> **Источник:** локальный файл `C:\Users\mails\Downloads\20260819183846278_package_archive.tar.gz`.
> **Статус:** research evidence. Это не принятие legacy-формата как PureK-контракта.

## 1. Состав outer archive

Внешний `tar.gz` содержит только два объекта:

```text
20260819183846278_repo.tar.gz
20260819183846278_package.yml
```

Отдельных `files` и `exports` archives нет: соответствующие поля в metadata
пустые. Внешний package — это metadata envelope плюс repository archive.

## 2. Что описано в `package.yml`

Пакет относится к meta-project release:

```text
project: second-1832-2
release tag: 0.0.2
build title: Релиз: 0.0.2
transfer_type: sod
```

В metadata присутствуют:

- project/meta-project identity;
- release и build identity;
- два sub-project entries;
- `build_order` и `deployment_order` со значениями 1 и 2;
- два `sub_project_releases`;
- repository binding;
- owner reference;
- transfer status reference;
- признак доступности Sfera deployment.

Пустыми или отсутствующими выглядят:

- group;
- runtimes;
- resources;
- environment profiles;
- custom pipeline;
- files archive;
- exports archive;
- sub-meta-project builds/releases.

Это похоже на мета-проект с двумя упорядоченными sub-projects, без вложенного
следующего уровня.

## 3. Состав repository archive

Вложенный `repo.tar.gz` содержит только пустой Git working repository skeleton:

```text
.git/HEAD
.git/config
.git/description
.git/hooks/*.sample
.git/info/exclude
.git/objects/pack/
.git/refs/heads/
.git/refs/tags/
```

Commit objects, refs, рабочие файлы и payload в архиве не обнаружены. Это означает,
что именно этот экземпляр package фактически metadata-only.

## 4. Наблюдение по checksum

Поле legacy `checksum` имеет значение:

```text
d41d8cd98f00b204e9800998ecf8427e
```

Это известное MD5-представление пустого значения. По одному полю нельзя доказать,
что именно оно проверяет. Для PureK это достаточная причина не наследовать его как
integrity contract:

```text
PureK:
  manifest
  SHA-256 package/object checksums
  immutable package revision
  target re-check
```

## 5. Архитектурные выводы

1. PreTransferValidator обязан проверять не только структуру metadata, но и
   **достаточность payload** для заявленного результата.
2. Metadata-only package может быть допустимым режимом для создания target
   skeleton/context, но не должен молча считаться deployable release.
3. Для deployable release нужно проверять наличие всех ожидаемых repository,
   artifact и dependency references, а также соответствие `build_order` /
   `deployment_order` закрытому графу.
4. Target Checkup должен отличать:

   ```text
   metadata-only / skeleton landing
   deployable release landing
   incomplete or invalid package
   ```

5. `transfer_type: sod` — только характеристика legacy package. Она не должна
   определять PureK transport или package schema.
6. Реальный архив подтверждает необходимость нашего разделения:

   ```text
   package generation
   → pre-transfer validation
   → transport
   → target checkup
   → bootstrap
   → deployment readiness
   ```
