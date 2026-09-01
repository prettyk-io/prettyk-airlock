# ПУ — черновик ТЗ: qualification и transfer flow

> **Статус:** рабочий черновик требований, 31 августа 2026 года. Не канон и не
> замена `ADMISSION.md`. Основан на продуктовых решениях Максима; открытые вопросы
> собраны в конце до начала implementation.

## 1. Цель

ПУ проводит релиз по жизненному циклу до production. Коробка выполняет DAST и
выпускает raw result, Evidence, execution verdict и Act. Хаб — source of truth
для Findings, решений, baseline и вычисленного QG status. ПУ остаётся
единственным оркестратором сборки, пакета, transfer и deployment.

```text
ПУ
→ Build / required checks / qualifying deployment
→ коробка: DAST + Evidence + execution verdict + Act
→ хаб: intake + Finding/triage/baseline/approval + QG assessment
→ хаб publishes candidate status: waiting | blocked | unlocked
→ ПУ monitors status and waits for unlocked
→ ПУ performs transfer
→ transfer release package
→ deployment in ЗПЭ
→ status «В эксплуатации»
```

Коробка закрывает DAST-часть security lifecycle. Хаб вычисляет QG Assessment
на основании facts от коробки и решений людей. Хаб пассивно публикует
канонический status `waiting`, `blocked` или `unlocked`, а не управляет ПУ.
ПУ ждёт status и самостоятельно выполняет transfer только после `unlocked`.

## 2. Автоматический и exception paths

### 2.1. Автоматический qualification, ручной transfer

Если QG даёт полный PASS либо действующая policy признаёт findings допустимым
риском, security qualification проходит без ручного действия:

```text
коробка выпускает result, Evidence и Act
→ хаб получает facts и применяет policy автоматически
→ хаб публикует QG status `unlocked`
→ ПУ уведомляет IT-лидера — владельца Project/Application — по email и в GUI
→ IT-лидер вручную выбирает допустимый маршрут и запускает transfer
→ ПУ повторно читает status хаба и начинает transfer только при `unlocked`
→ хаб получает transfer event для связанной истории
```

Автоматическое решение всегда должно содержать применённую версию policy,
основания и ссылки на Evidence/Act. Оно не скрывает Low/Medium findings и не
выдаёт отсутствующий/ошибочный execution result за PASS.

V1 должен поддерживать policy criteria по scanner, finding kind, severity и
count. До калибровки profiles на реальных прогонах default preset консервативен:

```text
confirmed secret or malware → blocked
new Critical or High        → blocked
Low or Medium               → visible, non-blocking by default
```

Не вводить один выдуманный числовой лимит на все scanners. Числовые budgets
добавляются в scanner-specific policy presets после evidence-based calibration;
позже Admin Sec может выбирать предсозданные policies и настраивать разрешённые
параметры.

V1 поставляет три предсозданные versioned policies:

```text
Regular
  → базовая release policy

Strict
  → security/regulatory policy с усиленными правилами

Hotfix
  → policy для Hotfix; не слабее Regular, но работает с Hotfix scanner profile
```

В V1 policy меняются только поставляемыми presets. Отдельный Admin Sec policy
editor появится позже и потребует audit trail, versioning и явных прав доступа.

## 2.2. QG status delivery

Хаб хранит канонический QG status конкретного candidate. В первом рабочем
контуре ПУ получает его запросом и ждёт изменения:

```text
waiting
  → blocked
  → unlocked
```

ПУ не хранит второе независимое QG-решение и не считает QG сам. Каждый ответ
хаба привязан к exact candidate и версии его QG status, чтобы ПУ не открыл
transfer по устаревшему ответу.

Архитектура V1 должна быть готова к notification path: позднее хаб публикует
event/SSE/webhook при изменении status, ПУ немедленно перечитывает канонический
status запросом. Event ускоряет реакцию, но не становится источником правды:
потерянное или повторённое сообщение не меняет итоговую корректность.

### 2.3. Ручной transfer и immutable evidence snapshot

`unlocked` не переносит release автоматически. Он открывает IT-лидеру — владельцу
Project/Application — возможность вручную выбрать допустимый маршрут и запустить
transfer в ПУ. ПУ отправляет это уведомление по email и в GUI. Для Flexible
Release уведомление также получает инициатор exception request.

