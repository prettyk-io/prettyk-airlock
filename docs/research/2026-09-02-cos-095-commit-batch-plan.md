# COS-095 — Release Candidate Hygiene: план коммит-партий

> Дата: 2026-09-02 · PO: Cosmo · Executor: Apex (worker-сессия)
> Статус: **разметка готова; commit НЕ выполнялся** (ждёт явной команды Максима)
> База: `db17618 docs(cosmo): baseline cross-zone transfer approaches`
> Дерево: **197** строк `git status` — **194** в партиях + **3 WIP-COS094**
> (чужая in-flight работа Buddy) + test-results под .gitignore; покрыто
> разметкой 197/197 без пропусков и дублей (аудит:
> `D:\Infra\Temp\opencode\cos095_party_audit.py`, перезапускаемый; скрипт
> поймал появление COS-094 WIP в живом дереве — работает).

## 0. Правила исполнения

- Каждая партия = один `git add` + один commit. Порядок — таблица ниже;
  после партий P02–P09 рекомендуется прогон `.\services\scripts\suite_gate.ps1`
  (или полный сет в scratch-PG) — хотя бы после P02 (схема), P08 (гвард-ядро)
  и P12 (wiring).
- Полный сет на момент разметки: **2312 passed / 2 skipped / 0 failed**
  (scratch-PG `cosmo_test_apex`, ×2 детерминированно).
- ⚠️ **P02 содержит правки уже применённых миграций** (COS-062 schema
  reconciliation: индексы в initial + builds/deployments + post_luna_001).
  Это осознанное решение COS-062 (схема reconcile до первого релизного
  тега); если канон изменится — партию переработать до commit.
- ⚠️ **WIP-COS094 (не коммитить в рамках этого плана):**
  `services/Caddyfile`, `frontend/nginx.conf`,
  `orchestrator/tests/cosmo/test_prod_edge_config.py` — in-flight сессия
  Buddy (COS-094 airgap/edge), nginx.conf правился 02.09 23:17, тест
  создан 23:23. Эти файлы исключены из P10/P11. Дополнительно ⚠️
  `services/docker-compose.yml` (mtime 02.09 11:35) может содержать
  airgap-профиль COS-094 — перед коммитом P10 сверить diff с Buddy.
  После приёмки COS-094 добавить партию (или расширить P10) и обновить
  аудит-скрипт.

## 1. Партии (порядок = рекомендуемый порядок коммитов)

