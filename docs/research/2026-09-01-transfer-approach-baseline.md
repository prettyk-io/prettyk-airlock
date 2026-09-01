# Transfer approach baseline

> **Статус:** согласованная PO-direction, не vendor contract и не окончательный
> deployment profile. Это фиксирует смысл текущего решения, чтобы не возвращаться
> к спору о «единственном правильном gap transport».

## 1. Customer network reality

Сетевой путь между зонами в большинстве случаев задаётся не PureK и не нашей
архитектурной прихотью. Он определяется заказчиком, security policy, владельцем
сети, действующим оборудованием, режимом изоляции и операционной процедурой.

Поэтому PureK не выбирает один универсальный transport и не делает customer
network похожей на удобную для приложения. PureK поставляет собственный общий
transfer kernel, несколько готовых transport profiles и extension seams для
customer-specific bridges.

Кастомизация под заказчика ожидаема и допустима. Наша цель — минимизировать её
до profile/configuration/adapter/deployment boundary, не размазывая customer
semantics по core domain и package contract.

## 2. PureK-owned invariants

Независимо от выбранного crossing approach должны сохраняться:

- immutable logical Release Package Set;
- `manifest.json` и per-item digest/checksum;
- `release_id`, `package_revision`, `transfer_plan_id`;
- correlation и idempotency;
- required/optional payload declaration;
- per-item status/retry/recovery;
- target staging и integrity verification;
- package-set completeness barrier;
- `LandingCheckReport` и `isLandingApproved`;
- reconstruction только после готовности обязательных items;
- audit/evidence references;
- target bootstrap и reconcile как отдельные observable stages.

Transport не должен менять эти invariants.

## 3. Approach suite

### Baseline profiles

1. **Direct authenticated transfer** — для connected/nongap маршрутов.
2. **Offline package exchange** — для airgap без live network.
3. **Controlled gateway/relay** — для разрешённого управляемого cross-zone path.
4. **Data diode** — для строгого физического one-way crossing.
   - strict one-way + operator ACK;
   - one-way data + отдельный разрешённый control/ACK channel.

### Optional adapter seam

Предусмотреть extension point для customer-specific:

- СОД;
- MFT/secure file exchange;
- vendor transfer appliance;
- proprietary gateway;
- firewall/session manager;
- registry/repository bridge;
- иного approved transport provider.

Наличие seam не означает, что конкретный vendor tool входит в PureK или должен
быть реализован заранее.

## 4. Что не смешивать

Это разные понятия:

```text
gap/security principle
  ≠ hole/session mechanism
  ≠ payload protocol
  ≠ artifact provider
  ≠ release package contract
```

Например, один маршрут может выглядеть так:

```text
strict data diode
  + diode sender/receiver protocol-break
  + immutable Package Set
  + Git/OCI/Nexus/evidence TransferItems
  + target staging and completeness barrier
```

А другой:

```text
controlled gateway
  + mTLS transfer API
  + resumable streaming
  + the same immutable Package Set
```

## 5. Logical unity, physical multi-plane delivery

Релиз передаётся как единый логический Package Set, но физически может быть
разделён на items/planes:

```text
metadata | source/Git | OCI | package/Nexus | evidence
```

Каждый item может иметь свой approved transport и provider. Это не разрешает
реконструкцию из случайно приехавшего поднабора.

Нормативная sequence для PureK direction:

```text
receive items separately
→ verify each item
→ evaluate completeness together
→ approve landing
→ split/import into provider planes
→ reconstruct target context
→ bind integrations
→ reconcile
→ ready for lifecycle
```

В физически едином offline archive всё это всё равно должно оставаться
логически раздельным через manifest и item records.

## 6. Что пока не решаем

Пока не фиксируем окончательно:

- какой profile primary для каждой customer network topology;
- нужен ли заказчику СОД вообще;
- какой именно vendor bridge будет подключён;
- какие payload planes конкретный bridge способен переносить;
- нужен ли отдельный transfer coordinator;
- какую часть ACK/status feedback возможно получить через gap.

Эти решения принимаются после customer/network evidence. Но core package,
landing и recovery boundaries от этого не должны плавать.

## 7. Роль legacy reference

Исходники СОД и Notification Service разрешено использовать как бесплатный
reference: найти реальные контракты, ограничения, recovery cases и полезные
операционные паттерны.

Они не являются автоматически:

- PureK architecture;
- product requirements;
- обязательными сервисами;
- default transport;
- доказательством необходимости Kafka, отдельного notification service или
  конкретной package topology.

Temporary inspection agent может отдельно выписать **general approach insights**,
если они следуют из фактов. Такие insights должны быть явно помечены как
non-binding observations и рассматриваться PO после отчёта, а не автоматически
добавляться в backlog или contracts.