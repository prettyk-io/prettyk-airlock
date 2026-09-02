# Legacy source-inspection acceptance: СОД + Notification Service

> **Статус:** PO acceptance-запись Cosmo. Не канон, не design.
> Источники: `2026-09-01-sod-source-inspection-worksheet.md`,
> `2026-09-01-notification-service-source-inspection-worksheet.md`.
> Все legacy-факты — non-binding observations для transport matrix; решения
> baseline (`2026-09-01-transfer-approach-baseline.md`) не пересматриваются.

## 1. Корзина Facts (подтверждено кодом, HIGH confidence)

### СОД

| Факт | Следствие для PureK/Cosmoport 2 |
|---|---|
| Gateway однонаправленной передачи файлов через InfoDiode поверх FTP; transport service + package registry, не orchestration | СОД подтверждён как transport-only bridge; orchestration остаётся у нас |
| State machine PREPARED → SENT → RECEIVED → DELIVERED (+ BROKEN/LOST/REJECTED/EXPIRED с guards) | Референс для нашей TransferItem state machine |
| RECEIVED = transport receipt + validation; DELIVERED = client confirmation; bootstrap после DELIVERED — вне СОД | Прямое подтверждение нашего разделения delivery → landing approval → bootstrap |
| Package = ZIP (payload + metadata.json), MD5 checksum | Формат legacy-only; подтверждает manifest+checksum инвариант (у нас SHA-256) |
| Idempotency = client-generated UUID packetId, dedup по ID | Подтверждает client-side idempotency key в TransferItem |
| Kafka — только state notifications (профиль KafkaNotifications), НЕ data transport | Закрывает вопрос роли Kafka: уведомления, не транспорт |
| Обратный канал: отдельный InfoDiode с meta-packets + опционально Kafka | Подтверждает diode profile №2 baseline: one-way data + отдельный control/ACK channel |
| Retry: FTP 3×5s; resend backoff 60→600s; TTL tracker; timeouts in-memory (теряются при рестарте) | Операционные значения — operator policy; durable retry state — наш обязательный инвариант |
| Status SoT в БД caller'а (Cosmoport), не в СОД | Подтверждает: authoritative transfer status живёт в Control Plane |

### Notification Service

| Факт | Следствие |
|---|---|
| Hub: Kafka consumer → BELL (DB) + EMAIL (PIS relay ZIP + callback) | Функциональность уведомлений нужна; стек доставки — replaceable |
| Inbound journal NOTIFICATION_REQUEST_INFO: NEW→PENDING→SUCCESS/FAILURE; PENDING>1h → NEW | Хороший pattern journal'а; у нас — transactional outbox |
| Нет outbox/DLQ; email NEW-записи после падения не подхватываются (resend только ERROR) | Anti-pattern, подтверждающий наш transactional outbox + DLQ |
| BELL: DB write = success; EMAIL: PIS accept = success | Слабая delivery semantics — задокументировать как нижнюю границу |
| Subscriptions: ALL/SELECTED, isExcluded (allow/blocklist), per-subscription delivery type | Полезная семантика; упростить при оформлении |
| Нет digest/throttle/quiet hours/multi-tenant isolation; нет валидации link (SSRF) | Требования-минимусы для нашей notification surface |
| 22+ event types (NOT v2.2); Cosmoport callers: Produce (Kafka), TypesProduce (startup registration), SendNotificationJob | Input для event taxonomy нашей SSE/notification поверхности |

## 2. Корзина General approach insights (non-binding)

1. Двухступенчатая модель «transport receipt → client/landing confirmation» —
   прямой референс для completeness barrier и `isLandingApproved`.
2. Client-generated idempotency UUID — подтверждённый индустриальный паттерн
   dedup при повторной отправке через ненадёжный канал.
3. Meta-packet отдельного обратного канала — референс для ACK/status plane,
   физически отделённого от data plane (diode profile).
4. Inbound journal с state machine запроса — референс для transfer event
   journal; у нас он объединяется с transactional outbox.
5. TTL/EXPIRED tracker — референс для transfer lease и stale-package GC.
6. Progressive resend backoff — полезный operational pattern; значения —
   operator policy, не архитектура.
7. Subscription-модель уведомлений (ALL/SELECTED + allow/blocklist) —
   кандидат в упрощённом виде для Control Station.

## 3. Корзина Legacy-only / discard

FTP, InfoDiode-реализация, ZIP+MD5, X-SYSTEM-TOKEN/410P, Blitz SSO, PIS relay,
Consul, Single-SPA, Splunk как audit-SoT, Spring Cloud Stream, Racecar/Sidekiq,
in-memory timeouts, 6-месячный retention без архивной политики.

Contradiction MD5 vs SHA-256 разрешён в пользу нашего канона: SHA-256.

## 4. Contradictions, влияющие на matrix

1. **СОД vs МЗП:** в legacy уже было два транспорта — СОД (metadata/reports) и
   МЗП (source + Docker images). Решение не меняет (МЗП исключён, СОД —
   optional bridge), но это историческое подтверждение multi-plane модели:
   один транспорт никогда не вёз весь payload.
2. **Kafka vs polling у СОД:** оба механизма реализованы; какой использовался
   в production — UNKNOWN. Влияет только на операционный референс, не на
   архитектуру.
3. **Email-дублирование Cosmoport** (Kafka→notification service + прямой SMTP
   UserMailer параллельно): анти-паттерн; у нас единая notification surface
   без параллельных ad-hoc каналов.

## 5. Вклад в transport matrix

```text
gap principle      — подтверждена отделённость transport от semantics
crossing mechanism — diode profile №2 (one-way + control channel) подтверждён кодом legacy
payload plane      — multi-plane подтверждена legacy-практикой (СОД/МЗП split)
ACK model          — meta-packet reference + operator polling; обе модели рабочие
recovery           — TTL + dedup + backoff + SoT у caller'а; durable retry обязателен
```

Открытым остаётся: production-топология и объёмы (interview), выбор
primary/secondary profiles (решение PO после matrix).

## 6. Follow-up

- Worksheet UNKNOWN «кто вызывает СОД» и «что после DELIVERED» → следующий
  inspection: поверхность transfer/reception Cosmoport 1
  (`Packages::TransferReleaseWithStatus`, `ReleaseReception`,
  `load_releases_from_dev.rb`, `transfer_statuses`).
- Product decisions (нужен ли СОД/отдельный notification service, delivery
  semantics, event taxonomy) — отдельно, после transport matrix.