| # | Партия | Файлов | `git add ...` | Предлагаемое commit-сообщение | Владелец поверхности |
|---|---|---:|---|---|---|
| 1 | **P02-migrations** | 12 | `alembic.ini alembic/ env-файлы версий (см. примечание)` `orchestrator/cosmo/db/migration_verifier.py orchestrator/tests/cosmo/test_migrations.py orchestrator/tests/cosmo/test_migration_reconciliation.py` | `feat(cosmo): migration chain — releases/transfer/notification tables, schema reconciliation, verifier (COS-055/062/078/089)` | Luna/PO |
| 2 | **P04-notifications** | 18 | `orchestrator/cosmo/notifications/ orchestrator/cosmo/db/models_notifications.py orchestrator/cosmo/api/routes/notifications.py orchestrator/tests/cosmo/test_email_adapter.py orchestrator/tests/cosmo/test_notification_*.py` | `feat(cosmo): durable notification manager — outbox, email adapter, workers, triggers (COS-055/065/084)` | **Flash** |
| 3 | **P03-transfer** | 12 | `orchestrator/cosmo/transfer/ orchestrator/cosmo/api/routes/transfer.py orchestrator/cosmo/db/models_transfer.py orchestrator/cosmo/db/transfer_registry_repo.py orchestrator/tests/cosmo/test_transfer_*.py orchestrator/tests/cosmo/test_offline_*.py` | `feat(cosmo): cross-zone transfer subsystem — kernel, registry, durable API, lease recovery, security matrix (COS-054/066/074/077)` | Luna/PO |
| 4 | **P05-evidence-gate-trail** | 9 | `orchestrator/cosmo/ledger/evidence_anchor.py orchestrator/cosmo/ledger/evidence_writer.py orchestrator/cosmo/ledger/evidence_chain.py orchestrator/cosmo/db/gate_trail_repo.py orchestrator/cosmo/db/models_gate_trail.py orchestrator/cosmo/api/routes/evidence.py orchestrator/tests/cosmo/test_evidence_anchor.py orchestrator/tests/cosmo/test_gate_trail_durable.py orchestrator/tests/cosmo/test_evidence_verification.py` | `feat(cosmo): evidence hardening — head anchor, durable writer, gate decision trail (COS-081/082/087)` | Luna |
| 5 | **P06-sfera-providers** | 10 | `orchestrator/cosmo/adapters/sfera_provider.py orchestrator/cosmo/adapters/provider_capability.py orchestrator/cosmo/adapters/provider_matrices.py orchestrator/cosmo/adapters/provider_result_mapping.py orchestrator/cosmo/adapters/fake_providers.py orchestrator/cosmo/adapters/tls_config.py orchestrator/tests/cosmo/test_sfera_adapter.py orchestrator/tests/cosmo/test_provider_capability.py orchestrator/tests/cosmo/test_provider_conformance.py orchestrator/tests/cosmo/test_tls_config.py` | `feat(cosmo): sfera adapter + provider capability matrix, offline alignment, TLS config (COS-049/060/069)` | Luna |
| 6 | **P07-sse** | 4 | `orchestrator/cosmo/api/sse_backlog.py orchestrator/cosmo/api/sse_tickets.py orchestrator/cosmo/api/routes/sse.py orchestrator/tests/cosmo/test_sse_backlog.py` | `feat(cosmo): SSE backlog + ticket sessions (COS-063/065)` | Flash |
| 7 | **P08-guards-auth** | 25 | `orchestrator/cosmo/api/deps.py orchestrator/cosmo/api/domain_guard.py orchestrator/cosmo/domain/rbac.py orchestrator/cosmo/api/routes/{apps,builds,deployments,gates,pipelines,projects,releases,repos,runs}.py orchestrator/tests/cosmo/test_deps_guard_regression.py orchestrator/tests/cosmo/test_domain_resolve_invariant.py orchestrator/tests/cosmo/test_surface_auth_regression.py` + fallout-тесты (см. примечание b) | `feat(cosmo): capability guards 1-4 — granular RBAC, unified domain resolve, opaque-bearer reject, in-body auth unification (COS-083/085/086/091)` | Apex |
| 8 | **P09-test-infra** | 15 | `orchestrator/tests/cosmo/_testpg.py orchestrator/tests/cosmo/integration/ orchestrator/tests/cosmo/conftest.py orchestrator/cosmo/db/session.py services/docker-compose.test-pg.yml services/scripts/cleanup_scratch_pg.py services/scripts/suite_gate.ps1 services/scripts/runtime-gate.ps1 orchestrator/tests/cosmo/test_api_routes.py orchestrator/tests/cosmo/test_cbr_luna_001_matrix.py orchestrator/tests/cosmo/test_int_012_013_016_steel_thread.py orchestrator/tests/cosmo/test_int_registry_smoke.py orchestrator/tests/cosmo/test_metrics_trends.py orchestrator/tests/cosmo/test_status_dashboard.py orchestrator/tests/cosmo/test_steel_thread.py` | `test(cosmo): isolated session PG, scratch janitor, suite gate, integration harness (COS-073/076/078/080/089)` | Apex/PO |
| 9 | **P10-services-infra** | 13 | `services/docker-compose.yml services/entrypoint.sh services/.env.example services/postgres-init/ services/scripts/HARDENING_CHECKLIT.md services/scripts/daily-backup.ps1 services/scripts/daily-backup.sh services/scripts/verify-hardening.ps1 services/scripts/verify-hardening.sh services/scripts/cosmo-start.ps1 services/scripts/cosmo-stop.ps1 services/scripts/smoke-delivery.ps1 services/scripts/stand-lock.ps1` ⚠️ перед коммитом сверить diff docker-compose.yml с Buddy (возможен airgap COS-094) | `chore(services): stand lifecycle, backup/hardening scripts, postgres-init, env example (Buddy surfaces)` | **Buddy** |
| 10 | **P11-frontend** | 13 | `.gitignore frontend/package.json frontend/package-lock.json frontend/src frontend/e2e frontend/playwright.config.ts frontend/Dockerfile` — ⚠️ НЕ `git add frontend` целиком: втянет WIP `nginx.conf` (COS-094) | `feat(frontend): notification ops panel, e2e playwright, station wiring (COS-064/084); ignore test artifacts` | **Flash** |
| 11 | **P12-core-wiring** | 12 | `orchestrator/cosmo/api/main.py orchestrator/cosmo/api/startup.py orchestrator/cosmo/api/health.py orchestrator/cosmo/db/models.py requirements.txt orchestrator/cosmo/api/routes/{artifacts,audit,domains,findings,metrics,status,release_batches}.py` | `feat(cosmo): app wiring — router registration, startup/health ready semantics, model registry, valkey dep (COS-050..090 cross-cutting)` | PO |
| 12 | **P01-docs** | 50 | `AGENTS.md docs/` | `docs(cosmo): backlog, research acceptances COS-049..095, openapi, deployment, canon updates` | PO |

