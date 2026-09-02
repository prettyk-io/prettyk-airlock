# Legacy Sfera contract map — фактический контракт из исходников

> **Дата:** 2 сентября 2026. **Исполнитель:** Luna. **Пакет:** Regression Snapshot
> Hygiene + Legacy Sfera Contract Map.
> **Источники:** legacy Cosmoport backend `D:\cosmo\cosmoport\backend`
> (в пакете указан `D:\prettyk-dev` — там только allure-артефакты; реальный
> путь зафиксирован в research §7 от 2026-09-01).
> **Правило:** каждый пункт имеет ссылку на код. Нет ссылки → UNKNOWN-до-live.
> Ни один эндпоинт не добавлен в adapter без этой карты + OpenAPI (COS-049).

## 1. Источники (прочитаны полностью)

| Файл | Роль |
|---|---|
| `backend/lib/sfera/client.rb` (362 стр.) | REST client: auth, provisioning, raw, docker tree, security |
| `backend/app/services/sfera/binary_pusher.rb` (148 стр.) | OCI push (blobs + manifest) через registry API |
| `backend/app/services/sfera/binary_fetcher.rb` (237 стр.) | OCI pull (manifest/config/layers, range/resume) |
| `backend/app/services/sfera/get_docker_image_checksums.rb` (67 стр.) | checksum из docker tree detail |
| `backend/app/services/integrations/establish_sfera.rb` (320 стр.) | provisioning-оркестрация + rollback |
| `backend/app/services/integrations/concerns/sfera_repo_configurable.rb` (54 стр.) | naming + repo options |
| `backend/lib/sfera/keycloak_client.rb` (176 стр.) | per-project ТУЗ (Keycloak Admin API, за feature flag) |

## 2. Транспорт и аутентификация (код-подтверждено)

| Канал | Механизм | Ссылка |
|---|---|---|
| REST API (`{sfera_url}`) | `POST /api/auth/login` `{username, password}` → JSON; токен из `access_token` \| `accessToken` \| `token`; далее `Authorization: Bearer` | client.rb:19,47–57,285–290 |
| Registry API (`https://{registry_host}` из `SferaService.repo_url`) | **Basic auth** `user:password` (НЕ Bearer!) | binary_pusher.rb:51–57 |
| Registry pull (fetcher) | **Bearer** с access_token от login | binary_fetcher.rb:171–181 |
| Keycloak (per-project ТУЗ, flag `:sfera_per_project_auth`) | password grant `admin-cli` → admin token → `/admin/realms/{realm}/users` | keycloak_client.rb:27–74 |
| PPAM (`ppam-access`, опционально) | переиспользование access_token; `assign_role(logins, object_ids, role_code)` | establish_sfera.rb:109–111,203–214 |

**TLS-факт legacy (важно):** проверка сертификатов ОТКЛЮЧЕНА во всех
непроизводственных средах (`VERIFY_NONE` client.rb:316; `ssl.verify = false`
pusher:60, fetcher:178) и в pusher/fetcher — всегда. Наш `tls_config.py`
(COS-060) такое поведение запрещает без явного `allow_insecure` —
live-Sfera-профиль обязан идти через private CA, не повторять legacy.

**Таймауты legacy:** open 10s, read 30s, upload read 200s (client.rb:28–30);
registry 3600s/open 600s (pusher:58–59). Наш adapter: `timeout_seconds=30.0`.

## 3. Подтверждённые REST-эндпоинты (client.rb)

Base: `{sfera_url}/app/ppdl/api/rest` (REST_API_BASE), core = `…/core`,
sec = `…/security-service/v1`.

