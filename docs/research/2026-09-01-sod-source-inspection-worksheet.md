# СОД: source-inspection worksheet

> **Статус:** reference-only research. Не канон, не design, не implementation
> approach и не решение включать СОД в Cosmoport 2.
>
> **Source tree:** `D:\cosmo\sod` (Maven multi-module Java 17 + Spring Boot 2.5.7)
> **Modules:** sod-core (domain/services/processors), sod-service (Spring Boot app + React UI), sod-db (PostgreSQL DDL)
> **Version:** 1.8.1
> **Организация:** Банк России, Томск, ППОД

## 1. Executive answer

1. **Что такое СОД фактически:** Gateway-сервис однонаправленной передачи файлов между зонами безопасности (ЗР, ЗТ, ЗПЭ) через InfoDiode поверх **FTP** каналов. Transport service + package registry. НЕ orchestration, НЕ payload inspector.

2. **Какие части flow реально реализованы:**
   - ✅ Multipart file upload (`POST /out/{domain}`) с X-SYSTEM-TOKEN auth
   - ✅ ZIP-упаковка: payload + metadata.json
   - ✅ FTP outbound→InfoDiode IN stream (Spring Integration)
   - ✅ FTP inbound poll (InfoDiode OUT stream) → распаковка, валидация MD5
   - ✅ Meta-packet-уведомления обратно через InfoDiode (state sync)
   - ✅ Kafka-нотификации (опционально, профиль `KafkaNotifications`)
   - ✅ REST API для получателя: `GET /in/{domain}/received`, `GET /in/{packetId}`, `PUT delivered/broken`
   - ✅ Admin-UI (React/Redux), админ-поиск, управление системами, повторная отправка
   - ❌ Только упомянуто, не реализовано: Kafka как data transport (only notifications), контрольные каналы помимо InfoDiode

3. **Граница между СОД и Cosmoport 1:** Cosmoport = caller (POST /out/{domain}), СОД = transport. Стык через `X-SYSTEM-TOKEN`. Нет integration на уровне БД или message broker. Cosmoport поллил `/in/{domain}/received` или ждал Kafka-нотификацию.

4. **Минимальный factual contract:** `POST /out/{domain}` (multipart: domain, subject, bytes, hex/MD5, file, timeout, additional), → `GET /in/{domain}/received` (RECEIVED packets) → `GET /in/{packetId}` (download) → `PUT /in/{packetId}/delivered` (confirm). State machine: PREPARED → SENT → RECEIVED → DELIVERED. Idempotency: packetId = client-generated UUID.

5. **Что остаётся неизвестным:**
   - Актуальная топология зон (ЗР/ЗТ/ЗПЭ) и количество инстансов СОД
   - Реальные размеры пакетов (size limits) и время прохождения InfoDiode
   - Кто именно в Cosmoport вызывает СОД (конкретные сервисы/контроллеры)
   - Production incidents, реальные потери пакетов, скорость InfoDiode
   - Есть ли альтернативные transport backends помимо FTP

## 2. Source map и запуск

**Source map:**
- `sod-core/` — 43 Java source files: domain entities (Packet, PayloadPacket, MetaPacket, System), DTOs, services, processors (FileOutboundProcessor, FileInboundProcessor), repositories, FTP/Kafka configs, trackers (expired packets, local dir cleanup)
- `sod-service/` — 27 Java source files + React frontend (9 JSX components): WebService (Spring Boot main), 4 controllers (Admin, Inbound, Outbound, Support), security (OAuth2 SSO + X-SYSTEM-TOKEN), Swagger
- `sod-db/` — 5 DDL tables + 5 evolution scripts

**Entrypoints:** Spring Boot main `WebService.java` (`@SpringBootApplication`, excludes Kafka auto-config). Controllers: `OutboundController` (POST /out/{domain}), `InboundController` (GET /in/{domain}/received, GET /in/{packetId}, PUT delivered/broken), `AdminController` (CRUD systems, packet search), `SupportController` (user/version).

