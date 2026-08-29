# Cosmoport 2.0 - Automated E2E Release Pipeline Runner (COS-091)
#
# Выполняет полный боевой сценарий:
#   Domain → App (L0+L1) → Bricks → Plan → Run → Batches → Gates → GOST-Act → Release → Transfer
#
#   .\services\scripts\run-e2e-pipeline.ps1 [-BaseUrl http://127.0.0.1:8080] [-DryRun]
#
# Перед запуском:
#   docker compose up -d cosmo-postgres cosmo-valkey cosmo-api cosmo-caddy
param(
    [string]$BaseUrl = "http://127.0.0.1:8080",
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
        $Headers = @{},
        [int]$ExpectedStatus = 200,
        [string]$FailDetail = ""
    )
    if ($DryRun) {
        Write-Step -Step $Step -Status "SKIP" -Detail "dry-run: $Method $Uri"
        return $null
    }
    try {
        $iwrParams = @{ Method = $Method; Uri = "$BaseUrl$Uri"; UseBasicParsing = $true; TimeoutSec = 10 }
        if ($Headers.Count -gt 0) { $iwrParams.Headers = $Headers }
        if ($Body) { $iwrParams.Body = ($Body | ConvertTo-Json -Depth 4 -Compress); $iwrParams.ContentType = "application/json" }
        $r = Invoke-WebRequest @iwrParams
        $sc = $r.StatusCode
        $ok = ($sc -ge 200 -and $sc -lt 300)
        if ($ok) {
            try { $body = $r.Content | ConvertFrom-Json } catch { $body = $r.Content }
        } else { $body = $null }
        $detail = if ($ok) { "HTTP $sc" } else { if ($FailDetail) { $FailDetail } else { "HTTP $sc unexpected" } }
        Write-Step -Step $Step -Status $(if ($ok) { "PASS" } else { "FAIL" }) -Detail $detail -HttpCode $sc
        return @{ response = $body; statusCode = $sc }
    } catch {
        $sc = $_.Exception.Response.StatusCode.value__
        $detail = if ($FailDetail) { $FailDetail } else { "HTTP $sc - $($_.Exception.Message.Substring(0, [Math]::Min(80, $_.Exception.Message.Length)))" }
        Write-Step -Step $Step -Status "FAIL" -Detail $detail -HttpCode $sc
        return @{ response = $null; statusCode = $sc }
    }
}

# �═════════════════════════════════════════════════════════════════════════════
Write-Host ""
Write-Host "=== Cosmoport 2.0 - E2E Release Pipeline ===" -ForegroundColor Cyan
Write-Host "  Target : $BaseUrl"
Write-Host "  Domain : $DomainId"
Write-Host "  DryRun : $DryRun"
Write-Host "  Time   : $Timestamp"
Write-Host ""

# ══════════════════════════════════════════════════════════════════════════════
# Phase 1: Domain & Applications Registry
# ══════════════════════════════════════════════════════════════════════════════
Write-Host "--- Phase 1: Domain & Applications ---" -ForegroundColor DarkCyan

Invoke-Step -Step "Create Domain" -Method POST -Uri "/api/v1/domains" -Body @{
    id = $DomainId; label = "E2E Steel Thread Domain"
    forge_binding = @{ forge_type = "gitea"; url = "http://cosmo-gitea:3000"; token_ref = "VAULT/E2E" }
} -ExpectedStatus 201

Invoke-Step -Step "Create Application L0 (library)" -Method POST -Uri "/api/v1/apps" -Body @{
    id = $APP_L0; domain_id = $DomainId; level = 0
    repo_binding = @{ forge_id = "gitea"; repo_path = "$DomainId/lib-common" }
} -ExpectedStatus 201

Invoke-Step -Step "Create Application L1 (service)" -Method POST -Uri "/api/v1/apps" -Body @{
    id = $APP_L1; domain_id = $DomainId; level = 1
    repo_binding = @{ forge_id = "gitea"; repo_path = "$DomainId/api-gateway" }
} -ExpectedStatus 201

# ══════════════════════════════════════════════════════════════════════════════
# Phase 2: Pipeline Bricks & Plan Compilation
# ══════════════════════════════════════════════════════════════════════════════
Write-Host ""
Write-Host "--- Phase 2: Bricks & Plan ---" -ForegroundColor DarkCyan

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

