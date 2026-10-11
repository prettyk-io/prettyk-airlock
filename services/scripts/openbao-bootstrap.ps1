<#
.SYNOPSIS
    COS-178: OpenBao bootstrap (dev contour) - up + init + AppRole cosmo-app + seed.

.DESCRIPTION
    Idempotent bootstrap of the platform OpenBao (prettyk-openbao):
      1. unseal key (32 bytes, static auto-unseal) -> services/.openbao/unseal.key (gitignored);
      2. docker compose up -d (openbao/openbao:2.6.3, raft storage, static seal);
      3. operator init (if not initialized) -> recovery key + root token saved to services/.openbao/init.json;
      4. kv-v2 mount secret/ + approle enable + policy/role cosmo-app;
      5. AppRole creds -> services/.env (VAULT_APPROLE_ROLE_ID/SECRET_ID; PRESERVED when still valid);
      6. seed secret/cosmo/{pg,minio,gitea,woodpecker} (PRESERVED on repeat) +
         seed-auth-secrets.py (auth, jwt-keys - idempotent, PRESERVED).

    After bootstrap, recreate cosmo-api so it picks up the creds:
      docker compose -f services/docker-compose.yml up -d cosmo-api

.NOTES
    Canon: D:\prettyk.io\void-core\OPENBAO-PLATFORM.md (section 4, dev topology).
    Production profile: KMS/HSM auto-unseal; unseal/recovery material kept outside OpenBao (canon section 7).
#>
[CmdletBinding()]
param(
    [switch]$RotateSecretId  # force-issue a new AppRole secret-id
)

$ErrorActionPreference = "Stop"

$RepoRoot      = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$ComposeFile   = Join-Path $RepoRoot "services\docker-compose.openbao.yml"
$SecretsDir    = Join-Path $RepoRoot "services\.openbao"
$UnsealKeyFile = Join-Path $SecretsDir "unseal.key"
$InitFile      = Join-Path $SecretsDir "init.json"
$PolicyFile    = Join-Path $RepoRoot "services\openbao\cosmo-app-policy.hcl"
$EnvFile       = Join-Path $RepoRoot "services\.env"
$Container     = "prettyk-openbao"
$BaoAddr       = "http://127.0.0.1:8200"

# -- helpers -------------------------------------------------------------

function Invoke-Docker {
    param([Parameter(Mandatory = $true)][string[]]$DockerArgs)
    # COS-064 lesson: PS 5.1 + native stderr with $ErrorActionPreference=Stop
    # yields a false terminating error; use $LASTEXITCODE as the verdict.
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        $output = (& docker @DockerArgs 2>&1 | Out-String).Trim()
        $code = $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $prevEap
    }
    return [pscustomobject]@{ Output = $output; Code = $code }
}

function Invoke-Bao {
    param(
        [Parameter(Mandatory = $true)][string[]]$BaoArgs,
        [string]$Token = "",
        [switch]$AllowFail
    )
    $dockerArgs = @("exec")
    if ($Token) { $dockerArgs += @("-e", "BAO_TOKEN=$Token") }
    $dockerArgs += @("-e", "BAO_ADDR=$BaoAddr", $Container, "bao")
    $dockerArgs += $BaoArgs
    $res = Invoke-Docker -DockerArgs $dockerArgs
    if ($res.Code -ne 0 -and -not $AllowFail) {
        throw "bao $($BaoArgs -join ' ') failed (exit $($res.Code)): $($res.Output)"
    }
    return $res
}

function Wait-BaoApi {
    param([int]$TimeoutSec = 90)
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        $r = Invoke-Bao -BaoArgs @("status", "-format=json") -AllowFail
        if ($r.Output -and $r.Output.StartsWith("{")) {
            return ($r.Output | ConvertFrom-Json)
        }
        Start-Sleep -Seconds 2
    }
    throw "OpenBao API did not respond within ${TimeoutSec}s - check: docker logs $Container"
}

function Ensure-Secret {
    param([string]$Name, [string[]]$KvPairs, [string]$Token)
    $check = Invoke-Bao -BaoArgs @("kv", "get", "-format=json", "secret/cosmo/$Name") -Token $Token -AllowFail
    if ($check.Code -eq 0) {
        Write-Host "[seed] secret/cosmo/${Name}: PRESERVED (exists)"
        return
    }
    Invoke-Bao -BaoArgs (@("kv", "put", "secret/cosmo/$Name") + $KvPairs) -Token $Token | Out-Null
    Write-Host "[seed] secret/cosmo/${Name}: SEEDED"
}

