# COS-171 / COS-172 — боевой trivy + syft в скане-раннере cosmo-api

> Owner: Boss (ре-диспатч из Flash). Статус: **исполнено — ждёт коммита Максима**.
> Repo: `D:\prettyk-airlock`. Дата: 2026-09-23 → 2026-09-24.

## Задача (словами пакета)

В образ `cosmo-api` ставятся боевые `trivy` (с offline DB) и `syft`. Итог:
`run_trivy_scan` на реальном образе отдаёт `source='trivy'` (не `unavailable`),
SBOM снимается `syft`'ом с `generator=syft` (не `python-inventory`). Оба бинаря
+ trivy-DB попадают в airgap-бандл.

## Рекон (что уже есть в коде — НЕ переписывать)

| Путь | Что делает | Плагин (plumbing) для этой карточки |
|---|---|---|
| `ledger/artifact_scan_gate.py::run_trivy_scan` | `trivy image --skip-db-update --format json <ref>`; честный `source='none'` при отсутствии бинаря | добавить `--cache-dir` + точечный `--insecure` для `cosmo-registry-zr:5000` |
| `ledger/artifact_sbom.py::generate_artifact_sbom` → `generate_sbom_inventory` → `_generate_syft_document` | `syft <target> -o cyclonedx-json`; fallback `python-inventory` | передать insecure для HTTP-registry |
| `ledger/sbom_inventory.py::generate_sbom_inventory` | syft → python-inventory; grype-визор (остаётся `available=false`) | plumbing insecure |
| `domain/sbom_inventory.py` | DTO: `generator` ∈ {`syft`,`python-inventory`} | без правок |
| `adapters/registry_per_zone.py` | `REGISTRY_ZR_ENDPOINT` env → `http://localhost:5100` (host) / `http://cosmo-registry-zr:5000` (docker) | источник host-имени для insecure-allowlist |
| `domain/artifact_record.py::qualified_image()` | `<registry>/cosmoport/zr/<name>` | целевой ref: `<qualified>@sha256:…` |

Scan-код правится **только ради plumbing (cache-dir / insecure)**. Логика гейтов,
digest-сверки, порогов, `parse_trivy_report`, `verify_and_attest_trivy_gate`,
`trivy_blocker_for_records` — не трогаются.

## Рекон окружения (проверено)

- Docker 29.6.2 — вверх; `cosmo-registry-zr` (distribution:3.1.0) слушает `:5100`, `/v2/` → 200.
- `cosmo-api` контейнер работает (`cosmo-api:local`, `:8100`), `cosmo-postgres` `:5432`.
- На хосте `trivy`/`syft` **отсутствуют** — ставятся внутрь образа.
- Живой образ запушен: `localhost:5100/cosmoport/zr/cosmo-testapp:0.1.0` (digest `sha256:59903d44…`).

## План исполнения

### A. Code plumbing (детерминированно, без сети/Docker)

1. `ledger/artifact_scan_gate.py::run_trivy_scan`:
   - `--cache-dir <dir>` из env `TRIVY_CACHE_DIR` (default `/root/.cache/trivy`), без смены `--skip-db-update`;
   - точечный `--insecure` — только если host `image_ref` ∈ allowlist `INSECURE_REGISTRY_HOSTS` (default `cosmo-registry-zr:5000`), иначе обычный вызов.
2. `ledger/artifact_sbom.py` / `ledger/sbom_inventory.py::_generate_syft_document`:
   - проброс registry-insecure для allowlist-хоста (syft), аналогично точечно.
   - ⚠️ syft НЕ имеет `--insecure-skip-tls-verify` (это grype). Реальный механизм —
     env `SYFT_REGISTRY_INSECURE_USE_HTTP=true`, ставится ТОЛЬКО если host `target`
     ∈ allowlist.
3. Юнит-тесты (mock `subprocess.run`): аргументы команды (наличие/отсутствие `--cache-dir`, `--insecure` только для allowlist), negative (бинарь/DB убран → честный `unavailable` / `python-inventory`).

### B. Образ + compose (требует версии бинарей + сеть)

4. `services/cosmo-api.Dockerfile`:
   - скачать trivy + syft фикс. версии, digest-pin, в `PATH`;
   - `RUN trivy image --download-db-only` (или `trivy --cache-dir … --download-db-only`) → предзагрузить offline DB в образ (0 сетевых загрузок в ран-тайме);
   - `ENV TRIVY_CACHE_DIR=… TRIVY_INSECURE=…` (точечно через allowlist, не глобально).