Invoke-Step -Step "Compile Plan" -Method POST -Uri "/api/v1/plans/compile" -Body @{
    plan_id = $PLAN_ID; app_id = $APP_L1; brick_ids = @($BRICK_B, $BRICK_S, $BRICK_D)
} -ExpectedStatus 201

# ══════════════════════════════════════════════════════════════════════════════
# Phase 3: Run & Batch Lifecycle
# ══════════════════════════════════════════════════════════════════════════════
Write-Host ""
Write-Host "--- Phase 3: Run & Batches ---" -ForegroundColor DarkCyan

Invoke-Step -Step "Create Run" -Method POST -Uri "/api/v1/runs" -Body @{
    id = $RUN_ID; plan_id = $PLAN_ID; trigger = "manual"; domain_id = $DomainId
    initiator_user_id = "e2e-operator"; initiator_role = "secops"
} -ExpectedStatus 201

# Simulate batch completion: fetch batches for the plan, advance each
$batchList = Invoke-Step -Step "List Batches for Plan" -Method GET -Uri "/api/v1/batches?plan_id=$PLAN_ID"
$batchIds = @()
if ($batchList.response) {
    foreach ($b in $batchList.response) { $batchIds += $b.id }
}
Write-Host "  Found $($batchIds.Count) batches: $batchIds" -ForegroundColor DarkGray

foreach ($bid in $batchIds) {
    Invoke-Step -Step "Batch '$bid': set running" -Method PATCH -Uri "/api/v1/batches/$bid/status" -Body @{ status = "running" }

    if (-not $DryRun) { Start-Sleep -Milliseconds 200 }

    Invoke-Step -Step "Batch '$bid': set passed" -Method PATCH -Uri "/api/v1/batches/$bid/status" -Body @{ status = "passed" }
}

