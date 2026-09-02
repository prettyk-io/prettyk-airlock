#!/usr/bin/env bash
# Cosmoport 2.0 — Pre-Production Hardening Gate (COS-103)
#
# Pre-release security audit: ports, secrets, Caddy, health probe.
# Exit 0 = all checks passed. Exit 1 = vulnerabilities found.
#
# Usage:
#   ./services/scripts/verify-hardening.sh                  # local
#   ./services/scripts/verify-hardening.sh production       # production
#   ./services/scripts/verify-hardening.sh production https://prettyk.io
set -euo pipefail

MODE="${1:-local}"
BASE_URL="${2:-http://127.0.0.1:8080}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
CONFIG_DIR="$REPO_ROOT/services"

PASSED=0
FAILED=0

# ── Production port exposure policy ──────────────────────────────────────
PROD_ALLOWED_PORTS=(443 80)
# Host-port canon (COS-064): MinIO binds 9100/9101 on the host because 9000 is
# PureK SonarQube canon (RUN-STACK). Container-internal ports stay 9000/9001.
DEV_INFRA_PORTS=(5432 6379 8200 9100 9101 3000 8000 8100 5174)

# Default secrets — must NOT appear in production configs
DEFAULT_SECRETS=(
    "prettyk-minio-dev"
    "cosmo-minio-dev"
    "dev-agent-secret-change-me"
    "cosmo-bao-root-dev"
    "prettyk-password"
    "admin123"
    "password123"
)

check_pass() { echo "  [PASS] $1"; PASSED=$((PASSED + 1)); }
check_fail() { echo "  [FAIL] $1 — $2"; FAILED=$((FAILED + 1)); }
check_warn() { echo "  [WARN] $1 — $2"; }

echo ""
echo "=== Cosmo Security Hardening Gate ==="
echo "  Mode   : $MODE"
echo "  Target : $BASE_URL"
echo "  Config : $CONFIG_DIR"
echo ""

# ══════════════════════════════════════════════════════════════════════════
# Check 1: Port Exposure
# ══════════════════════════════════════════════════════════════════════════

echo "[Check 1] Port Exposure"

if [ "$MODE" = "production" ] || [ "$MODE" = "airgap" ]; then
    ALL_PORTS=("${PROD_ALLOWED_PORTS[@]}" "${DEV_INFRA_PORTS[@]}")
    UNIQUE_PORTS=($(printf '%s\n' "${ALL_PORTS[@]}" | sort -u -n))

    EXPOSED=0
    for port in "${UNIQUE_PORTS[@]}"; do
        if command -v netstat >/dev/null 2>&1; then
            LISTENING=$(netstat -an 2>/dev/null | grep LISTEN | grep ":$port " || true)
        elif command -v ss >/dev/null 2>&1; then
            LISTENING=$(ss -tlnp 2>/dev/null | grep ":$port " || true)
        else
            check_warn "Port $port" "no netstat/ss available — cannot scan"
            continue
        fi

        if [ -n "$LISTENING" ]; then
            # Check if it's bound to 0.0.0.0 or *
            if echo "$LISTENING" | grep -qE '0\.0\.0\.0|\*|::\s'; then
                if printf '%s\n' "${PROD_ALLOWED_PORTS[@]}" | grep -qx "$port"; then
                    check_pass "Port $port (allowed)"
                else
                    check_fail "Port $port exposed to all interfaces" "must be 127.0.0.1 or removed in production"
                    EXPOSED=1
                fi
            else
                check_pass "Port $port (bound to localhost only)"
            fi
        fi
    done
    if [ $EXPOSED -eq 0 ]; then
        check_pass "Port exposure policy (no internal ports exposed)"
    fi
else
    for port in "${DEV_INFRA_PORTS[@]}"; do
        if command -v netstat >/dev/null 2>&1; then
            if netstat -an 2>/dev/null | grep LISTEN | grep -q ":$port "; then
                check_pass "Dev port :$port (listening)"
            else
                check_warn "Dev port :$port" "not listening — services may be down"
            fi
        fi
    done
    echo "  NOTE: $MODE mode — all dev ports are expected to be open"
fi

# ══════════════════════════════════════════════════════════════════════════
# Check 2: Default Secrets
# ══════════════════════════════════════════════════════════════════════════

echo ""
echo "[Check 2] Default Secrets & Hardcoded Credentials"

