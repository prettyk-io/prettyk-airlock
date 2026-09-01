# Notification service: source-inspection worksheet

> **Статус:** reference-only research. Не канон, не design, не решение включать
> Notification Service в Cosmoport 2 и не предложение копировать его архитектуру.
>
> **Source tree:** `D:\cosmo\notification-service` (Maven multi-module Java 11 + Spring Boot 2.3.12)
> **Modules:** notify-app (Spring Boot backend), notify-db (Liquibase migrations), notify-gateway (React/TypeScript Single-SPA frontend)
> **Version:** 2.6.1
> **Product name:** dossier-notify / Пифагор.Менеджер уведомлений
> **Организация:** Банк России (CBR)

## 1. Executive answer

1. **Какую реальную проблему решает сервис:** Это notification hub для экосистемы ППОД. Принимает события через Kafka от приложений, рассылает уведомления пользователям через два канала: in-app/GUI (bell/колокольчик) и email (через PIS relay). Управляет подписками, хранит историю уведомлений, предоставляет UI для чтения/фильтрации/экспорта.

2. **Роли сервиса:** Notification hub + delivery worker + preference store + event bus adapter. **НЕ** template service (templates жёстко заданы), **НЕ** webhook dispatcher.

3. **Каналы, которые реально работают:**
   - ✅ In-app/GUI (bell/колокольчик) — BELL delivery, статусы NEW→DELIVERED→READ
   - ✅ Email — через PIS relay (POST ZIP с metadata → accept callback)
   - ❌ Webhook — найден только в упоминании `PpodOrderCallbackRestTemplate`, не в notification delivery
   - ❌ SMS, messenger, push — не найдены

4. **Минимальный factual contract:** Kafka message (`NotificationDto` с title, message, link, priority, app code, recipients, recipientRoles, deliveryType, objects, metaInfList, ignoreSubscription) → сервис сохраняет, разрешает получателей через LDAP+подписки, рассылает BELL+EMAIL, предоставляет REST API для чтения/статуса.

5. **Что в нём legacy-specific:** Привязка к Spring Cloud Stream Kafka (специфический биндинг), PIS как email relay (специфичный для ЦБ), Blitz SSO opaque token introspect, PPOD order lifecycle, Consul service discovery. Все — инфраструктурные coupling, не бизнес-логика.

6. **Какие факты никак не подтверждены исходниками:**
   - Реальный volume уведомлений (неизвестно)
   - Горизонтальное масштабирование (single instance в deployment, 1 replica)
   - SMS/webhook/push delivery (не реализованы)
   - Multi-tenant/domain изоляция (нет в коде)
   - Production runbooks и incident response

## 2. Source map и deployment

**Source map:**
- `notify-app/src/main/java/cbr/` — ~80 Java source files: domain entities (Notification, BellData, EmailData, Subscription, App, MetaInf), repositories (JPA + views), services (NotificationService, EmailService, DBCreateService, NotificationTypeService, SubscriptionService), REST controllers (NotifyController, SubscriptionController, UiSettingsController, NotifySepController, ServiceOrderController), Kafka consumer (NotifyBusReceiver), request processing pipeline (RequestProcessingService, NotificationRequestScheduler, RequestHandlingQueueService), security (OAuth2 SSO, token permit aspect), schedulers (delete old notifications, email resend)
- `notify-db/` — Liquibase changelogs + SQL (16 таблиц + 2 DB views)
- `notify-gateway/front/` — React 16 + TypeScript + Single-SPA (~70 TSX/TS components)
- `deckhouse/` — Helm chart v2.6.1 (Deployment, Ingress-nginx, Service)
- `docs/` — Swagger в формате Adoc, документация API, скрипты тестовых данных

**Entrypoints:** Spring Boot main `NotifyApplication.java`. REST controllers (см. раздел 3). `NotifyBusReceiver` — @StreamListener на канал `notification-service-in-0`.

**Workers/background:**
- `NotificationRequestScheduler` — каждые 10с: обработка NEW запросов → PENDING → handler
- `NotificationRequestScheduler` — каждый день 3 AM: удаление старых запросов (>1 мес)
- `DeleteOldNotificationsScheduler` — каждый день 4 AM: удаление уведомлений старше retention (default 6 мес)
- `EmailResendScheduler` — cron (default "1 1 * * * *"): повторная отправка ERROR email

