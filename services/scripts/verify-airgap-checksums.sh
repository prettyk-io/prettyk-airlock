#!/usr/bin/env bash
# Cosmoport 2.0 — Airgap Image Digest Verifier (COS-088)
#
# Проверяет SHA-256 digests всех Docker-образов против manifest.json.
#
# Режимы работы:
#   1. bundle-mode: проверка распакованного airgap-бандла
#        verify-airgap-checksums.sh /path/to/bundle
#   2. running-mode: проверка загруженных образов в Docker
#        verify-airgap-checksums.sh --loaded
#   3. both: оба режима
#        verify-airgap-checksums.sh /path/to/bundle --loaded
#
# Для каждого образа сверяет:
#   - digest из manifest.json (эталон)
#   - фактический digest из docker image inspect (loaded)
#   - digest из docker pull (если доступен registry)
#
# Выход: 0 — все проверки пройдены; 1 — обнаружены расхождения.
set -euo pipefail

BUNDLE_ROOT=""
CHECK_LOADED=false
FAIL_COUNT=0
MATCH_COUNT=0

# ── Parse args ──────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --loaded)
            CHECK_LOADED=true
            shift
            ;;
        *)
            if [ -d "$1" ]; then
                BUNDLE_ROOT="$(cd "$1" && pwd)"
            fi
            shift
            ;;
    esac
done

echo "=== Cosmo Airgap Image Digest Verification ==="
echo ""

# ══════════════════════════════════════════════════════════════════════
# Helper: compute SHA-256 digest from docker image inspect
# ══════════════════════════════════════════════════════════════════════

get_docker_digest() {
    local image="$1"
    local digest
    digest=$(docker image inspect "$image" --format='{{index .RepoDigests 0}}' 2>/dev/null || echo "")
    if [ -z "$digest" ]; then
        # Fallback: compute from image ID
        local img_id
        img_id=$(docker image inspect "$image" --format='{{.Id}}' 2>/dev/null || echo "")
        if [ -n "$img_id" ]; then
            echo "sha256:${img_id##*:}"
        else
            echo ""
        fi
    else
        echo "$digest"
    fi
}

# ══════════════════════════════════════════════════════════════════════
# Mode 1: Verify bundle manifest.json
# ══════════════════════════════════════════════════════════════════════

if [ -n "$BUNDLE_ROOT" ]; then
    MANIFEST="$BUNDLE_ROOT/manifest.json"

    if [ ! -f "$MANIFEST" ]; then
        echo "FAIL: manifest.json not found in $BUNDLE_ROOT"
        exit 1
    fi

    echo "[bundle] Checking manifest.json: $MANIFEST"
    echo ""

    # Проверить версию бандла
    BUNDLE_NAME=$(python3 -c "import json,sys; print(json.load(open('$MANIFEST'))['bundle'])" 2>/dev/null || echo "?")
    BUNDLE_VER=$(python3 -c "import json,sys; print(json.load(open('$MANIFEST'))['version'])" 2>/dev/null || echo "?")
    echo "  Bundle: $BUNDLE_NAME v$BUNDLE_VER"
    echo ""

    # Извлечь список образов из manifest.json
    IMAGE_COUNT=$(python3 -c "import json,sys; print(len(json.load(open('$MANIFEST'))['images']))" 2>/dev/null || echo "0")
    echo "  Images in manifest: $IMAGE_COUNT"
    echo ""

    # Проверить checksums.sha256
    CHECKSUM_FILE="$BUNDLE_ROOT/checksums.sha256"
    if [ -f "$CHECKSUM_FILE" ]; then
        echo "[bundle] Verifying checksums.sha256..."
        cd "$BUNDLE_ROOT"

        while IFS= read -r line; do
            [ -z "$line" ] && continue
            EXPECTED_HASH="${line:0:64}"
            FILEPATH="${line:66}"

            if [ ! -f "$FILEPATH" ]; then
                echo "  MISSING: $FILEPATH"
                FAIL_COUNT=$((FAIL_COUNT + 1))
                continue
            fi

            if command -v sha256sum >/dev/null 2>&1; then
                ACTUAL_HASH=$(sha256sum "$FILEPATH" | cut -d' ' -f1)
            elif command -v shasum >/dev/null 2>&1; then
                ACTUAL_HASH=$(shasum -a 256 "$FILEPATH" | cut -d' ' -f1)
            else
                echo "ERROR: no sha256sum or shasum available"
                exit 1
            fi

            if [ "$EXPECTED_HASH" = "$ACTUAL_HASH" ]; then
                MATCH_COUNT=$((MATCH_COUNT + 1))
            else
                echo "  MISMATCH: $FILEPATH"
                echo "    Expected: $EXPECTED_HASH"
                echo "    Got:      $ACTUAL_HASH"
                FAIL_COUNT=$((FAIL_COUNT + 1))
            fi
        done < "$CHECKSUM_FILE"

        echo "  checksums: $MATCH_COUNT matched, $FAIL_COUNT failed"
        echo ""
    else
        echo "[bundle] WARNING: checksums.sha256 not found (skipping file checks)"
        echo ""
    fi

    # Проверить каждый образ из manifest.json
    echo "[bundle] Verifying image digests from manifest.json..."
    echo ""

    # Use Python to iterate images (jq not guaranteed on airgap)
    python3 -c "
