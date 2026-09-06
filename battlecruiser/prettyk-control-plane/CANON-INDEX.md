# Cosmoport 2.0 — индекс канонов Battlecruiser

## Главный монолит

```text
D:\prettyk-airlock\docs\COSMOPORT2-CANONICAL-MONOLITH.md
```

Он содержит согласованную модель:

- instance-per-airgap/zone;
- КИТС как tags;
- Project как главную сущность;
- Applications и teams;
- роли и visibility;
- Pipeline/Build/Run/Evidence/Gates;
- Release Types;
- Project Release Batch;
- PrettyK DAST/QG;
- Release Package;
- sovereign cross-zone transport, СОД bridge и future zone instances.

## Канон artifact registry

```text
pure/ARTIFACT-REGISTRY-CANON.md
```

Nexus — baseline target для PureK/PrettyK bundle.

```text
prettyk-control-plane/ARTIFACT-REGISTRY-CANON.md
```

Т1-Сфера — целевой отечественный provider для Cosmoport 2.0.
Nexus — переходный источник через mirror/staging.
Второй registry fallback в Cosmoport target не входит.

## Текущее решение по Cosmoport

```text
Cosmoport
  → нейтральный ArtifactRegistry adapter
  → provider из instance configuration
  → старый Nexus → mirror/staging → t1_sfera
```

Свой registry не пишем. Т1-Сферу не считаем OCI/Docker-compatible до проверки
официальной документации и доступной поставки.

## Связанные источники

- Официальная страница платформы Сфера: <https://www.sferaplatform.ru/sfera-platform>
- Официальная страница «Сфера.Дистрибутивы и лицензии»: <https://www.sferaplatform.ru/distributivy-licenzii>
- Документация PrettyK Control Plane в репозитории: `D:\prettyk-airlock\docs\`