FOUND_SECRETS=0
for secret in "${DEFAULT_SECRETS[@]}"; do
    HITS=$(grep -rn "$secret" \
        "$CONFIG_DIR" \
        "$REPO_ROOT/orchestrator" \
        --include='*.yml' --include='*.yaml' --include='*.env' --include='*.ps1' --include='*.sh' --include='*.py' \
        --exclude-dir='.venv' --exclude-dir='node_modules' --exclude-dir='.git' --exclude-dir='reports' \
        2>/dev/null || true)

    if [ -n "$HITS" ]; then
        FILES=$(echo "$HITS" | head -3 | sed "s|$REPO_ROOT/||g" | tr '\n' ', ' | sed 's/,$//')
        check_fail "Default secret '$secret' found" "in files: $FILES"
        FOUND_SECRETS=1
    fi
done

if [ $FOUND_SECRETS -eq 0 ]; then
    check_pass "Default secrets scan (no defaults found)"
fi

# ══════════════════════════════════════════════════════════════════════════
# Check 3: Caddy Configuration
# ══════════════════════════════════════════════════════════════════════════

echo ""
echo "[Check 3] Caddy Configuration"

CADDYFILE="$CONFIG_DIR/Caddyfile"
if [ ! -f "$CADDYFILE" ]; then
    check_fail "Caddyfile exists" "not found at $CADDYFILE"
else
    check_pass "Caddyfile exists"

    if grep -q 'rate_limit' "$CADDYFILE" 2>/dev/null; then
        check_pass "Rate limiting configured"
    else
        check_fail "Rate limiting configured" "NO rate_limit directive in Caddyfile"
    fi

    if [ "$MODE" = "production" ] || [ "$MODE" = "airgap" ]; then
        if grep -q 'tls ' "$CADDYFILE" 2>/dev/null || grep -q ':443' "$CADDYFILE" 2>/dev/null; then
            check_pass "TLS enabled"
        else
            check_fail "TLS enabled" "production MUST use HTTPS"
        fi
    else
        check_warn "TLS check" "skipped — $MODE mode allows HTTP"
    fi
fi

# ══════════════════════════════════════════════════════════════════════════
# Check 4: Health Probe Sanitization
# ══════════════════════════════════════════════════════════════════════════

echo ""
echo "[Check 4] Health Probe Sanitization"

HEALTH_URL="$BASE_URL/api/health"
HEALTH_RESP=$(curl -sk --max-time 5 "$HEALTH_URL" 2>/dev/null || echo "")

if [ -z "$HEALTH_RESP" ]; then
    check_fail "GET $HEALTH_URL" "unable to reach API"
else
    if echo "$HEALTH_RESP" | grep -q '"status"'; then
        check_pass "GET $HEALTH_URL (HTTP 200)"
    else
        check_fail "GET $HEALTH_URL" "invalid response: ${HEALTH_RESP:0:80}"
    fi

    # Check for sensitive data leaks
    LEAKED=0
    PATTERNS=(
        "postgresql://[^@]+@"         "DSN/PostgreSQL connection string"
        "token[=:]\s*[\w-]{20,}"     "likely token"
        "password[=:]\s*[\w!@#\$\^&\*\\(\\)\-]+" "password value"
        "squ_[a-zA-Z0-9]{20,}"       "SonarQube token"
        "BEGIN\s+(RSA|EC|DSA|OPENSSH)\s+PRIVATE\s+KEY" "private key"
        "Traceback\s+\(most recent call last\)" "Python traceback"
    )

    for ((i=0; i<${#PATTERNS[@]}; i+=2)); do
        pattern="${PATTERNS[$i]}"
        label="${PATTERNS[$i+1]}"
        if echo "$HEALTH_RESP" | grep -qE "$pattern"; then
            check_fail "$label exposed" "/api/health response contains sensitive data"
            LEAKED=1
        fi
    done

    if [ $LEAKED -eq 0 ]; then
        check_pass "Response sanitization (no credentials, DSN, or tracebacks)"
    fi
fi

# �══════════════════════════════════════════════════════════════════════════════
# Summary
# �══════════════════════════════════════════════════════════════════════════════

echo ""
echo "═ Hardening Gate Summary �═"
echo "  Pased : $PASED"
echo "  Failed : $FAILED"

if [ "$FAILED" -gt 0]; then
    echo ""
    echo "═ HARDENING GATE FAILED═"
    echo "  Fix the issues above before deploying to production."
    echo "  Checklist: services/scripts/HARDENING_CHECKLIST.md"
    exit 1
fi

echo ""
echo "═ HARDENING GATE PASED �═"
exit 0