**Workers/background:** `ExpiredPacketTrackerImpl` (1 min interval — marks expired), `LocalDirPayloadTrackerImpl` (1 min — cleans temp files), `PayloadInboundSynchronizer` (Spring Integration FTP poll), `PayloadOutboundGateway` (FTP upload with 3 retries, 5s backoff).

**Language/framework:** Java 17, Spring Boot 2.5.7, Spring Integration 5.5.0 (FTP), Spring Kafka 2.7.2, Hibernate/JPA, Lombok, Jackson.

**Deployment:** OpenShift (deploymentConfig.yml: 1 replica, ClusterIP port 8080, route TLS edge, PodMonitor for Prometheus), persistent volume for temp files (`LOCAL_ROOT_DIR`). Docker image `recommend/axiom-jre-alpine-musl:17_autoheap`.

**Env vars (ключевые, без секретов):** `sod.from-zone`, `sod.to-zone`, `sod.max-packet-timeout-sec`, `sod.action-timeouts-sec` (resend backoff: "60 120 240 480 600"), `sod.channel.driver.type=FTP`, `sod.channel.outbound` (InfoDiode IN directory path), `sod.channel.inbound` (InfoDiode OUT directory path), `security.oauth2.*` (Blitz SSO endpoint URLs), `KAFKA_BOOTSTRAP`, `KAFKA_NOTIFICATIONS_TOPIC`, `KAFKA_META_NOTIFICATIONS_TOPIC`.

**Database:** PostgreSQL 10.5+, 5 tables (system, payload_packet, meta_packet, packet_state_change, packet_attribute), Hibernate validation mode (DDL managed by SQL migrations).

**Health:** `/monitoring/prometheus` on port 22222 (Prometheus metrics), standard Spring Boot actuator.

**Evidence:**

| Область | Факт | Источник | Уверенность | Unknown/gap |
|---|---|---|---|---|
| Runtime | Java 17, Spring Boot 2.5.7, AxiomJRE-Alpine autoheap | pom.xml, deploymentConfig.yml | HIGH | — |
| Deployment | OpenShift, 1 replica, 70+ env vars, PVC, Route TLS, PodMonitor | deploymentConfig.yml | HIGH | Актуальна ли OpenShift vs Deckhouse сейчас |
| Network | FTP (2 раздельных хоста: in/out), Kafka (SASL_SSL/SCRAM-SHA-256), Blitz SSO (HTTPS) | FtpChannelsAutoConfiguration.java, KafkaConfiguration.java, SecurityConfiguration.java | HIGH | Реальная latency InfoDiode |
| Storage | PostgreSQL 10.5, локальный PVC для temp файлов, FTP как транспорт, файлы удаляются из FTP после sync | create_tables.sql, FtpChannelsAutoConfiguration.java, deploynmentConfig.yml | HIGH | — |

## 3. API и authentication

### Endpoints

| Controller | Method | Path | Auth | Description |
|---|---|---|---|---|
| Outbound | POST | `/out/{domain}` | X-SYSTEM-TOKEN | Send file: multipart (domain, subject, bytes, hex/MD5, file, timeout, additional) |
| Outbound | GET | `/out/{packetId}` | X-SYSTEM-TOKEN | Get packet state |
| Inbound | GET | `/in/{domain}/received` | X-SYSTEM-TOKEN | List RECEIVED packets for system+domain |
| Inbound | GET | `/in/{packetId}` | X-SYSTEM-TOKEN | Download packet payload (octet-stream) |
| Inbound | PUT | `/in/{packetId}/delivered` | X-SYSTEM-TOKEN | Confirm delivery (deletes local data) |
| Inbound | PUT | `/in/{packetId}/broken` | X-SYSTEM-TOKEN | Report corruption (deletes local data) |
| Admin | GET | `/admin/packet/search` | ROLE_ADMIN (SSO) | Search packets with filters |
| Admin | GET | `/admin/packet/{packetId}` | ROLE_ADMIN | Download admin |
| Admin | GET | `/admin/packet/{packetId}/resend` | ROLE_ADMIN | Resend |
| Admin | GET/POST/PUT/DELETE | `/admin/system/**` | ROLE_ADMIN | Manage client systems |
| Support | GET | `/user/current` | Any SSO | Current user info |
| Support | GET | `/version` | Any | Version |

