# COS-059 / COS-201: Cosmoport startup - canonical delivery profile.
# Usage:  .\services\scripts\cosmo-start.ps1 [-Full] [-Dev] [-CheckOnly]
# Core       : PG, Valkey, API, Frontend, Caddy
# -Full      : + MinIO, Gitea, Woodpecker ('full' profile) + OpenBao + Registry ZR
# -Dev       : dev profile (COS-195): sources mounted, hot-reload, no rebuilds
# -CheckOnly : skip 'up' - probe the contour and print the honest summary only
#              (pair with -Full for the demo set; exits non-zero when not green)
# Exit codes : 0 = all probed inputs up; 1 = degraded/down inputs; 2 = Docker engine unreachable
param(
    [switch]$Full,
    [switch]$Dev,
    [switch]$CheckOnly,
    [string]$ComposeFile = "$PSScriptRoot\..\docker-compose.yml"
)
$ErrorActionPreference = "Continue"
$ComposeDir = Split-Path -Parent $ComposeFile
$script:Rows = @()

function Add-Result {
    param([string]$Name, [string]$Verdict, [string]$Detail)
    $script:Rows += [pscustomobject]@{ Name = $Name; Verdict = $Verdict; Detail = $Detail }
}

function Try-Probe {
    param([string]$Name, [scriptblock]$Probe, [int]$Retries = 1)
    $reason = "no result"
    for ($i = 1; $i -le $Retries; $i++) {
        try {
            $detail = & $Probe
            Add-Result $Name "up" "$detail"
            return
        } catch {
            $reason = $_.Exception.Message
            if ($i -lt $Retries) {
                Write-Host "  [$Name] $reason - retry $i/$($Retries - 1)..." -ForegroundColor DarkYellow
                Start-Sleep -Seconds 2
            }
        }
    }
    Add-Result $Name "down" $reason
    return
}

Write-Host "=== Cosmoport startup ($([math]::Round((Get-Date).TimeOfDay.TotalSeconds))s tick) ===" -ForegroundColor Cyan
Write-Host "Compose: $ComposeFile"
Write-Host "Profile: $(if ($Full) { 'full' } else { 'core' })$(if ($Dev) { ' + dev (mounts/hot-reload)' } else { '' })$(if ($CheckOnly) { ' [check-only: no up]' } else { '' })"

# 1. Engine preflight (COS-201): no engine -> honest stop, never pretend the stand is up.
Write-Host ""
Write-Host "[preflight] Docker engine..."
$dv = & docker version --format "{{.Server.Version}}" 2>&1
if ($LASTEXITCODE -ne 0 -or ("$dv" -match "Cannot connect|error during connect|failed to connect")) {
    Write-Host "[FAIL] Docker engine unreachable - the stand cannot be started or probed." -ForegroundColor Red
    Write-Host "       detail: $($dv -join ' | ')"
    Write-Host "       hint  : start Docker Desktop, wait for 'Engine running', then re-run this command."
    exit 2
}
Write-Host "[OK] Docker engine $dv" -ForegroundColor Green