Перед началом ручного transfer ПУ заново читает канонический status хаба. Если
он `unlocked`, ПУ фиксирует в Release Package immutable evidence snapshot:

```text
candidate identity
QG status and its version at transfer start
policy version
Act reference
resolutions references
flexible_override_obtained, if applicable
```

После начала transfer этот пакет не переписывается поздними scans, resolutions
или status changes. Новое исправление, новый прогон или устранение причины для
override создают новый ReleaseCandidate и отдельный qualification/evidence scope.
Они не коллидируют со старым Flexible package и не меняют его historical facts.

### 2.4. Flexible Release / override

Если кандидат имеет QG blockers, а бизнес выбирает Flexible Release:

```text
Flexible Release + QG blockers
→ override request in коробка
→ Admin Sec review in коробка
→ approve or reject decision
→ коробка выпускает Exception Act
→ решение + Exception Act передаются в хаб и ПУ
→ хаб пересчитывает QG status
→ ПУ уведомляет IT-лидера и инициатора request
→ они вручную запускают transfer только после `unlocked`
```

Underlying scanner/DAST FAIL, blockers и исходные Evidence остаются в истории.
Override — документированное исключение, а не переписывание результата.

## 3. Топология хабов

Один хаб разворачивается на один кластер. Количество хабов в цепочке равно
количеству кластеров, где есть qualification zones:

```text
один cluster: ЗР + ЗТ + ЗПЭ
→ один хаб

cluster A: ЗР
cluster B: ЗТ + ЗПЭ
→ два хаба
```

ЗПЭ никогда не получает собственный хаб. ЗПЭ работает в кластере ЗТ и не
исполняет qualification scans: после transfer туда идёт deployment уже
собранного и квалифицированного пакета.

## 4. Qualification spaces в одном хабе

Хаб не смешивает полученные security/qualification facts ЗР и ЗТ даже если они
работают в одном кластере. Для каждого проекта в каждой qualification zone
создаётся отдельный контекст:

```text
ZR Project Space
  → собственные scans, coverage, findings, decisions, QG policy and clearance

ZT Project Space
  → новый project/repository context
  → собственные scans, coverage, findings, decisions, QG policy and clearance
  → первый qualifying запуск всегда FULL
```

Transfer из ЗР в ЗТ не создаёт автоматической связи со старым проектом. Он
создаёт новый самостоятельный ЗТ project/application/repository context.
Qualification status, coverage, baseline, approvals, clearance и history не
переносятся как живое состояние нового ЗТ проекта.

При этом сам immutable release package навсегда сохраняет transfer Evidence
исходной зоны:

```text
Act reference
approved resolutions references
QG status snapshot at transfer start
flexible_override_obtained, if applicable
```

Это provenance пакета, а не переносимый baseline или clearance. ЗТ не может
зачесть эти факты вместо собственного FULL qualification и собственной QG policy.

Оператор в одном хабе видит переключатель:

```text
[ЗР] [ЗТ] [ЗР + ЗТ]
```

`ЗР + ЗТ` — агрегированный read-only обзор transfer packages и их deployment
status. Это не третий project space, не склейка projects/findings/QG и не режим,
в котором facts одной зоны могут влиять на QG другой зоны.

При двух кластерах вместе с release package передаются только нужные для transfer
метаданные. Второй хаб создаёт независимый ЗТ Project Space. Default transport
для PrettyK и ПУ строится отдельно; для Cosmoport 2 поддерживается bridge к
внешнему СОД. Его подробный API пока `UNKNOWN`: он не должен быть замаскирован
под готовый прямой межкластерный API.

## 5. ЗР → ЗТ

ЗР и ЗТ могут быть в одном или разных кластерах. Независимо от топологии:

```text
qualified release package in ЗР
→ ПУ выполняет transfer
→ в ЗТ появляется новый project/repository context
→ code и разрешённая часть настроек воссоздаются по transfer package
→ package сохраняет immutable Evidence о Flexible override, если он был в ЗР
→ первая qualification в ЗТ начинается с FULL coverage
→ QG policy ЗТ применяется независимо от ЗР
```

