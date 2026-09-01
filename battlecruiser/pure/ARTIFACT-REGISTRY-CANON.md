# PureK / PrettyK — канон Artifact Registry

> **Статус:** baseline integration canon  
> **Контур:** PureK/PrettyK bundle  
> **Provider baseline:** Nexus

## 1. Роль PureK/PrettyK

PureK/PrettyK — исполнительный DAST/AppSec и тестовый контур. Он может работать
с исходным кодом, зависимостями, контейнерными образами и артефактами, но не
должен превращаться в собственный registry, если хранение уже закрывается
готовым продуктом.

```text
PureK/PrettyK
  → получает source/image/artifact reference
  → запускает собственные проверки
  → возвращает результат, Evidence и акт
```

## 2. Nexus

Nexus — утверждённый integration target для PureK/PrettyK bundle.
Они подходят как:

- registry для контейнерных образов;
- repository для зависимостей и сборочных артефактов;
- proxy/cache для внешних зависимостей;
- источник immutable manifest/digest;
- локальный provider в airgap-поставке.

PureK не пишет собственное хранилище образов, менеджер зависимостей или proxy
registry поверх этих продуктов.

## 3. Adapter boundary

Интеграция выполняется через официальный API/протокол конкретного provider:

```text
RegistryAdapter
├── resolve artifact
├── pull manifest / metadata
├── resolve digest
├── push result/artifact, если разрешено поставкой
├── read SBOM reference
└── publish scan/evidence reference
```

Внутренние SDK и модули Nexus в PureK не импортируются.

## 4. Security и supply chain

Для каждого образа или артефакта по возможности фиксируются:

- registry URL/ID;
- repository;
- artifact name;
- tag;
- immutable digest;
- media type;
- SBOM reference;
- scan result reference;
- signature/attestation, если provider её поддерживает.

`latest` и другие mutable tags не являются достаточной идентификацией релизного
артефакта.

Credentials хранятся только через secret reference. PureK не получает raw
пароли в конфигурации или в Evidence.

## 5. Airgap и зоны

PureK не предполагает единую registry на все зоны:

```text
PureK/PrettyK ЗР  → registry ЗР
PureK/PrettyK ЗТ  → registry ЗТ
PureK/PrettyK ЗПЭ → registry ЗПЭ
```

Конкретный provider задаётся конфигурацией поставки. Для PureK baseline
используется Nexus; второй registry fallback не закладывается.

## 6. Не входит в этот канон

- написание собственного registry;
- копирование или обход лицензии коммерческих продуктов;
- зашивка одного provider в ядро PureK;
- импорт Cosmoport-модулей;
- утверждение совместимости Т1-Сферы с OCI/Docker без проверки документации;
- реализация sovereign cross-zone transport или СОД bridge без отдельного
  межпродуктового admission; МЗП исключён.

Т1-Сфера остаётся отдельным Cosmoport-target до подтверждения конкретной
поставки и API-контракта.