# 2. Up (skipped in -CheckOnly)
if (-not $CheckOnly) {
    if (-not (Test-Path (Join-Path $ComposeDir ".env"))) {
        Write-Host "[i] No .env found - compose built-in dev defaults apply." -ForegroundColor DarkYellow
        Write-Host "    For non-default credentials: copy .env.example -> .env first."
    }

    # External networks must exist before compose up (idempotent guard).
    foreach ($net in @("cosmo-net")) {
        & docker network inspect $net *> $null
        if ($LASTEXITCODE -ne 0) { Write-Host "[i] Creating missing network '$net'..."; & docker network create $net *> $null }
    }
    if ($Full) {
        & docker network inspect pk-infra *> $null
        if ($LASTEXITCODE -ne 0) { Write-Host "[i] Creating missing network 'pk-infra'..."; & docker network create pk-infra *> $null }
    }

    # Core up. PS 5.1: docker writes compose progress to stderr; EAP=Stop would
    # abort on a healthy startup. Verdict = $LASTEXITCODE only.
    $upArgs = @("compose", "-f", $ComposeFile)
    if ($Dev) { $upArgs += @("-f", (Join-Path $ComposeDir "docker-compose.dev.yml")) }
    if ($Full) { $upArgs += "--profile", "full" }
    $upArgs += "up", "-d"
    Write-Host ""
    $upOut = & docker @upArgs 2>&1 | ForEach-Object { "$_" }
    $upOut | ForEach-Object { "$_" }
    if ($LASTEXITCODE -ne 0) { Write-Error "docker compose up failed (exit $LASTEXITCODE)"; exit 1 }
    if ($upOut -match "Found orphan containers") {
        Write-Host "[i] Note: 'Found orphan containers' above is the shared 'services' project label (several lab stacks resolve to it). Containers are untouched. Do NOT use --remove-orphans - it would touch foreign stacks." -ForegroundColor DarkYellow
    }

    if ($Full) {
        # COS-178: shared OpenBao (bootstrap/unseal = services/scripts/openbao-bootstrap.ps1).
        Write-Host ""
        Write-Host "[up] OpenBao (shared, idempotent)..."
        & docker compose -f (Join-Path $ComposeDir "docker-compose.openbao.yml") up -d 2>&1 | ForEach-Object { "$_" }
        if ($LASTEXITCODE -ne 0) { Write-Error "openbao compose up failed (exit $LASTEXITCODE)"; exit 1 }
        # COS-199/COS-201: Registry ZR (+ honest health sidecar). ZT stays off by design (replicas=0).
        Write-Host ""
        Write-Host "[up] Registry ZR ..."
        & docker compose -f (Join-Path $ComposeDir "docker-compose.registry.yml") up -d 2>&1 | ForEach-Object { "$_" }
        if ($LASTEXITCODE -ne 0) { Write-Error "registry compose up failed (exit $LASTEXITCODE)"; exit 1 }
    }

    # Wait for readiness (PG+Valkey healthy -> API /ready 200)
    Write-Host ""
    Write-Host "Waiting for readiness (max 90s)..."
    $ready = $false
    $deadline = (Get-Date).AddSeconds(90)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep 3
        try {
            $r = Invoke-RestMethod -Uri "http://localhost:8100/ready" -TimeoutSec 3 -ErrorAction Stop
            if ($r.status -eq "ok") { $ready = $true; break }
            Write-Host "  ready: $($r.status) (db=$($r.database), cache=$($r.cache))"
        } catch {
            Write-Host "  API not answering yet..."
        }
    }
    if ($ready) {
        Write-Host "[OK] API ready: PostgreSQL + Valkey connected" -ForegroundColor Green
    } else {
        Write-Host "[FAIL] API not ready in 90s. Partial-failure diagnostics:" -ForegroundColor Red
        # COS-064: diagnosable reason on partial failure - container states + tail of sick ones.
        docker ps -a --filter "name=cosmo-" --format "{{.Names}}  {{.Status}}"
        foreach ($c in (docker ps -a --filter "name=cosmo-" --format "{{.Names}}")) {
            $st = docker inspect -f "{{.State.Status}} {{.State.Health.Status}}" $c 2>$null
            if ($st -match "exited|restarting|paused|unhealthy|starting") {
                Write-Host "--- $c ($st) last 15 lines:" -ForegroundColor Yellow
                docker logs --tail 15 $c 2>&1 | ForEach-Object { "$_" }
            }
        }
    }
} else {
    $ready = $true   # no up-flow: probe a single snapshot immediately
}

# 3. Probe key inputs (COS-201). Patient retries only in a healthy up-flow.
$retries = if ($CheckOnly -or (-not $ready)) { 1 } else { 10 }

Write-Host ""
Write-Host "Probing inputs..."

Try-Probe "API" {
    $r = Invoke-RestMethod -Uri "http://localhost:8100/ready" -TimeoutSec 4 -ErrorAction Stop
    if ($r.status -ne "ok") { throw "status=$($r.status) db=$($r.database) cache=$($r.cache)" }
    ":8100/ready ok (db=$($r.database), cache=$($r.cache))"
} $retries

Try-Probe "Edge" {
    $r = Invoke-WebRequest -Uri "http://localhost:8180/live" -UseBasicParsing -TimeoutSec 4 -ErrorAction Stop
    if ($r.StatusCode -ne 200) { throw "HTTP $($r.StatusCode)" }
    ":8180/live HTTP 200 (via Caddy)"
} $retries

Try-Probe "Frontend" {
    $direct = Invoke-WebRequest -Uri "http://localhost:5174/" -UseBasicParsing -TimeoutSec 4 -ErrorAction Stop
    $via = Invoke-WebRequest -Uri "http://localhost:8180/" -UseBasicParsing -TimeoutSec 4 -ErrorAction Stop
    ":5174 HTTP $($direct.StatusCode); via edge :8180/ HTTP $($via.StatusCode)"
} $retries

if ($Full) {
    Try-Probe "Registry ZR" {
        $r = Invoke-RestMethod -Uri "http://localhost:5100/v2/_catalog" -TimeoutSec 4 -ErrorAction Stop
        $repos = $r.repositories
        $n = if ($repos) { @($repos).Count } else { 0 }
        ":5100/v2/_catalog -> $n repos"
    } $retries
    # COS-199: ZT off by design - not masked as reachable, stated honestly.
    Add-Result "Registry ZT" "off" "off by design (deploy.replicas=0); not part of the demo"

    Try-Probe "Gitea" {
        $r = Invoke-RestMethod -Uri "http://localhost:3100/api/v1/version" -TimeoutSec 4 -ErrorAction Stop
        ":3100 v$($r.version)"
    } $retries

    Try-Probe "Woodpecker" {
        $r = Invoke-RestMethod -Uri "http://localhost:8000/version" -TimeoutSec 4 -ErrorAction Stop
        ":8000 v$($r.version)"
    } $retries

    Try-Probe "OpenBao" {
        try {
            $r = Invoke-RestMethod -Uri "http://127.0.0.1:8200/v1/sys/health" -TimeoutSec 4 -ErrorAction Stop
        } catch {
            $resp = $_.Exception.Response
            if ($resp -and ([int]$resp.StatusCode -eq 503)) { throw "sealed or uninitialized (HTTP 503) - run services/scripts/openbao-bootstrap.ps1" }
            throw
        }
        if ($r.sealed) { throw "sealed - run services/scripts/openbao-bootstrap.ps1" }
        ":8200 initialized=$($r.initialized), sealed=$($r.sealed)"
    } $retries
}

