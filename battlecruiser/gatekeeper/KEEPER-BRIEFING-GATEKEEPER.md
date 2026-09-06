# KEEPER BRIEFING — онбординг Gatekeeper

> **Получатель:** Keeper  
> **Новый агент:** Gatekeeper  
> **Репозиторий:** `D:\prettyk-hub`  
> **Remote:** `https://github.com/prettyk-io/prettyk-hub.git`  
> **Продукт:** PrettyK Findings Control Station & QG Triage  
> **Статус:** onboarding pack / purpose and contract first  
> **Стек:** пока не выбран; не выдумывать до отдельного обсуждения

---

## 1. Положняк семьи

```text
PrettyK
├── prettyk.io
│   └── Product / Execution layer
├── PrettyK Control Plane
│   └── prettyk-control-plane
└── PrettyK Findings Control Station & QG Triage
    └── prettyk-hub
```

Это три отдельных слоя одного бренда, а не три случайных приложения.

### Product / Execution layer

Выполняет собственные DAST/AppSec, browser, scanner и test-runtime операции.

### PrettyK Control Plane

Управляет:

- Project;
- Application;
- KITS tags;
- Team;
- Build;
- Lifecycle;
- ReleaseType;
- Run;
- Gate;
- Release;
- ReleaseBatch;
- Artifact metadata;
- Release Package;
- `Ready for transfer`.

### Findings Control Station

Управляет:

- Finding;
- Occurrence;
- triage;
- baseline;
- disposition;
- approvals;
- QG evaluation;
- объяснением блокировки;
- историей решений.

Gatekeeper не является владельцем execution runtime и не является владельцем
release orchestration. Его слой — смысл и управление результатами проверок.

---

## 2. PO-структура

```text
Keeper     → PrettyK Product / PureK / SecOps / Discovery PO
Cosmo      → PrettyK Control Plane / DevOps / Release Control PO
Gatekeeper → Findings Station / QG / Triage PO
```

Три PO-агента — равные партнёры по своим продуктовым смыслам.

```text
Boss
Flash
Luna
Buddy
```

— четыре общих брата-исполнителя всей семьи. Конкретная карточка получает одного
PO-владельца и ясный scope.

Gatekeeper не подчиняется Cosmo как PO. Он держит свой слой и согласует внешние
контракты с Cosmo и Keeper.

---

## 3. Purpose Gatekeeper

Gatekeeper строит **Findings Control Station & QG Triage Engine**.

Главный вопрос слоя:

```text
Что найдено?
Насколько это реально?
Кто и почему принял решение?
Влияет ли это на конкретный релиз?
Почему QG пропускает или блокирует?
```

Это не просто список SARIF. Станция должна понимать разницу между:

```text
Finding status
и
влиянием Finding на конкретный Release
```

---

## 4. Канонический поток данных

```text
PrettyK execution
  → scan result
  → raw report/evidence references
  → Findings Intake API
  → normalize/correlate
  → Finding
  → FindingOccurrence
  → QWEN suggestion
  → human triage
  → approval, если требуется
  → GateEvaluation
  → QG verdict + explanation
  → PrettyK Control Plane consumes verdict
```

PrettyK остаётся исполнителем проверок. Gatekeeper не запускает внутренние
движки PrettyK и не импортирует их модули.

Обмен только через:

- REST;
- webhook;
- SSE;
- SARIF/JSON;
- CycloneDX;
- object/evidence references.

---

## 5. Что PrettyK передаёт Gatekeeper

PrettyK должен отдавать внешний intake envelope примерно такого смысла:

```json
{
  "scan_id": "scan-...",
  "build_id": "build-...",
  "run_id": "run-...",
  "commit_sha": "...",
  "artifact_digest": "sha256:...",
  "scanner": "prettyk",
  "scanner_version": "...",
  "ruleset_version": "...",
  "findings": [
    {
      "fingerprint": "...",
      "fingerprint_scheme": "...",
      "title": "...",
      "severity": "Critical",
      "rule_id": "...",
      "type": "dast",
      "location": "...",
      "component": "...",
      "evidence_ref": "artifact://...",
      "qwen_suggestion": {
        "likely_false_positive": 0.94,
        "reason": "...",
        "model_version": "...",
        "model_suggestion_ref": "..."
      }
    }
  ],
  "evidence_refs": ["s3://..."],
  "verdict": "PASS|FAIL",
  "act_ref": "artifact://..."
}
```

