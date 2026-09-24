# COS-173 — OpenBao standalone host + миграция Cosmo (план + журнал исполнения)

> **Карточка:** `D:\prettyk-airlock\docs\BACKLOG.md` → COS-173 (Owner: Flash, P1).
> **Канон:** `D:\prettyk.io\nexus-core\OPENBAO-PLATFORM.md`.
> **Исполнитель:** Flash. **Коммит:** по команде Максима.
> **Тип:** live-infra (dev-контур), не кодовая фича.

---

## 0. Цель

Разблокировать auth-эпик (COS-157): issuer обязан брать signing-ключи из
платформенного OpenBao `secret/cosmo/*`. Поднять один shared OpenBao на сети
`pk-infra`, завести AppRole `cosmo-app` (`rw secret/cosmo/*`), мигрировать
секреты, переключить Cosmo API, убрать per-product `cosmo-openbao`.

---

## 1. Разведка (факты на входе)

- `cosmo-openbao` живёт на `:8200` (dev mode, image 2.2 → версия 2.2.2),
  **kv пуст** — `LIST secret/metadata/cosmo` → `{}`. Мигрировать «по значению»
  нечего; все рантайм-креды сейчас — dev-дефолты в `services/.env.example`
  (PG `cosmo/cosmo`, MinIO `cosmo/cosmo-minio-dev`, Woodpecker
  `dev-agent-secret-change-me`, Gitea admin `cosmo-admin-dev`).
- `cosmo-api` работает **без единой Vault-энв** → адаптер COS-105
  (`infra/vault.py`) дремлет; переключение — чистый конфиг, не логика.
- Сети `pk-infra` **нет**. Конфликтов нет: контейнера `prettyk-openbao` нет,
  volume `prettyk_openbao` никем не создан (secops infra openbao не поднимался).
- `services/.env` отсутствует (только `.env.example`); `.env` gitignored →
  AppRole role-id/secret-id прошиваются как runtime-secrets, не в git.
- Дефолт OpenBao dev mode генерит случайный root token (2.2.2 игнорирует
  `VAULT_DEV_ROOT_TOKEN_ID`); текущий cosmo-oтoken — из `docker logs`.

---

## 2. Решения

| Вопрос | Решение |
|---|---|
| Где живёт платформенный Compose | `D:\prettyk-airlock\services\docker-compose.openbao.yml` (dev-контур, поверхность Cosmo; при появлении platform-репо — перенос) |
| Имя контейнера / volume | `prettyk-openbao` / `prettyk_openbao` (канон §4/§8) |
| Порт | `127.0.0.1:8200:8200` (только localhost; наружу не публикуется) |
| Image | `openbao/openbao:2.2` |
| Namespace | `secret/cosmo/*` (канон §3; в MASTER.md опечатка «cosmos» — игнорирую) |
| Root token в рантайме | не используется Cosmo; только bootstrap (AppRole provisioning + запись секретов) |
| AppRole creds | `services/.env` (gitignored), композ через `${VAULT_APPROLE_ROLE_ID}` / `..._SECRET_ID` |

### Имена секретов (`secret/cosmo/*`)

| Путь | Поля | Источник значения |
|---|---|---|
| `pg` | `user, password, db` | `cosmo/cosmo/cosmo` |
| `minio` | `access_key, secret_key` | `cosmo/cosmo-minio-dev` |
| `gitea` | `admin_user, admin_password, webhook_secret` | `cosmo/cosmo-admin-dev/dev-webhook-secret-change-me` |
| `woodpecker` | `agent_secret` | `dev-agent-secret-change-me` |
| `jwt-keys` | `rsa_private, rsa_public` | дефолтный dev keypair (для COS-157) |

> Значения — dev-контур; для prod ротация через `rotate-secrets.ps1` / Buddy.

---

## 3. Топология (итог)

```
prettyk-openbao (openbao/openbao:2.2)
  network: pk-infra (external)
  volume: prettyk_openbao
  port: 127.0.0.1:8200
  AppRole: cosmo-app (policy: rw secret/cosmo/*)

cosmo-api
  networks: [cosmo-net, pk-infra (external)]
  env: VAULT_ADDR=http://prettyk-openbao:8200 + VAULT_APPROLE_ROLE_ID/SECRET_ID
```

---

## 4. Порядок исполнения

1. `docker network create pk-infra`.
2. Написать `services/docker-compose.openbao.yml`.
3. Остановить/удалить `cosmo-openbao` (освободить 8200).
4. Поднять platform OpenBao; достать root token из логов.
5. Bootstrap: enable `approle`, policy `cosmo-app`, создать AppRole
   `cosmo-app`, получить role-id + secret-id.
6. Записать секреты `secret/cosmo/*`.
7. Правка `services/docker-compose.yml`: убрать `cosmo-openbao` + volume,
   добавить `pk-infra` external-net + VAULT-энв в `cosmo-api`.
8. Записать `services/.env` (role-id/secret-id).
9. Пересоздать `cosmo-api`, проверить health.
10. Live-доказательство через AppRole (read/write/negative).
11. Обновить BACKLOG/PROGRESS.

---

## 5. Журнал (заполняется по факту)

<!-- step log appended during execution -->