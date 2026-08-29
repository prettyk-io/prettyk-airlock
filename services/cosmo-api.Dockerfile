# Cosmoport 2.0 — Cosmo API Dockerfile
#
# FastAPI modular monolith. Собирает orchestrator/ + alembic/.
# Точка входа: orchestrator.cosmo.api.main:app
#
# Build:
#   docker build -f services/cosmo-api.Dockerfile -t cosmo-api:local ..
#
# Зависит от: requirements.txt в корне репозитория.
# После старта проверка: curl http://localhost:8100/live

FROM python:3.12-slim

WORKDIR /app

# ── Dependencies layer (cacheable) ────────────────────────────────────
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Application layer ─────────────────────────────────────────────────
COPY orchestrator/ ./orchestrator/
COPY alembic.ini .
COPY alembic/ ./alembic/

# ── Runtime ───────────────────────────────────────────────────────────
EXPOSE 8100

# Entrypoint: Alembic migrations → uvicorn
COPY services/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

CMD ["/entrypoint.sh"]