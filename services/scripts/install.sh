#!/usr/bin/env bash
# Cosmoport 2.0 — airgap installer (Linux)
#
#   tar -xzf cosmoport2-vX.Y.Z-airgap.tar.gz
#   ./scripts/install.sh
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BUNDLE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "=== Cosmoport 2.0 Airgap Install ==="

if ! docker version --format '{{.Server.Version}}' >/dev/null 2>&1; then
    echo "ERROR: Docker Engine not available."
    exit 1
fi
echo "Docker $(docker version --format '{{.Server.Version}}') OK"

echo "[install] load images"
for img in "$BUNDLE_ROOT"/images/*.tar; do
    echo "  $(basename "$img")"
    docker load -i "$img"
done

echo "[install] start Cosmo stack"
docker compose -f "$BUNDLE_ROOT/compose/docker-compose.yml" up -d

echo "=== install OK ==="
echo "  API:       https://localhost/api/live"
echo "  Dashboard: https://localhost/"
echo "  Forge:     https://localhost/forge/"
echo "  Artifacts: https://localhost/artifacts/"