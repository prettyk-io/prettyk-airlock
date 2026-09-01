# Cosmoport 2.0 — канон Artifact Registry

> **Статус:** согласованное направление, provider contract требует отдельной реализации  
> **Текущий инстанс:** Cosmoport ПлЦР / ЗР  
> **Provider path:** старый Nexus → mirror/staging → Т1-Сфера

## 1. Зачем нужен слой

Cosmoport управляет не только Git и Build. Ему нужен отдельный слой хранения и
доставки образов, SBOM и сборочных артефактов:

```text
Source / Build
  → Artifact Registry
  → artifact-aware checks
  → Release
  → Deployment по immutable digest
```

Cosmoport не хранит образы в PostgreSQL, не строит собственное файловое
хранилище и не должен ссылаться на один только `latest`.

## 2. Т1-Сфера

На официальной странице Т1/Сфера продуктовая линейка описывает:

- инструменты корпоративного уровня для сквозного процесса производства ПО;
- «Сфера.Сборка» с интеграцией разработки, тестирования и развертывания;
- хранение и управление артефактами разработки;
- отдельный продукт «Сфера.Дистрибутивы и лицензии» для работы с артефактами
  разработки и сборки;
- личные репозитории команд;
- объединение репозиториев в группу;
- проксирующие репозитории с кешированием;
- произвольные метаданные компонентов;
- staging-перенос компонентов между средами;
- SCA, SBOM и контроль лицензий;
- RBAC, LDAP и REST API.

Источник метаинформации:

```text
https://www.sferaplatform.ru/sfera-platform
https://www.sferaplatform.ru/distributivy-licenzii
```

Эти страницы подтверждают продуктовую роль Сферы как отечественного слоя
управления артефактами и зависимостями. Они **не подтверждают автоматически**
конкретную OCI/Docker Registry V2 совместимость, поэтому это отдельная проверка.

## 3. Зачем она нужна в ЦБ-контуре

Выбор Т1-Сферы в закрытом российском контуре естественно связан с:

- импортозамещением после 2022 года;
- снижением зависимости от внешних вендоров;
- on-premise/airgap-размещением;
- контролем цепочки поставки;
- локальным управлением артефактами и зависимостями;
- поддержкой корпоративных политик SCA/SBOM/лицензий.

Переходный режим для Cosmoport:

```text
старый Nexus
  → mirror/staging
  → Т1-Сфера
```

Nexus остаётся переходным источником, а Т1-Сфера — целевым отечественным
provider. Второй registry fallback не закладывается.

### Наблюдаемая схема репозиториев Сферы

По текущему наблюдению, при создании одной GitLab-репозитории в Сфере создаётся
четыре связанных репозитория:

```text
clean
dirty
raw
```

Это пока зафиксированная topology, но не расшифрованный семантический контракт.
Нужно отдельно выяснить у коллег и по живому скрейпу:

- что именно пишется в `raw`;
- что считается `dirty`;
- кто и по какой политике переносит данные в `clean`;
- участвует ли KCS в переходе `dirty → clean`;
- являются ли эти репозитории физическими, логическими или proxy/staging views;
- что разрешено хранить в `docs`;
- как четыре репозитория связаны с Build, SBOM и Release Package.

До подтверждения это имеет статус:

```text
observed / semantics unknown
```

## 4. Нейтральный provider contract

Cosmoport использует абстракцию, а не жёсткую привязку к Т1-Сфере:

```text
ArtifactRegistry
├── registry_id
├── provider
├── endpoint
├── zone
├── repository_namespace
├── read_policy
├── write_policy
└── secret_ref
```

Провайдеры:

```text
nexus
t1_sfera
```

Операционный минимум:

```text
push_artifact()
pull_manifest()
resolve_digest()
check_artifact()
get_sbom_reference()
```

Реализация — через официальный REST/OCI/Docker Registry API. Внутренние SDK и
модули registry-поставщиков в Cosmoport не импортируются.

## 5. Registry metadata в Build/Release

Build и Release должны фиксировать:

- `registry_id`;
- provider;
- repository;
- artifact/image name;
- tag;
- immutable digest;
- media type;
- размер;
- SBOM reference;
- scan references;
- signature/attestation, если доступно.

В БД хранятся только ссылки на секреты:

```text
vault:secret/...
openbao:secret/...
```

## 6. Registry по зонам

```text
Cosmoport ЗР  → Registry ЗР
Cosmoport ЗТ  → Registry ЗТ
Cosmoport ЗПЭ → Registry ЗПЭ
```

Текущий scope — Registry ЗР. ЗТ и ЗПЭ будут отдельными инстансами с отдельными
registry. Физическое перемещение образов между зонами остаётся за sovereign
zone-transfer контуром; legacy СОД подключается к Cosmoport 2 отдельным bridge
adapter. МЗП исключён.

## 7. Artifact-aware lifecycle

Профиль ЖЦ определяется типом артефакта, типом приложения и Типом релиза.

### Source code

```text
Build
→ Unit Tests
→ Documentation
→ SonarQube
→ CodeScoring
→ SBOM
→ Deploy в ЗР
```

Для обычного source code не запускаем KCS/Trivy как container scan.

### Docker/container image

```text
Build image
→ SBOM
→ Trivy и/или KCS
→ Deploy в ЗР
```

Docker-образ не отправляем на SonarQube/CodeScoring как на source-code scan.

В одном `Project Release Batch` разные приложения могут иметь разные типы
артефактов и разные профили ЖЦ.

## 8. Проверка Т1-Сферы до реализации адаптера

Нужно получить официальную документацию или разрешённый доступ и проверить:

1. OCI/Docker Registry V2 compatibility;
2. push/pull/manifest/digest;
3. authentication и robot/service accounts;
4. TLS и airgap deployment;
5. repository/group/proxy/cache semantics;
6. webhook/event API;
7. SBOM и signature/attestation support;
8. REST API и лимиты;
9. staging/promote semantics;
10. модель RBAC и secret integration.

До этой проверки `t1_sfera` — утверждённый архитектурный target, но не заявленная
реализованная интеграция.

## 9. Не входит в scope

- собственный registry;
- хардкод Т1-Сферы в ядре;
- копирование или несанкционированное извлечение продукта;
- общая registry-БД между зонами;
- реализация СОД bridge до исследования его внешнего контракта;
- любая реализация МЗП;
- внутренние импорты PureK/PrettyK;
- подмена artifact registry локальными mock-файлами.