**Language/framework:** Java 11 (AxiomJDK 11), Spring Boot 2.3.12, Spring Cloud Hoxton.SR12, Spring Cloud Stream Kafka 3.0.7, Hibernate/JPA, Lombok, HikariCP, Racecar (Kafka consumer).

**Deployment:** Deckhouse (Helm chart, Ingress-nginx, TLS, port 3020). Также OpenShift (openshift.yml). Health: `:22222/monitoring/health`. Single instance (1 replica).

**Database:** PostgreSQL (PostgreSQLDialect), HikariCP (max 100, min 30), schema `public`. 16 таблиц + 2 DB views.

**Kafka:** Spring Cloud Stream Kafka binder, SASL_SSL/SCRAM-SHA-256. Topic: `KBROKER_TOPICNAME`, consumer group: `KBROKER_GROUPNAME_TOPICNAME`. Чтение только inbound (`@Input` channel, нет outbound producer в коде сервиса).

**External providers:** Blitz SSO (opaque token introspection), PIS (email relay), Consul (service discovery), Splunk (security event logging), LDAP (employee directory lookup).

**Evidence:**

| Область | Факт | Источник | Уверенность | Unknown/gap |
|---|---|---|---|---|
| Runtime | Java 11, Spring Boot 2.3.12, AxiomJDK 11 | pom.xml, BuildInfo.yaml | HIGH | — |
| Deployment | Deckhouse (Helm v2.6.1), 1 replica, port 3020, Ingress-nginx, health :22222 | deckhouse/templates/, openshift.yml | HIGH | Масштабируется ли горизонтально |
| Persistence | PostgreSQL, HikariCP (max 100, min 30), Liquibase, 16 tables + 2 views | application.yml, notify-db/ | HIGH | — |
| Queue/broker | Kafka (SASL_SSL/SCRAM-SHA-256), Spring Cloud Stream, inbound only | application.yml, NotifyBusReceiver.java, Kafka binder config | HIGH | Топик и группа из env, не известны names |
| External channels | PIS (email relay, HTTPS POST ZIP), Blitz SSO (OAuth2 opaque token), LDAP (employee lookup), Consul (service registry) | EmailServiceImpl.java, SecurityConfig, LdapServiceImpl.java, @EnablePpodConsulDiscovery | HIGH | PIS API contract не полностью раскрыт |

## 3. Event и API contract

### Кто публикует notification event

Неизвестно кто именно (внешние приложения). Известен протокол: Kafka message на топик `KBROKER_TOPICNAME` с заголовками:
- `objectType` = `NotificationDto` или `NotificationTypesAppDto`
- `uuid` = уникальный ID сообщения
- `senderName`, `senderVersion`, `senderDomainUrl` = метаданные отправителя
- `senderCodeAndSecret` = `appCode=secret` (проверяется `NotificationRequestPermitService`)

### Event schema (NotificationDto)

```json
{
  "appCode": "string",
  "notifications": [{
    "title": "string (max 500?)",
    "message": "string (max 4000?)",
    "link": "string (URL, max 2000?)",
    "type": "string (notification type code)",
    "priority": "HIGHEST|HIGH|MEDIUM|LOW|LOWEST",
    "recipients": ["login1", "login2"],
    "recipientRoles": ["role1"],
    "deliveryType": "BELL|EMAIL|BELL_EMAIL",
    "metaInfList": [{"metaName": "string", "metaValue": "string"}],
    "objects": [{"objectType": "CREDIT_ORGANIZATION|TASK_TYPE|...", "objectId": "string", "objectName": "string"}]
  }],
  "ignoreSubscription": false
}
```

**Поля обязательны:** `title`, `message`, `type`, `priority`, `appCode`. `recipients` нужен хотя бы один — иначе уведомление сохраняется но никому не доставляется. `deliveryType` — если не указан, default BELL.

**Валидация:** LDAP-валидация получателей (inactive/несуществующие пользователи skip с warning). `appCode` проверяется через `NotificationRequestPermitService` (secret key). Никакой валидации размера полей в коде не найдено (ограничения на уровне DB: title/message/text — varchar/text без explicit limit).

### API endpoints

**NotifyController (`/api/notifications`):**

