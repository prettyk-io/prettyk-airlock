# COS-049 — Sfera/ДиБ discovery evidence + redacted-contract checklist

> **Дата:** 2 сентября 2026. **Исполнитель:** Luna. **Карточка:** BACKLOG.md
> COS-049 (P3, 6-8h, без зависимостей).
> **Правило карточки:** без выдуманных endpoints. Каждый пункт чеклиста
> ссылается на код-подтверждённую карту (`2026-09-02-legacy-sfera-contract-map.md`,
> принятая как SoT в COS-068) либо честно помечен UNKNOWN-до-live.

## 1. Discovery evidence pack (что уже собрано)

COS-049 собирает уже произведённые и верифицированные evidence-артефакты в
один контур и закрывает недостающее звено — checklist. Состав пака:

| Артефакт | Роль | Статус |
|---|---|---|
| `docs/research/2026-09-01-sfera-openapi-and-registry-boundary.md` | Discovery: локальный browser-scrape `Sfera_OpenAPI` (`D:\cosmo\cosmo-frontend-to-scrape\Sfera_OpenAPI`) с `https://sfera.apps.dh5.dev.ppod.cbr.ru/ppdl/administration/openapi` — подтверждает существование операторской API-поверхности; machine-readable контракт из него НЕ извлекается (minified UI, не спека) | принят |
| `docs/research/2026-09-02-legacy-sfera-contract-map.md` | Legacy source-code map: 7 файлов legacy backend прочитаны полностью, 14 REST-эндпоинтов + OCI push/pull — каждый с ссылкой файл:строка; транспорт/auth (login Bearer / registry Basic split / Keycloak ТУЗ / PPAM); TLS-девиация legacy; naming; provisioning-оркестрация с rollback; UNKNOWN-список | принят (COS-068) |
| `docs/research/2026-09-02-cos-069-sfera-adapter-alignment.md` | Adapter выровнен с картой: auth split, клиентский digest, naming, ALREADY_EXISTS-идемпотентность, таймаут-профиль; micro-PR матрицы применён с тестами | принят |
| `orchestrator/cosmo/adapters/provider_matrices.py::sfera_matrix` | 18 capabilities, честные UNKNOWN/UNSUPPORTED, все notes с evidence-ссылками | COS-052/069 |
| `docs/research/2026-08-31-legacy-transfer-interview-brief.md` §E | Формат evidence-чеклиста для встречи (перенос СОД — соседний контур, НЕ Sfera API) | 2026-08-31 |

Ключевой факт discovery: **Sfera CORE OpenAPI существует как операторская
страница** (`/ppdl/administration/openapi`), но локально есть только HTML-scrape
с microfrontend bundles — не экспорт JSON/YAML. Отсюда все CONFIRMED-статусы
adapter'а блокируются live-верификацией (карта §9, ниже §3 чеклиста).

## 2. Redacted-contract checklist (основной deliverable)

### 2.1 Что запросить у команды Сферы/ДиБ (разрешённые, redacted артефакты)

| # | Артефакт | Зачем | Красная линия |
|---|---|---|---|
| A1 | OpenAPI JSON/YAML export с версией и base URL (`administration/openapi` — UI-страница существует: scrape 2026-09-01) | machine-readable сверка карты §3 с официальной спекой | без токенов/реальных хостов |
| A2 | Auth/TLS/private CA scheme + scope/role matrix | закрыть split-факт: Bearer (REST) vs Basic (registry push) vs Bearer (registry pull); КЦ-профиль для `tls_config` | без credentials, только схема |
| A3 | Redacted request/response: login, create_area, create_repository, raw upload, OCI blob/manifest | сверка §3/§4 карты: точные поля, заголовки, Content-Type | hosts/имена → плейсхолдеры |
| A4 | Error contract: точный HTTP-статус и тело `ALREADY_EXISTS_ERROR` для create_area/create_repository | идемпотентность уже смоделирована кодом (COS-069), нужно live-подтверждение кода ошибки и статуса | redacted body |
| A5 | Pagination tree endpoints: глубже `parentId` 1 уровня, totals, фильтры, сортировки | LIST-детали: сейчас UNKNOWN до OpenAPI | — |
| A6 | Quotas / storage stats (если есть) | QUOTA_REPORT UNKNOWN | — |
| A7 | Signatures / SBOM / attestations surface (если есть) | SIGNATURE_REF / SBOM_REF / ATTESTATION_REF | — |
| A8 | tag→digest resolve / promotion(копия) API — если существуют | RESOLVE_DIGEST / COPY_OR_PROMOTE UNKNOWN | — |
| A9 | Job/status lifecycle (если есть в Sfera CORE) | UNKNOWN до live | — |

Ничего из этого не придумано: A5–A8 дословно UNKNOWN-список карты §7 (кода в
legacy нет); A1–A5 закрывают §9 карты.

### 2.2 Live-верификация по код-подтверждённым эндпоинтам (только карта §2–§6)