Примечания:
- a) В `git add alembic/` входят и 4 новых версии (b8c9d0e1f2a3,
  c1d2e3f4a5b6, d2e3f4a5b6c7, e4f5a6b7c8d9) — они в той же партии, чтобы
  цепочка миграций была атомарной.
- b) Fallout-тесты P08 (правки из guard-карточек): `test_final_luna_001.py`,
  `test_lr_persist_api_visiblity.py`, `test_nx_luna_integration.py`,
  `test_post_luna_001_semantic_boundary.py`, `test_rbac.py`,
  `test_rbac_regression.py`, `test_release_envelope.py`,
  `test_sanitary_rbac.py`, `test_security_perimeter_negative.py`,
  `test_sod_and_transfer_linear.py`.
- c) Пересечения поверхностей (файл трогали несколько карточек) сведены в
  одну партию по доминирующему владельцу: `gates.py` (COS-081 trail +
  COS-083 guard) → P08; `releases.py` (transfer + guards + mode="json") →
  P08; `routes/evidence.py` → P05. Hunk-сплит не предлагается — партии
  остаются читаемыми.
- d) `.gitignore` дополнен (`frontend/test-results/`,
  `frontend/playwright-report/`) — 35 Playwright-артефактов COS-064 больше
  не светятся в status и не попадут в commit случайно.

## 2. Test-tails — закрытие

1. **Skipped (2, оба легитимные environmental opt-in):**
   `test_int_registry_smoke.py:52` (`[local-oci] Registry offline`) и
   `:136` (`NEXUS_REGISTRY_ENDPOINT not set`). Это integration-smoke против
   живых registry-эндпоинтов: в офлайне пропуск — задуманный контракт
   (не fail в airgap). Владелец не требуется; при необходимости точечного
   прогона — поднять registry / задать переменную.
2. **Janitor SIGKILL-хвост** — команда ручной очистки **уже
   задокументирована** в `docs/DEPLOYMENT.md` (Gate G, COS-089):
   `python services\scripts\cleanup_scratch_pg.py [--apply]`; проверено —
   секция актуальна (prefix-безопасность, guard на dev-порт 5432).

## 3. transfer model_dump(mode="json") — унификация

`releases.py`: transfer v1 и transfer-v2 переведены на
`model_dump(mode="json")` (единообразие с approve/reject после COS-091).
Полный сет после правки: **2312 passed / 2 skipped / 0 failed**.

## 4. Coverage-аудит

`D:\Infra\Temp\opencode\cos095_party_audit.py` (перезапускаемый перед
каждым коммит-раундом): каждая строка `git status --porcelain` попадает
ровно в одну партию, WIP-бакет или excluded; `RESULT: OK`, 197/197.
Если Максим коммитит постепенно — аудит покажет только ещё не
закоммиченное. Живой скрипт также детектирует появление чужих WIP-файлов
(уже поймал COS-094 в-flight) и зафейлит разметку при расширении чужой
поверхности — тогда партии обновлять до коммита.
