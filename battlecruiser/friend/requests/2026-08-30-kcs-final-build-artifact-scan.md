# KCS как финальный container scan по артефакту конкретной сборки

> **Статус:** friend-request / first 2FA agreed / implementation candidate  
> **Дата:** 30 августа 2026  
> **Участники:** Максим ↔ Cosmo  
> **Контур:** Cosmoport 2.0 / container artifact lifecycle

## 1. Наблюдение в текущем Cosmoport

По просмотренному pipeline в легаси-процессе:

```text
образ уже существует в registry/repository
→ его находят там
→ KCS выполняет финальный scan
```

KCS не получает как вход явно зафиксированный artifact output конкретного Build.
Это создаёт риск сканировать не тот tag/image, использовать устаревший образ или
потерять связь между результатом scan и фактическим Build.

## 2. Целевое улучшение Cosmoport

Cosmoport не повторяет эту ошибку:

```text
Build image
  → получить immutable digest
  → записать Build + ArtifactRecord
  → push exact artifact в разрешённый registry flow
  → source/container scans
  → KCS как последний container scan
  → сохранить PASS/FAIL для exact digest
  → только после readiness продолжить deploy/package
```

KCS должен сканировать:

```text
artifact produced by this Build
identified by immutable digest
```

а не произвольный существующий tag из repository.

## 3. Профиль Docker image

Предлагаемый профиль:

```text
build_image
→ sbom
→ trivy (если включён типом релиза)
→ kcs (финальный container scan)
→ deploy
```

KCS — последняя **container scan** операция. `deploy` после него не является
scan и не нарушает это правило.

После добавления KCS Docker profile изменится с 4 до 5 шагов. Truth table,
ReleaseType profiles и тесты должны быть обновлены согласованно, а не только
изменением одного списка.

Source-code profile по-прежнему не получает KCS/Trivy как container scans.

## 4. Что фиксируется в Evidence

Для KCS result сохраняются:

- build_id;
- release_id;
- artifact registry;
- repository;
- image name;
- immutable digest;
- KCS check id;
- status;
- timestamp;
- Evidence reference;
- Act/QG reference, если входит в итоговый пакет.

Tag может отображаться оператору, но identity проверки — digest.

## 5. Что пока не утверждаем

Не фиксируем без коллег/вендора:

- в какой из `raw/dirty/clean` потоков должен попадать image до KCS;
- является ли KCS самостоятельным promotion engine;
- делает ли KCS copy/promote или только возвращает verdict;
- как КCS получает artifact: pull, API, webhook или job integration;
- должен ли PrettyK DAST идти до или после KCS;
- где именно хранится Act для KCS.

Утверждено только направление:

```text
KCS scans exact Build artifact by digest and is the final container scan.
```

## 6. Acceptance scenarios

### Correct artifact

```text
Given: Build B produced image digest D
When: KCS scan is requested
Then: KCS receives/resolves D, not a mutable tag
And: result links to B and Release
```

### Tag drift

```text
Given: tag points to digest D2 after Build produced D1
When: KCS scan runs for the Release
Then: scan still checks D1
And: D2 is not accepted as evidence
```

### Missing artifact

```text
Given: Build has no immutable digest
When: container lifecycle starts
Then: KCS is not called
And: release is blocked with missing_artifact_digest
```

### KCS failure

```text
Given: KCS returns FAIL for exact digest D
When: readiness is evaluated
Then: release/package is blocked
And: Evidence contains the failed KCS result
```

## 7. Следующий шаг

После повторного 2FA и получения технического контракта KCS:

1. обновить Docker artifact truth table: 4 → 5 steps;
2. добавить KCS executor/adapter contract;
3. связать KCS check с Build digest;
4. добавить persistence и idempotency tests;
5. проверить package readiness;
6. не путать KCS container scan с PrettyK full DAST/QG.
