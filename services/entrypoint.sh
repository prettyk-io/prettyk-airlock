#!/bin/sh
# Cosmoport 2.0 — API entrypoint
# 1. Run Alembic migrations
# 2. Start uvicorn
set -e

echo "[entrypoint] Running Alembic migrations..."
alembic -c /app/alembic.ini upgrade head

echo "[entrypoint] Starting Cosmo API..."
exec uvicorn orchestrator.cosmo.api.main:app --host 0.0.0.0 --port 8100