### Authentication

1. **System-to-system (X-SYSTEM-TOKEN):** `TokenAuthenticationFilter` на `/in/**` и `/out/**`. Токен генерируется по 410P-совместимому алгоритму (32 chars, rentgen-utility), хранится в таблице `system(token)`. Проверка: lookup system by token → `SodUser(type=SYSTEM, NO_AUTHORITIES)`. Access control: `SystemPrivilegeService` проверяет, что система-владелец пакета = аутентифицированная система.

2. **Human admin (OAuth2 SSO):** Blitz SSO (`sso.*.ppod.cbr.ru`). `SodPrincipalExtractor` → `displayName`; `SodAuthoritiesExtractor` → группы → `ROLE_ADMIN` если принадлежит admin-group. Unprotected paths: `/login**`, `/error`, Swagger.

3. **TLS:** Route edge termination на OpenShift. Сервис сам TLS не терминирует.

4. **Versioning:** нет formal API versioning. No compatibility negotiation.

5. **Callback/webhook:** нет. Получатель сам поллит `/in/{domain}/received` или читает Kafka.

### Request/response schemas (фактические поля)

**POST /out/{domain} (multipart form-data):**
- `domain` — логический домен/категория (varchar(20))
- `subject` — инициатор (varchar(60))
- `bytes` — размер файла (bigint)
- `hex` — MD5 checksum (text)
- `file` — multipart file
- `timeout` — optional, TTL пакета в секундах (иначе `max-packet-timeout-sec`)
- `additional` — optional, JSON строка → set of `{name, value}` для `packet_attribute`

**Response (PayloadPacketDto):**
```json
{
  "id": "UUID",
  "type": "IN|OUT",
  "state": "PREPARED|SENT|RECEIVED|DELIVERED|BROKEN|LOST|REJECTED|EXPIRED",
  "domain": "string",
  "systemId": "string",
  "subject": "string",
  "payloadName": "string",
  "bytes": 0,
  "hex": "MD5",
  "createDate": "datetime",
  "processedDate": "datetime",
  "expiredDate": "datetime",
  "attributes": [{"id": "UUID", "name": "string", "value": "string"}]
}
```

## 4. Package и data contract

1. **Что является package:** Один ZIP-файл = payload file + meta entry (JSON сериализация `PayloadPacketDto`).

2. **Обязательные поля:** `id` (UUID, генерируется клиентом), `type` (IN/OUT), `domain`, `systemId`, `subject`, `payloadName`, `bytes`, `hex` (MD5 checksum), `createDate`. Опционально: `timeout` (TTL), `additional` (attributes key-value), `expiredDate` (вычисляется из timeout).

3. **Checksum/signature:** Только MD5 checksum (`hex` поле). Вычисляется клиентом при отправке, проверяется СОД при приёме (FileInboundProcessor валидирует bytes + hex). Legacy `hex` — это MD5 хеш файла, не signature (tamper evidence нет — MD5 не криптостойкий).

4. **Manifest:** Нет manifest'а как отдельного документа. `additional` key-value pairs — ближайший аналог. Meta entry внутри ZIP — JSON сериализация packet DTO.

5. **Size limits / chunking / streaming / compression:** ZIP compression. No explicit size limits в коде (зависит от `max-packet-timeout-sec` как таймаут, а не size cap). FTP file transfer, no chunking/streaming API. No supported media types restriction (любой файл).

6. **Multi-type payload:** Нет. Один package = один payload file. Git bundle, OCI images, Nexus packages — не поддерживаются нативно. Косвенно: через `additional` attributes можно указать тип содержимого, но СОД не валидирует.