# Advance Run lifecycle
foreach ($st in @("queued", "running")) {
    Invoke-Step -Step "Run: $st" -Method PATCH -Uri "/api/v1/runs/$RUN_ID/status" `
        -Headers @{ "X-Cosmo-Domain" = $DomainId } -Body @{ status = $st }
}

Invoke-Step -Step "Run: succeeded (final)" -Method PATCH -Uri "/api/v1/runs/$RUN_ID/status" `
    -Headers @{ "X-Cosmo-Domain" = $DomainId } -Body @{ status = "succeeded" }

# ══════════════════════════════════════════════════════════════════════════════
# Phase 4: Security Gates
# ══════════════════════════════════════════════════════════════════════════════
Write-Host ""
Write-Host "--- Phase 4: Security Gates ---" -ForegroundColor DarkCyan

Invoke-Step -Step "Create Gate: Automatic" -Method POST -Uri "/api/v1/gates" -Body @{
    id = $GATE_A; plan_id = $PLAN_ID; type = "automatic"; position = 0
    policy = @{ rules = @(@{ finding_type = "Critical"; action = "block" }, @{ finding_type = "High"; action = "warn"; max_count = 5 }) }
} -ExpectedStatus 201

Invoke-Step -Step "Create Gate: Manual" -Method POST -Uri "/api/v1/gates" -Body @{
    id = $GATE_M; plan_id = $PLAN_ID; type = "manual"; position = 1
    policy = @{ rules = @(@{ finding_type = "Critical"; action = "block" }) }
} -ExpectedStatus 201

Invoke-Step -Step "Gate Auto: decide PASS" -Method POST -Uri "/api/v1/gates/$GATE_A/decision" -Body @{
    decision = "pass"
} -ExpectedStatus 200

Invoke-Step -Step "Gate Manual: decide PASS" -Method POST -Uri "/api/v1/gates/$GATE_M/decision" -Body @{
    decision = "pass"; decided_by = "e2e-secops-lead@cosmoport.io"; signature = "e2e-sha256-test"
} -ExpectedStatus 200

# ══════════════════════════════════════════════════════════════════════════════
# Phase 5: GOST-Act & Evidence
# ══════════════════════════════════════════════════════════════════════════════
Write-Host ""
Write-Host "--- Phase 5: GOST-Act & Evidence ---" -ForegroundColor DarkCyan

Invoke-Step -Step "GOST-Act (JSON)" -Method GET -Uri "/api/v1/runs/$RUN_ID/gost-act"

Invoke-Step -Step "GOST-Act (HTML)" -Method GET -Uri "/api/v1/runs/$RUN_ID/gost-act/html"

Invoke-Step -Step "Evidence Chain" -Method GET -Uri "/api/v1/runs/$RUN_ID/evidence"

# ══════════════════════════════════════════════════════════════════════════════
# Phase 6: Release Lifecycle
# ══════════════════════════════════════════════════════════════════════════════
Write-Host ""
Write-Host "--- Phase 6: Release Lifecycle ---" -ForegroundColor DarkCyan

Invoke-Step -Step "Create Release" -Method POST -Uri "/api/v1/releases" -Body @{
    id = $REL_ID; domain_id = $DomainId; plan_id = $PLAN_ID; run_ids = @($RUN_ID)
    trigger = "manual"; version = "0.1.0-e2e"; changelog = "E2E automated release test"
} -ExpectedStatus 201

Invoke-Step -Step "Release: Submit" -Method POST -Uri "/api/v1/releases/$REL_ID/submit"

Invoke-Step -Step "Release: Approve" -Method POST -Uri "/api/v1/releases/$REL_ID/approve" -Body @{
    approved_by = "e2e-release-manager@cosmoport.io"
    role = "release_manager"
} -ExpectedStatus 200

Invoke-Step -Step "Release: Deploy" -Method POST -Uri "/api/v1/releases/$REL_ID/deploy"

# ══════════════════════════════════════════════════════════════════════════════
# Phase 7: Inter-zone Transfer (COS-054)
# ══════════════════════════════════════════════════════════════════════════════
Write-Host ""
Write-Host "--- Phase 7: Transfer to ZT ---" -ForegroundColor DarkCyan

$transferRes = Invoke-Step -Step "Release: Transfer ZR→ZT" -Method POST -Uri "/api/v1/releases/$REL_ID/transfer" -Body @{
    initiated_by = "e2e-operator@cosmoport.io"
    comment = "E2E pipeline automated transfer"
} -ExpectedStatus 200

$targetZone = "?"
if ($transferRes.response) {
    $targetZone = $transferRes.response.current_zone
}
Write-Host "  Release transferred to zone: $targetZone" -ForegroundColor DarkGray

# ══════════════════════════════════════════════════════════════════════════════
# Phase 8: Final Verification
# ══════════════════════════════════════════════════════════════════════════════
Write-Host ""
Write-Host "--- Phase 8: Final Verification ---" -ForegroundColor DarkCyan

# Check domain has the app
Invoke-Step -Step "Verify Domain Graph" -Method GET -Uri "/api/v1/domains/$DomainId/graph"

# Check runs for this domain
Invoke-Step -Step "Verify Runs List" -Method GET -Uri "/api/v1/runs?domain_id=$DomainId"

# Check release status
Invoke-Step -Step "Verify Release Status" -Method GET -Uri "/api/v1/releases/$REL_ID"

# Check status dashboard
Invoke-Step -Step "Status Dashboard" -Method GET -Uri "/api/v1/status/dashboard"

# ══════════════════════════════════════════════════════════════════════════════
# Report
# ══════════════════════════════════════════════════════════════════════════════
$elapsed = [math]::Round(((Get-Date) - $StartTime).TotalSeconds, 1)
$report = @{
    pipeline  = "cosmoport2-e2e"
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
        domain   = $DomainId
        app_l0   = $APP_L0
        app_l1   = $APP_L1
        plan     = $PLAN_ID
        run      = $RUN_ID
        release  = $REL_ID
        transfer_zone = $targetZone
    }
}

$reportPath = Join-Path $RepoRoot $ReportPath
New-Item -ItemType Directory -Force -Path (Split-Path $reportPath) | Out-Null
$report | ConvertTo-Json -Depth 3 | Set-Content -Path $reportPath -Encoding UTF8

Write-Host ""
Write-Host "=== E2E Pipeline Complete ===" -ForegroundColor Cyan
Write-Host "  Elapsed : ${elapsed}s" -ForegroundColor White
Write-Host "  Passed  : $Passed" -ForegroundColor Green
Write-Host "  Failed  : $Failed" -ForegroundColor $(if ($Failed -gt 0) { "Red" } else { "Green" })
Write-Host "  Report  : $reportPath" -ForegroundColor Magenta
Write-Host ""

if ($Failed -gt 0) { exit 1 } else { exit 0 }