# Cosmoport 2.0 -- Secret Rotation Drill via OpenBao (COS-088)
# Rotates PostgreSQL password, Gitea token, Woodpecker agent secret.
# OpenBao is the source of new values. Old secrets saved in audit log.
# Usage: .\services\scripts\rotate-secrets.ps1 [-DryRun]
param(
    [string]$BaoUrl = "http://127.0.0.1:8200",
    [string]$BaoRootToken = $env:COSMO_BAO_ROOT_TOKEN,
    [string]$PgUser = "cosmo",
    [string]$PgHost = "127.0.0.1",
    [int]$PgPort = 5432,
    [string]$ComposeDir = $null,
    [switch]$DryRun,
    [string]$AuditLog = "reports/secret-rotation-audit.log"
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
$ScriptRoot = Split-Path -Parent $PSCommandPath
$RepoRoot = Resolve-Path (Join-Path $ScriptRoot "..\..")
if (-not $ComposeDir) { $ComposeDir = Join-Path $RepoRoot "services" }
if (-not $BaoRootToken) { $BaoRootToken = "cosmo-bao-root-dev" }

$AuditDir = Split-Path -Parent (Join-Path $RepoRoot $AuditLog)
if ($AuditDir) { New-Item -ItemType Directory -Force -Path $AuditDir | Out-Null }

function Write-Audit {
    param([string]$Message)
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "[$ts] $Message"
    Write-Host $line
    $auditPath = Join-Path $RepoRoot $AuditLog
    Add-Content -Path $auditPath -Value $line -Encoding UTF8
}

function New-RandomSecret {
    param([int]$Length = 32)
    $chars = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!@#%^-_=+"
    $random = New-Object System.Random
    -join (1..$Length | ForEach-Object { $chars[$random.Next(0, $chars.Length)] })
}

function Invoke-BaoWrite {
    param([string]$Path, [string]$Key, [string]$Value)
    $headers = @{ "X-Vault-Token" = $BaoRootToken; "Content-Type" = "application/json" }
    $body = @{ data = @{ $Key = $Value } } | ConvertTo-Json -Compress
    $url = "$BaoUrl/v1/secret/data/cosmo/$Path"
    if ($DryRun) {
        Write-Audit "DRY-RUN would write to OpenBao: $url -> key=$Key"
        return
    }
    try {
        $r = Invoke-RestMethod -Method POST -Uri $url -Headers $headers -Body $body -TimeoutSec 10
        Write-Audit "OpenBao write OK: secret/cosmo/$Path key=$Key"
    } catch {
        Write-Audit "OpenBao write FAILED: $($_.Exception.Message)"
        throw "OpenBao write failed: $($_.Exception.Message)"
    }
}

function Invoke-BaoRead {
    param([string]$Path, [string]$Key)
    $headers = @{ "X-Vault-Token" = $BaoRootToken }
    $url = "$BaoUrl/v1/secret/data/cosmo/$Path"
    try {
        $r = Invoke-RestMethod -Method GET -Uri $url -Headers $headers -TimeoutSec 10
        return $r.data.data.$Key
    } catch {
        Write-Audit "OpenBao read FAILED for secret/cosmo/$Path: $($_.Exception.Message)"
        return $null
    }
}

# ============================================================
# Step 0: Pre-flight
# ============================================================
Write-Audit "=== Secret Rotation Drill started ==="
Write-Audit "DryRun=$DryRun | BaoUrl=$BaoUrl | PgUser=$PgUser @ $PgHost`:$PgPort"

try {
    $r = Invoke-RestMethod -Method GET -Uri "$BaoUrl/v1/sys/health" -Headers @{ "X-Vault-Token" = $BaoRootToken } -TimeoutSec 5
    if ($r.initialized -ne $true) { throw "OpenBao not initialized" }
    Write-Audit "OpenBao health: initialized=$($r.initialized) sealed=$($r.sealed)"
} catch {
    Write-Audit "OpenBao health check FAILED: $($_.Exception.Message)"
    Write-Audit "Check standalone OpenBao on pk-infra (prettyk-openbao) on 127.0.0.1:8200."
    exit 1
}

# ============================================================
# Step 1: Rotate PostgreSQL password
# ============================================================
Write-Audit ""
Write-Audit "--- ROTATING PostgreSQL Password ---"

$newPgPassword = New-RandomSecret -Length 24

$oldPgPassword = Invoke-BaoRead -Path "database" -Key "password"
if ($oldPgPassword) {
    Invoke-BaoWrite -Path "database" -Key "password_prev" -Value $oldPgPassword
    Write-Audit "Old PostgreSQL password backed up in OpenBao (password_prev)"
} else {
    Write-Audit "No previous PostgreSQL password found in OpenBao -- this is first rotation"
}

Invoke-BaoWrite -Path "database" -Key "password" -Value $newPgPassword

$pgConnString = "host=$PgHost port=$PgPort user=$PgUser password=$oldPgPassword dbname=cosmo"
if (-not $DryRun -and $oldPgPassword) {
    $alterResult = & psql $pgConnString -c "ALTER USER $PgUser WITH PASSWORD '$newPgPassword'" 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Audit "ALTER USER FAILED: $alterResult -- restoring old password"
        Invoke-BaoWrite -Path "database" -Key "password" -Value $oldPgPassword
        throw "PostgreSQL password rotation failed -- rolled back"
    }
    Write-Audit "PostgreSQL password rotated (ALTER USER $PgUser)"
} elseif ($DryRun) {
    Write-Audit "DRY-RUN: would ALTER USER $PgUser with new password (skipped)"
} else {
    Write-Audit "First rotation -- no old password to connect with."
}