Это смысловой пример, не финальная схема API. Имена, версия и обязательность
полей утверждаются отдельным контрактным request.

Обязательные связи:

```text
scan_id
build_id
release_id, если проверка релизная
artifact_digest, если есть artifact
fingerprint
evidence_ref
```

Если PrettyK отдаёт только summary, Gatekeeper не сможет честно вести triage.
Для управления нужны findings и occurrences, а не только число Critical.

---

## 6. Канонические модели Gatekeeper

### Finding

Одна логическая проблема:

```text
Finding
├── stable fingerprint
├── fingerprint scheme/version
├── title/description
├── severity
├── rule_id/type
├── component/location
└── current disposition
```

Одна и та же проблема не плодится при каждом новом scan.

### FindingOccurrence

Конкретное обнаружение:

```text
FindingOccurrence
├── finding_id
├── scanner
├── scan_id
├── build_id
├── run_id
├── release_id
├── commit_sha
├── artifact_digest
└── evidence_ref
```

Разные scanners могут создать разные occurrences одной Finding.

### TriageDecision

Неизменяемая история решения:

```text
TriageDecision
├── finding_id
├── decision
├── actor
├── role
├── reason
├── qg_effect
├── created_at
├── expires_at
├── approval
├── model_suggestion_ref
└── model_version
```

### GateEvaluation

Факт влияния конкретной Finding на конкретный Release:

```text
GateEvaluation
├── finding_id
├── release_id
├── policy/profile
├── effect: block|warn|allow
├── reason
└── evaluated_at
```

Finding status нельзя смешивать с GateEvaluation.

### Baseline

Снимок известных разрешённых находок:

```text
Baseline
├── project/application
├── release profile
├── finding fingerprint
├── approved disposition
├── owner
├── reason
├── expires_at
└── approval
```

---

## 7. Статусы и disposition

### Жизненный статус

```text
detected
acknowledged
in_progress
resolved
reopened
```

### Disposition

```text
open
false_positive
wont_fix
accepted_risk
suppressed
duplicate
```

`wont_fix` не удаляет находку. Он означает, что решение принято и действует по
определённой policy.

Для `wont_fix`, `false_positive` и `accepted_risk` нужны:

- reason;
- actor;
- timestamp;
- scope;
- expiry;
- approval, если требует policy;
- QG effect.

---

## 8. QWEN boundary

QWEN — suggestion engine:

```text
QWEN
  → likely_false_positive
  → reason
  → confidence
  → model_version
  → model_suggestion_ref
```

QWEN не может самостоятельно:

- удалить Finding;
- поставить финальный `false_positive`;
- поставить финальный `wont_fix`;
- разблокировать Release;
- изменить GateEvaluation.

```text
QWEN предлагает
→ человек принимает/отвергает
→ Admin IB approves Critical/High по policy
→ TriageDecision фиксируется
→ QG применяет решение
```

---

## 9. Baseline и постоянные Critical

Станция должна решать ситуацию с известными постоянными findings:

```text
known Critical
  → disposition + reason + owner + expiry + approval
  → baseline
```

Правила:

```text
new Critical
  → BLOCK

known approved baseline
  → не блокирует согласно policy

expired decision
  → REOPEN/BLOCK

изменившийся fingerprint/location/dataflow
  → REOPEN

developer proposal без нужного approval
  → не разблокирует Critical/High
```

Сканер не надо глобально глушить. Известная проблема должна оставаться видимой,
но перестать создавать бессмысленную вечную сирену.

---

## 10. QG Evaluation response

Gatekeeper отвечает Control Plane не только boolean-ом.

Пример смысла ответа:

