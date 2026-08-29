#!/usr/bin/env bash
# Cosmoport 2.0 — Automated E2E Release Pipeline Runner (COS-091)
#
# Full lifecycle: Domain → App → Bricks → Plan → Run → Batches → Gates → GOST-Act → Release → Transfer
#
#   ./services/scripts/run-e2e-pipeline.sh [base_url]
#
# Prerequisites:
#   docker compose up -d cosmo-postgres cosmo-valkey cosmo-api cosmo-caddy
set -euo pipefail

BASE_URL="${1:-http://127.0.0.1:8080}"
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
REPORT_DIR="$REPO_ROOT/reports"
SUFFIX="$(date +%H%M%S)"
TS="$(date '+%Y-%m-%d %H:%M:%S')"

DOMAIN_ID="e2e-steel-domain"
APP_L0="e2e-lib-$SUFFIX"
APP_L1="e2e-app-$SUFFIX"
PLAN_ID="e2e-plan-$SUFFIX"
RUN_ID="e2e-run-$SUFFIX"
REL_ID="e2e-rel-$SUFFIX"
BRICK_B="e2e-b-build-$SUFFIX"
BRICK_S="e2e-b-sast-$SUFFIX"
BRICK_D="e2e-b-dast-$SUFFIX"
GATE_A="e2e-gate-auto-$SUFFIX"
GATE_M="e2e-gate-manual-$SUFFIX"

PASSED=0
FAILED=0
declare -a STEPS
START_TS=$(date +%s)

# ── Helpers ───────────────────────────────────────────────────────────────

step() {
    local label="$1" method="$2" uri="$3" expected="${4:-200}" body="${5:-}"
    local opts=(-s -o /dev/null -w "%{http_code}" -X "$method" --max-time 10)
    if [ -n "$body" ]; then
        opts+=(-H "Content-Type: application/json" -d "$body")
    fi

    local sc
    sc=$(curl "${opts[@]}" "$BASE_URL$uri" 2>/dev/null || echo "000")
    local status="PASS"
    if [ "$sc" -ge 200 ] 2>/dev/null && [ "$sc" -lt 300 ] 2>/dev/null; then
        status="PASS"
        PASSED=$((PASSED + 1))
    else
        status="FAIL"
        FAILED=$((FAILED + 1))
    fi

    local icon="[OK]"
    [ "$status" = "FAIL" ] && icon="[FAIL]"
    printf "  %s %-55s HTTP %s\n" "$icon" "$label" "$sc"
    STEPS+=("$(printf '{"step":"%s","status":"%s","httpCode":%s}' "$label" "$status" "$sc")")
}

header_patch() {
    # PATCH with X-Cosmo-Domain header
    local label="$1" uri="$2" body="${3:-}" domain="${4:-}"
    local opts=(-s -o /dev/null -w "%{http_code}" -X PATCH --max-time 10)
    if [ -n "$body" ]; then
        opts+=(-H "Content-Type: application/json" -d "$body")
    fi
    if [ -n "$domain" ]; then
        opts+=(-H "X-Cosmo-Domain: $domain")
    fi

    local sc
    sc=$(curl "${opts[@]}" "$BASE_URL$uri" 2>/dev/null || echo "000")
    local status="PASS"
    if [ "$sc" -ge 200 ] 2>/dev/null && [ "$sc" -lt 300 ] 2>/dev/null; then
        status="PASS"
        PASSED=$((PASSED + 1))
    else
        status="FAIL"
        FAILED=$((FAILED + 1))
    fi

    local icon="[OK]"
    [ "$status" = "FAIL" ] && icon="[FAIL]"
    printf "  %s %-55s HTTP %s\n" "$icon" "$label" "$sc"
    STEPS+=("$(printf '{"step":"%s","status":"%s","httpCode":%s}' "$label" "$status" "$sc")")
}

# ══════════════════════════════════════════════════════════════════════════

mkdir -p "$REPORT_DIR"

echo ""
echo "=== Cosmoport 2.0 — E2E Release Pipeline ==="
echo "  Target : $BASE_URL"
echo "  Domain : $DOMAIN_ID"
echo "  Time   : $TS"
echo ""

# ── Phase 1: Domain & Apps ────────────────────────────────────────────
echo "--- Phase 1: Domain & Applications ---"

step "Create Domain" POST "/api/v1/domains" 201 \
  "{\"id\":\"$DOMAIN_ID\",\"label\":\"E2E Steel Thread Domain\",\"forge_binding\":{\"forge_type\":\"gitea\",\"url\":\"http://cosmo-gitea:3000\",\"token_ref\":\"VAULT/E2E\"}}"

step "Create App L0 (library)" POST "/api/v1/apps" 201 \
  "{\"id\":\"$APP_L0\",\"domain_id\":\"$DOMAIN_ID\",\"level\":0,\"repo_binding\":{\"forge_id\":\"gitea\",\"repo_path\":\"$DOMAIN_ID/lib-common\"}}"

