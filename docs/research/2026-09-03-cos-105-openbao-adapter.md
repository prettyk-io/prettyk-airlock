# COS-105 — Platform OpenBao Migration & Adapter (acceptance)

Дата: 2026-09-03 · Worker: Dev · Статус: готово к приёмке

## Что требовалось (карточка Boss, 8-12h, P1, dep COS-102)

OpenBao AppRole Vault-адаптер, env-канон, compose-интеграция, тесты.
Production: AppRole (VAULT_APPROLE_ROLE_ID + VAULT_APPROLE_SECRET_ID) →
scoped token secret/cosmo/*. Dev: root token (COSMO_ENV=test).

## Что сделано

### 1. `orchestrator/cosmo/infra/vault.py` — VaultClient
- AppRole-аутентификация: `POST /v1/auth/approle/login` → `client_token`
- Dev-режим (`COSMO_ENV=test`): root token из `VAULT_DEV_ROOT_TOKEN_ID`
- kv-v2 secret I/O: `read_secret(name)`, `write_secret(name, data)`
  — путь `secret/data/cosmo/<name>` (kv-v2 data path)
- Retry на транзиентах (5xx, метод GET/POST, 3 попытки)
- Token expiry: 401/403 → re-auth + retry (один раз)
- Health: `GET /v1/sys/health` (без аутентификации)
- Ошибки: `VaultError`, `VaultAuthError`, `VaultLookupError`,
  `VaultNotConfigured`
- Зависимость: только `requests` (уже в requirements)

### 2. Интеграция в рантайм
- `api/deps.py`: `get_vault()` — FastAPI-dependency (503, если
  не инициализирован); `init_vault()` — вызывается lifespan'ом
- `api/startup.py`: Vault health check + authenticate на старте
  (warning, не crash при недоступности — честная деградация)

### 3. Compose
- Сервис `cosmo-openbao` уже существовал (OpenBao 2.2.2, порт 8200)
- Добавлены `OPENBAO_DEV_ROOT_TOKEN_ID` + `OPENBAO_DEV_LISTEN_ADDRESS`
  параллельно с `VAULT_DEV_*` — OpenBao 2.2.2 НЕ уважает
  `VAULT_DEV_ROOT_TOKEN_ID` (генерирует случайный root-токен),
  `OPENBAO_DEV_*` — приоритетный, если контейнер их читает

### 4. Тесты (`tests/cosmo/test_vault.py`) — 20 тестов
| Категория | Количество | Что покрыто |
|---|---|---|
| Dev mode | 6 | root token auth ok/empty reject, default addr, not configured, not authenticated rejected |
| AppRole mock | 4 | login success, 401 → VaultAuthError, empty token → VaultAuthError, dev mode wins over approle |
| KV secret I/O mock | 5 | read ok, 404 → Lookup, write path/data, 403 → re-auth → retry, kv-v2 path |
| Health mock | 1 | health OK (no auth) |
| **Live OpenBao** (gate `COSMO_LIVE_BAO`) | **4** | dev root auth → health, KV write-read roundtrip, 404 lookup, bad-token health |

Live-тест добывает рут-токен из логов контейнера (OpenBao-квирк),
fallback на `COSMO_LIVE_BAO_ROOT_TOKEN` env-переменную.

## Верификация

| Проверка | Результат |
|---|---|
| `test_vault.py` offline | **16/16** |
| `test_vault.py` live (cosmo-openbao) | **4/4** |
| `test_vault.py` full | **20/20** |
| Импорт приложения + init_vault | OK (VaultNotConfigured без env — честно) |
| **Suite gate** | **2542 passed / 13 failed / 12 skipped** — все 13 фейлов в `test_workspace_routes.py` (Luna, COS-103, чужие); мои 20 vault-тестов зелёные |

## Честные границы / follow-up
- **Production-развёртывание OpenBao вне compose-стека** — out of scope
  (PK-C-005, Buddy).
- **AppRole provisioning** (создание role cosmo-app, policy
  secret/cosmo/*) — инфра-часть (Buddy, compose entrypoint-скрипт).
  Адаптер и тесты готовы к приёму AppRole, когда роль создана.
- **Ротация токенов / lease renewal** — follow-up за пределами 8-12h
  карточки (адаптер уже обрабатывает expiry через re-auth).
- **OpenBao-квирк**: `VAULT_DEV_ROOT_TOKEN_ID` игнорируется в 2.2.2 —
  compose держит и `VAULT_DEV_*`, и `OPENBAO_DEV_*`; live-тест парсит
  токен из логов контейнера. При обновлении OpenBao проверить, что
  нужный env-механизм работает — поменять только одну строку в compose.