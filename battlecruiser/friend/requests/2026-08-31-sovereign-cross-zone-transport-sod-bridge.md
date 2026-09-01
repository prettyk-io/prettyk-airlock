# Sovereign cross-zone transport и СОД bridge

> **Статус:** friend-request / `PROVISIONAL` / подтверждение Максима получено /
> Keeper admission pending
>
> **Инициатор:** Максим, зафиксировал Cosmo
>
> **Цель:** единый безопасный default межзонной доставки для PrettyK и
> Cosmoport 2 без наследования legacy МЗП или внутренностей СОД.

## 1. Решение

```text
Sovereign Cross-Zone Transport
  → default для PrettyK и Cosmoport 2

legacy СОД bridge
  → одна поддерживаемая внешняя интеграция Cosmoport 2

МЗП
  → EXCLUDED
```

МЗП не появляется в новых routes, DTO, configuration, UI, adapter или fallback.
Исторические упоминания допускаются только в research с отметкой `EXCLUDED`.

## 2. Подтверждённые legacy facts

```text
ПУ source zone
  → СОД client
  → Kafka
  → СОД acceptor
  → target-zone bootstrap
```

- СОД состоит из пары client/acceptor.
- Между ними используется Kafka; это внешняя внутренняя механика СОД, а не новый
  dependency Control Plane.
- Наблюдаемый transport — QUIC.
- Наблюдаемый lifecycle: `PREPARED → SENT → RECEIVED → DELIVERED`.
- Acceptor передаёт package в target zone; bootstrap создаёт/настраивает контекст
  приложения и подключает интеграции, включая forge contract.

## 3. Граница и семантика успеха

```text
transport delivered
→ target package verified
→ target bootstrap completed
→ deployment completed
→ «В эксплуатации»
```

`DELIVERED` в СОД — технический transport-success. Он не доказывает целевой
business-success и не может сам опубликовать «В эксплуатации».

ПУ хранит отдельные durable audit/state events для transport delivery, package
verification, bootstrap и deployment. Никаких raw secrets в ПУ или package.

## 4. Границы scope

### В scope после admission

- определить provider-neutral external transport contract;
- определить immutable package manifest, SHA-256 integrity и idempotency;
- создать СОД bridge adapter для Cosmoport 2 после получения API/operations
  evidence;
- согласовать общий PrettyK/Cosmo default transport как отдельный межпродуктовый
  contract.

### Не в scope

- импорт Kafka/acceptor code в ПУ;
- новая реализация или fallback МЗП;
- предположение, что `DELIVERED` означает deployment success;
- перенос raw credentials в package, config или pipeline variables;
- implementation до DevOps evidence и отдельной delivery card.

## 5. Evidence, которое предоставляет DevOps СОД

1. Helm/Kustomize/Compose manifests, images, entrypoints и redacted configs;
2. OpenAPI/Swagger или collection, authentication и redacted request/response;
3. network/QUIC/TLS topology client ↔ acceptor;
4. Kafka topics, schema/key/headers, retention, retries и DLQ;
5. package limits, manifest, `hex` algorithm, integrity/signature, expiry;
6. correlation trace real non-sensitive package source → target bootstrap;
7. idempotency, partial delivery/replay/recovery runbook and monitoring;
8. target bootstrap/deployment completion callback or query contract.

## 6. Критерий admission

Keeper и Максим подтверждают, что:

1. МЗП исключён из обеих product lines;
2. shared sovereign transport — direction, а не неявное требование копировать
   legacy СОД;
3. СОД bridge — adapter boundary Cosmoport 2;
4. Kafka остаётся снаружи утверждённого stack ПУ;
5. transport delivery и target deployment — разные факты жизненного цикла.