function Get-EnvValue {
    param([string]$Key)
    if (-not (Test-Path $EnvFile)) { return "" }
    foreach ($line in (Get-Content -Path $EnvFile -Encoding UTF8)) {
        if ($line -match "^\s*$([regex]::Escape($Key))\s*=\s*(.+)$") { return $Matches[1].Trim() }
    }
    return ""
}

function Set-EnvValues {
    param([hashtable]$Values)
    $lines = @()
    if (Test-Path $EnvFile) { $lines = @(Get-Content -Path $EnvFile -Encoding UTF8) }
    $keys = @($Values.Keys | ForEach-Object { [regex]::Escape($_) })
    $lines = @($lines | Where-Object { $line = $_; -not ($keys | Where-Object { $line -match "^\s*$_\s*=" }) })
    foreach ($k in ($Values.Keys | Sort-Object)) {
        $lines += "$k=$($Values[$k])"
    }
    [System.IO.File]::WriteAllLines($EnvFile, $lines, (New-Object System.Text.UTF8Encoding($false)))
}

# -- 1. unseal key --------------------------------------------------------

New-Item -ItemType Directory -Force -Path $SecretsDir | Out-Null
if (-not (Test-Path $UnsealKeyFile)) {
    $bytes = New-Object byte[] 32
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $rng.GetBytes($bytes)
    $rng.Dispose()
    [System.IO.File]::WriteAllBytes($UnsealKeyFile, $bytes)
    Write-Host "[init] unseal key created: $UnsealKeyFile (gitignored, static auto-unseal)"
} else {
    Write-Host "[init] unseal key exists (reused): $UnsealKeyFile"
}

# -- 2. bring the container up -------------------------------------------

Write-Host "[up] docker compose up -d ($ComposeFile)"
$up = Invoke-Docker -DockerArgs @("compose", "-f", $ComposeFile, "up", "-d")
if ($up.Code -ne 0) { throw "docker compose up failed (exit $($up.Code)): $($up.Output)" }

$status = Wait-BaoApi
Write-Host "[up] openbao responds: initialized=$($status.initialized) sealed=$($status.sealed) storage=$($status.storage_type)"

# -- 3. init (one-time) ---------------------------------------------------

if (-not $status.initialized) {
    Write-Host "[init] OpenBao not initialized - running operator init (recovery 1/1, dev profile)"
    $initRes = Invoke-Bao -BaoArgs @(
        "operator", "init", "-recovery-shares=1", "-recovery-threshold=1", "-format=json"
    )
    [System.IO.File]::WriteAllText($InitFile, $initRes.Output)
    Write-Host "[init] init material saved: $InitFile (gitignored; recovery key + root token)"
    $status = Wait-BaoApi
} else {
    Write-Host "[init] OpenBao already initialized - reusing init material"
}

if (-not (Test-Path $InitFile)) {
    throw "No $InitFile while vault is initialized - root token was not saved. Recovery: offline recovery key + 'bao operator generate-root' (see SECURITY_MAINTENANCE.md)."
}
$init = Get-Content -Path $InitFile -Raw | ConvertFrom-Json
$rootToken = $init.root_token
if (-not $rootToken) { throw "init.json has no root_token - recreate bootstrap from scratch (services/.openbao/ + volume)." }

if ($status.sealed) {
    Write-Host "[unseal] vault sealed - restarting container for static auto-unseal"
    Invoke-Docker -DockerArgs @("restart", $Container) | Out-Null
    $status = Wait-BaoApi
    if ($status.sealed) { throw "vault stayed sealed after restart - check unseal.key and seal static config" }
}

# -- 4. kv-v2 + approle + policy/role ------------------------------------

$mounts = (Invoke-Bao -BaoArgs @("secrets", "list", "-format=json") -Token $rootToken).Output | ConvertFrom-Json
if (-not $mounts.'secret/') {
    Invoke-Bao -BaoArgs @("secrets", "enable", "-path=secret", "-version=2", "kv") -Token $rootToken | Out-Null
    Write-Host "[bootstrap] kv-v2 enabled at secret/"
} else {
    Write-Host "[bootstrap] secret/ mount exists"
}

$auths = (Invoke-Bao -BaoArgs @("auth", "list", "-format=json") -Token $rootToken).Output | ConvertFrom-Json
if (-not $auths.'approle/') {
    Invoke-Bao -BaoArgs @("auth", "enable", "approle") -Token $rootToken | Out-Null
    Write-Host "[bootstrap] approle auth enabled"
} else {
    Write-Host "[bootstrap] approle auth exists"
}