# COS-097/COS-201: executor indicator - config-level truth from the live container
# (app-level INFO logs do not reach `docker logs`, so the env var is the honest probe).
$ev = & docker exec cosmo-api printenv COSMO_EXECUTOR_ENABLED 2>$null
if ($LASTEXITCODE -ne 0) {
    Add-Result "Executor" "down" "cosmo-api container not running (exec failed)"
} else {
    $ev = "$ev".Trim()
    if ($ev -match "^(1|true|yes)$") { Add-Result "Executor" "up" "enabled, poll loop (COSMO_EXECUTOR_ENABLED=$ev)" }
    elseif ($ev -eq "") { Add-Result "Executor" "degraded" "disabled (COSMO_EXECUTOR_ENABLED unset) - run polling off" }
    else { Add-Result "Executor" "degraded" "disabled (COSMO_EXECUTOR_ENABLED=$ev)" }
}

# 4. COS-063: idempotent Gitea admin bootstrap (full profile, up-flow only).
if ((-not $CheckOnly) -and $Full) {
    docker exec cosmo-gitea curl -sf "http://localhost:3000/api/v1/users/cosmo" 2>$null | Out-Null
    $adminExists = ($LASTEXITCODE -eq 0)
    if ($adminExists) {
        Write-Host "[OK] Gitea admin 'cosmo' exists" -ForegroundColor Green
    } else {
        if (-not $env:COSMO_FORGE_ADMIN_PASSWORD) { $env:COSMO_FORGE_ADMIN_PASSWORD = "cosmo-admin-dev" }
        Write-Host "[i] Creating Gitea admin 'cosmo' (dev creds, rotate via .env for prod)..."
        docker exec -u git cosmo-gitea gitea admin user create `
            --admin --username cosmo `
            --password "$env:COSMO_FORGE_ADMIN_PASSWORD" `
            --email "cosmo@cosmoport.local" `
            --must-change-password=false 2>$null
        if ($LASTEXITCODE -eq 0) {
            Write-Host "[OK] Gitea admin 'cosmo' created" -ForegroundColor Green
        } else {
            # user may exist from a previous run with different API state
            Write-Host "[i] Gitea admin create skipped (likely already exists)" -ForegroundColor DarkYellow
        }
    }
}

# 5. Honest summary (COS-201): up / degraded / down / off - each with a reason.
Write-Host ""
Write-Host "=== Cosmoport stand summary ($(if ($Full) { 'demo set' } else { 'core set' })) ===" -ForegroundColor Cyan
$w = 12
foreach ($row in $script:Rows) { if ($row.Name.Length -gt $w) { $w = $row.Name.Length } }
foreach ($row in $script:Rows) {
    switch ($row.Verdict) {
        "up"       { $tag = "[UP]  "; $color = "Green" }
        "degraded" { $tag = "[DEG] "; $color = "Yellow" }
        "off"      { $tag = "[OFF] "; $color = "DarkGray" }
        default    { $tag = "[DOWN]"; $color = "Red" }
    }
    Write-Host ("  {0} {1}  {2}" -f $tag, $row.Name.PadRight($w), $row.Detail) -ForegroundColor $color
}

$up   = @($script:Rows | Where-Object { $_.Verdict -eq "up" }).Count
$deg  = @($script:Rows | Where-Object { $_.Verdict -eq "degraded" }).Count
$down = @($script:Rows | Where-Object { $_.Verdict -eq "down" }).Count
$off  = @($script:Rows | Where-Object { $_.Verdict -eq "off" }).Count

Write-Host ""
if ($down -eq 0 -and $deg -eq 0) {
    Write-Host "=== STAND GREEN: $up inputs up$(if ($off -gt 0) { ", $off off by design" }) ===" -ForegroundColor Green
    Write-Host "  Control Station : http://localhost:8180/     (via Caddy)"
    Write-Host "  API direct      : http://localhost:8100/docs"
    Write-Host "  Smoke           : .\services\scripts\smoke-delivery.ps1"
    exit 0
} else {
    Write-Host "=== STAND NOT GREEN: $down down, $deg degraded (of $($script:Rows.Count) probed) ===" -ForegroundColor Red
    exit 1
}
