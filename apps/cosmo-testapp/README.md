# Cosmo TestApp

Минимальное deployable приложение — **target** конвейера build+deploy
(gitea → woodpecker → registry) для Steel Thread. Авторизация (JWT RS256)
+ CRUD-набор `notes`. Полностью независимо от ядра Cosmoport.

## Запуск локально

```bash
cd apps/cosmo-testapp
python -m venv .venv && . .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
# опционально: задать persistent ключ (иначе генерируется эфемерный dev-ключ)
export TESTAPP_JWT_PRIVATE_KEY="$(cat tests/private.pem)"
export TESTAPP_JWT_PUBLIC_KEY="$(cat tests/public.pem)"
uvicorn app:app --host 0.0.0.0 --port 8000
```

Проверка:

```bash
curl http://localhost:8000/live            # -> {"status":"ok"}
curl http://localhost:8000/ready           # -> {"status":"ready",...}
```

## Сборка docker-образа

```bash
docker build -f apps/cosmo-testapp/Dockerfile -t cosmo-testapp:0.1.0 apps/cosmo-testapp
docker run --rm -p 8000:8000 cosmo-testapp:0.1.0
```

## Конфиг (env)

| Переменная                | Назначение                                     | Default            |
|---------------------------|------------------------------------------------|--------------------|
| `TESTAPP_JWT_PRIVATE_KEY` | PEM private key (выдача RS256)                  | эфемерный dev-ключ |
| `TESTAPP_JWT_PUBLIC_KEY`  | PEM public key (верификация RS256)              | к парному эфемерному |
| `TESTAPP_JWT_ISSUER`      | issuer токена                                   | `cosmo-testapp`    |
| `TESTAPP_DB`              | `memory` (in-memory sqlite) или путь к файлу    | `memory`           |
| `TESTAPP_PORT`            | порт                                            | `8000`             |

## API

- `POST /auth/login` -> `{access_token, token_type, expires_in}` (dogfooding)
- `GET  /auth/me` (защищён)
- `GET/POST /api/notes`, `GET/PUT/DELETE /api/notes/{id}` (защищены)

Все защищённые эндпоинты требуют `Authorization: Bearer <RS256 JWT>`;
нет/битый токен -> `401`.