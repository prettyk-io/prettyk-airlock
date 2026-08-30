#!/usr/bin/env bash
# Cosmoport 2.0 — Automated E2E Release Pipeline Runner (SAN-015 / COS-091 / CLN-009)
#
# Full canonical lifecycle — all phases OK:
#   Domain → App (L0+L1) → Build → Bricks → Plan → Run → Batches → Gates (SoD) → Release → Deploy (ЗР→ЗТ) → Transfer-v2
#
#   ./services/scripts/run-e2e-pipeline.sh [base_url]
#
# Prerequisites:
#   uvicorn orchestrator.cosmo.api.main:app --port 8100
set -euo pipefail

BASE_URL="${1:-http://127.0.0.1:8100}"
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
BUILD_ID="bld-e2e-$SUFFIX"
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
    local opts=(
        -s -o /dev/null -w "%{http_code}" -X "$method" --max-time 10
        -H "Authorization: Bearer cosmo_e2e_sec_officer_token"
        -H "X-Cosmo-Domain: $DOMAIN_ID"
        -H "X-Cosmo-Zone: zr"
        -H "X-User-Roles: security_officer,admin_sec"
        -H "X-User-Id: sec_officer_e2e"
    )
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
    printf "  %-4s %-55s HTTP %s\n" "$icon" "$label" "$sc"
    STEPS+=("$(printf '{"step":"%s","status":"%s","httpCode":%s}' "$label" "$status" "$sc")")
}

# step_json — like step but extracts a field from JSON response body
step_json() {
    local label="$1" method="$2" uri="$3" expected="${4:-200}" body="${5:-}" jq_expr="${6:-id}"
    local sc_opts=(
        -s -o /dev/null -w "%{http_code}" -X "$method" --max-time 10
        -H "Authorization: Bearer cosmo_e2e_sec_officer_token"
        -H "X-Cosmo-Domain: $DOMAIN_ID"
        -H "X-Cosmo-Zone: zr"
        -H "X-User-Roles: security_officer,admin_sec"
        -H "X-User-Id: sec_officer_e2e"
    )
    if [ -n "$body" ]; then
        sc_opts+=(-H "Content-Type: application/json" -d "$body")
    fi
    local resp
    resp=$(curl -s -X "$method" --max-time 10 \
        -H "Authorization: Bearer cosmo_e2e_sec_officer_token" \
        -H "X-Cosmo-Domain: $DOMAIN_ID" \
        -H "X-Cosmo-Zone: zr" \
        -H "X-User-Roles: security_officer,admin_sec" \
        -H "X-User-Id: sec_officer_e2e" \
        ${body:+-H "Content-Type: application/json" -d "$body"} \
        "$BASE_URL$uri" 2>/dev/null || echo '{}')
    local sc
    sc=$(curl "${sc_opts[@]}" "$BASE_URL$uri" 2>/dev/null || echo "000")
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
    printf "  %-4s %-55s HTTP %s\n" "$icon" "$label" "$sc"
    STEPS+=("$(printf '{"step":"%s","status":"%s","httpCode":%s}' "$label" "$status" "$sc")")
    echo "$resp"
}

# ───────────────────────────────────────────────────────────────────────

mkdir -p "$REPORT_DIR"

echo ""
echo "=== Cosmoport 2.0 — E2E Release Pipeline (SAN-015) ==="
echo "  Target : $BASE_URL"
echo "  Domain : $DOMAIN_ID"
echo "  Time   : $TS"
echo ""

# ── Phase 1: Domain & Apps (Vault-guarded) ──────────────────────────────────
echo "--- Phase 1: Domain & Applications ---"

step "Create Domain" POST "/api/v1/domains" 201 \
    "{\"id\":\"$DOMAIN_ID\",\"label\":\"E2E Steel Thread Domain\",\"forge_binding\":{\"forge_type\":\"gitea\",\"url\":\"http://cosmo-gitea:3000\",\"token_ref\":\"vault:secret/cosmo/forge/gitea\"}}"

step "Create Application L0 (library)" POST "/api/v1/apps" 201 \
    "{\"id\":\"$APP_L0\",\"domain_id\":\"$DOMAIN_ID\",\"level\":0,\"repo_binding\":{\"forge_id\":\"gitea\",\"repo_path\":\"$DOMAIN_ID/lib-common\"}}"

