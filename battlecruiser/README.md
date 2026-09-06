# Battlecruiser — общие каноны экосистемы

> **Назначение:** единая папка для согласованных архитектурных канонов PureK/PrettyK и Cosmoport 2.0.  
> **Дата создания:** 30 августа 2026

## Структура

```text
D:\prettyk-airlock\battlecruiser\
├── README.md
├── captains_bridge.md
├── ADMISSION.md
├── MAXIM-PROFILE.md
├── friend\
│   └── requests\
├── pure\
│   └── ARTIFACT-REGISTRY-CANON.md
└── prettyk-control-plane\
    ├── CANON-INDEX.md
    └── ARTIFACT-REGISTRY-CANON.md
```

## Продуктовые контуры

```text
PureK / PrettyK
  → DAST/AppSec runtime
  → browser, scanner, fuzzer, test execution
  → собственные artifact/dependency registry integrations

Cosmoport 2.0
  → operator control plane
  → projects, applications, builds, lifecycle, gates, evidence, releases
  → release package, sovereign cross-zone transport и bridge к СОД
```

## Общие правила

1. PureK и Cosmoport — разные продукты и разные кодовые контуры.
2. Никаких внутренних импортов между репозиториями и продуктовыми модулями.
3. Общение между контурами — REST, webhook, SSE и официальные протоколы registry.
4. Не пишем собственный artifact registry, если задачу закрывает Nexus или другой утверждённый provider.
5. Provider выбирается конфигурацией конкретной поставки, airgap-сети и зоны.
6. Образы и релизные артефакты фиксируются immutable digest, а не только mutable tag.
7. В БД хранятся только secret references; raw credentials не допускаются.
8. ЗР, ЗТ и ЗПЭ — отдельные инстансы с отдельными Gitea, registry и БД.
9. Sovereign cross-zone transport — default для PrettyK и Cosmoport 2. СОД —
   внешняя bridge-интеграция; его внутреннюю механику не выдумываем. МЗП исключён.
10. Лицензионные продукты используем только по легальной поставке, документации и разрешённым API.

## Каноны по направлениям

### Pure

`pure/ARTIFACT-REGISTRY-CANON.md` — Nexus как baseline integration target для PureK/PrettyK bundle.

### Cosmoport 2.0

`prettyk-control-plane/ARTIFACT-REGISTRY-CANON.md` — миграционный путь Control Plane: старый Nexus → mirror/staging → Т1-Сфера.

Основной продуктовый монолит пока находится в:

```text
D:\prettyk-airlock\docs\COSMOPORT2-CANONICAL-MONOLITH.md
```

Индекс связки — `prettyk-control-plane/CANON-INDEX.md`.