7. **Source/Target staging:** Локальный PVC: `{LOCAL_ROOT_DIR}/{payloadLocalRootDir}` для временных файлов. После DELIVERED/BROKEN — удаляется. FTP staging: файлы удаляются после успешного sync (FtpInboundSynchronizer).

## 5. State machine и delivery semantics

### Подтверждённый state machine (из `PacketState.java` + `PayloadStateProcessor.java`):

```
               ┌──────────────────┐
               │   null (initial) │
               └────────┬─────────┘
                        ↓
               ┌──────────────────┐
               │    PREPARED      │──→ LOST (FTP upload fail)
               └────────┬─────────┘──→ EXPIRED (timeout)
                        ↓
               ┌──────────────────┐
               │      SENT        │──→ EXPIRED (timeout before receive)
               └────────┬─────────┘
                        ↓                  ┌→ REJECTED (target system not found)
               ┌──────────────────┐       │
               │    RECEIVED      │───────┼→ BROKEN (corruption detected)
               └────────┬─────────┘       │→ LOST (file missing on download)
                        ↓                  └→ EXPIRED (timeout before delivery)
               ┌──────────────────┐
               │    DELIVERED     │  ← terminal success
               └──────────────────┘
```

**Допустимые переходы (guard):**
- PREPARED ← null only
- SENT ← PREPARED, SENT (retry)
- RECEIVED ← SENT, PREPARED
- DELIVERED ← RECEIVED, SENT, PREPARED
- BROKEN ← null, RECEIVED, SENT
- LOST ← RECEIVED, PREPARED, SENT
- REJECTED ← SENT only

2. **Observed path `PREPARED → SENT → RECEIVED → DELIVERED`:** **ПОДТВЕРЖДЁН.** Именно этот happy path реализован. Факт: `FileOutboundProcessor.send()` создаёт PREPARED, FTP upload success → SENT; `FileInboundProcessor.receive()` → RECEIVED; client `PUT /in/{packetId}/delivered` → DELIVERED.

3. **Semantics:**
   - `RECEIVED` = файл физически прибыл в целевую зону, разархивирован, checksum валидирован, сохранён локально. Это **transport receipt + validation**, НЕ business success.
   - `DELIVERED` = клиент подтвердил получение (после download). Файл удаляется из локального PVC. Это **client confirmation**, НЕ bootstrap/deployment/reconstruction.

4. **Partial delivery:** НЕ поддерживается. Нет понятия «частично доставленного» пакета. Один пакет = один файл = один статус.

5. **Edge cases:**
   - **Timeout:** `ExpiredPacketTrackerImpl` (1 min) переводит PREPARED/SENT/RECEIVED → EXPIRED. TTL: per-packet `timeout` parameter или `max-packet-timeout-sec`.
   - **Network break:** FTP gateway retry 3 раза с 5s backoff (`@Retryable`). После 3 fail → LOST (outbound) или пакет не прибывает (inbound poll продолжит когда связь восстановится).
   - **Process crash:** Состояние в БД (PostgreSQL). Temp файлы в PVC — восстанавливаются при перезапуске. Зависшие PENDING запросы НЕ существуют в СОД (это notification service pattern).
   - **Duplicate:** `FileInboundProcessor` детектит дубликат по packet ID. Если ID уже существует → ресетит текущее состояние, не создаёт дубль.
   - **Corrupted payload:** При приёме: MD5 проверка → BROKEN (notify source via meta outbound). При скачивании: если файл отсутствует → LOST.

6. **Retry связность:** `PacketActionTimeoutService` поддерживает progressive backoff для resend операций (60s → 120s → 240s → 480s → 600s → 600s...). Хранится in-memory в ConcurrentHashMap (НЕ переживает рестарт — после рестарта все таймауты сбрасываются). Это **code + config**, не operator policy.

7. **Idempotency key:** `packetId` (UUID, генерируется клиентом). СОД детектит дубликат по ID. Повторный POST с тем же ID НЕ создаст новый пакет. **Безопасен ли повтор upload:** да, но только если первый завершился (иначе race condition с in-flight обработкой — неясно из кода).