$cp = Invoke-Docker -DockerArgs @("cp", $PolicyFile, "${Container}:/tmp/cosmo-app-policy.hcl")
if ($cp.Code -ne 0) { throw "docker cp policy failed: $($cp.Output)" }
Invoke-Bao -BaoArgs @("policy", "write", "cosmo-app", "/tmp/cosmo-app-policy.hcl") -Token $rootToken | Out-Null
Write-Host "[bootstrap] policy cosmo-app written"

Invoke-Bao -BaoArgs @(
    "write", "auth/approle/role/cosmo-app",
    "token_policies=cosmo-app", "token_ttl=1h", "token_max_ttl=24h",
    "secret_id_ttl=0", "bind_secret_id=true"
) -Token $rootToken | Out-Null
Write-Host "[bootstrap] role cosmo-app configured"

# -- 5. AppRole creds -> services/.env -----------------------------------

$roleId = (Invoke-Bao -BaoArgs @("read", "-field=role_id", "auth/approle/role/cosmo-app/role-id") -Token $rootToken).Output
if (-not $roleId) { throw "role-id is empty" }

$existingRole   = Get-EnvValue "VAULT_APPROLE_ROLE_ID"
$existingSecret = Get-EnvValue "VAULT_APPROLE_SECRET_ID"
$preserved = $false
if (-not $RotateSecretId -and $existingRole -eq $roleId -and $existingSecret) {
    try {
        $loginBody = @{ role_id = $existingRole; secret_id = $existingSecret } | ConvertTo-Json
        $loginResp = Invoke-RestMethod -Uri "$BaoAddr/v1/auth/approle/login" -Method Post -Body $loginBody -ContentType "application/json" -TimeoutSec 10
        if ($loginResp.auth.client_token) { $preserved = $true }
    } catch { $preserved = $false }
}

if ($preserved) {
    $secretId = $existingSecret
    Write-Host "[approle] existing secret-id still valid - PRESERVED"
} else {
    $secretId = (Invoke-Bao -BaoArgs @("write", "-f", "-field=secret_id", "auth/approle/role/cosmo-app/secret-id") -Token $rootToken).Output
    if (-not $secretId) { throw "secret-id is empty" }
    Set-EnvValues @{
        "VAULT_APPROLE_ROLE_ID"   = $roleId
        "VAULT_APPROLE_SECRET_ID" = $secretId
    }
    Write-Host "[approle] new secret-id issued -> services/.env updated (gitignored)"
}

# -- 6. seed secret/cosmo/* ----------------------------------------------

Ensure-Secret -Name "pg"         -KvPairs @("user=cosmo", "password=cosmo", "db=cosmo") -Token $rootToken
Ensure-Secret -Name "minio"      -KvPairs @("access_key=cosmo", "secret_key=cosmo-minio-dev") -Token $rootToken
Ensure-Secret -Name "gitea"      -KvPairs @("admin_user=cosmo", "admin_password=cosmo-admin-dev", "webhook_secret=dev-webhook-secret-change-me") -Token $rootToken
Ensure-Secret -Name "woodpecker" -KvPairs @("agent_secret=dev-agent-secret-change-me") -Token $rootToken

$pyExe = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $pyExe)) { $pyExe = "python" }

$env:VAULT_ADDR              = $BaoAddr
$env:VAULT_APPROLE_ROLE_ID   = $roleId
$env:VAULT_APPROLE_SECRET_ID = $secretId
Push-Location $RepoRoot
$prevEap = $ErrorActionPreference
$ErrorActionPreference = 'Continue'
try {
    Write-Host "[seed] auth + jwt-keys via services/scripts/seed-auth-secrets.py"
    & $pyExe "services\scripts\seed-auth-secrets.py"
    $seedCode = $LASTEXITCODE
} finally {
    $ErrorActionPreference = $prevEap
    Pop-Location
}
if ($seedCode -ne 0) { throw "seed-auth-secrets.py failed (exit $seedCode)" }

# -- 7. summary -----------------------------------------------------------

$final = (Invoke-Bao -BaoArgs @("status", "-format=json") -Token $rootToken).Output | ConvertFrom-Json
Write-Host ""
Write-Host "=== OpenBao bootstrap complete ==="
Write-Host "  container : $Container (v$($final.version), storage=$($final.storage_type), seal=$($final.type))"
Write-Host "  state     : initialized=$($final.initialized) sealed=$($final.sealed)"
Write-Host "  approle   : cosmo-app (role-id ...$($roleId.Substring([Math]::Max(0, $roleId.Length - 6))))"
Write-Host "  secrets   : secret/cosmo/{pg,minio,gitea,woodpecker,auth,jwt-keys}"
Write-Host "  next      : docker compose -f services/docker-compose.yml up -d cosmo-api"