step "Create App L1 (service)" POST "/api/v1/apps" 201 \
  "{\"id\":\"$APP_L1\",\"domain_id\":\"$DOMAIN_ID\",\"level\":1,\"repo_binding\":{\"forge_id\":\"gitea\",\"repo_path\":\"$DOMAIN_ID/api-gateway\"}}"

# ── Phase 2: Bricks & Plan ────────────────────────────────────────────
echo ""
echo "--- Phase 2: Bricks & Plan ---"

step "Create Brick: Build" POST "/api/v1/bricks" 201 \
  "{\"id\":\"$BRICK_B\",\"name\":\"App Build\",\"type\":\"build\",\"source\":\"internal\",\"definition\":{\"executor\":\"woodpecker\",\"image\":\"golang:1.22\",\"timeout_s\":600}}"

step "Create Brick: SAST" POST "/api/v1/bricks" 201 \
  "{\"id\":\"$BRICK_S\",\"name\":\"Sonar SAST\",\"type\":\"sast\",\"source\":\"internal\",\"definition\":{\"executor\":\"woodpecker\",\"image\":\"sonarsource/sonar-scanner-cli:latest\",\"timeout_s\":1200},\"depends_on\":[\"$BRICK_B\"]}"

step "Create Brick: DAST" POST "/api/v1/bricks" 201 \
  "{\"id\":\"$BRICK_D\",\"name\":\"ZAP DAST\",\"type\":\"dast\",\"source\":\"internal\",\"definition\":{\"executor\":\"woodpecker\",\"image\":\"zaproxy/zap-stable:2.17.0\",\"timeout_s\":1800},\"depends_on\":[\"$BRICK_S\"]}"

step "Compile Plan" POST "/api/v1/plans/compile" 201 \
  "{\"plan_id\":\"$PLAN_ID\",\"app_id\":\"$APP_L1\",\"brick_ids\":[\"$BRICK_B\",\"$BRICK_S\",\"$BRICK_D\"]}"

# ── Phase 3: Run & Batches ────────────────────────────────────────────
echo ""
echo "--- Phase 3: Run & Batches ---"

step "Create Run" POST "/api/v1/runs" 201 \
  "{\"id\":\"$RUN_ID\",\"plan_id\":\"$PLAN_ID\",\"trigger\":\"manual\",\"domain_id\":\"$DOMAIN_ID\",\"initiator_user_id\":\"e2e-operator\",\"initiator_role\":\"secops\"}"

# Get batch IDs from the compiled plan
BATCH_JSON=$(curl -s --max-time 5 "$BASE_URL/api/v1/batches?plan_id=$PLAN_ID" 2>/dev/null || echo "[]")
BATCH_IDS=$(echo "$BATCH_JSON" | python3 -c "import json,sys; [print(b['id']) for b in json.load(sys.stdin)]" 2>/dev/null || echo "")
echo "  Batches: $BATCH_IDS"

for bid in $BATCH_IDS; do
    step "Batch '$bid': set running" PATCH "/api/v1/batches/$bid/status" 200 "{\"status\":\"running\"}"
    sleep 0.2
    step "Batch '$bid': set passed"  PATCH "/api/v1/batches/$bid/status" 200 "{\"status\":\"passed\"}"
done

# Advance Run lifecycle (PATCH requires X-Cosmo-Domain header via curl -H)
for st in queued running; do
    header_patch "Run: $st" "/api/v1/runs/$RUN_ID/status" "{\"status\":\"$st\"}" "$DOMAIN_ID"
done
header_patch "Run: succeeded (final)" "/api/v1/runs/$RUN_ID/status" "{\"status\":\"succeeded\"}" "$DOMAIN_ID"

# ── Phase 4: Gates ────────────────────────────────────────────────────
echo ""
echo "--- Phase 4: Security Gates ---"

step "Create Gate: Automatic" POST "/api/v1/gates" 201 \
  "{\"id\":\"$GATE_A\",\"plan_id\":\"$PLAN_ID\",\"type\":\"automatic\",\"position\":0,\"policy\":{\"rules\":[{\"finding_type\":\"Critical\",\"action\":\"block\"},{\"finding_type\":\"High\",\"action\":\"warn\",\"max_count\":5}]}}"

step "Create Gate: Manual" POST "/api/v1/gates" 201 \
  "{\"id\":\"$GATE_M\",\"plan_id\":\"$PLAN_ID\",\"type\":\"manual\",\"position\":1,\"policy\":{\"rules\":[{\"finding_type\":\"Critical\",\"action\":\"block\"}]}}"

step "Gate Auto: PASS" POST "/api/v1/gates/$GATE_A/decision" 200 \
  "{\"decision\":\"pass\"}"

step "Gate Manual: PASS" POST "/api/v1/gates/$GATE_M/decision" 200 \
  "{\"decision\":\"pass\",\"decided_by\":\"e2e-secops-lead@cosmoport.io\",\"signature\":\"e2e-sha256-test\"}"