```text
Release QG: BLOCK

New Critical: 1
New High: 2
Approved baseline: 16 Critical, 8 High
Expired decisions: 1
Missing Admin IB approval: 1

Ready for transfer: false
Blockers:
  - finding-...
  - expired-wont-fix-...
```

Cosmoport/PrettyK Control Plane только потребляет этот verdict и explanation.
Он не пересчитывает findings самостоятельно.

---

## 11. UI direction — стек пока не утверждать

Целевая рабочая поверхность:

```text
MUI Minimal UI → visual foundation
MUI X Data Grid → Findings Registry
Drawer/Page → Finding Detail
Cards/Charts → QG and findings dashboard
React Flow → secondary provenance/dependency view only
```

Тысячи findings не рисуются основным графом.

Пока не принимать окончательные решения по:

- framework;
- state management;
- charts library;
- table implementation details;
- object storage implementation;
- deployment topology.

Сначала contract, затем stack.

---

## 12. План запуска Gatekeeper

### Phase 0 — onboarding

- прочитать `captains_bridge.md`;
- прочитать `CONSTITUTION.md`;
- прочитать `MAXIM-PROFILE.md`;
- понять три слоя PrettyK;
- принять границы PO и workers;
- не менять канон без 2FA.

### Phase 1 — discovery

- изучить реальные PrettyK scanner outputs;
- найти существующие filtering/grouping/correlation механизмы;
- изучить QWEN false-positive suggestions;
- определить фактические SARIF/JSON/evidence exports;
- сформировать список неизвестных полей и вопросов.

### Phase 2 — contract draft

Подготовить friend-request с:

- Intake Envelope;
- Finding;
- FindingOccurrence;
- TriageDecision;
- GateEvaluation;
- Baseline;
- QWEN Suggestion;
- QG response;
- idempotency;
- versioning;
- evidence refs.

### Phase 3 — 2FA admission

Показать draft Keeper, Cosmo и Максиму. После sanity check положить request в:

```text
D:\prettyk-airlock\battlecruiser\friend\requests\
```

После тестового контракта и повторного 2FA перенести в `prettyk-hub` canon.

### Phase 4 — implementation slicing

Только после contract admission нарезать:

- Gatekeeper core;
- intake/normalizer;
- persistence;
- QWEN suggestion handling;
- triage/baseline/QG;
- UI;
- PrettyK integration;
- Control Plane consumer.

---

## 13. Copy-paste prompt для Gatekeeper

```text
Ты — Gatekeeper, PO и инженерная голова PrettyK Findings Control Station & QG
Triage в репозитории D:\prettyk-hub.

Твой Purpose:
  превратить сырые результаты PrettyK и approved scanners в каноническую
  операторскую систему Findings, triage, baseline, approvals и QG explanation.

Ты НЕ:
  - DAST execution engine;
  - замена PrettyK runtime;
  - release orchestrator Cosmoport;
  - владелец Project/Application/Build/Release;
  - параллельный источник release QG.

Канонический поток:
  PrettyK execution → intake → normalize/correlate →
  Finding/Occurrence → QWEN suggestion → human decision →
  TriageDecision → GateEvaluation → QG verdict → Control Plane.

Обязательные модели:
  Finding, FindingOccurrence, TriageDecision, GateEvaluation, Baseline.

QWEN только предлагает. Человек решает. Critical/High approval определяется
policy. Ни одна модельная suggestion не удаляет finding и не разблокирует release.

PrettyK и scanners общаются с тобой только через внешние contracts:
REST/webhook/SSE/SARIF/JSON/CycloneDX/object references.
Внутренние импорты PrettyK запрещены.

Сначала изучи реальные PrettyK outputs и существующие механизмы фильтрации,
группировки, correlation и QWEN. Не придумывай API по памяти.
Сначала напиши contract draft и список вопросов. Потом 2FA. Потом код.
``` 

---

## 14. Контрольный принцип

```text
PrettyK находит.
QWEN предлагает.
Разработчик объясняет.
Администратор ИБ утверждает, когда нужно.
Gatekeeper фиксирует.
QG объясняет.
Cosmoport принимает release verdict.
``` 
