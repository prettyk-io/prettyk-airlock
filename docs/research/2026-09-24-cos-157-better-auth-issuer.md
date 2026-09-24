# COS-157 — Better Auth issuer + OpenBao: план исполнения (Flash)

> **Карточка:** `docs/BACKLOG.md` → COS-157 (P1, 12-16h, зависит от COS-173/CO-156).
> **Статус:** план до кода; стоп-решения согласуются с PO до реализации.
> **Дата:** 2026-09-24.

---

## Контекст

Verifier (COS-156, Luna) уже готов и fail-closed: `security/jwt_verifier.py`
читает ключи в порядке JWKS URL → статичный PEM → OpenBao `secret/cosmo/jwt-keys`
→ dev-ключ, и `api/deps.py::get_current_principal` требует крипто-подпись.
Но выпускать токены некому: логина нет, фронт шлёт dev-stub `operator:admin`,
`frontend/src/auth/` не существует. COS-157 закрывает issuer-сторону.

---

## Стоп-решения (согласовать до кода)

1. **Топология** — default: **Python-native issuer внутри `cosmo-api`** (монорепо
   Python, verifier-плюмбинг уже есть, новый рантайм не заводим). Подтверждено:
   не отделилBetter Auth в TS/Node-сервис.
2. **Креденшел-источник** — default: **self-managed email/password**. Внешний
   OIDC/Blitz — вне scope. ОТКРЫТО: где физически живут креды (нет таблицы
   users, миграционная цепочка заморожена) — см. «Блокирующий вопрос» ниже.

---

## Поверхности (план)

| # | Файл (новый/правка) | Что |
|---|---|---|
| 1 | `orchestrator/cosmo/security/jwt_issuer.py` (новый) | mint RS256 JWT: claims `sub/email/roles/scopes/is_admin`, `iss/exp/nbf/aud`; приватный ключ из OpenBao `secret/cosmo/jwt-keys` (`rsa_private`) через `get_vault()` (AppRole, не root). `cryptography>=42` уже в requirements. |
| 2 | `orchestrator/cosmo/api/routes/auth.py` (новый) | `POST /api/v1/auth/login` (email/password → 200 {token, user} / 401), `GET /.well-known/jwks.json` (RFC 7517, `rsa_public` → JWK `n/e/kid/alg/kty/use`). |
| 3 | `orchestrator/cosmo/api/main.py` (правка) | include `auth_router`; CORS-заметка (login route — public, без guard). |
| 4 | (зависит от решения) креденшел-стор | проверка email/password против источника (OpenBao-seeded admin / отдельная `cosmo_users` таблица вне frozen-цепочки). |
| 5 | `orchestrator/cosmo/security/jwt_issuer.py` keys | чтение keypair из `jwt-keys` с согласованной формой (см. ниже). |

## Ключевой контракт — форма `jwt-keys` (сверил с COS-156)

COS-156 verifier (`default_vault_reader`) ожидает в `jwt-keys` поля
`jwks_url` / `public_key` / `issuers` / `audience` / `algorithms`.
COS-157 issuer-скоп требует `rsa_private` / `rsa_public`.

**Рекомендуемая каноническая форма `secret/cosmo/jwt-keys`** (одно место):
```json
{
  "rsa_private": "<RSA-2048 PKCS#8 PEM>",
  "rsa_public":  "<RSA-2048 SPKI PEM>",
  "issuers": ["cosmo-issuer"],
  "audience": "cosmo-api",
  "jwks_url": "http://cosmo-api:8100/.well-known/jwks.json"
}
```
- issuer читает `rsa_private` (подпись) и `rsa_public` (JWKS);
- verifier приоритетно ходит по `jwks_url` (сквозной mint→JWKS→verify), а
  `public_key` остаётся fallback-полем COS-156 (не трогаем COS-156 в скоупе).

**Разъяснение имени `public_key` vs `rsa_public`:** COS-156 читает `public_key`,
COS-157 пишет/читает `rsa_public`. Чтобы не плодить два поля под один ключ —
в `jwt-keys` кладём ОБА синонима (`public_key` = `rsa_public`) либо принимаем,
что verifier ходит по `jwks_url` и `public_key` не нужен. Решение фиксируется
в docstring `jwt_issuer.py`, не меняем COS-156 (вне скоупа).

## Принятие (acceptance COS-157 → отчёт)

1. `POST /api/v1/auth/login` (валидные креды) → RS256 JWT, claims верные, `iss`
   в allowlist, подпись валидна; неверный пароль → 401.
2. `GET /.well-known/jwks.json` отдаёт ключ; verifier через `COSMO_JWT_JWKS_URL`
   собирает principal из выпущенного токена (сквозной прогон, не unit-mock).
3. Приватный ключ ТОЛЬКО из `secret/cosmo/jwt-keys`; в git/`.env` нет.
4. Negative: нет ключа → явная ошибка (не дефолт-success/не 200).
5. auth-regression + jwt_verification + suite gate зелёные; OpenAPI
   документирует login/JWKS route (регенерация `docs/cosmo-openapi.*`).

## Блокирующий вопрос (до кода)

Нет таблицы users; миграционная цепочка заморожена (несколько карточек).
Где хранить email/password для self-managed логина?
- **(A) OpenBao-seeded admin** (`secret/cosmo/auth` — hashed password; bootstrap
  секрет кладётся при деплое, как Gitea/Woodpecker admin) — canon-aligned,
  без миграции; v1-минимум.
- **(B) Отдельная `cosmo_users` таблица** на новом non-frozen Base (прецеденты
  gate_decision_trail / TransferRegistryBase, `create_all` в lifespan) — честный
  user store, тяжелее, расширяемо на registration.

Рекомендация: **(A) для v1** (совпадает с «секреты в OpenBao, не .env/коде»),
(B) — как следующий follow-up (COS-158/registration).

## Зарегистрированные хвосты (не блокеры, фиксируются)

- **Flat-name drift COS-173:** в OpenBao записано `pg`/`gitea`/`woodpecker`,
  канон (vault_ref `_KNOWN_VAULT_PATHS`, rotate-secrets.ps1) — `database`/
  `forge/gitea`/`ci/woodpecker`. Ничего в рантайме эти имена пока не читает
  (env-driven), но имена расходятся. Рекомендация: переписать в канон при
  COS-157 vault-bootstrap (раз всё равно трогаем `jwt-keys`).
- `COSMO_JWT_JWKS_URL` для dev-контура: JWKS endpoint живёт в cosmo-api; verifier
  того же процесса не должен дёргать сам себя по сети — в test/unit прогонах
  ключ задаётся статичным PEM (COS-156 dev-ключ), JWKS проверяется интеграционно.

## Out of scope (явно)

FE login surface + session (COS-158); session/refresh/rotation; внешний
OIDC/Blitz; изменение verifier COS-156; перенос OpenBao (COS-173 done);
миграционная цепочка.