8. **Retries/backoff/TTL:** FTP upload: 3 retries, 5s delay (hardcoded в `@Retryable`). Resend backoff: конфигурируемая последовательность секунд (`sod.action-timeouts-sec`). TTL: per-packet `timeout` параметр или глобальный `max-packet-timeout-sec` (default: конфигурируемый).

## 6. Cross-zone topology

### Factual sequence (подтверждено кодом):

```
Source Zone (ЗР)                              Target Zone (ЗТ/ЗПЭ)
─────────────                                 ────────────────────
                                                                  
Cosmoport Client                                 Client (receiver)
  │ POST /out/{domain}                           │ GET /in/{domain}/received
  │ (multipart + MD5)                            │ (poll list)
  ▼                                              ▼
SOD Service (outbound)                       SOD Service (inbound)
  │ ZIP (payload+meta)                          │ poll FTP OUT dir
  │ state → PREPARED                            │ unzip + validate MD5
  ▼                                              │ state → RECEIVED
FTP Outbound Gateway                             │
  │ upload ZIP (3 retries)                       │
  │ state → SENT                                 │
  ▼                                              ▼
InfoDiode IN dir ──[ONE-WAY]──→ InfoDiode OUT dir
(FTP upload side)                  (FTP download side)
                                         
  ◄── state sync (SENT/RECEIVED/DELIVERED) ──►  JSON meta packet
       через ОБРАТНЫЙ InfoDiode
       (FTP OUT dir → InfoDiode → FTP IN dir)
                                         
  ◄── Kafka notification (опционально) ──►      sod_notifications topic
       (SASL_SSL, SCRAM-SHA-256)
```

- **Data flow:** ОДНОНАПРАВЛЕННЫЙ. InfoDiode гарантирует физическую однонаправленность.
- **Return ACK/control channel:** ОБРАТНЫЙ InfoDiode (отдельный физический канал) + опционально Kafka (SASL_SSL). Meta-packets (JSON с `PayloadPacketDto`) передаются обратно для синхронизации состояния.
- **Session/lease owner:** СОД владеет сессией: создаёт пакет, отслеживает TTL, чистит EXPIRED. Клиент не владеет сессией, только инициирует и подтверждает.
- **Dynamic ports:** Нет. Все порты статические (FTP 21, HTTP 8080, Kafka 9092).
- **Kafka role:** ТОЛЬКО state change notifications (`sod_notifications`, `sod_meta_notifications`). НЕ data transport. Топики используются внешними слушателями (например Cosmoport ПУ) для мониторинга статуса без polling. CONFIRMED: `KafkaStateNotificationStrategy` serialises `PayloadPacketDto`/`MetaPacketDto` to JSON, sends as String. Key = packet ID.

### ЗР→ЗТ vs ЗТ→ЗПЭ:
- **Одинаковый код**, одинаковый протокол. Разница только в конфигурации: `sod.from-zone` и `sod.to-zone`, адреса FTP-хостов. Никакой специальной логики для конкретного направления нет.
- Есть упоминание ЗТ→ЗПЭ как через Gitlab runner polling T1-Сфера (из документации LCZD v3.3), но это НЕ в коде СОД — это отдельный механизм для зон без прямого сетевого соединения.

## 7. Cosmoport 1 integration

1. **Callers СОД:** Косвенно — через Cosmoport контроллеры (`Packages::TransferReleaseWithStatus`, `Transfers::MzpTransferRelease`). Прямых вызовов в коде СОД нет (СОД не знает о Cosmoport). СОД видит только system_id (зарегистрированная система) + пакет. CONFIRMED: в `cosmo-dump.sql` есть `external_id` в packages таблице со ссылкой на СОД.