| # | Операция | Маршрут | Body / детали | Ссылка |
|---|---|---|---|---|
| 1 | login | `POST /api/auth/login` | `{username, password}` → token | client.rb:47–57 |
| 2 | create_area | `POST {CORE_BASE}/areas` | `{key, name}`; key = project.code / area по зоне | client.rb:198–200 |
| 3 | delete_area | `DELETE {CORE_BASE}/areas/{area_key}` | — | client.rb:205–207 |
| 4 | create_repository | `POST {REST_API_BASE}/{format}/{type}` | `{name, areaKey, state:'ACTIVE', blobs:[blob_store_ids], **options}` | client.rb:170–181 |
| 5 | delete_repository | `DELETE {REST_API_BASE}/{format}/{type}/{name}` | — | client.rb:189–191 |
| 6 | raw tree listing | `GET {REST_API_BASE}/raw/tree/{repo}/items[?parentId=]` | → `{items: [...]}` | client.rb:123–128,276–278 |
| 7 | docker tree listing | `GET {REST_API_BASE}/docker/tree/{repo}/items[?parentId=]` | узлы COMPONENT/ARTIFACT | client.rb:135–140,280–283 |
| 8 | docker node detail | `GET {REST_API_BASE}/docker/tree/{repo}/items/{id}` | включает `fileInfo.sha1`/`fileInfo.sha256` | client.rb:147–149 |
| 9 | docker node delete | `DELETE {REST_API_BASE}/docker/tree/{repo}/items/{id}` | удаляет поддерево | client.rb:155–157 |
| 10 | raw upload | `PUT {repo_base_url}/raw/{repo}/{path}` | `Content-Type: application/octet-stream`, streaming, Content-Length | client.rb:247–270 |
| 11 | raw download | `GET {repo_base_url}/{path}` (streaming в файл/контент) | — | client.rb:62–115 |
| 12 | upsert_user | `PUT {SEC_BASE}/sources/internal/users/{user_id}` | `{email, firstName, lastName, password}` | client.rb:216–219 |
| 13 | delete_user | `DELETE {SEC_BASE}/sources/internal/users/{user_id}` | — | client.rb:224–226 |
| 14 | assign_roles | `PUT {SEC_BASE}/sources/internal/users/{user_id}/roles` | `{roles: {role_id => [space_id, …]}}` | client.rb:233–239 |

Ошибки: 401→AuthenticationError, 404→NotFoundError, прочие не-2xx/204→ApiError
(client.rb:341–353). Ответ `ALREADY_EXISTS_ERROR` / "already exists" трактуется
оркестрацией как idempotent-успех (establish_sfera.rb:125,160).

## 4. OCI push/pull (registry API) — код-подтверждено

Push (binary_pusher.rb):
1. `HEAD /v2/{repo}/blobs/{digest}` — dedup-проверка (pusher:123);
2. `POST /v2/{repo}/blobs/uploads/` → `Location` (pusher:125–128);
3. `PUT {Location}&digest={sha256:…}` octet-stream (pusher:131–135);
4. `PUT /v2/{repo}/manifests/{tag}` с `Content-Type:
   application/vnd.docker.distribution.manifest.v2+json` (pusher:96–102).
   Digest считается **клиентом** (`sha256:` + SHA256 payload, pusher:120–121) —
   серверный Docker-Content-Digest в push-пути не используется.

Pull (binary_fetcher.rb):
1. `GET /v2/{repo}/manifests/{tag}` с Accept manifest.v2 (fetcher:93–104);
2. `GET /v2/{repo}/blobs/{digest}` с `Range: bytes=N-` resume + retry
   ×5 с экспоненциальной задержкой (fetcher:127–169).

Tag-конвенция: `build.last_commit_id.first(8)` или `latest`
(fetcher:82–91, checksums:54–55).

## 5. Provisioning-оркестрация (establish_sfera.rb)

Порядок: `ensure_area` → docker → dirty_docker → raw → docs →
[flag] ТУЗ keycloak ×2 + PPAM-роли. Фейл шага → **rollback в обратном порядке**
уже созданного (establish_sfera.rb:31–42,223–242). Audit event `create`
(establish_sfera.rb:53–71).

Naming (sfera_repo_configurable.rb:8–50): `{code}` (docker), `{code}-dirty`
(docker, rewrite ALLOWED_ALL), `{code}-raw` (raw), `{code}-docs` (raw);
docker/raw/docs — `validateChecksums: true`, docker — `artifactRewritePolicy:
PROHIBITED`. Area key по зоне: `SferaService::AREA_KEY_BY_ZONE[ENV['ZONE']]`
(cosmo / cosmotst / cosmozp — client.rb:163 docstring).

UI-паттерн Сферы: `{url}/ppdl/areas/{area}/repositories/{format}/{type}/{name}`
(establish_sfera.rb:305–309).

## 6. Checksum (get_docker_image_checksums.rb)

docker tree: COMPONENT → дочерний ARTIFACT по тегу → detail `fileInfo.sha1
|| fileInfo.sha256` (строки 20–23). **Расхождение с PureK:** legacy
предпочитает **sha1**; canonical identity PureK — sha256. Наш adapter обязан
брать sha256 и не подменять его sha1 (см. §8, D2).