step "Create Application L1 (service)" POST "/api/v1/apps" 201 \
    "{\"id\":\"$APP_L1\",\"domain_id\":\"$DOMAIN_ID\",\"level\":1,\"repo_binding\":{\"forge_id\":\"gitea\",\"repo_path\":\"$DOMAIN_ID/api-gateway\"}}"

# ── Phase 2: Builds (SAN-012, capture ID from API) ────────────────────────
echo ""
echo "--- Phase 2: Builds (SAN-012) ---"

BUILD_JSON=$(step_json "Trigger App Build" POST "/api/v1/apps/$APP_L1/builds" 201 \
    "{\"commit_sha\":\"e4d909c290d0fb1ca068ffaddf22cbd0adddef11\",\"branch\":\"main\",\"initiator_user_id\":\"dev_e2e\"}" \
    "id")
CAPTURED_ID=$(echo "$BUILD_JSON" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('id',''))" 2>/dev/null || echo "")
if [ -n "$CAPTURED_ID" ]; then
    BUILD_ID="$CAPTURED_ID"
fi
echo "  Captured Build ID: $BUILD_ID"

step "List App Builds" GET "/api/v1/apps/$APP_L1/builds" 200

# ── Phase 3: Bricks & Plan Compilation ───────────────────────────────────────
echo ""
echo "--- Phase 3: Bricks & Plan Compilation ---"

step "Create Brick: Build" POST "/api/v1/bricks" 201 \
    "{\"id\":\"$BRICK_B\",\"name\":\"App Build\",\"type\":\"build\",\"source\":\"internal\",\"definition\":{\"executor\":\"woodpecker\",\"image\":\"golang:1.22\",\"timeout_s\":600}}"

step "Create Brick: SAST" POST "/api/v1/bricks" 201 \
    "{\"id\":\"$BRICK_S\",\"name\":\"Sonar SAST\",\"type\":\"sast\",\"source\":\"internal\",\"definition\":{\"executor\":\"woodpecker\",\"image\":\"sonarsource/sonar-scanner-cli:latest\",\"timeout_s\":1200},\"depends_on\":[\"$BRICK_B\"]}"

step "Create Brick: DAST" POST "/api/v1/bricks" 201 \
    "{\"id\":\"$BRICK_D\",\"name\":\"ZAP DAST\",\"type\":\"dast\",\"source\":\"internal\",\"definition\":{\"executor\":\"woodpecker\",\"image\":\"zaproxy/zap-stable:2.17.0\",\"timeout_s\":1800},\"depends_on\":[\"$BRICK_S\"]}"

step "Compile Plan (8-step lifecycle)" POST "/api/v1/plans/compile" 201 \
    "{\"plan_id\":\"$PLAN_ID\",\"app_id\":\"$APP_L1\",\"brick_ids\":[\"$BRICK_B\",\"$BRICK_S\",\"$BRICK_D\"]}"

# ── Phase 4: Run & Batches Lifecycle ─────────────────────────────────────────
echo ""
echo "--- Phase 4: Run & Batches ---"

step "Create Run" POST "/api/v1/runs" 201 \
    "{\"id\":\"$RUN_ID\",\"plan_id\":\"$PLAN_ID\",\"trigger\":\"manual\",\"domain_id\":\"$DOMAIN_ID\",\"initiator_user_id\":\"e2e-operator\"}"

step "Run: running" PATCH "/api/v1/runs/$RUN_ID/status" 200 "{\"status\":\"running\"}"
step "Run: succeeded" PATCH "/api/v1/runs/$RUN_ID/status" 200 "{\"status\":\"succeeded\"}"

# ── Phase 5: Security Gates (SoD Compliance) ─────────────────────────────────
echo ""
echo "--- Phase 5: Security Gates (SoD) ---"

step "Create Gate: Automatic" POST "/api/v1/gates" 201 \
    "{\"id\":\"$GATE_A\",\"plan_id\":\"$PLAN_ID\",\"type\":\"automatic\",\"position\":0,\"policy\":{\"rules\":[{\"finding_type\":\"Critical\",\"action\":\"block\"}]}}"

step "Create Gate: Manual" POST "/api/v1/gates" 201 \
    "{\"id\":\"$GATE_M\",\"plan_id\":\"$PLAN_ID\",\"type\":\"manual\",\"position\":1,\"policy\":{\"rules\":[{\"finding_type\":\"Critical\",\"action\":\"block\"}]}}"

