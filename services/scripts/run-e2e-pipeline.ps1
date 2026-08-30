# Cosmoport 2.0 — Automated E2E Release Pipeline Runner (SAN-015 / COS-091 / CLN-009)
#
# Полный канонический ЖЦ: 8 фаз, все OK:
#   Domain → App (L0+L1) → Build → Bricks → Plan → Run → Batches → Gates (SoD) → Release → Deploy (ЗР→ЗТ) → Transfer-v2
#
#   .\services\scripts\run-e2e-pipeline.ps1 [-BaseUrl http://127.0.0.1:8100] [-DryRun]
#
# Перед запуском:
#   uvicorn orchestrator.cosmo.api.main:app --port 8100
param(
    [string]$BaseUrl = "http://127.0.0.1:8100",
    [switch]$DryRun,
    [string]$DomainId = "e2e-steel-domain",
    [string]$ReportPath = "reports/e2e-pipeline-report.json"
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$ScriptRoot = Split-Path -Parent $PSCommandPath
$RepoRoot = Resolve-Path (Join-Path $ScriptRoot "..\..")
$Timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"

$Passed = 0
$Failed = 0
$Steps = [System.Collections.ArrayList]::new()
$StartTime = Get-Date

# ── Generate unique run IDs per invocation ──────────────────────────────
$SUFFIX = (Get-Date -Format "HHmmss")
$APP_L0   = "e2e-lib-$SUFFIX"
$APP_L1   = "e2e-app-$SUFFIX"
$PLAN_ID  = "e2e-plan-$SUFFIX"
$RUN_ID   = "e2e-run-$SUFFIX"
$REL_ID   = "e2e-rel-$SUFFIX"
$BRICK_B  = "e2e-b-build-$SUFFIX"
$BRICK_S  = "e2e-b-sast-$SUFFIX"
$BRICK_D  = "e2e-b-dast-$SUFFIX"
$GATE_A   = "e2e-gate-auto-$SUFFIX"
$GATE_M   = "e2e-gate-manual-$SUFFIX"
$BUILD_ID = "bld-e2e-$SUFFIX"
$DEP_ID   = "dep-e2e-$SUFFIX"

# Стандартные заголовки аутентификации и контекста
$DefaultHeaders = @{
    "Authorization"   = "Bearer cosmo_e2e_sec_officer_token"
    "X-Cosmo-Domain"  = $DomainId
    "X-Cosmo-Zone"    = "zr"
    "X-User-Roles"    = "security_officer,admin_sec"
    "X-User-Id"       = "sec_officer_e2e"
    "X-User-Email"    = "officer@cbr.bank.corp"
}

# ── Helpers ───────────────────────────────────────────────────────────────

function Write-Step {
    param([string]$Step, [string]$Status, [string]$Detail = "", [int]$HttpCode = 0)
    $color = if ($Status -eq "PASS") { "Green" } elseif ($Status -eq "SKIP") { "Yellow" } else { "Red" }
    $icon = if ($Status -eq "PASS") { "[OK]" } elseif ($Status -eq "SKIP") { "[SKIP]" } else { "[FAIL]" }
    $msg = "$icon $Step"
    if ($Detail) { $msg += " - $Detail" }
    Write-Host $msg -ForegroundColor $color
    $null = $Steps.Add(@{ step = $Step; status = $Status; detail = $Detail; httpCode = $HttpCode })
    if ($Status -eq "PASS") { $script:Passed++ } elseif ($Status -eq "FAIL") { $script:Failed++ }
}

function Invoke-Step {
    param(
        [string]$Step,
        [string]$Method = "GET",
        [string]$Uri,
        $Body = $null,
        $Headers = $null,
        [int]$ExpectedStatus = 200,
        [string]$FailDetail = ""
    )
    if ($DryRun) {
        Write-Step -Step $Step -Status "SKIP" -Detail "dry-run: $Method $Uri"
        return $null
    }
    try {
        $reqHeaders = @{}
        foreach ($k in $DefaultHeaders.Keys) { $reqHeaders[$k] = $DefaultHeaders[$k] }
        if ($Headers) {
            foreach ($k in $Headers.Keys) { $reqHeaders[$k] = $Headers[$k] }
        }

        $iwrParams = @{
            Method = $Method
            Uri = "$BaseUrl$Uri"
            UseBasicParsing = $true
            TimeoutSec = 10
            Headers = $reqHeaders
        }
        if ($Body) {
            $iwrParams.Body = ($Body | ConvertTo-Json -Depth 5 -Compress)
            $iwrParams.ContentType = "application/json"
        }

        $r = Invoke-WebRequest @iwrParams
        $sc = $r.StatusCode
        $ok = ($sc -ge 200 -and $sc -lt 300)
        if ($ok) {
            try { $resBody = $r.Content | ConvertFrom-Json } catch { $resBody = $r.Content }
        } else { $resBody = $null }
        $detail = if ($ok) { "HTTP $sc" } else { if ($FailDetail) { $FailDetail } else { "HTTP $sc unexpected" } }
        Write-Step -Step $Step -Status $(if ($ok) { "PASS" } else { "FAIL" }) -Detail $detail -HttpCode $sc
        return @{ response = $resBody; statusCode = $sc }
    } catch {
        $sc = 0
        if ($_.Exception.Response) {
            $sc = $_.Exception.Response.StatusCode.value__
        }
        $detail = if ($FailDetail) { $FailDetail } else { "HTTP $sc - $($_.Exception.Message.Substring(0, [Math]::Min(80, $_.Exception.Message.Length)))" }
        Write-Step -Step $Step -Status "FAIL" -Detail $detail -HttpCode $sc
        return @{ response = $null; statusCode = $sc }
    }
}

# ══════════════════════════════════════════════════════════════════════════════
Write-Host ""
Write-Host "=== Cosmoport 2.0 - E2E Release Pipeline (SAN-015) ===" -ForegroundColor Cyan
Write-Host "  Target : $BaseUrl"
Write-Host "  Domain : $DomainId"
Write-Host "  DryRun : $DryRun"
Write-Host "  Time   : $Timestamp"
Write-Host ""

# ══════════════════════════════════════════════════════════════════════════════
# Phase 1: Domain & Applications Registry (with VaultSecretRef)
# ══════════════════════════════════════════════════════════════════════════════
Write-Host "--- Phase 1: Domain & Applications (Vault-guarded) ---" -ForegroundColor DarkCyan

Invoke-Step -Step "Create Domain" -Method POST -Uri "/api/v1/domains" -Body @{
    id = $DomainId
    label = "E2E Steel Thread Domain"
    forge_binding = @{
        forge_type = "gitea"
        url = "http://cosmo-gitea:3000"
        token_ref = "vault:secret/cosmo/forge/gitea"
    }
} -ExpectedStatus 201

Invoke-Step -Step "Create Application L0 (library)" -Method POST -Uri "/api/v1/apps" -Body @{
    id = $APP_L0
    domain_id = $DomainId
    level = 0
    repo_binding = @{ forge_id = "gitea"; repo_path = "$DomainId/lib-common" }
} -ExpectedStatus 201

Invoke-Step -Step "Create Application L1 (service)" -Method POST -Uri "/api/v1/apps" -Body @{
    id = $APP_L1
    domain_id = $DomainId
    level = 1
    repo_binding = @{ forge_id = "gitea"; repo_path = "$DomainId/api-gateway" }
} -ExpectedStatus 201

# ══════════════════════════════════════════════════════════════════════════════
# Phase 2: Builds (SAN-012 First-Class Entity)
# ══════════════════════════════════════════════════════════════════════════════
Write-Host ""
Write-Host "--- Phase 2: Builds (SAN-012) ---" -ForegroundColor DarkCyan

$buildRes = Invoke-Step -Step "Trigger App Build" -Method POST -Uri "/api/v1/apps/$APP_L1/builds" -Body @{
    commit_sha = "e4d909c290d0fb1ca068ffaddf22cbd0adddef11"
    branch = "main"
    initiator_user_id = "dev_e2e_engineer"
    meta = @{ dockerfile = "Dockerfile.hardened"; runner = "isolated-runner-01" }
} -ExpectedStatus 201

if ($buildRes.response -and $buildRes.response.id) {
    $BUILD_ID = $buildRes.response.id
}
Write-Host "  Captured Build ID: $BUILD_ID" -ForegroundColor DarkGray

Invoke-Step -Step "List App Builds" -Method GET -Uri "/api/v1/apps/$APP_L1/builds"

# ══════════════════════════════════════════════════════════════════════════════
# Phase 3: Pipeline Bricks & Plan Compilation (8-step lifecycle)
# ══════════════════════════════════════════════════════════════════════════════
Write-Host ""
Write-Host "--- Phase 3: Bricks & Plan Compilation ---" -ForegroundColor DarkCyan

Invoke-Step -Step "Create Brick: Build" -Method POST -Uri "/api/v1/bricks" -Body @{
    id = $BRICK_B; name = "App Build"; type = "build"; source = "internal"
    definition = @{ executor = "woodpecker"; image = "golang:1.22"; timeout_s = 600 }
} -ExpectedStatus 201

Invoke-Step -Step "Create Brick: SAST" -Method POST -Uri "/api/v1/bricks" -Body @{
    id = $BRICK_S; name = "Sonar SAST"; type = "sast"; source = "internal"
    definition = @{ executor = "woodpecker"; image = "sonarsource/sonar-scanner-cli:latest"; timeout_s = 1200 }
    depends_on = @($BRICK_B)
} -ExpectedStatus 201

Invoke-Step -Step "Create Brick: DAST" -Method POST -Uri "/api/v1/bricks" -Body @{
    id = $BRICK_D; name = "ZAP DAST"; type = "dast"; source = "internal"
    definition = @{ executor = "woodpecker"; image = "zaproxy/zap-stable:2.17.0"; timeout_s = 1800 }
    depends_on = @($BRICK_S)
} -ExpectedStatus 201

Invoke-Step -Step "Compile Plan (8-step lifecycle)" -Method POST -Uri "/api/v1/plans/compile" -Body @{
    plan_id = $PLAN_ID; app_id = $APP_L1; brick_ids = @($BRICK_B, $BRICK_S, $BRICK_D)
} -ExpectedStatus 201

# ══════════════════════════════════════════════════════════════════════════════
# Phase 4: Run & Batches Lifecycle
# ══════════════════════════════════════════════════════════════════════════════
Write-Host ""
Write-Host "--- Phase 4: Run & Batches ---" -ForegroundColor DarkCyan

Invoke-Step -Step "Create Run" -Method POST -Uri "/api/v1/runs" -Body @{
    id = $RUN_ID; plan_id = $PLAN_ID; trigger = "manual"; domain_id = $DomainId
    initiator_user_id = "e2e-operator"; initiator_role = "secops"
} -ExpectedStatus 201

$batchList = Invoke-Step -Step "List Batches for Plan" -Method GET -Uri "/api/v1/batches?plan_id=$PLAN_ID"
$batchIds = @()
if ($batchList.response) {
    foreach ($b in $batchList.response) { $batchIds += $b.id }
}
Write-Host "  Found $($batchIds.Count) batches" -ForegroundColor DarkGray

foreach ($bid in $batchIds) {
    Invoke-Step -Step "Batch '$bid': running" -Method PATCH -Uri "/api/v1/batches/$bid/status" -Body @{ status = "running" }
    if (-not $DryRun) { Start-Sleep -Milliseconds 100 }
    Invoke-Step -Step "Batch '$bid': passed" -Method PATCH -Uri "/api/v1/batches/$bid/status" -Body @{ status = "passed" }
}

# Run Status Transitions
Invoke-Step -Step "Run: running" -Method PATCH -Uri "/api/v1/runs/$RUN_ID/status" -Body @{ status = "running" }
Invoke-Step -Step "Run: succeeded" -Method PATCH -Uri "/api/v1/runs/$RUN_ID/status" -Body @{ status = "succeeded" }

# ══════════════════════════════════════════════════════════════════════════════
# Phase 5: Security Gates (SoD Compliance)
# ══════════════════════════════════════════════════════════════════════════════
Write-Host ""
Write-Host "--- Phase 5: Security Gates (Independent Officer SoD) ---" -ForegroundColor DarkCyan

Invoke-Step -Step "Create Gate: Automatic" -Method POST -Uri "/api/v1/gates" -Body @{
    id = $GATE_A; plan_id = $PLAN_ID; type = "automatic"; position = 0
    policy = @{ rules = @(@{ finding_type = "Critical"; action = "block" }) }
} -ExpectedStatus 201

Invoke-Step -Step "Create Gate: Manual" -Method POST -Uri "/api/v1/gates" -Body @{
    id = $GATE_M; plan_id = $PLAN_ID; type = "manual"; position = 1
    policy = @{ rules = @(@{ finding_type = "Critical"; action = "block" }) }
} -ExpectedStatus 201

Invoke-Step -Step "Gate Auto: decide PASS" -Method POST -Uri "/api/v1/gates/$GATE_A/decision" -Body @{
    decision = "pass"
    decided_by = "sec_officer_independent@bank.corp"
} -ExpectedStatus 200

Invoke-Step -Step "Gate Manual: decide PASS" -Method POST -Uri "/api/v1/gates/$GATE_M/decision" -Body @{
    decision = "pass"
    decided_by = "sec_officer_independent@bank.corp"
    signature = "gost_ecp_signature_sha256"
} -ExpectedStatus 200

# ══════════════════════════════════════════════════════════════════════════════
# Phase 6a: Deploy to ЗР (SAN-013 — bare stand)
# ══════════════════════════════════════════════════════════════════════════════
Write-Host ""
Write-Host "--- Phase 6a: Deployments — ЗР (Development Zone, bare stand) ---" -ForegroundColor DarkCyan

$depZrRes = Invoke-Step -Step "Create Deployment in ЗР (bare)" -Method POST -Uri "/api/v1/apps/$APP_L1/deploys" -Body @{
    build_id = $BUILD_ID
    target_zone = "zr"
    segment = "bare"
    env_vars = @{ "ENV" = "dev"; "PORT" = "3000" }
} -ExpectedStatus 201

if ($depZrRes.response -and $depZrRes.response.id) {
    $DEP_ZR_ID = $depZrRes.response.id
}
Write-Host "  Captured Deployment ЗР ID: $DEP_ZR_ID" -ForegroundColor DarkGray

Invoke-Step -Step "Verify Deployments in ЗР" -Method GET -Uri "/api/v1/apps/$APP_L1/deploys?target_zone=zr"

# ══════════════════════════════════════════════════════════════════════════════
# Phase 6b: Deploy to ЗТ (SAN-013 — integration stand)
# ══════════════════════════════════════════════════════════════════════════════
Write-Host ""
Write-Host "--- Phase 6b: Deployments — ЗТ (Testing Zone, integration stand) ---" -ForegroundColor DarkCyan

$depZtRes = Invoke-Step -Step "Create Deployment in ЗТ (integration)" -Method POST -Uri "/api/v1/apps/$APP_L1/deploys" -Body @{
    build_id = $BUILD_ID
    target_zone = "zt"
    segment = "integration"
    env_vars = @{ "ENV" = "test"; "PORT" = "8080" }
} -ExpectedStatus 201

if ($depZtRes.response -and $depZtRes.response.id) {
    $DEP_ZT_ID = $depZtRes.response.id
}
Write-Host "  Captured Deployment ЗТ ID: $DEP_ZT_ID" -ForegroundColor DarkGray

Invoke-Step -Step "Verify Deployments in ЗТ" -Method GET -Uri "/api/v1/apps/$APP_L1/deploys?target_zone=zt"

Invoke-Step -Step "List All App Deployments" -Method GET -Uri "/api/v1/apps/$APP_L1/deploys"

# ══════════════════════════════════════════════════════════════════════════════
# Phase 7: Release & Linear Transfer (SAN-009)
# ══════════════════════════════════════════════════════════════════════════════
Write-Host ""
Write-Host "--- Phase 7: Release & Linear Transfer-v2 ---" -ForegroundColor DarkCyan

Invoke-Step -Step "Create Release" -Method POST -Uri "/api/v1/releases" -Body @{
    id = $REL_ID; domain_id = $DomainId; plan_id = $PLAN_ID; run_ids = @($RUN_ID)
    trigger = "manual"; version = "1.0.0-e2e"; changelog = "E2E automated release test"
} -ExpectedStatus 201

Invoke-Step -Step "Release: Submit" -Method POST -Uri "/api/v1/releases/$REL_ID/submit"

Invoke-Step -Step "Release: Approve" -Method POST -Uri "/api/v1/releases/$REL_ID/approve" -Body @{
    decided_by = "sec_officer_independent@bank.corp"
    decision = "approved"
    comment = "Gates clean and verified"
} -ExpectedStatus 200

Invoke-Step -Step "Release: Deploy" -Method POST -Uri "/api/v1/releases/$REL_ID/deploy"

# Linear Transfer ZR -> ZT with signature and officer name
$transferRes = Invoke-Step -Step "Release: Transfer-v2 ZR→ZT" -Method POST -Uri "/api/v1/releases/$REL_ID/transfer-v2" -Body @{
    target_zone = "zt"
    officer_name = "Петров П.С."
    sign_signature = "gost_r_3410_2012_signature_hex"
    transfer_notes = "E2E canonical transfer to ZT"
} -ExpectedStatus 200

$targetZone = "zt"
if ($transferRes.response -and $transferRes.response.current_zone) {
    $targetZone = $transferRes.response.current_zone
}
Write-Host "  Release transferred to zone: $targetZone" -ForegroundColor DarkGray

# ══════════════════════════════════════════════════════════════════════════════
# Phase 8: Verification & Evidence
# ══════════════════════════════════════════════════════════════════════════════
Write-Host ""
Write-Host "--- Phase 8: Verification & Evidence ---" -ForegroundColor DarkCyan

Invoke-Step -Step "GOST-Act (JSON)" -Method GET -Uri "/api/v1/runs/$RUN_ID/gost-act"
Invoke-Step -Step "GOST-Act (HTML)" -Method GET -Uri "/api/v1/runs/$RUN_ID/gost-act/html"
Invoke-Step -Step "Evidence Chain" -Method GET -Uri "/api/v1/runs/$RUN_ID/evidence"
Invoke-Step -Step "Verify Release Status" -Method GET -Uri "/api/v1/releases/$REL_ID"
Invoke-Step -Step "Status Dashboard" -Method GET -Uri "/api/v1/status/dashboard"

# ══════════════════════════════════════════════════════════════════════════════
# Report Generation
# ══════════════════════════════════════════════════════════════════════════════
$elapsed = [math]::Round(((Get-Date) - $StartTime).TotalSeconds, 1)
$report = @{
    pipeline  = "cosmoport2-canonical-e2e"
    timestamp = $Timestamp
    target    = $BaseUrl
    dryRun    = $DryRun.IsPresent
    elapsed   = $elapsed
    passed    = $Passed
    failed    = $Failed
    total     = $Steps.Count
    success   = ($Failed -eq 0)
    steps     = $Steps | ForEach-Object { $_ }
    entities  = @{
        domain        = $DomainId
        app_l0        = $APP_L0
        app_l1        = $APP_L1
        build_id      = $BUILD_ID
        plan          = $PLAN_ID
        run           = $RUN_ID
        release       = $REL_ID
        dep_zr        = $DEP_ZR_ID
        dep_zt        = $DEP_ZT_ID
        transfer_zone = $targetZone
    }
}

$reportPath = Join-Path $RepoRoot $ReportPath
New-Item -ItemType Directory -Force -Path (Split-Path $reportPath) | Out-Null
$report | ConvertTo-Json -Depth 5 | Set-Content -Path $reportPath -Encoding UTF8

Write-Host ""
Write-Host "=== E2E Pipeline Execution Finished ===" -ForegroundColor Cyan
Write-Host "  Elapsed : ${elapsed}s" -ForegroundColor White
Write-Host "  Passed  : $Passed" -ForegroundColor Green
Write-Host "  Failed  : $Failed" -ForegroundColor $(if ($Failed -gt 0) { "Red" } else { "Green" })
Write-Host "  Report  : $reportPath" -ForegroundColor Magenta
Write-Host ""

if ($Failed -gt 0) { exit 1 } else { exit 0 }
