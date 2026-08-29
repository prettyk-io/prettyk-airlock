#!/usr/bin/env bash
# Cosmoport 2.0 — integrity check for airgap bundle.
#
# Выполнять ПЕРЕД install.sh.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
BUNDLE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CHECKSUM_FILE="$BUNDLE_ROOT/checksums.sha256"

if [ ! -f "$CHECKSUM_FILE" ]; then
    echo "FAIL: checksums.sha256 not found"
    exit 1
fi

cd "$BUNDLE_ROOT"
echo "=== Cosmoport 2.0 Bundle Integrity Check ==="

FAIL_COUNT=0
MATCH_COUNT=0

while IFS= read -r line; do
    [ -z "$line" ] && continue
    expected_hash="${line:0:64}"
    expected_path="${line:66}"

    if [ ! -f "$expected_path" ]; then
        echo "MISSING: $expected_path"
        FAIL_COUNT=$((FAIL_COUNT + 1))
        continue
    fi

    if command -v sha256sum >/dev/null 2>&1; then
        actual_hash=$(sha256sum "$expected_path" | cut -d' ' -f1)
    elif command -v shasum >/dev/null 2>&1; then
        actual_hash=$(shasum -a 256 "$expected_path" | cut -d' ' -f1)
    else
        echo "ERROR: neither sha256sum nor shasum found"
        exit 1
    fi

    if [ "$expected_hash" = "$actual_hash" ]; then
        MATCH_COUNT=$((MATCH_COUNT + 1))
    else
        echo "MISMATCH: $expected_path"
        FAIL_COUNT=$((FAIL_COUNT + 1))
    fi
done < "$CHECKSUM_FILE"

# Проверить compose на внешние ссылки
if grep -qE '(https?://|pip install|npm install)' "$BUNDLE_ROOT"/compose/*.yml 2>/dev/null; then
    echo "FAIL: compose contains external URLs (forbidden for airgap)"
    FAIL_COUNT=$((FAIL_COUNT + 1))
fi

echo "---"
echo "Matched: $MATCH_COUNT  Failed: $FAIL_COUNT"
[ "$FAIL_COUNT" -eq 0 ] && echo "=== integrity OK ==="
exit $FAIL_COUNT