| Method | Path | Auth | Purpose |
|---|---|---|---|
| GET | `/getPopupNotifications` | SSO | Unread popup notifications for current user |
| GET | `/getMetaInf` | SSO | Metadata definitions for notification type |
| POST | `/getFilteredNotifications` | SSO | Filtered/paginated notification list |
| PUT | `/changeNotificationStatus` | SSO | Toggle single notification READ↔DELIVERED |
| PUT | `/changeAllNotificationStatuses` | SSO | Bulk status change by filter |
| GET | `/getMetaInfSelect` | SSO | Get SELECT metadata values |
| POST | `/getExcelByIDs` | SSO | Export to Excel by IDs |
| POST | `/getExcelByFilter` | SSO | Export filtered to Excel |
| GET | `/getNotificationTypes` | SSO | Get types by app code |
| GET | `/getKzNames` | SSO | Get app list for user |

**NotificationSubscriptionController (`/api/notifications/subscriptions`):** GET apps, GET user subscriptions, PATCH subscription settings.

**NotifySepController (`/api/integration/pis/sep`):** POST — receive PIS email delivery ACK (`srcMsgId`, `resultCode`, `description`). **No auth** (public endpoint).

**ServiceOrderController (`/api/orders`):** POST create order, DELETE order. Auth: `X-Portal-Token`.

**Versioning:** Нет API versioning. No content negotiation. No schema evolution strategy.

**Link safety:** `link` поле передаётся как есть. Нет валидации URL, SSRF защиты, проверки домена.

## 4. Recipient, preference и policy semantics

### Как определяется recipient

Три механизма (в порядке приоритета):
1. **Explicit recipients:** `notificationDto.notifications[].recipients` — список login'ов
2. **Role-based recipients:** `notificationDto.notifications[].recipientRoles` — роли (сохраняются в `NOTIFICATION_RECIPIENT_ROLE`, но resolution logic не найдена — видимо используется external system, не сам сервис)
3. **Subscription-based:** Получатели фильтруются через `NOTIFICATION_SUBSCRIPTION` (BELL delivery type). Если у пользователя нет подписки на этот notification type — auto-create default subscription (BELL only, ALL objects, enabled).

**LDAP проверка:** `CachedLdapService` (Guava cache) валидирует, что получатель существует и активен. Неактивные/удалённые пользователи пропускаются с warning.

### Preferences/policy