# ── Phase 5: GOST-Act & Evidence ──────────────────────────────────────
echo ""
echo "--- Phase 5: GOST-Act & Evidence ---"

step "GOST-Act (JSON)" GET "/api/v1/runs/$RUN_ID/gost-act" 200 ""
step "GOST-Act (HTML)"  GET "/api/v1/runs/$RUN_ID/gost-act/html" 200 ""
step "Evidence Chain"  GET "/api/v1/runs/$RUN_ID/evidence" 200 ""

# ── Phase 6: Release ───────────────────────────────────────────────────
echo ""
echo "--- Phase 6: Release Lifecycle ---"

step "Create Release" POST "/api/v1/releases" 201 \
  "{\"id\":\"$REL_ID\",\"domain_id\":\"$DOMAIN_ID\",\"plan_id\":\"$PLAN_ID\",\"run_ids\":[\"$RUN_ID\"],\"trigger\":\"manual\",\"version\":\"0.1.0-e2e\",\"changelog\":\"E2E automated release test\"}"

step "Release: Submit" POST "/api/v1/releases/$REL_ID/submit" 200 ""
step "Release: Approve" POST "/api/v1/releases/$REL_ID/approve" 200 \
  "{\"approved_by\":\"e2e-release-manager@cosmoport.io\",\"role\":\"release_manager\"}"
step "Release: Deploy" POST "/api/v1/releases/$REL_ID/deploy" 200 ""

# ── Phase 7: Transfer ──────────────────────────────────────────────────
echo ""
echo "--- Phase 7: Transfer to ZT ---"

TRANSFER_SC=$(curl -s -o /dev/null -w "%{http_code}" -X POST --max-time 10 \
  -H "Content-Type: application/json" \
  -d "{\"initiated_by\":\"e2e-operator@cosmoport.io\",\"comment\":\"E2E pipeline automated transfer\"}" \
  "$BASE_URL/api/v1/releases/$REL_ID/transfer" 2>/dev/null || echo "000")

ZONE="?"
if [ "$TRANSFER_SC" -ge 200 ] 2>/dev/null && [ "$TRANSFER_SC" -lt 300 ] 2>/dev/null; then
    ZONE="zt"
    echo "  [OK] Release: Transfer ZR->ZT              HTTP $TRANSFER_SC (zone=$ZONE)"
    PASSED=$((PASSED + 1))
else
    echo "  [FAIL] Release: Transfer ZR->ZT              HTTP $TRANSFER_SC"
    FAILED=$((FAILED + 1))
fi
STEPS+=("$(printf '{"step":"%s","status":"%s","httpCode":%s}' "Release: Transfer ZR->ZT" "$([ "$TRANSFER_SC" -ge 200 ] 2>/dev/null && [ "$TRANSFER_SC" -lt 300 ] 2>/dev/null && echo "PASS" || echo "FAIL")" "$TRANSFER_SC")")

# ── Phase 8: Verification ─────────────────────────────────────────────
echo ""
echo "--- Phase 8: Final Verification ---"

step "Verify Domain Graph"   GET "/api/v1/domains/$DOMAIN_ID/graph" 200 ""
step "Verify Runs List"      GET "/api/v1/runs?domain_id=$DOMAIN_ID" 200 ""
step "Verify Release Status" GET "/api/v1/releases/$REL_ID" 200 ""
step "Status Dashboard"      GET "/api/v1/status/dashboard" 200 ""

# ══════════════════════════════════════════════════════════════════════════
# Report
# ══════════════════════════════════════════════════════════════════════════

ELAPSED=$(($(date +%s) - START_TS))
SUCCESS="false"
[ "$FAILED" -eq 0 ] && SUCCESS="true"

REPORT_FILE="$REPORT_DIR/e2e-pipeline-report-$(date +%Y%m%d-%H%M%S).json"
python3 -c "
import json, sys
steps = [json.loads(s) for s in sys.argv[1:]]
report = {
    'pipeline': 'cosmoport2-e2e',
    'timestamp': '$TS',
    'target': '$BASE_URL',
    'elapsed': $ELAPSED,
    'passed': $PASSED,
    'failed': $FAILED,
    'total': len(steps),
    'success': $SUCCESS,
    'steps': steps,
    'entities': {
        'domain': '$DOMAIN_ID',
        'app_l0': '$APP_L0',
        'app_l1': '$APP_L1',
        'plan': '$PLAN_ID',
        'run': '$RUN_ID',
        'release': '$REL_ID',
        'transfer_zone': '$ZONE'
    }
}
with open('$REPORT_FILE', 'w') as f:
    json.dump(report, f, indent=2)
" "${STEPS[@]}" 2>/dev/null || true

echo ""
echo "=== E2E Pipeline Complete ==="
echo "  Elapsed : ${ELAPSED}s"
echo "  Passed  : $PASSED"
echo "  Failed  : $FAILED"
echo "  Report  : $REPORT_FILE"
echo ""

[ "$FAILED" -eq 0 ] && exit 0 || exit 1