step "Gate Auto: decide PASS" POST "/api/v1/gates/$GATE_A/decision" 200 \
    "{\"decision\":\"pass\",\"decided_by\":\"sec_officer_independent@bank.corp\"}"

step "Gate Manual: decide PASS" POST "/api/v1/gates/$GATE_M/decision" 200 \
    "{\"decision\":\"pass\",\"decided_by\":\"sec_officer_independent@bank.corp\",\"signature\":\"gost_sig_2026\"}"

# ── Phase 6a: Deploy to ЗР (SAN-013 — bare stand) ─────────────────────────
echo ""
echo "--- Phase 6a: Deployments — ЗР (Development Zone, bare stand) ---"

step "Create Deployment in ЗР (bare)" POST "/api/v1/apps/$APP_L1/deploys" 201 \
    "{\"build_id\":\"$BUILD_ID\",\"target_zone\":\"zr\",\"segment\":\"bare\",\"env_vars\":{\"ENV\":\"dev\",\"PORT\":\"3000\"}}"

step "Verify Deployments in ЗР" GET "/api/v1/apps/$APP_L1/deploys?target_zone=zr" 200

# ── Phase 6b: Deploy to ЗТ (SAN-013 — integration stand) ────────────────────
echo ""
echo "--- Phase 6b: Deployments — ЗТ (Testing Zone, integration stand) ---"

step "Create Deployment in ЗТ (integration)" POST "/api/v1/apps/$APP_L1/deploys" 201 \
    "{\"build_id\":\"$BUILD_ID\",\"target_zone\":\"zt\",\"segment\":\"integration\",\"env_vars\":{\"ENV\":\"test\",\"PORT\":\"8080\"}}"

step "Verify Deployments in ЗТ" GET "/api/v1/apps/$APP_L1/deploys?target_zone=zt" 200

step "List All App Deployments" GET "/api/v1/apps/$APP_L1/deploys" 200

# ── Phase 7: Release & Linear Transfer ───────────────────────────────────────
echo ""
echo "--- Phase 7: Release & Linear Transfer-v2 ---"

step "Create Release" POST "/api/v1/releases" 201 \
    "{\"id\":\"$REL_ID\",\"domain_id\":\"$DOMAIN_ID\",\"plan_id\":\"$PLAN_ID\",\"run_ids\":[\"$RUN_ID\"],\"trigger\":\"manual\",\"version\":\"1.0.0-e2e\"}"

step "Release: Submit" POST "/api/v1/releases/$REL_ID/submit" 200 ""

step "Release: Approve" POST "/api/v1/releases/$REL_ID/approve" 200 \
    "{\"decided_by\":\"sec_officer_independent@bank.corp\",\"decision\":\"approved\",\"comment\":\"Gates verified\"}"

step "Release: Deploy" POST "/api/v1/releases/$REL_ID/deploy" 200 ""

step "Release: Transfer-v2 ZR→ZT" POST "/api/v1/releases/$REL_ID/transfer-v2" 200 \
    "{\"target_zone\":\"zt\",\"officer_name\":\"Петров П.С.\",\"sign_signature\":\"gost_sig_hex\"}"

# ── Phase 8: Verification & Evidence ─────────────────────────────────────────
echo ""
echo "--- Phase 8: Verification & Evidence ---"

step "GOST-Act (JSON)" GET "/api/v1/runs/$RUN_ID/gost-act" 200
step "GOST-Act (HTML)" GET "/api/v1/runs/$RUN_ID/gost-act/html" 200
step "Evidence Chain" GET "/api/v1/runs/$RUN_ID/evidence" 200
step "Verify Release Status" GET "/api/v1/releases/$REL_ID" 200
step "Status Dashboard" GET "/api/v1/status/dashboard" 200

# ── Report Summary ───────────────────────────────────────────────────────────
END_TS=$(date +%s)
ELAPSED=$((END_TS - START_TS))

echo ""
echo "=== E2E Pipeline Complete ==="
echo "  Elapsed : ${ELAPSED}s"
echo "  Passed  : $PASSED"
echo "  Failed  : $FAILED"
echo ""

[ "$FAILED" -eq 0 ] && exit 0 || exit 1
