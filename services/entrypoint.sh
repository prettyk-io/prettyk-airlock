#!/bin/sh
# Cosmoport 2.0 API entrypoint (COS-063).
#
# Migration strategy (after Luna's COS-062 chain fix):
#   Fresh DB            -> plain `alembic upgrade head` (verified: 8 steps, 32 tables).
#   Legacy create_all DB (tables exist, no alembic_version) -> `alembic stamp head`,
#   then upgrade is a no-op. Luna's guidance: stamp, do NOT run full chain (DuplicateTable).
#
# 1. Bootstrap DB state -> version table
# 2. Start uvicorn
set -e

# COS-171/172: seed trivy offline DB into mounted volume on first boot.
# Образ несёт скачанный DB (--download-db-only на сборке). Volume в compose
# тенирует image-layer; если volume пуст — восстанавливаем из seed-тарбола
# (offline, без сети). Идемпотентно: при наличии DB шаг пропускается.
TRIVY_CACHE_DIR="${TRIVY_CACHE_DIR:-/var/lib/trivy}"
if [ ! -d "$TRIVY_CACHE_DIR/db" ] || [ -z "$(ls -A "$TRIVY_CACHE_DIR/db" 2>/dev/null)" ]; then
    if [ -f /opt/trivy-db-seed.tar.gz ]; then
        echo "[entrypoint] Seeding trivy offline DB -> ${TRIVY_CACHE_DIR}"
        mkdir -p "$TRIVY_CACHE_DIR"
        tar -xzf /opt/trivy-db-seed.tar.gz -C "$TRIVY_CACHE_DIR"
    else
        echo "[entrypoint] WARN: no trivy DB seed and DB absent (scans will be 'unavailable')"
    fi
fi

echo "[entrypoint] Checking DB state..."
DB_STATE=$(python - <<'PYEOF'
import os
from sqlalchemy import create_engine, text

url = os.environ["COSMO_DATABASE_URL"].replace("+asyncpg", "+psycopg2")
e = create_engine(url)
with e.connect() as c:
    tables = c.execute(text(
        "SELECT count(*) FROM pg_tables WHERE schemaname='public'"
    )).scalar()
    try:
        c.execute(text("SELECT 1 FROM alembic_version"))
        stamped = True
    except Exception:
        stamped = False
e.dispose()
if tables == 0:
    print("FRESH")
elif stamped:
    print("STAMPED")
else:
    print("LEGACY")
PYEOF
)

case "$DB_STATE" in
  FRESH)
    echo "[entrypoint] Fresh DB -> alembic upgrade head"
    alembic -c /app/alembic.ini upgrade head
    ;;
  LEGACY)
    # create_all-era database: stamp to head, migrations reconcile later.
    echo "[entrypoint] Legacy create_all DB -> alembic stamp head"
    alembic -c /app/alembic.ini stamp head
    ;;
  STAMPED)
    echo "[entrypoint] Existing DB -> alembic upgrade head"
    alembic -c /app/alembic.ini upgrade head
    ;;
esac

echo "[entrypoint] Starting Cosmo API..."
exec uvicorn orchestrator.cosmo.api.main:app --host 0.0.0.0 --port 8100