2. **Что отправлял Cosmoport:** Git bundle (source code) + Docker images (через `delivery_types` jsonb в `mzp_transfers`) + metadata. Но это через МЗП (mzp_transfers), а НЕ напрямую через СОД. СОД использовался для release metadata и report transfers. FACT: в `packages` таблице есть `zone` колонка и `transfer_package_log_id`.

3. **Что Cosmoport поллил/получал:** `transfer_statuses` таблица в Cosmoport. Статусы: `not_transferred → processing → building_package → transferring → success/failed`. Эти статусы маппятся на СОД-статусы без прямого API-поллинга — через `release_route_package_transfers` и `release_transfer_histories`.

4. **PackageTransfer/reception:** `release_route_package_transfers` в Cosmoport — запись о пакетном трансфере. `release_receptions` — приёмка на целевой стороне. Source of truth статуса: Cosmoport (таблица `release_route_package_transfers.status`), НЕ СОД.

5. **После DELIVERED:** СОД удаляет локальный файл. Что происходит дальше (bootstrap, import, repository reconstruction, deployment) — НЕ в СОД. Это происходит в Cosmoport (`Packages::ReceiveReleaseStatus`, `ReleaseReception`).

6. **Retry/recovery:** Cosmoport-level retry через `repeat_transfer` флаг на release. СОД-level retry: FTP gateway 3 попытки, resend backoff. Никакой координации между ними.

7. **Legacy-only assumptions:**
   - FTP как транспорт (в Cosmoport 2 — Gitea/Kubernetes)
   - MD5 как checksum (в Cosmoport 2 — SHA-256)
   - Однонаправленный InfoDiode (в Cosmoport 2 — bidirectional Git push/pull)
   - X-SYSTEM-TOKEN (в Cosmoport 2 — ForgeAdapter token/API key)
   - Отдельный физический канал для meta/ACK (в Cosmoport 2 — Git webhook/status API)
   - ZIP-архив как формат пакета (в Cosmoport 2 — Git bundle + manifest)

## 8. Security, audit и operations

- **Audit:** `packet_state_change` таблица — каждое изменение состояния пишет `(state, date, payload_packet_id)`. Correlation ID = packet UUID. Это audit trail, но НЕ tamper-evident (можно удалить/изменить в БД).
- **Tamper evidence:** НЕТ. MD5 checksum только для integrity, не для non-repudiation. Нет цифровых подписей, нет immutable ledger.
- **Redaction:** `subject` поле (инициатор) логируется в открытом виде. `payload_name` visible. `hex` (MD5) visible. Содержимое файла НЕ логируется.
- **RBAC для операций:** Только ROLE_ADMIN (SSO admin group) для админ-операций. System token для send/receive — любая зарегистрированная система.
- **Quarantine/malware:** НЕТ. СОД не проверяет содержимое пакетов.
- **Runbook:** НЕТ в коде. Есть admin-UI (React) с возможностью поиска, скачивания, повторной отправки. Это и есть операторский интерфейс.
- **Metrics/alerts/dashboards:** Prometheus метрики через PPOD monitoring starter. PodMonitor в OpenShift. No built-in dashboards or alerts in code.

## 9. Final factual report