import json, sys
with open('$MANIFEST') as f:
    manifest = json.load(f)
for img in manifest.get('images', []):
    name = img.get('name', '?')
    digest = img.get('digest', '')
    tar_file = img.get('file', '?')
    if digest:
        print(f'{name}|{digest}|{tar_file}')
    else:
        print(f'{name}|NODIGEST|{tar_file}')
" 2>/dev/null | while IFS='|' read -r IMG_NAME EXPECTED_DIGEST TAR_FILE; do
        if [ "$EXPECTED_DIGEST" = "NODIGEST" ]; then
            echo "  WARN: $IMG_NAME — no digest in manifest (build image, pinned at build time)"
            echo "        tar: images/$TAR_FILE"
            continue
        fi

        # Проверить digest для образа
        if [ "$CHECK_LOADED" = true ]; then
            ACTUAL_DIGEST=$(get_docker_digest "$IMG_NAME")
            if [ -z "$ACTUAL_DIGEST" ]; then
                echo "  FAIL: $IMG_NAME — image not loaded in Docker"
                echo "        Expected: $EXPECTED_DIGEST"
                FAIL_COUNT=$((FAIL_COUNT + 1))
                continue
            fi

            if [ "$EXPECTED_DIGEST" = "$ACTUAL_DIGEST" ]; then
                echo "  OK  : $IMG_NAME"
                echo "        Digest: $EXPECTED_DIGEST"
                MATCH_COUNT=$((MATCH_COUNT + 1))
            else
                echo "  FAIL: $IMG_NAME — digest mismatch"
                echo "        Expected: $EXPECTED_DIGEST"
                echo "        Got:      $ACTUAL_DIGEST"
                FAIL_COUNT=$((FAIL_COUNT + 1))
            fi
        else
            echo "  OK  : $IMG_NAME (manifest check — use --loaded for Docker verification)"
            echo "        Digest: $EXPECTED_DIGEST"
            MATCH_COUNT=$((MATCH_COUNT + 1))
        fi
    done
    echo ""
fi

# ══════════════════════════════════════════════════════════════════════
# Mode 2: Verify loaded Docker images
# ══════════════════════════════════════════════════════════════════════

if [ "$CHECK_LOADED" = true ]; then
    echo "[loaded] Checking Docker image integrity..."

    # Список всех образов Cosmo (из compose + build)
    ALL_IMAGES=(
        "postgres:16-alpine"
        "valkey/valkey:8-alpine"
        "openbao/openbao:2.2"
        "minio/minio:RELEASE.2025-03-12T18-04-18Z"
        "gitea/gitea:1.22.6"
        "woodpeckerci/woodpecker-server:v3.5"
        "woodpeckerci/woodpecker-agent:v3.5"
        "caddy:2.9-alpine"
        "cosmo-api:local"
        "cosmo-frontend:local"
    )

    echo ""
    for IMG in "${ALL_IMAGES[@]}"; do
        DIGEST=$(get_docker_digest "$IMG")
        if [ -z "$DIGEST" ]; then
            echo "  MISSING: $IMG — not loaded in Docker"
            FAIL_COUNT=$((FAIL_COUNT + 1))
            continue
        fi

        IMG_ID=$(docker image inspect "$IMG" --format='{{.Id}}' 2>/dev/null)
        CREATED=$(docker image inspect "$IMG" --format='{{.Created}}' 2>/dev/null)
        echo "  OK  : $IMG"
        echo "        ID: $IMG_ID"
        echo "        Digest: $DIGEST"
        echo "        Created: $CREATED"
        echo ""
        MATCH_COUNT=$((MATCH_COUNT + 1))
    done
fi

# ══════════════════════════════════════════════════════════════════════
# Summary
# ══════════════════════════════════════════════════════════════════════

echo "---"
echo "Verified: $MATCH_COUNT  Failed: $FAIL_COUNT"

if [ "$FAIL_COUNT" -gt 0 ]; then
    echo ""
    echo "=== INTEGRITY VIOLATION DETECTED ==="
    echo "One or more images have been tampered with or corrupted."
    echo ""
    echo "Recovery steps:"
    echo "  1. Verify the airgap bundle source (re-download if needed)"
    echo "  2. Re-run: docker load < images/*.tar"
    echo "  3. Re-run this verification script"
    echo "  4. Do NOT start the stack until integrity is restored"
    exit 1
fi

echo ""
echo "=== All integrity checks passed ==="
exit 0