| Механизм | Реализация | Evidence |
|---|---|---|
| **Mute** | Нет прямого mute. `isEnabled=false` на подписке — эквивалент. | NOTIFICATION_SUBSCRIPTION.is_enabled |
| **Digest** | НЕТ | — |
| **Throttle** | НЕТ (отдельные сообщения, без batching) | — |
| **Quiet hours** | НЕТ | — |
| **Locale/timezone** | НЕТ (только русский) | — |
| **Тип подписки** | `ALL` (все уведомления этого типа) / `SELECTED` (только с определёнными object'ами) | NOTIFICATION_SUBSCRIPTION.subscription_type |
| **Exclusion** | `isExcluded=false` → allowlist (видит только выбранные object'ы); `isExcluded=true` → blocklist (видит всё кроме выбранных) | NOTIFICATION_SUBSCRIPTION.is_excluded |
| **Delivery type** | BELL, EMAIL, BELL_EMAIL (per subscription) | NOTIFICATION_SUBSCRIPTION_DELIVERY_TYPE |

**Mandatory vs best-effort vs audit-only:** НЕТ такой классификации. Все уведомления обрабатываются одинаково. `ignoreSubscription=true` позволяет bypass подписок.

**Tenant/domain/zone isolation:** НЕТ. Нет multi-tenancy. Сервис один на все зоны/приложения. Отправитель идентифицируется по `appCode`, но изоляции между приложениями нет (нет проверки «пользователь X имеет доступ к уведомлениям приложения Y»).

**Данные, запрещённые в notification payload:** НЕТ политики. Нет redaction, нет PII scanning.

## 5. Channels и delivery

| Channel | Provider | Input | Auth | Retry | Status | Idempotency | Evidence |
|---|---|---|---|---|---|---|---|
| In-app/GUI (BELL) | Internal (DB) | Kafka → NotificationBellData | SSO (OAuth2) | — | NEW→DELIVERED→READ (toggle) | notificationId + recipientLogin unique | NotificationBellData.java, NotificationBellDataRepository.java, DB schema |
| Email | PIS relay | Kafka → EmailServiceImpl → PIS POST ZIP → callback | X-Pis-Auth-Token | Resend scheduler (cron) | NEW→SENT→DELIVERED/ERROR | pisMessageId (UUID) generated per send | EmailServiceImpl.java, NotifySepController.java, EmailResendScheduler.java |
| Webhook | НЕТ | — | — | — | — | — | — |

### Channel-specific details:

**BELL:**
- `NotificationBellData` record: recipientLogin, status (NEW/DELIVERED/READ), readDttm, deliveredDttm
- `NotificationUnreadCounter` — per-user counter (login PK, count)
- При чтении: toggle статус (READ→DELIVERED→READ), counter ±1
- Security event: `SendNotificationEvent` logged to Splunk

**Email:**
- Генерирует ZIP: `y.meta.json` с PisMetaDTO (baseSystemId, routeInstanceId, srcMsgId, extra attributes)
- POST на PIS endpoint с `X-Pis-Auth-Token` header
- PIS callback: `POST /api/integration/pis/sep` с `srcMsgId`, `resultCode` (0=success), `description`
- Resend: EmailResendScheduler забирает ERROR записи батчами по 100, повторяет отправку
- Status flow: NEW → SENT (PIS accept) → DELIVERED (PIS callback resultCode=0) / ERROR (resultCode≠0 или ошибка HTTP)

### Что считается успехом:

**BELL:** Запись в БД (NotificationBellData создана). **Enqueue в БД = success.** Не гарантирует, что пользователь увидит.

**Email:** PIS callback с `resultCode=0` → DELIVERED. **Provider acceptance = success.** Не гарантирует конечную доставку в inbox пользователя.

### Outbox/transaction boundary:

НЕТ outbox pattern. Kafka сообщение сохраняется в `NOTIFICATION_REQUEST_INFO` (inbound journal), затем обрабатывается асинхронно. При падении между записью в БД и отправкой:
- Белл: данные в БД, counter обновлён — inconsistency невозможна (single transaction)
- Email: PIS вызов идёт после сохранения NotificationEmailData в БД. Если сервис упадёт между ними — запись останется в статусе NEW (не SENT). EmailResendScheduler обрабатывает только ERROR, не NEW.

### Retry/dead-letter:

| Уровень | Механизм | Параметры |
|---|---|---|
| Kafka → сервис | Spring Cloud Stream default retry | Неизвестно (нет explicit конфигурации) |
| Kafka → сервис (stuck) | NotificationRequestScheduler: PENDING > 1 час → обратно в NEW | 1 час |
| Email отправка | EmailResendScheduler (cron) | По cron, батчами 100, max 4 страницы |
| Email отправка | RetryableAction в EmailServiceImpl | max 5 попыток, 50ms интервал |
| Сервис рестарт | Запрошенные но не обработанные Kafka сообщения — UNKNOWN | Нет DLQ, нет replay mechanism |

## 6. Persistence и lifecycle

### Таблицы (16 + 2 views):

| Таблица | Назначение |
|---|---|
| `NOTIFICATION` | Основная таблица уведомлений: title, message, link, priority, app FK, type FK, created_dttm |
| `NOTIFICATION_TYPE` | Каталог типов уведомлений: code, title, icon_type, is_editable, is_deletable |
| `NOTIFICATION_TYPE_APP` | Many-to-many: типы к приложениям |
| `NOTIFICATION_APP` | Зарегистрированные приложения: code, short_name, full_name, order_id, secret_key |
| `META_INF` | Определения метаданных: meta_type, meta_name, meta_ui_name, filterable, sortable |
| `NOTIFICATION_META_INF` | Значения метаданных для конкретного уведомления |
| `NOTIFICATION_OBJECT` | Объекты привязанные к уведомлению: object_type, object_id, object_name |
| `NOTIFICATION_RECIPIENT_ROLE` | Роли получателей уведомления |
| `NOTIFICATION_BELL_DATA` | Данные bell-доставки: recipient_login, status (NEW/DELIVERED/READ), read_dttm, delivered_dttm |
| `NOTIFICATION_EMAIL_DATA` | Данные email-доставки: recipient_login, recipient_email, pis_message_id, status (NEW/SENT/DELIVERED/ERROR), sent_dttm, error_text |
| `NOTIFICATION_UNREAD_COUNTER` | Счётчик непрочитанных: login (PK), count |
| `NOTIFICATION_SUBSCRIPTION` | Подписки: recipient_login, notification_type, subscription_type, is_excluded, is_enabled |
| `NOTIFICATION_SUBSCRIPTION_DELIVERY_TYPE` | Типы доставки для подписки: BELL, EMAIL |
| `NOTIFICATION_SUBSCRIPTION_OBJECT` | Объекты для фильтрации подписки |
| `NOTIFICATION_REQUEST_INFO` | Журнал входящих Kafka сообщений: uuid, state (NEW/PENDING/SUCCESS/FAILURE), type, data (LOB), error |
| `NOTIFICATION_APP_ORDER` | Данные заказа приложения через PPOD |
| `V_BELL_NOTIFICATION` | DB view: уведомления с фильтрацией по подпискам |
| `V_NOTIFICATION_OBJECT_FOR_SUBSCRIPTION_SETTINGS` | DB view: объекты для настроек подписок |

### Retention:
- Уведомления: 6 месяцев (конфигурируемо `NOTIFICATION_RETENTION_MONTHS`). DeleteOldNotificationsScheduler удаляет старые записи из NOTIFICATION, NOTIFICATION_BELL_DATA, NOTIFICATION_EMAIL_DATA, NOTIFICATION_META_INF, NOTIFICATION_OBJECT, NOTIFICATION_RECIPIENT_ROLE
- Request journal: 1 месяц. NotificationRequestScheduler.deleteOldRequests
- НЕТ archival/backup механизма

### Source of truth:
- **Unread/read:** `NOTIFICATION_BELL_DATA.status` + `NOTIFICATION_UNREAD_COUNTER.count`
- **Delivery status (email):** `NOTIFICATION_EMAIL_DATA.status` (NEW→SENT→DELIVERED/ERROR)
- **Audit history:** Splunk security events (ViewNotificationEvent, SendNotificationEvent, etc.) — НЕ в БД
- **Transaction boundary:** Создание уведомления + всех связанных записей (BellData, EmailData, MetaInf, Objects, Roles) — в одной транзакции JPA. Counter update — в той же транзакции.

### Concurrency/ordering:
- `NotificationUnreadCounter` — update via JPA `@Modifying @Query` (UPDATE SET count = count + 1). Возможна потеря при concurrent updates (нет `SELECT FOR UPDATE`).
- Request queue: `RequestHandlingQueueServiceImpl` с `BlockingQueueMap` (ConcurrentHashMap of LinkedBlockingQueue). Per-uuid ключ — гарантирует последовательную обработку дубликатов одного сообщения.

## 7. Security и privacy

1. **Authn/authz:**
   - REST API: OAuth2 opaque token introspection через Blitz SSO. Endpoints `/api/notifications/**` требуют аутентификации.
   - `/api/integration/pis/**` — public (PIS callback)
   - `/api/orders/**` — custom token (`X-Portal-Token`)
   - Kafka messages: secret key валидация (`senderCodeAndSecret` header → `NotificationRequestPermitService`)
   - НЕТ авторизации на уровне уведомления: любой аутентифицированный пользователь видит все уведомления своего приложения (без scoping по ролям/доменам)

2. **Provider credentials:**
   - PIS token: `pis.token` в application.yml — **plaintext в конфигурации**
   - Kafka credentials: `spring.kafka.properties.sasl.jaas.config` — SASL/SCRAM, **credentials в application.yml**
   - Email credentials: через PIS (НЕ прямой SMTP), token в конфиге
   - Blitz SSO client secret: через стандартный Spring Security OAuth2 config

3. **SSRF/open redirect/template injection:**
   - `link` поле (URL в уведомлениях): **НЕТ валидации** — SSRF риск, open redirect
   - `HtmlUtils.decodeHtml()` используется для стриппинга HTML тегов из `message` при отображении — частичная защита от XSS, но не от template injection
   - Email: ZIP с `y.meta.json` — plain JSON, нет HTML-темплейтов. Риск injection низкий.

4. **Redaction в логах:** НЕТ явного redaction. Security events в Splunk логируют event type, но не само содержимое уведомлений.

5. **Link/attachment/recipient/bulk send ограничения:** НЕТ. Нет rate limiting, нет ограничений на количество получателей, нет валидации link URL.

6. **Audit events (Splunk):** ViewNotificationEvent, ViewNotificationListEvent, SendNotificationEvent, SendPisNotificationEvent, EditNotificationSubscriptionEvent, ExportNotificationListEvent. Сохраняются в Splunk, **НЕ в БД**. Нет tamper-evident audit trail в БД.

## 8. Cosmoport 1 factual usage

### Direct callers (из кода Cosmoport):

**Cosmoport → Notification Service:**
- `NotificationService::Produce` (`D:\cosmo\cosmoport\backend\app\services\notification_service\produce.rb`) — отправляет уведомления через Kafka (топик `notification-service_event`)
- `NotificationService::TypesProduce` — регистрирует типы уведомлений
- `SendNotificationJob` (Sidekiq worker) — async отправка: вызывает `Produce`, затем `UserMailer.send_email` для прямых email

**Cosmoport ← Notification Service:**
- НЕТ прямого вызова. Notification Service не вызывает Cosmoport API.

### Каталог событий (найдено в Cosmoport):

Из `common_notifications` + `SendNotificationJob` + документации NOT v2.2:

| Событие | Тип | Триггер |
|---|---|---|
| Сборка создана | Информационное: Сборки и развертывания | Build creation |
| Сборка успешна / ошибка | Информационное / Ошибка | Build status change |
| Деплой создан / завершён | Информационное: Сборки и развертывания | Deployment status change |
| Релиз перенесён | Информационное: Перенос данных | Release transfer |
| Релиз принят | Информационное: Перенос данных | Release reception |
| Ошибка переноса | Ошибка: Перенос данных | Transfer failure |
| Квота изменена | Информационное: Ресурсы | Quota change |
| Пароль изменён | Информационное: Доступ | Password change |
| Участник добавлен/удалён | Информационное: Доступ | Member change |
| Ошибка интеграции | Ошибка: Интеграции и инфраструктура | Integration failure |
| Предупреждение о профилях | Предупреждение: Рабочее пространство | Profile usage limit |
| Common notification (ручное) | Критическое / Информационное | Admin creates via UI |
| Security event | Ошибка: Безопасность | Security doc generation |
| Документация безопасности | Информационное: Безопасность | Security doc generation |

**22 конкретных события** задокументированы в спецификации NOT v2.2. В коде Cosmoport: `common_notifications` + `SendNotificationJob` реализуют subset из них.

### Критичные для оператора:
1. Ошибка сборки / деплоя
2. Ошибка переноса релиза между зонами
3. Критические оповещения (admin-created)
4. Предупреждения профилей (quota)
5. Ошибки интеграций

### Coupling к инфраструктуре Cosmoport 1:
- **Kafka (PUNS):** жёсткая зависимость — Spring Cloud Stream Kafka binder
- **Sidekiq (Cosmoport):** `SendNotificationJob` — Redis dependency
- **Racecar (Cosmoport):** Kafka consumer в Rails
- **PostgreSQL:** общая БД (отдельный инстанс, но та же технология)
- **Blitz SSO:** opaque token introspection
- **SMTP (Cosmoport):** `UserMailer` в Rails — прямой email, не через сервис уведомлений
- **React/Single-SPA:** фронтенд как микрофронтенд

## 9. Tests and operational evidence

**Test coverage (notify-app/src/test):** 15 test classes. Покрывают: Kafka message reception, notification creation/delivery, subscription management, email processing, retry mechanism, UI settings, PPOD order lifecycle.

**Не покрыто тестами:**
- Bulk notification status changes (changeAllNotificationStatuses)
- Excel export
- PIS email callback edge cases (retry exhaustion, network timeout)
- LDAP cache invalidation
- Concurrent counter updates (race condition)
- Service restart между Kafka consumption и DB write
- Email resend после длительного downtime

**Production evidence:** НЕТ runbooks, dashboards, incident reports в исходниках. Splunk security events — единственный audit trail. Prometheus метрики — через стандартный PPOD monitoring starter (health endpoint).

## 10. Final factual report

| Question | Answer | Evidence | Confidence | Impact if wrong |
|---|---|---|---|---|
| Actual service role | Notification hub: Kafka consumer + BELL/EMAIL delivery + GUI + subscription management | NotifyBusReceiver.java, DBCreateService.java, NotifyController.java, notify-gateway/front/ | HIGH | Строим не тот сервис |
| Event contract | Kafka message (NotificationDto): title, message, link, priority, recipients, deliveryType, objects, metaInf | NotifyBusReceiver.java, NotificationDto (domain) | HIGH | Event schema несовместим |
| Channels | BELL (DB, in-app) + EMAIL (PIS relay). NO webhook/SMS/push | NotificationBellData.java, EmailServiceImpl.java | HIGH | Пропускаем канал |
| Preferences/policy | Subscription (ALL/SELECTED, isExcluded, isEnabled). NO mute/digest/throttle/quiet hours | NOTIFICATION_SUBSCRIPTION table, DBCreateService.java | HIGH | Нет нужных policy |
| Delivery guarantees | BELL: DB write = success. Email: PIS accept = success. NO outbox. NO dead-letter. | DBCreateService.java, EmailResendScheduler.java, NotificationRequestInfo state machine | HIGH | Гарантии слабее, чем нужно |
| Persistence/outbox | NOTIFICATION_REQUEST_INFO — inbound journal. NO outbox pattern. 6-month retention. | NOTIFICATION_REQUEST_INFO table, DeleteOldNotificationsScheduler | HIGH | Данные могут быть потеряны при падении |
| Security/privacy | OAuth2 SSO, app secret key validation. NO link validation (SSRF), NO PII redaction, NO per-notification authz. | SecurityConfig, NotificationRequestPermitService, link field без валидации | HIGH | Уязвимости переносятся |
| Cosmoport callers | `NotificationService::Produce` (Rails, Kafka), `SendNotificationJob` (Sidekiq), manual via `common_notifications` UI | produce.rb, send_notification_job.rb, common_notifications_controller.rb | MEDIUM | Пропущен caller |

### Contradictions and competing evidence

1. **Cosmoport email дублирование:** `SendNotificationJob` отправляет email ЧЕРЕЗ СЕРВИС уведомлений (Kafka → notification service → PIS) И напрямую через `UserMailer.send_email` (SMTP). ДВА независимых канала email — вероятно, разные use cases (автоматические vs ручные уведомления). Evidence: `send_notification_job.rb` вызывает оба.

2. **Notification types: register vs send:** `NotificationService::TypesProduce` регистрирует типы через отдельный Kafka message (NotificationTypesAppDto). Это startup-операция (делается один раз при деплое приложения), не per-event.

3. **Rails UserMailer vs notification service email:** В Cosmoport есть `app/mailers/user_mailer.rb` который отправляет прямые email через SMTP (ActionMailer). Это отдельный канал от notification service. Используется для критических уведомлений администраторам.

### Legacy-only behaviour

1. Spring Cloud Stream Kafka binder (специфический протокол)
2. PIS как email relay (банковский специфичный сервис)
3. Blitz SSO opaque token introspection
4. Consul service discovery
5. PPOD order lifecycle (заказ/удаление сервиса через портал)
6. Single-SPA микрофронтенд (React 16)
7. Splunk security events (специфический SIEM)
8. Racecar/Sidekiq в Rails для Kafka produce
9. `ignoreSubscription` bypass (для административных уведомлений)
10. 6-месячный retention без архивной политики

### Not enough evidence for a Cosmoport 2 decision

1. **Нужен ли отдельный notification service:** Сервис решает реальную проблему (push + email уведомления с подписками), но весь delivery pipeline (Kafka, PIS, Blitz, Consul, Single-SPA) — legacy coupling. Decision: функциональность нужна, но standalone Java-сервис не обязателен.

2. **Нужен ли email:** Email используется (релизы, ошибки, критические оповещения). Но legacy реализация через PIS relay специфична для ЦБ. Decision: email нужен, но провайдер — replaceable.

3. **Нужен ли Kafka как транспорт:** Используется для inbound (приём событий). Но в Cosmoport 2 события могут идти через Run Control Plane events → notification service напрямую. Decision: Kafka не обязателен.

4. **Нужна ли subscription/policy система:** Реализована (ALL/SELECTED, isExcluded, delivery type). Это полезный business feature для пользователей. Decision: нужно, но дизайн упростить.

5. **Нужен ли GUI (Single-SPA микрофронтенд):** Реализован на React 16 + TypeScript. UI-компоненты (popup, список уведомлений, настройки подписок) — reusable pattern. Decision: UI нужен, но стек — Cosmo 2.0 native (MUI X, Zustand).

6. **Нужен ли inbound journal (NOTIFICATION_REQUEST_INFO):** Полезный pattern для reliability (dedup, replay, state tracking). Decision: да, но как часть Event Outbox в Cosmo 2.0.

7. **Какая event taxonomy:** 22+ событий задокументированы в NOT v2.2. Decision: taxonomy нужна, но пересмотреть categories и обязательность.

8. **Какая delivery semantics:** BELL (best-effort, DB write = success) + EMAIL (PIS accept = success). Нет гарантий конечной доставки. Decision: нужны более строгие гарантии (outbox + retry + dead-letter).