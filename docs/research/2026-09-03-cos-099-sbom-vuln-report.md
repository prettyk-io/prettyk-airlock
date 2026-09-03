# COS-099 — SBOM & Vulnerability Report в release bundle

> Исполнитель: Apex. Дата: 2026-09-03. Зависимости: COS-053 (Transfer kernel: PackageBuilder/PreTransferValidator/landing), COS-109/126 (DigitalReleaseEnvelope + AirgapReleaseBundle), COS-126 (envelope artifacts digest).

## 1. Постановка

Карточка PK-C-003.6: PackageBuilder генерирует машиночитаемый SBOM
(SPDX/CycloneDX via syft) и vulnerability report (grype), digests пиннятся в
манифест с tamper-proof проверкой при landing; 100% offline-ready. Out of
scope: live NVD/OSV enrichment.

## 2. Ключевые находки исследования

1. **Transfer kernel уже хеширует манифест**: `PackageRevision.compute_manifest_sha256`
   — детерминированный SHA-256 canonical JSON. Пин дайджестов внутри
   `manifest["security"]` автоматически становится tamper-evident: модификация
   пина ломает manifest checksum и ловится существующим `MANIFEST_CHECKSUM_MISMATCH`.
2. **COS-126 уже хеширует байты артефактов при импорте бандла**:
   `AirgapReleaseBundle.import_and_verify` пересчитывает sha256 каждого артефакта
   против `envelope.artifacts_digest`. Третий слой tamper-evidence достался бесплатно.
