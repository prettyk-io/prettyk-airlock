# Naming proposal: PrettyK Control Plane

> **Статус:** friend-request / naming suggestion / not canon  
> **Дата:** 31 августа 2026  
> **Инициатор:** Максим  
> **Обсуждение:** Максим ↔ Cosmo

## Proposal

Переименовать продуктовую сущность Cosmoport 2.0 в:

```text
PrettyK Control Plane
```

При этом после переименования техническое имя репозитория:

```text
prettyk-control-plane
```

## Причина и позиционирование

`Cosmoport` — не отдельная конечная продуктовая сущность. Это первый рабочий
alias/profile и первая интеграция, на которой сейчас скрейпится ЦБ/ПлЦР-контур
и строится универсальное ядро.

```text
PrettyK Control Plane
  ├── Cosmoport alias/profile — первая интеграция, текущий ЦБ/ПлЦР scope
  └── PureK profile/fork      — появится после созревания универсального ядра
```

Сначала строится универсальная control-plane основа. После этого она
кастомизируется под конкретных заказчиков и поставки, а не превращается в
отдельный легаси-продукт на каждого клиента.

Предлагаемая граница:

```text
PrettyK bundle
├── PrettyK execution plane
├── Findings Control Station
└── PrettyK Control Plane
```

`Cosmoport` остаётся:

- alias первой интеграции;
- текущим UI/brand name для ЦБ/ПлЦР-профиля;
- именем discovery context;
- техническим repository/package namespace после rename.

В будущем PureK будет рождён и выделен как отдельный профиль/fork тогда, когда
универсальное ядро и граница кастомизации будут достаточно зрелыми.

## Что не меняется автоматически

- repository path `prettyk-control-plane`;
- Python package names;
- API prefixes;
- Docker image names;
- database names;
- пользовательские маршруты;
- PureK/Cosmoport code boundary.

Название не является основанием для массового rename без отдельного migration
plan.

## Вопросы для 2FA

1. Финальное публичное имя — `PrettyK Control Plane` или другой вариант?
2. Остаётся ли `Cosmoport` временным UI label?
3. Как называть backend package и API namespace?
4. Как разделять PrettyK Control Plane и PureK execution plane в bundle?
5. Нужно ли оставлять `Cosmoport 2.0` как version/legacy alias?
6. Какие docs и registry names менять после admission?

До второго 2FA и migration plan это только naming proposal.
