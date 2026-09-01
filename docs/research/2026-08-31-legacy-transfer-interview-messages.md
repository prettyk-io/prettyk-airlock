# Legacy Cosmoport: copy-paste сообщения для интервью

> Цель интервью: выделить подтверждённые внешние ограничения для ПУ 2, а не
> переносить Rails/GitLab/Sidekiq реализацию legacy. Просим отвечать фактами и
> прикладывать source: API/schema/test/log/document/production incident.

## 1. Главный разработчик transfer / СОД

```text
Мы проектируем новый ПУ и хотим сохранить реальные обязательные ограничения
transfer, не копируя legacy-реализацию. По source уже видно: ReleaseRoute
использовал либо СОД, либо МЗП; СОД возвращал external package id и status;
в ЗПЭ был отдельный GitLab reception flow metadata/artifacts. МЗП исключён из
целевой архитектуры: его больше не рассматриваем как новый transport или fallback.

Нужны точные ответы и, по возможности, ссылка на API/schema/log/example:

1. Какой фактически используемый сейчас contract СОД: endpoint/version, auth,
   maximum package size, allowed checksum/signature, idempotency key,
   upload/receive/status operations?
2. Какие статусы СОД terminal, какие retryable, что означает partial delivery,
   и когда повторная отправка запрещена или создаёт дубль?
3. Как target доказывает, что получил именно полный и неизменный package:
   manifest, SHA-256/подпись, object list, artifact digests? Что сверяется?
4. Что случается при timeout после upload, когда source не знает, принял ли
   СОД пакет? Какой recovery выполняет оператор без повторного side effect?
5. Для чего legacy разрешал выбрать несколько маршрутов одному release:
   реальный fan-out, резервный маршрут или исторический UI? Какие сочетания
   разрешены сейчас?
6. Подтверждает ли `DELIVERED` только доставку client → acceptor или также
   успешный target bootstrap? Как target возвращает независимое business-success
   подтверждение source ПУ?
7. Какая реальная последовательность ЗР→ЗТ и ЗТ→ЗПЭ после package receipt:
   кто создаёт target repository/context, кто переносит artifact, кто вызывает
   deployment, какой факт означает «в эксплуатации»?
8. Какие самые дорогие production incidents/recovery cases были у transfer?
   Что в legacy вы бы точно не стали повторять?

Важно: legacy МЗП не рассматриваем. Новый default transport проектируется нами;
СОД нужен ПУ 2 как отдельный external bridge. Внутреннюю Kafka-механику СОД в
stack ПУ не переносим.

Для каждого пункта важны: current behaviour, источник доказательства, причина
ограничения, последствия нарушения и оценка «обязателен для нового ПУ /
legacy-only».
```

## 2. Backend lifecycle / release

```text
Нужны факты о lifecycle релиза старого ПУ, чтобы корректно определить contract
нового ПУ. Не просим воспроизводить модели Rails.

1. Какие identity неизменны и связывают source, build, artifact и target:
   project/release/build/repository/commit/tag/package/route?
2. Какие preconditions действительно запрещали transfer, кроме UI?
3. Что происходило с зависимыми releases уровня 0/1 и почему?
4. Что является source of truth статуса после target reception/deployment?
5. Какие payload fields должны попасть в package manifest для точного recovery?
6. Какие settings, env, resource and RBAC data переносимы, пересоздаются в
   target, либо никогда не должны покидать source zone?
```

## 3. Frontend

```text
Нужны operator-critical требования legacy transfer UI, а не реализация.

1. Какие действия выполнял IT-лидер и какие роли могли выбирать/запускать route?
2. Какие disabled states, confirmations и warnings были нужны для безопасного
   ручного transfer?
3. Какие progress/status/error details позволяли оператору отличить pending,
   processing, partial receipt, recoverable failure и terminal failure?
4. Какие notifications и history/audit views реально использовались?
5. Какие самые частые UX-ошибки делали пользователи и как интерфейс их снижал?
```

## 4. QA

```text
Нужны реальные test/recovery cases transfer subsystem.

1. Какие сценарии были покрыты тестами, а какие выполнялись только вручную?
2. Есть ли fixtures/logs для timeout after upload, duplicate delivery, corrupted
   package, partial metadata/artifact receipt, target already exists и retry?
3. Какие production regressions повторялись?
4. Какие assertions обязательны для нового ПУ: idempotency, digest integrity,
   auditability, retry safety, no unintended deployment?
5. Какими были acceptance criteria для «пакет доставлен» и «в эксплуатации»?
```

## 5. Аналитик / владелец требований

```text
Нужно отделить действующие обязательные требования от исторического поведения
legacy ПУ.

1. Какие определения зон, маршрута, package и поставки нормативно обязательны?
2. Какие обязательные требования СОД сохраняются для внешнего bridge, а какие
   относятся только к legacy-реализации?
3. Какие данные запрещено переносить между зонами: credentials, RBAC, configs,
   findings/evidence, персональные данные?
4. Кто имеет право инициировать, подтверждать, повторять и отменять transfer?
5. Что юридически/операционно является доказательством готовности к production?
6. Какие requirements изменились или устарели после LCZD/BEMR?
```