| Question | Answer | Evidence | Confidence | Impact if wrong |
|---|---|---|---|---|
| Actual role of SOD | Gateway однонаправленной передачи файлов через InfoDiode/FTP | FileOutboundProcessor.java, FileInboundProcessor.java, FtpChannelsAutoConfiguration.java | HIGH | Мы строим не тот транспорт |
| API/auth | REST (POST /out, GET /in) + X-SYSTEM-TOKEN + OAuth2 SSO | OutboundController.java, InboundController.java, SecurityConfiguration.java | HIGH | API контракт для Cosmoport 2 неверен |
| Package scope | Один ZIP: file + metadata JSON. MD5 checksum. | FileOutboundProcessor.java, create_tables.sql | HIGH | Формат пакета не подходит |
| Status semantics | PREPARED→SENT→RECEIVED→DELIVERED. RECEIVED=транспорт, DELIVERED=клиентская квитанция | PacketState.java, PayloadStateProcessor.java | HIGH | Маппинг на Cosmoport-статусы неверен |
| Idempotency/recovery | packetId как dedup key. FTP gateway: 3 retries, 5s. Resend: progressive backoff. TTL: per-packet timeout. | PayloadStateProcessor.java, PacketActionTimeoutService.java | HIGH | Повторная отправка небезопасна |
| Kafka role | Только state change notifications, НЕ data transport | KafkaStateNotificationStrategy.java, KafkaConfiguration.java | HIGH | Ошибочно считаем Kafka транспортом |
| Gap topology | InfoDiode (однонаправленный) через FTP. Обратный канал: отдельный InfoDiode + Kafka. | FtpChannelsAutoConfiguration.java, deploymentConfig.yml | HIGH | Топология нерелевантна для Gitea/K8s |
| Cosmoport boundary | Cosmoport = caller (POST /out), consumer (GET /in + Kafka listener). Статус в Cosmoport DB, не в СОД. | cosmo-dump.sql: packages, release_route_package_transfers, transfer_statuses | MEDIUM | Пропущена часть integration logic |

### Contradictions and competing evidence

1. **MZP vs СОД:** Cosmoport использует ДВА механизма трансфера — СОД (Service of Data Exchange) и МЗП (Module of Secure Transfer). В коде есть `mzp_transfers`, `mzp_deliveries`, `mzp_url`. MZP использует GitLab impersonation tokens и delivery types. Evidence: `cosmo-dump.sql:mzp_transfers`, `Transfers::MzpTransferRelease`. **СОД был основным транспортом для release transfer, MZP — альтернативным для source code + Docker images.**

2. **Kafka notifications vs polling:** СОД поддерживает Kafka для push-нотификаций (профиль `KafkaNotifications`) И polling (`GET /in/{domain}/received`). Оба механизма рабочие. Непонятно, какой использовался в production.

3. **Checksum: MD5 в коде vs SHA-256 в концептах:** СОД использует только MD5 (поле `hex` в `payload_packet`). Упоминания SHA-256 обнаружены в документации Cosmoport, но НЕ в коде СОД.

### Legacy-only behaviour

1. FTP как транспортный протокол
2. InfoDiode (однонаправленный физический диод)
3. X-SYSTEM-TOKEN (системная аутентификация по токену из БД)
4. ZIP-архив как контейнер пакета (payload + metadata JSON)
5. MD5 checksum (не криптостойкий)
6. Раздельные FTP in/out хосты (разные физические каналы)
7. Meta-packets через обратный InfoDiode для синхронизации состояния
8. In-memory action timeout (не переживает рестарт)
9. OAuth2 SSO через Blitz для админ-доступа
10. Spring Integration FTP adapters
11. Ключевые слова 410P (генерация токенов по стандарту ЦБ РФ)

### Not enough evidence for a Cosmoport 2 decision

1. **Нужен ли СОД в Cosmoport 2:** Нельзя принять решение на основе source inspection. Gitea + Kubernetes обеспечивают bidirectional transfer, который заменяет СОД + InfoDiode. Но нужно подтверждение, что bidirectional transfer разрешён в целевых зонах.

2. **Нужен ли Kafka для транспортных нотификаций:** СОД использует Kafka только для оповещений. В Cosmoport 2 аналогичную роль может играть Gitea webhook + Run Control Plane events.

3. **Нужен ли формат ZIP + metadata JSON:** Это legacy-формат, привязанный к InfoDiode/FTP. В Cosmoport 2 — Git bundle + manifest.

4. **Нужна ли таблица packet_state_change:** Аналог — Evidence Chain в Cosmoport 2.

5. **Нужен ли resend backoff (60s-120s-...-600s):** Полезный operational pattern для retry, но конкретные значения — operator policy, не архитектурное требование.

6. **Какие transport backends:** FTP подтверждён. Альтернативы (SFTP, S3, HTTP) упомянуты в архитектуре каналов (`ChannelsConfiguration`) но не реализованы.