| Чек | Источник (код) | Что подтверждает live | Критерий CONFIRMED |
|---|---|---|---|
| L1 login: `POST /api/auth/login` → token, 401→AuthenticationError | client.rb:47–57,341–353 | статус/тело 401, имя token-поля (access_token \| accessToken \| token) | redacted 401-ответ |
| L2 create_area idempotent-семантика: повтор → `ALREADY_EXISTS_ERROR`/«already exists»; точный HTTP-код и тело | establish_sfera.rb:125,160 | наш `_result_from_response(idempotent_conflict=True)` подтверждён на живом инстансе | один redacted 409/ALREADY_EXISTS |
| L3 create_repository: `POST {REST}/{format}/{type}` `{name, areaKey, state, blobs[], options}` | client.rb:170–181 | сверка полей body + blob_store_ids | redacted example |
| L4 delete area/repository/docker node: статус-код delete-семантики (204?) | client.rb:189–191,205–207,155–157 | фактический код удаления | один пример |
| L5 raw tree: `GET {REST}/raw/tree/{repo}/items[?parentId=]` | client.rb:123–128,276–278 | схема item, pagination глубже 1 уровня, totals | 2 уровня parentId |
| L6 docker tree + detail `fileInfo.sha256` | client.rb:135–149 | наличие sha256 (не только sha1) в detail | один detail-ответ |
| L7 raw upload/download: streaming PUT `octet-stream` + Content-Length; GET download | client.rb:62–115,247–270 | лимиты размера, chunking, Content-Type семантика | redacted trace |
| L8 OCI push: HEAD blob dedup → POST uploads → PUT `?digest=` → PUT manifest | pusher:96–138 | **Basic auth** на живом push; серверный Docker-Content-Digest против клиентского sha256 | два redacted trace (успех/фейл) |
| L9 OCI pull: manifest Accept-header, blob Range-resume, retry ×5 | fetcher:93–169,171–181 | подтверждение Bearer + Range-семантики на живом | redacted 206/partial example |
| L10 checksum: sha1 vs sha256 приоритет | checksums:20–23 | legacy отдаёт `sha1 \|\| sha256` — подтверждение, что sha256 присутствует в detail | один пример |
| L11 mTLS/private CA: TLS-профиль против registry-host | карта §2 (legacy VERIFY_NONE — НЕ повторять) | `tls_config` live-профиль private CA | сертификат CA (redacted) |
| L12 Keycloak ТУЗ (flag) + PPAM assign_role | keycloak_client.rb:27–74; establish:203–214 | realm/roles контракты, scope | redacted config |
| L13 pagination totals/фильтры (LIST) | client.rb:123–149 | если OpenAPI покажет — upgrade notes | — |

### 2.3 Правило redaction

В пакете артефактов не допускаются: токены/passwords, реальные hostname'ы
(заменяются на `{sfera_url}`, `{registry_host}`), реальные user_id/email,
blob-содержимое. Достаточно: URL-шаблоны, коды ошибок, заголовки,
схемы полей, статус-коды. Каждый пункт чеклиста → evidence-строка в
`CapabilityReport` (status CONFIRMED + evidence-ссылка) только после
живой проверки.

### 2.4 Чего НЕ запрашивать и НЕ выдумывать (anti-checklist)

- `SFAS_*` переменные — runtime-переменные сборки, НЕ протокол (карта §7);
- release events `/external/package/release_events` — Portal-to-Portal,
  НЕ Sfera API (карта §7);
- эндпоинты, которых нет в карте §3/§4: exists/HEAD generic, tag→digest
  resolve, promotion/copy, quotas, signatures/SBOM/attestations, job
  lifecycle, tree-фильтры — UNTIL checklist A1–A9 вернётся с подтверждением;
- Kafka contract Сферы — вне adapter seam (СОД bridge отдельно, §4 boundary-дока).

## 3. Gates CONFIRMED (по карте §9 + COS-069 §4)

1. OpenAPI export сверён с картой §3/§4 (14 REST + OCI push/pull) — расхождения
   фиксируются как OpenAPI-факт, не выдумка;
2. идемпотентность create_area/create_repository на живом инстансе:
   код ошибки и HTTP-статус `ALREADY_EXISTS_ERROR`;
3. Basic-vs-Bearer подтверждён на живом push (§9#4); `registry_auth_mode`
   для live-профиля обязан быть `basic` — Bearer-fallback не принимать
   как CONFIRMED;
4. private CA + mTLS-профиль против живого registry-host (tls_config);
   legacy VERIFY_NONE НЕ переносится;
5. pagination-контракт tree (глубже parentId уровня 1, totals).

## 4. Матрица/adapter после карты (уже применено, COS-069)

- `sfera_matrix`: LIST → DOCUMENTED (client.rb:123–149), GET_CHECKSUM —
  sha256-only note, OCI_PUSH/PULL — auth split-факты, HEALTH — уточнён.
  Pin-тесты `TestMatrixMicroPR` (4) в `tests/cosmo/test_sfera_adapter.py`.
- Adapter: auth split (basic/bearer, режим фиксируется в
  `raw["registry_auth_mode"]`), клиентский digest на push,
  naming/options калька, ALREADY_EXISTS → идемпотентный OK, timeout-профиль
  legacy задокументирован.
- Выдуманных эндпоинтов нет: exists/resolve_digest/copy_promote/signature/
  sbom/attestation/quota — UNKNOWN (unsupported честно).

## 5. Ссылки

- SoT карты: `docs/research/2026-09-02-legacy-sfera-contract-map.md`
- Discovery (scrape): `docs/research/2026-09-01-sfera-openapi-and-registry-boundary.md`
- Alignment: `docs/research/2026-09-02-cos-069-sfera-adapter-alignment.md`
- Соседний чеклист (СОД/transfer, не Sfera): `2026-08-31-legacy-transfer-interview-brief.md` §E
- Матрица: `orchestrator/cosmo/adapters/provider_matrices.py::sfera_matrix`
