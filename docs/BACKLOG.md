# Бэклог Cosmoport 2.0

> **Ты:** Cosmo. **Исполнители:** Boss, Flash, Luna, Buddy.
> **Легенда:** 🔄 в работе · ⬜ ready · ✅ done · ❌ cancelled

---

## ⬜ READY — SFERA / PROVIDER BOUNDARY WAVE

| ID | Кто | h | Приоритет | Зависимость | Результат |
|---|---|---:|---|---|---|
| **COS-050** | Boss | 8-10h | P0 | COS-049 (discovery input, не blocker) | Provider-neutral TransferItem/TransferPlan contract, package modes и 3 transport profiles |
| **COS-053** | Boss | 12-16h | P0 | COS-050 | PackageBuilder + PreTransferValidator + LandingCheckReport + target landing state machine |
| **COS-052** | Luna | 10-14h | P1 | COS-050 | Harbor/Nexus/MinIO/Git provider capability matrix и adapter test fixtures; без третьего registry |
| **COS-054** | Luna | 10-14h | P1 | COS-053 | Offline importer и vendor-neutral DiodeAdapter: spool/chunk/resume/status без физического diode |
| **COS-049** | Luna | 6-8h | P3 | — | Sfera/ДиБ discovery evidence, legacy source-code map и redacted-contract checklist без выдуманных endpoints |
| **COS-051** | Luna | 10-14h | P3 | COS-050 | Optional SferaProviderAdapter: area/repository provisioning, raw/OCI push-pull и contract tests; live OpenAPI verification отдельно |

### Порядок

1. COS-050 замораживает внутреннюю границу Cosmoport и не зависит от конкретной
   Sfera implementation.
2. COS-053 реализует общий package/landing kernel после контракта; он не зависит
   от конкретного Sfera provider.
3. COS-052 и COS-054 развивают самостоятельную provider/airgap линию.
4. COS-049 остаётся низкоприоритетным discovery item: он находится в backlog,
   но не блокирует общий transfer kernel. Legacy backend уже дал первичную карту
   Sfera API и release flow; продолжение ждёт tool/API access.
5. COS-051 не блокируется отсутствием vendor OpenAPI: legacy client даёт базовый
   push/pull/provisioning contract. Live OpenAPI нужен для verification и
   расширенных операций, а не для старта adapter seam.
6. Sfera в Cosmoport может оказаться optional artifact provider (raw/OCI/package)
   и/или transfer bridge; SOD, Portal events и Sfera artifact API не смешиваем.

---

## ✅ CLEANUP WAVE — ВСЕ 13 КАРТОЧЕК ЗАКРЫТЫ (100%)

| ID | Кто | h | Результат |
|---|---|---|---|
| **CLN-001** | Flash | 2h | Колонки исправлены, Vault Path и хардкод-контакты вырезаны |
| **CLN-002** | Flash | 1h | Evidence mockEntries удалены → честный EmptyState |
| **CLN-003** | Flash | 3h | DEFAULT_RELEASES удалены, клиентские хэши-подписи убраны |
| **CLN-004** | Flash | 2h | PipelineStudio setInterval удалён, честный POST /runs |
| **CLN-005** | Flash | 2h | DeepLinker fix + plan-steel убран |
| **CLN-006** | Flash | 2h | api.ts .catch(()=>[]) удалены, честные ошибки |
| **CLN-007** | Luna | 2h | SoD в create_gate: HTTP 409, 10/10 тестов |
| **CLN-008** | Boss/Luna | 1h | Линейный трансфер: ZR→ZPE запрещён → HTTP 400 |
| **CLN-009** | Buddy | 4h | E2E-скрипт 8 фаз |
| **CLN-010** | Buddy | 3h | CI regression gate в GitHub Actions |
| **CLN-011** | Luna | 3h | Негативные тесты SoD + трансфер |
| **CLN-012** | Luna | 2h | Аудит API: 0 хардкод-ответов |
| **CLN-013** | Luna | 2h | Финальный вердикт: **1222 passed, 39 passed, 0 failed** |

> **Acceptance:** Cleanup Wave принята как завершённая. Следующее направление
> открыто отдельно: Sfera/ДиБ — Cosmoport bridge; Harbor + Nexus + MinIO/S3 + Git
> — PureK provider baseline. Artifactory и собственный registry не открываются.