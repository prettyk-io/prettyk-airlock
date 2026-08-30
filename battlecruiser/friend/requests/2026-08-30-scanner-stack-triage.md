# Scanner stack triage — canonical choices and low-priority candidates

> **Статус:** friend-request / first 2FA agreed  
> **Дата:** 30 августа 2026  
> **Участники:** Максим ↔ Cosmo  
> **Цель:** не превратить ЖЦ в зоопарк сканеров

## 1. Approved baseline

### KICS

```text
capability: iac_policy_scan
provider: KICS
```

Один baseline IaC scanner для PureK и Cosmoport. Применяется к Terraform,
Kubernetes, Helm, Docker Compose, Ansible и другим поддерживаемым конфигурациям.
Не запускается на каждом source repository без IaC.

### ClamAV

```text
capability: artifact_content_scan
provider: ClamAV
```

Один baseline malware/content scanner для PureK и Cosmoport. Применяется к
контейнерным filesystem, binary, archive и vendor artifacts. Не запускается как
антивирусный scan каждого исходного `.py`/`.ts` файла.

Оба решения approved по 2FA как направление default profiles, но production
admission требует pinned version, offline bundle, rules/signatures provenance и
targeted tests.

## 2. Canonical choice: SLSA vs in-toto

Это не два одинаковых scanner steps:

```text
SLSA    = требования и модель provenance
in-toto = формат/обёртка аттестации supply chain
```

Выбор:

```text
product capability: SLSA provenance
```

`in-toto` не показываем отдельным шагом ЖЦ и не считаем вторым обязательным
инструментом. Если реализация SLSA использует in-toto statement как wire format,
это внутренний технический формат, а не дополнительная бизнес-проверка.

## 3. Canonical choice: Syft vs CycloneDX

Это тоже разные уровни:

```text
Syft       = генератор SBOM
CycloneDX  = канонический формат SBOM
```

Выбор:

```text
product contract: CycloneDX
```

Syft не утверждается как отдельный обязательный продуктовый шаг. Генератор
может быть заменён при сохранении CycloneDX contract.

## 4. Candidates removed from active stack

Пока не тащим:

```text
Checkov
OPA/Conftest
YARA
```

Причина:

- Checkov дублирует KICS для текущего baseline;
- OPA/Conftest требует самостоятельного policy corpus и не является baseline scanner;
- YARA даёт custom threat-hunting value, но при наличии ClamAV и PrettyK сейчас
  нет обязательной бизнес-потребности.

## 5. Final chance — low priority candidates

### Semgrep

Потенциальный плюс: быстрые custom SAST rules и короткий feedback loop.
Минус: значительное пересечение с SonarQube. Не baseline.

### CodeQL

Потенциальный плюс: глубокий semantic/interprocedural SAST.
Минусы: ресурсы, базы, offline maintenance и licensing. Только будущий PureK
deep profile при доказанном language coverage gap.

### Grype

Потенциальный плюс: отдельный SBOM-centric vulnerability verifier.
Минус: пересечение с Trivy. Не запускать рядом без доказанной причины.

### cosign

Потенциальный плюс: независимая проверка подписи image перед Kubernetes pull,
что реально усиливает GAP supply-chain control.

Статус: единственный candidate, который может дать явное дополнительное
преимущество, но только после проверки key management, OpenBao, airgap и registry
support. Пока P2/P3, не baseline.

## 6. Release profiles: SonarQube + CodeQL

### PureK/PrettyK ordinary release

Обычный релиз PureK целевой модели включает оба source-code контроля:

```text
SonarQube + CodeQL
```

Они не дублируют друг друга полностью:

- SonarQube даёт общую картину качества, technical debt, coverage, bugs и
  quality gate;
- CodeQL даёт глубокий semantic/interprocedural dataflow analysis.

Вместе это жирный source-code profile.

### Cosmoport 2.0 ordinary release

Пока CodeQL bridge не готов, обычный релиз Cosmoport использует:

```text
SonarQube
```

CodeQL нельзя объявлять рабочим только потому, что он появился в DTO или UI.

### Cosmoport 2.0 security/regulatory profile

Целевой deep security/regulatory profile включает:

```text
SonarQube + CodeQL
```

CodeQL становится mandatory только после завершения bridge:

- licensing check;
- offline query/database bundle;
- supported languages;
- execution adapter;
- normalized result;
- Evidence/Gate integration.

### Development/non-release build

Нерелизная сборка — отдельный рабочий сценарий для разработчиков и тестировщиков.
Она не является Release, не входит в Project Release Batch и не квалифицирует
артефакт для перемещения по зонам.

```text
Development Build
  → выбранные приложения/карточки
  → список шагов-чекбоксов
  → оператор может отключать почти любой шаг
  → результат только для работы/отладки
```

Релизный flow другой:

```text
Release Type
  → immutable lifecycle snapshot
  → пользователь не меняет ЖЦ чекбоксами
  → QG/Gates/Evidence/Act
  → Release Package
```

Нерелизный и релизный Build должны быть различимы в API, БД и UI, чтобы debug-run
нельзя было случайно принять за квалифицирующий релиз.

## 7. Current recommended profiles

### Cosmoport / банк

```text
Source:
  Gitleaks
  SonarQube
  CodeScoring
  CycloneDX SBOM
  KICS if IaC exists
  SLSA provenance

Container:
  Hadolint
  CycloneDX SBOM
  Trivy
  ClamAV
  KCS last container scan
  KubeLinter for manifests
  PrettyK QG
```

### PureK

Тот же baseline, без Т1-Сферы, с возможностью позже добавить Semgrep, CodeQL,
Grype, cosign или YARA только как доказанные optional profiles.

## 8. Admission condition

До второго 2FA и targeted tests:

- KICS и ClamAV остаются approved implementation candidates;
- SLSA и CycloneDX — выбранные product contracts;
- Syft/in-toto не становятся отдельными steps;
- Checkov/OPA/YARA не возвращаются в baseline;
- Semgrep/CodeQL/Grype/cosign остаются low-priority candidates, кроме CodeQL в
  целевом security/regulatory профиле и PureK ordinary profile;
- ни один optional candidate не добавляется в обычный профиль без доказанной
  бизнес-ценности.