## 7. UNKNOWN-до-live (кода нет — не выдумывать)

- exists/HEAD generic (вне OCI blob HEAD);
- tag→digest resolve API (в tree есть fileInfo, но публичного tag→digest нет);
- promotion/copy API (legacy promotion = наш pull+push, §7.3 research);
- quotas / storage stats;
- signatures / SBOM / attestations;
- tree pagination глубже `parentId` (фильтры, totals, сортировки);
- job/status lifecycle;
- `SFAS_*` переменные — runtime-переменные сборки, НЕ протокол (research §7.4);
- release events — это Portal-to-Portal (`/external/package/release_events`
  через `Portal::Client`), НЕ Sfera API (research §7.4).

## 8. Сверка с capability matrix (sfera_matrix, COS-052)

Фактический размер enum: **18 capabilities** (ProviderCapability,
provider_capability.py:35–62). В пакете указано 19 — расхождение счётчика
пакета, не кода.

Статусы матрицы против новой карты кода:

| Capability | Матрица сейчас | Что даёт код | Вердикт |
|---|---|---|---|
| PROVISION_AREA | DOCUMENTED | §3#2 + §5 | ✅ сходится |
| PROVISION_REPOSITORY | DOCUMENTED | §3#4 + §5 naming | ✅ сходится |
| DELETE_REPOSITORY | DOCUMENTED | §3#3,#5,#9 | ✅ сходится |
| RAW_PUSH | DOCUMENTED | §3#10 (точный маршрут PUT) | ✅ сходится |
| RAW_PULL | DOCUMENTED | §3#6,#11 | ✅ сходится |
| OCI_PUSH | DOCUMENTED | §4 push (Basic auth!) | ✅ сходится; уточнить auth-факт |
| OCI_PULL | DOCUMENTED | §4 pull (Bearer, range/resume) | ✅ сходится |
| GET_CHECKSUM | DOCUMENTED | §6 — код подтверждает с точностью до строк | ⚠️ уточнить: sha1-предпочтение legacy |
| LIST | **UNKNOWN** | tree listing КОДОМ подтверждён (§3#6–8, parentId-пагинация) | ⚠️ **рекомендован upgrade → DOCUMENTED** (маршруты известны; паттерны/фильтры — остаются UNKNOWN) |
| EXISTS | UNKNOWN | generic exists в коде нет | ✅ сходится (OCI blob HEAD — частный случай push) |
| RESOLVE_DIGEST | UNKNOWN | tag→digest API нет | ✅ сходится |
| COPY_OR_PROMOTE | UNKNOWN | promotion API нет | ✅ сходится |
| SIGNATURE_REF / SBOM_REF / ATTESTATION_REF | UNKNOWN | кода нет | ✅ сходятся |
| HEALTH | DOCUMENTED («auth login + /v2/ ping») | login ✅; `/v2/` как ping в явном виде нет, но HEAD/GET `/v2/…` в push/fetch есть | ⚠️ уточнить evidence |
| QUOTA_REPORT | UNKNOWN | кода нет | ✅ сходится |
| GIT_BUNDLE_TRANSFER | NOT_SUPPORTED | bundle идёт как RAW-объект (research §7.3) | ✅ сходится |

**Рекомендации владельцу матрицы (COS-052 — Luna, отдельным микро-PR):**
- `LIST` → DOCUMENTED + evidence client.rb:123–149 (маршруты подтверждены);
- `GET_CHECKSUM` note: «legacy отдаёт sha1 || sha256 — adapter обязан
  использовать только sha256»;
- `OCI_PUSH/PULL` notes: registry auth = Basic (push) / Bearer (pull).

В код матрицы в этом пакете ничего не правил — только карта (сдерживание scope).

## 9. Live-верификация (требования, не реализация)

1. Sfera CORE OpenAPI export (COS-049) — сверка §3 с официальной спекой;
2. live-инстанс: идемпотентность create_area/create_repository
   (ALREADY_EXISTS_ERROR — код ошибки и HTTP-статус);
3. private CA + mTLS-профиль (tls_config) против реального registry-host;
4. подтверждение registry auth: Basic vs Bearer на живом push;
5. pagination-контракт tree endpoints (parentId глубже 1 уровня, totals).