3. **CycloneDX — единый SBOM-контракт** (build_modes: "SLSA is sole provenance,
   CycloneDX is sole SBOM contract"); internal-генератор `ScanProfileEngine.cyclonedx_sbom`
   существует, но не покрывает деревья — нужен парсер dependency-манифестов.
4. **syft/grype в airgap — опциональны**: бинарника на стенде нет. Контракт:
   честный fallback (internal parser / source="none" с reason), никогда фейковый
   отчёт; grype без сети (GRYPE_DB_AUTO_UPDATE=false, GRYPE_DB_VALIDATE_AGE=false,
   GRYPE_DB_CACHE_DIR на offline-снапшот).
5. **ArtifactPlane.SBOM** уже есть в контракте transfer — TransferItem со SBOM
   легитимен без изменений контракта.

## 3. Реализация

### 3.1. `transfer/sbom.py` (новый, self-contained)

- **`generate_sbom(target, *, syft_path, runner, timeout)`**: syft CLI
  (`syft <target> -o cyclonedx-json`); инъекция runner'а для тестов
  (если runner задан, а бинарник не резолвится — exe="syft", делегирование);
  любой сбой (нет бинарника, timeout, non-zero, не-CycloneDX вывод) →
  internal fallback с warning.
- **Internal parser** (airgap fallback): обход дерева (prune .git/node_modules/
  venv/dist/build, depth≤6, ≤500 файлов) с парсерами requirements*.txt
  (`==/>=/~/…`), pyproject.toml (tomllib: [project].dependencies +
  [tool.poetry.dependencies]), package.json (dependencies+devDependencies).
  Дедуп по (ecosystem, name), сортировка → детерминированный components-набор.
  Документ: CycloneDX 1.5, serialNumber = urn:uuid(sha256 контента),
  components с purl (`pkg:pypi/name@ver`, `pkg:npm/name@ver`).
- **`generate_vuln_report(sbom_document, *, grype_path, db_dir, runner)`**:
  SBOM во временный файл → `grype sbom:<file> -o json` c offline-env; сбой →
  `{"status": "unavailable", "reason": stderr-tail}` и `source="none"` —
  отсутствие отчёта не маскируется.
- **Pins**: `SBOMPin{format, source, tool_version, ref, sha256}`,
  `VulnReportPin{source, tool_version, ref, sha256, reason}`,
  `SecuritySection{sbom, vulnerability_report}` (pydantic Strict).
  `extract_security(manifest)` — толерантное чтение.
- **`build_secured_package(...)` facade**: generate_sbom → generate_vuln_report →
  `PackageBuilder.build_item(artifact_plane=SBOM, package_mode=FULL_PACKAGE,
  payload_refs=[sbom/cdx.json], security=SecuritySection)`.
- **`envelope_artifacts_from_security(sec, payload_bytes)`** → envelope-записи
  (`artifact_type="sbom" | "vulnerability_report"`) для `seal_envelope(artifacts=...)`.

### 3.2. `transfer/builder.py`

- `build_manifest`/`build_item` — опциональный `security` (dict | pydantic):
  манифест получает `manifest["security"]` **до** вычисления checksum.
- `rebuild_with_revision` сохраняет security-секцию (payload_refs те же →
  SBOM валиден для новой revision).
- `PreTransferValidator.validate` — check 7: sanity пинов
  (`SECURITY_DIGEST_MALFORMED` — sha256 не hex64;
  `SECURITY_REF_NOT_IN_PAYLOAD` — pinned ref не в payload_refs при FULL_PACKAGE).
- **`validate_with_artifacts(item, payload_bytes, *, envelope_artifacts=None)`** —
  source-side tamper-проверка: sha256 фактических байтов против пина;
  `SECURITY_PAYLOAD_MISSING` / `SECURITY_PAYLOAD_DIGEST_MISMATCH` (CHECKSUM_MISMATCH) /
  `SECURITY_ENVELOPE_DIGEST_MISMATCH` (сверка с COS-126 envelope artifacts,
  без импорта ledger — duck-typed список dict'ов).

### 3.3. `transfer/landing.py`

- **`LandingStateMachine.receive_and_verify(payloads: dict[str, bytes])`** —
  target-side tamper-evidence: NOT_RECEIVED → RECEIVED → проверка
  (manifest checksum; `sbom_digest` — sha256 фактических байтов против пина;
  `vulnerability_report_digest` при pinned grype) → VERIFIED | CHECKSUM_MISMATCH.
  Несовпадение → `requires_new_revision()` (existing semantics), reasons
  содержат "modified SBOM". Повторный вызов → LandingStateError.

### 3.4. Итоговая модель tamper-evidence (три слоя)

1. **manifest checksum** (PackageRevision): пины не подменить без разрыва checksum;
2. **payload bytes** (validator source-side / landing target-side): байты не
   подменить без разрыва пина;
3. **envelope digest** (COS-126 bundle import): байты не подменить без разрыва
   подписи конверта.

## 4. Тесты (+33, `test_transfer_sbom.py`)

- Схема CycloneDX 1.5, три экосистемы, prune node_modules, дедуп, digest =
  sha256 canonical JSON, single-file target, пустое дерево.
- syft wrapper: инъекция runner'а (cmd содержит syft/target/cyclonedx-json);
  failure/OSError/не-CycloneDX/timeout → internal fallback с warning; нет
  бинарника и runner'а → internal.
- grype: offline-env утверждается (AUTO_UPDATE=false, VALIDATE_AGE=false,
  DB_CACHE_DIR), честный none при отсутствии/сбое, pin успешного скана.
- Pinning: валидный item проходит validate; revision checksum покрывает
  security (подмена пина ломает checksum); модифицированные байты →
  SECURITY_PAYLOAD_DIGEST_MISMATCH; missing payload; ref-not-in-payload;
  malformed digest; envelope cross-check.
- Landing: success → VERIFIED; модифицированный SBOM → CHECKSUM_MISMATCH +
  requires_new_revision + "modified SBOM" в reasons; missing payload;
  double receive → LandingStateError; tamper манифеста ловится.
- Airgap roundtrip: seal_envelope + export/import — intact OK, подменённые
  SBOM-байты в ZIP отвергаются bundle-верификацией.
- Offline-гигиена: модуль без urllib/requests/httpx/socket.

Верификацией пойманы и исправлены: разные порядки таплов у парсеров
(`pkg:gunicorn/21.2.0@pypi` в single-file ветке), двойная упаковка payload
в тестах, отсутствие вызова injected runner'а при нерезолвленном бинарнике.

## 5. Результаты

- Полный сет: **2559 passed / 8 skipped / 0 failed** (3:12), против
  COS-101-бейслайна 2526/8/0 → +33.
- Смежные сеты transfer/envelope/build-modes: 302 passed.

## 6. Открытые вопросы / follow-up

1. **Живой smoke syft/grype**: на стенде бинарников нет; wrapper-контракты
   покрыты fake-runner'ами. Первый живой прогон — при появлении syft/grype
   в airgap-образе (runtime-приёмка).
2. **SPDX-формат**: карточка упоминала SPDX JSON как альтернативу; канон
   проекта — CycloneDX sole SBOM contract, поэтому сгенерация — CycloneDX only.
3. **Точка вызова в build pipeline**: `build_secured_package` готов к вызову
   из release-оркестрации (шаг "sbom" в SOURCE/DOCKER профилях) — связующий
   шаг отдельной карточкой при необходимости.