5. `services/docker-compose.yml` (cosmo-api): env `TRIVY_CACHE_DIR`/`INSECURE_REGISTRY_HOSTS` + volume под DB-кэш.
6. Rebuild `cosmo-api:local`, поднять, прогнать реальный скан + SBOM против registry-zr.

### C. Airgap

7. `services/scripts/airgap-bundle.ps1`: секция `tools/` — trivy+syft бинари + trivy-DB snapshot в бандл и в `manifest.json`.

### D. Live smoke (opt-in, self-skip оффлайн как COS-166)

8. Focused-юнит (бинарь/DB/insecure)+ live smoke `cosmo-testapp:0.1.0` → `source='trivy'`, `generator=syft`, durable-read после рестарта.

## Открытые решения (нужно от максим/диспетчера)

1. **Версии бинарей** (digest-pin). Рекомендация: trivy `v0.59.1`, syft `v1.20.0` (последние стабильные; можно ужесточить).
2. **Разрешён ли сейчас сетевой download** trivy-DB (~сотни МБ) + сборка образа, или только plumbing?
3. **Insecure-механизм**: env-allowlist `INSECURE_REGISTRY_HOSTS` (рекомендую) vs хардкод `cosmo-registry-zr:5000`.

## Приёмка (маппинг на тесты)

- `trivy --version` / `syft version` в контейнере — smoke.
- `run_trivy_scan` → `source='trivy'`, findings реальные — smoke.
- SBOM `cosmo-testapp:0.1.0` → `generator=syft`, CycloneDX 1.5, `sbom_ref`, GET после рестарта — smoke + unit.
- Negative: registry/бинарь/DB убраны → честный `unavailable`/`python-inventory`, не 5xx — unit.
- airgap-бандл несёт оба бинаря + DB; `suite_gate` без регрессий.

## Результат (2026-09-24, live smoke из контейнера)

| Проверка | Факт |
|---|---|
| Версии | `trivy 0.74.0` (DB v2), `syft 1.20.0` (`Application: syft`) |
| sha256-пин | trivy `2ae6fe3e…` / syft `689e12c5…` — проверены в Dockerfile на сборке |
| Offline DB | `/var/lib/trivy/db/trivy.db` = 1.4G, seed из `/opt/trivy-db-seed.tar.gz` (entrypoint идемпотентный) |
| TRIVY_CACHE_DIR | единый: build `--cache-dir` == `ENV` == volume compose (`/var/lib/trivy`) |
| Insecure trivy | `--insecure` только для allowlist `INSECURE_REGISTRY_HOSTS` (в `registry_policy.py`) |
| Insecure syft | env `SYFT_REGISTRY_INSECURE_USE_HTTP=true` только при `allows_insecure(target)` (в `_generate_syft_document`) |
| Live scan | `run_trivy_scan("cosmo-registry-zr:5000/cosmoport/zr/cosmo-testapp:0.1.0")` → `source=trivy`, **203 findings** |
| Live SBOM | `generate_sbom_inventory(...)` → `generator=syft`, **2820 components**, CycloneDX |
| Negative trivy | `cache_dir=/tmp/empty` → `source=none`, `available=False`, честный reason |
| Negative syft | unreachable host → `None` → `generator=python-inventory`, честный `warnings` |
| Suite gate | `pytest orchestrator/tests/cosmo/` → **3476 passed, 16 skipped, 0 failed** |

### Найденный и закрытый баг (syft plumbing)

Прежний `_generate_syft_document` ставил `--insecure-skip-tls-verify` (флаг grype,
которого нет у syft) и только при `"://" in target` (реф `cosmo-registry-zr:5000/…`
схемы не имеет) — syft падал на HTTPS→HTTP и молча уходил в python-inventory.
Исправлено: env `SYFT_REGISTRY_INSECURE_USE_HTTP` по allowlist; argv без лишних
флагов. Покрыто 3 юнитами в `test_sbom_inventory.py::TestGenerateSyftDocument`.

### Blocker'ы / open

- Коммит + push — по команде Максима (не выполняю без явного разрешения).
- `grype` НЕ входит в scope COS-171/172 — `vuln_summary.available=false` (честно).