Репозиторий в ЗТ новый. Его lifecycle и RBAC могут отличаться от ЗР. Если ЗР и
ЗТ находятся в одном кластере, хаб хранит изолированные Project Spaces. Если
кластеры разные, выбранный transport передаёт release package и нужную мету; хаб
ЗТ не обязан иметь runtime-доступ к хабу ЗР. В Cosmoport 2 legacy СОД доступен
только как bridge adapter.
иметь runtime-доступ к хабу ЗР.

## 6. ЗТ → ЗПЭ

ЗПЭ не создаёт новую repository identity, новый хаб, новую сборку или новый
scan lifecycle:

```text
ПУ переносит готовый release package из ЗТ
→ воссоздаёт package/artifact/build records из transfer evidence
→ использует repository из ЗТ
→ использует уже выполненную в ЗТ сборку и immutable artifact digest
→ делает единственный шаг ЗПЭ: deployment
→ successful deployment
→ ПУ публикует status «В эксплуатации» во всех zone contexts
```

ПУ не перестраивает артефакт и не запускает новое QG/DAST в ЗПЭ. Если deployment
неуспешен, статус «В эксплуатации» не публикуется. ПУ сохраняет честный
deployment result и повторяет deployment тем же transfer package, repository и
immutable artifact digest. ПУ повторяет deployment, поскольку релиз уже прошёл
полный qualification lifecycle в ЗТ.

Legacy ЗТ→ЗПЭ формировал новый архив и воссоздавал/обновлял target metadata
через GitLab reception pipelines. Это исследованный historical path, не
требование V1: ПУ 2 обязан определить отдельный transport/package-manifest
contract и явный deployment result, прежде чем реализовывать межзонный transfer.

Технический успех внешнего delivery provider не равен deployment success:

```text
transport delivered
→ target package verified
→ target context/bootstrap completed
→ deployment completed
→ «В эксплуатации»
```

Каждая ступень имеет отдельный durable audit/state event. Например, legacy СОД
наблюдаемо проходит `PREPARED → SENT → RECEIVED → DELIVERED` между client и
acceptor; `DELIVERED` не даёт ПУ права публиковать «В эксплуатации».

## 7. Границы ответственности

```text
ПУ
  → Project/Application/Repository/Build/Release/Package/Transfer/Deployment

коробка
  → DAST execution, raw result, Evidence, execution PASS/FAIL, Act

хаб
  → Finding/Occurrence/triage/baseline, deterministic QG assessment and
    canonical candidate status; storage and operator presentation of
    Act/transfer history
```

Хаб не переписывает DAST result или Exception Act коробки, но применяет QG
policy к принятым facts и human decisions. ПУ не пересчитывает QG и не создаёт
findings как источник истины. `blocked` или `unlocked` — вычисленный status,
который ПУ наблюдает перед ручным transfer.

## 8. Resolutions и approvals

Разработчик может предложить `suppress`, `wont_fix` или другой разрешённый
resolution только с причиной и достаточным контекстом. Хаб сохраняет решение,
его автора, policy/version и применимость для последующих релевантных прогонов.

```text
High/Critical resolution
→ Admin Sec открывает submitted list
→ подтверждает или отклоняет каждый finding
→ только подтверждённые findings учитываются как approved resolution
→ rejected items остаются причиной `blocked` и возвращаются на доработку/re-run

Medium/Low resolution
→ допустим без Admin Sec, если это разрешает действующая policy
→ разработчик обязан указать причину
→ count/severity thresholds могут поднять требование approval

Strict policy
→ Admin Sec approval required for every applicable resolution,
  including Medium/Low
```

Approved list не удаляет исходные findings. Он сохраняется, виден в Evidence и
учитывается при последующих релевантных перепрогонах, пока его применимость
действительна по policy. Изменённый finding, иной candidate или новая policy не
могут молча использовать старое approval.

## 9. Открытые решения перед implementation

1. После каких evidence-based calibration runs вводить первые числовые budgets
   по каждому scanner preset, не смешивая их с глобальным лимитом на все tools?
2. Как именно СОД доставляет release package и его метаданные между кластерами?
   До подтверждения этот транспорт остаётся `UNKNOWN`.
3. Какие сроки действия и правила renewal нужны для approved resolutions в
   каждом preset policy?
4. Какой API/contract СОД обеспечивает межкластерную доставку, идемпотентность,
   integrity verification и recovery после partial delivery?