# ============================================================
# Step 2: Rotate Gitea admin token
# ============================================================
Write-Audit ""
Write-Audit "--- ROTATING Gitea Token ---"

$newGiteaToken = New-RandomSecret -Length 40

$oldGiteaToken = Invoke-BaoRead -Path "forge/gitea" -Key "admin_token"
if ($oldGiteaToken) {
    Invoke-BaoWrite -Path "forge/gitea" -Key "admin_token_prev" -Value $oldGiteaToken
    Write-Audit "Old Gitea token backed up in OpenBao"
}

Invoke-BaoWrite -Path "forge/gitea" -Key "admin_token" -Value $newGiteaToken

if (-not $DryRun -and $oldGiteaToken) {
    $giteaHeaders = @{
        "Authorization" = "token $oldGiteaToken"
        "Content-Type"  = "application/json"
    }
    $tokenPayload = @{ name = "cosmoport-rotated-$(Get-Date -Format 'yyyyMMdd')" } | ConvertTo-Json
    try {
        $r = Invoke-RestMethod -Method POST -Uri "http://127.0.0.1:3000/api/v1/users/cosmo/tokens" -Headers $giteaHeaders -Body $tokenPayload -TimeoutSec 10
        Write-Audit "Gitea token created: $($r.sha1)"
    } catch {
        Write-Audit "Gitea token creation FAILED: $($_.Exception.Message)"
        Invoke-BaoWrite -Path "forge/gitea" -Key "admin_token" -Value $oldGiteaToken
        throw "Gitea token rotation failed -- rolled back"
    }
} elseif ($DryRun) {
    Write-Audit "DRY-RUN: would create new Gitea token (skipped)"
}

# ============================================================
# Step 3: Rotate Woodpecker agent secret
# ============================================================
Write-Audit ""
Write-Audit "--- ROTATING Woodpecker Agent Secret ---"

$newWoodpeckerSecret = New-RandomSecret -Length 32

$oldWoodpeckerSecret = Invoke-BaoRead -Path "ci/woodpecker" -Key "agent_secret"
if ($oldWoodpeckerSecret) {
    Invoke-BaoWrite -Path "ci/woodpecker" -Key "agent_secret_prev" -Value $oldWoodpeckerSecret
    Write-Audit "Old Woodpecker agent secret backed up in OpenBao"
}

Invoke-BaoWrite -Path "ci/woodpecker" -Key "agent_secret" -Value $newWoodpeckerSecret

if (-not $DryRun) {
    Push-Location $ComposeDir
    try {
        docker compose up -d --force-recreate cosmo-woodpecker-agent 2>&1 | Out-Null
        Write-Audit "Woodpecker agent restarted with new secret"
    } finally {
        Pop-Location
    }
} else {
    Write-Audit "DRY-RUN: would restart cosmo-woodpecker-agent (skipped)"
}

# ============================================================
# Step 4: Post-rotation smoke check
# ============================================================
Write-Audit ""
Write-Audit "--- POST-ROTATION SMOKE CHECK ---"

$smokeOk = $true

try {
    $r = Invoke-RestMethod -Uri "http://127.0.0.1:8100/live" -TimeoutSec 5
    Write-Audit "cosmo-api /live: $($r.status)"
} catch {
    Write-Audit "cosmo-api /live FAILED: $($_.Exception.Message)"
    $smokeOk = $false
}

try {
    $r = Invoke-RestMethod -Uri "http://127.0.0.1:3000/api/v1/version" -TimeoutSec 5
    Write-Audit "cosmo-gitea /api/v1/version: OK"
} catch {
    Write-Audit "cosmo-gitea FAILED: $($_.Exception.Message)"
    $smokeOk = $false
}

try {
    $r = Invoke-RestMethod -Uri "http://127.0.0.1:8080/live" -TimeoutSec 5
    Write-Audit "Caddy /live: $($r.status)"
} catch {
    Write-Audit "Caddy /live FAILED: $($_.Exception.Message)"
    $smokeOk = $false
}

# ============================================================
# Step 5: Summary
# ============================================================
Write-Audit ""
Write-Audit "=== Secret Rotation Drill Complete ==="
Write-Audit "Smoke check: $(if ($smokeOk) { 'PASSED' } else { 'FAILED -- CHECK SERVICES' })"
Write-Audit "Audit log: $(Join-Path $RepoRoot $AuditLog)"
Write-Audit ""
Write-Audit "New secrets in OpenBao:"
Write-Audit "  secret/cosmo/database      -> password"
Write-Audit "  secret/cosmo/forge/gitea   -> admin_token"
Write-Audit "  secret/cosmo/ci/woodpecker -> agent_secret"

if (-not $smokeOk) {
    Write-Audit ""
    Write-Audit "ATTENTION: Post-rotation smoke check FAILED!"
    Write-Audit "  - Previous secrets saved with _prev suffix in OpenBao"
    Write-Audit "  - Rollback: restore _prev values and restart services"
    exit 1
}

exit 0