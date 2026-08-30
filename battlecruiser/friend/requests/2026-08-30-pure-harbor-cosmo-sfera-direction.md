# Provider direction: PureK Harbor, Cosmoport Т1-Сфера

> **Статус:** friend-request / first 2FA agreed / awaiting implementation evidence  
> **Дата:** 30 августа 2026  
> **Участники 2FA:** Максим ↔ Cosmo

## 1. Решение, которое предлагаем принять

### PureK/PrettyK

```text
Nexus + Harbor
без Т1-Сферы
```

Разделение ролей:

```text
Nexus  → широкий dependency/artifact hub
Harbor → container/OCI registry и staging для образов
```

Т1-Сфера в PureK-контур не входит.

### Cosmoport 2.0

```text
старый Nexus
  → mirror/staging
  → Т1-Сфера
```

До доступности Т1-Сферы Cosmoport должен работать в переходном режиме через
Nexus/совместимый OCI provider. Т1-Сфера — target текущего ЦБ-направления, но не
единственная предпосылка запуска Cosmoport.

Artifactory из обоих направлений исключён.

## 2. Подтверждённая семантика Сферы

Подтверждено в обсуждении:

```text
dirty → после SAST/SCA
clean → после DAST + всех Gates PASS
```

Наблюдаемая topology:

```text
raw
dirty
clean
```

Предварительное описание `raw` и `docs`, а также точная роль KCS требуют
подтверждения у коллег/вендора. Не кодировать их semantics до evidence.

## 3. Роль Harbor в PureK

Harbor допускается как специализированный container/OCI слой:

- хранение образов;
- container staging;
- registry projects/namespaces;
- RBAC и robot accounts;
- digest-based identity;
- promotion/replication, если нужно поставке;
- Kubernetes pull;
- security/SBOM/signature integration при наличии контрактов.

Harbor не заменяет Nexus для всех package ecosystems и не должен становиться
вторым source of truth для одних и тех же артефактов.

## 4. Что требуется проверить до canon admission

### PureK Harbor

- registry protocol;
- push/pull/manifest/digest;
- retention/GC;
- robot accounts;
- RBAC;
- staging/promotion;
- Kubernetes pull;
- airgap operation.

### Cosmoport Т1-Сфера

- официальный API;
- OCI/Docker compatibility;
- Nexus mirror/staging path;
- four-repository semantics;
- clean/dirty promotion;
- KCS role;
- SBOM/Act/digest behavior;
- secret and RBAC model.

## 5. Правило до второго 2FA

До реализации и тестов:

- PureK canon не меняется на Harbor;
- Cosmoport canon не объявляет Harbor production provider;
- Т1-Сфера остаётся target/capability unknown;
- `clean/dirty` можно использовать как подтверждённое domain finding;
- `raw/docs/KCS promotion` остаются observed/provisional.

После evidence и targeted tests request можно перенести в:

```text
D:\cosmoport2\battlecruiser\pure\
D:\cosmoport2\battlecruiser\cosmoport2\
```

только после повторного 2FA и polish.
