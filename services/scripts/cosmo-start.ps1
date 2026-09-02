# COS-059: Cosmoport startup — canonical delivery profile.
# Usage:  .\services\scripts\cosmo-start.ps1 [-Full]
# Core    : PG, Valkey, API, Frontend, Caddy
# -Full   : + MinIO, OpenBao, Gitea, Woodpecker
param(
    [switch]$Full,
    [string]$ComposeFile = "$PSScriptRoot\..\docker-compose.yml"
)
$ErrorActionPreference = "Stop"
$ComposeDir = Split-Path -Parent $ComposeFile

Write-Host "=== Cosmoport startup ($([math]::Round((Get-Date).TimeOfDay.TotalSeconds))s tick) ===" -ForegroundColor Cyan
Write-Host "Compose: $ComposeFile"
Write-Host "Profile: $(if ($Full) { 'full' } else { 'core' })"

# 1. Pre-flight: env template hint
if (-not (Test-Path (Join-Path $ComposeDir ".env"))) {
    Write-Host "[i] No .env found - compose built-in dev defaults apply." -ForegroundColor DarkYellow
    Write-Host "    For non-default credentials: copy .env.example -> .env first."
}

# 2. Up
$args_ = @("compose", "-f", $ComposeFile)
if ($Full) { $args_ += "--profile", "full" }
$args_ += "up", "-d"
# PS 5.1: docker writes compose progress to stderr; EAP=Stop would abort on a
# healthy startup. Verdict = $LASTEXITCODE only.
$ErrorActionPreference = "Continue"
& docker @args_ 2>&1 | ForEach-Object { "$_" }
if ($LASTEXITCODE -ne 0) { Write-Error "docker compose up failed (exit $LASTEXITCODE)"; exit 1 }

# 3. Wait for readiness (PG+Valkey healthy -> API /ready 200)
Write-Host ""
Write-Host "Waiting for readiness (max 90s)..."
$deadline = (Get-Date).AddSeconds(90)
$ready = $false
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
if (-not $ready) {
    Write-Host "[FAIL] API not ready in 90s. Partial-failure diagnostics:" -ForegroundColor Red
    # COS-064: diagnosable reason on partial failure — container states + tail of sick ones.
    docker ps -a --filter "name=cosmo-" --format "{{.Names}}  {{.Status}}"
    foreach ($c in (docker ps -a --filter "name=cosmo-" --format "{{.Names}}")) {
        $st = docker inspect -f "{{.State.Status}} {{.State.Health.Status}}" $c 2>$null
        if ($st -match "exited|restarting|paused|unhealthy|starting") {
            Write-Host "--- $c ($st) last 15 lines:" -ForegroundColor Yellow
            docker logs --tail 15 $c 2>&1 | ForEach-Object { "$_" }
        }
    }
    exit 1
}
Write-Host "[OK] API ready: PostgreSQL + Valkey connected" -ForegroundColor Green

# 4. Edge check
try {
    $null = Invoke-WebRequest -Uri "http://localhost:8180/live" -UseBasicParsing -TimeoutSec 5 -ErrorAction Stop
    Write-Host "[OK] Caddy edge on 8180: /live 200" -ForegroundColor Green
} catch {
    Write-Host "[FAIL] Caddy edge unreachable on 8180" -ForegroundColor Red
    exit 1
}

# 5. COS-063: idempotent Gitea admin bootstrap (full profile only).
#    INSTALL_LOCK=true skips the install wizard, but an admin user must exist
#    for the API (healthcheck /api/v1/version and rotate-secrets.ps1).
if ($Full) {
    $adminExists = $false
    try {
        docker exec cosmo-gitea curl -sf "http://localhost:3000/api/v1/users/cosmo" | Out-Null
        $adminExists = ($LASTEXITCODE -eq 0)
    } catch { }
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

Write-Host ""
Write-Host "=== Cosmoport UP ===" -ForegroundColor Green
Write-Host "  Control Station : http://localhost:8180/     (via Caddy)"
Write-Host "  API direct      : http://localhost:8100/docs"
Write-Host "  Smoke           : .\services\scripts\smoke-delivery.ps1"
exit 0