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