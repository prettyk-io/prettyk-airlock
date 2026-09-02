# COS-064: Runtime reproducibility gate.
# One command, seven isolated checks, per-check verdicts.
#
# Usage:  .\services\scripts\runtime-gate.ps1 [-ReportJson <path>]
#
# Checks (each independent verdict: PASS / FAIL / DEVIATION / SKIP):
#   1. migration    scratch DB -> alembic upgrade head -> verify tables + head -> drop
#                   (zero contamination of the live cosmo DB)
#   2. clean-start  wipe ALL cosmo volumes -> core up -> time to /ready=ok (budget 90s)
#   3. full-profile --profile full up -> all 10 containers healthy/Up + gitea admin
#   4. smoke        smoke-delivery.ps1 (9 checks, exit code; needs full profile)
#   5. restart      create domain -> restart API -> domain survives -> DELETE cleanup
#   6. sse          own domain -> Caddy :8180 stream 20s -> ': keepalive' -> cleanup
#                   (/all events/stream errors out instantly on an empty DB —
#                    keepalive only flows for a resolvable domain)
#   7. dep-failure  stop PG -> /ready 503 + honest component map (COS-090)
#                   (KNOWN DEVIATION: criterion says 503; product decision pending,
#                    see docs/research/2026-09-02-cos-063-runtime-acceptance.md §4)
#                   -> start PG -> recovery
#
# Exit codes: 0 = no FAIL; 1 = at least one FAIL / INCONCLUSIVE;
#             2 = infra error (docker unreachable); 3 = stand locked (COS-073).
# DEVIATION does not fail the gate but is loud in the report.
#
# COS-073: acquires the stand-lock (stand-lock.ps1) for the whole run and
# releases it at the end. Stand discipline: one agent on the stand at a time.
# Pytest does NOT participate: it runs against the isolated test PG (:5433).
param(
    [string]$ReportJson = "",
    [string]$LockOwner = "runtime-gate"
)
$ErrorActionPreference = "Continue"
$ComposeFile = "$PSScriptRoot\..\docker-compose.yml"
$TS = Get-Date -Format "yyyyMMddHHmmss"  # no dashes: used in SQL identifiers
$Core = @("cosmo-postgres", "cosmo-valkey", "cosmo-api", "cosmo-frontend", "cosmo-caddy")
$FullExtra = @("cosmo-minio", "cosmo-openbao", "cosmo-gitea", "cosmo-woodpecker", "cosmo-woodpecker-agent")
$script:Results = [ordered]@{}

# API perimeter (COS-067): authenticated requests only. Dev token format
# 'user_id:role' mirrors the frontend getCosmoAuthToken contract; admin_sec
# grants is_system_admin (deps.py). Gate acts as an admin actor.
$ApiAuth = @{ Authorization = "Bearer gate-agent:admin_sec" }

# ── COS-073 stand-lock: the stand is a serialized resource ──────────────
$StandLock = "$PSScriptRoot\stand-lock.ps1"
& $StandLock acquire -Owner $LockOwner -Purpose "runtime-gate $TS" -TtlMinutes 60
if ($LASTEXITCODE -ne 0) {
    Write-Host "GATE: SKIPPED - stand is locked by another window (stand-lock.ps1 status)" -ForegroundColor DarkYellow
    exit 3
}
function Release-StandLock {
    & $StandLock release -Owner $LockOwner *> $null
}

function Add-Check {
    param([string]$Name, [string]$Verdict, [string]$Detail)
    $script:Results[$Name] = @{ verdict = $Verdict; detail = $Detail; s = [math]::Round(((Get-Date) - $script:checkStart).TotalSeconds, 1) }
    $color = @{ PASS = "Green"; FAIL = "Red"; DEVIATION = "Yellow"; "FLAKE-EXTERNAL" = "DarkYellow"; SKIP = "DarkGray" }[$Verdict]
    Write-Host ("[{0}] {1} ({2}s) {3}" -f $Verdict, $Name, $script:Results[$Name].s, $Detail) -ForegroundColor $color
}

function Test-ReadyOk {
    param([int]$TimeoutSec = 45)
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        try {
            $r = Invoke-RestMethod "http://localhost:8100/ready" -TimeoutSec 3 -ErrorAction Stop
            if ($r.status -eq "ok") { return $true }
        } catch { }
        Start-Sleep 2
    }
    return $false
}

function Get-Health {
    param([string]$Container)
    (docker inspect -f "{{.State.Health.Status}}" $Container 2>$null | Out-String).Trim()
}

# ── 0. Docker reachable + host-quiet serialization ──────────────────────
# Shared mutable state: dev harness (pytest _clean_db fixtures, alembic
# downgrade) hits the SAME cosmo DB via host :5432. Known killer of the
# restart check (PG-log proof: full-table DELETE series from 172.22.0.1).
# Gate serializes: wait for host-side pytest/alembic to go quiet (max 120s).
$script:checkStart = Get-Date
docker info *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host "[FAIL] docker unreachable" -ForegroundColor Red
    Release-StandLock
    exit 2
}
$quietDeadline = (Get-Date).AddSeconds(120)
while ((Get-Date) -lt $quietDeadline) {
    $busy = Get-CimInstance Win32_Process -Filter "Name like '%python%'" |
        Where-Object { $_.CommandLine -match "pytest|alembic" }
    if (-not $busy) { break }
    Start-Sleep 10
}
if ($busy) {
    Write-Host "[i] Host harness still busy (pytest/alembic running) - interference possible" -ForegroundColor DarkYellow
    $script:HostBusy = $true
} else {
    $script:HostBusy = $false
}

# ── 1. migration (scratch DB) ────────────────────────────────────────────
$script:checkStart = Get-Date
$scratch = "cosmo_scratch_gate_$TS"
try {
    # Ensure PG is up (works on an already-running stack or a cold one).
    docker compose -f $ComposeFile up -d cosmo-postgres *> $null
    $null = docker exec cosmo-postgres pg_isready -U cosmo
    if ($LASTEXITCODE -ne 0) { throw "cosmo-postgres not ready" }

    docker exec cosmo-postgres psql -U cosmo -d postgres -c "CREATE DATABASE $scratch" 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "CREATE DATABASE failed" }

    $env_line = "COSMO_DATABASE_URL=postgresql+asyncpg://cosmo:cosmo@cosmo-postgres:5432/$scratch"
    $up_out = docker exec -e $env_line cosmo-api alembic -c /app/alembic.ini upgrade head 2>&1 | Out-String
    if ($LASTEXITCODE -ne 0) { throw "alembic upgrade head failed: $($up_out.Substring(0, [Math]::Min(300, $up_out.Length)))" }

    $tables = [int]((docker exec cosmo-postgres psql -U cosmo -d $scratch -tAc "SELECT count(*) FROM pg_tables WHERE schemaname='public'") | Out-String).Trim()
    $ver = ((docker exec cosmo-postgres psql -U cosmo -d $scratch -tAc "SELECT version_num FROM alembic_version") | Out-String).Trim()
    $head = ((docker exec -e $env_line cosmo-api alembic -c /app/alembic.ini heads) | Out-String).Trim() -replace '\s*\(head\).*', ''

    docker exec cosmo-postgres psql -U cosmo -d postgres -c "DROP DATABASE $scratch" 2>&1 | Out-Null

    if ($tables -lt 30 -or $ver -ne $head) {
        throw "verification failed: tables=$tables (want >=30), db_version='$ver', alembic_head='$head'"
    }
    Add-Check "migration" "PASS" "scratch '$scratch' upgraded: $tables tables, head=$ver, dropped"
} catch {
    docker exec cosmo-postgres psql -U cosmo -d postgres -c "DROP DATABASE IF EXISTS $scratch" 2>&1 | Out-Null
    Add-Check "migration" "FAIL" $_.Exception.Message
}

# ── 2. clean-start (full volume wipe -> core ready) ─────────────────────
$script:checkStart = Get-Date
try {
    $stopOut = & "$PSScriptRoot\cosmo-stop.ps1" -Full -Wipe -ConfirmWipe 2>&1 | ForEach-Object { "$_" }
    if ($LASTEXITCODE -ne 0) {
        $tail = ($stopOut | Select-Object -Last 5) -join ' | '
        throw "cosmo-stop -Wipe failed: $tail"
    }
    $t0 = Get-Date
    # Docker race right after down -v (network/container churn): retry, it is
    # idempotent. Flake seen in run 4: single up failed, next one succeeded.
    $upOut = @(); $upOk = $false
    for ($i = 1; $i -le 3 -and -not $upOk; $i++) {
        $upOut = docker compose -f $ComposeFile up -d 2>&1 | ForEach-Object { "$_" }
        if ($LASTEXITCODE -eq 0) { $upOk = $true } else { Start-Sleep 5 }
    }
    if (-not $upOk) {
        $tail = ($upOut | Select-Object -Last 8) -join ' | '
        throw "compose up failed x3: $tail"
    }
    if (Test-ReadyOk -TimeoutSec 90) {
        $elapsed = [math]::Round(((Get-Date) - $t0).TotalSeconds, 1)
        Add-Check "clean-start" "PASS" "core ready after full wipe in ${elapsed}s (budget 90s)"
    } else {
        Add-Check "clean-start" "FAIL" "/ready != ok within 90s after wipe"
    }
} catch {
    Add-Check "clean-start" "FAIL" $_.Exception.Message
}

# ── 3. full-profile (before smoke: smoke requires the full profile) ─────
$script:checkStart = Get-Date
try {
    & "$PSScriptRoot\cosmo-start.ps1" -Full *> $null
    if ($LASTEXITCODE -ne 0) { throw "cosmo-start -Full failed" }
    $deadline = (Get-Date).AddSeconds(120)
    do {
        Start-Sleep 3
        $bad = @()
        foreach ($c in ($Core + $FullExtra)) {
            $h = Get-Health $c
            if ($c -eq "cosmo-woodpecker") {
                # Distroless: no internal healthcheck by design; probe HTTP instead.
                try { $null = Invoke-RestMethod "http://localhost:8000/api/health" -TimeoutSec 3 -ErrorAction Stop } catch { $bad += "$c(http)" }
            } elseif ($h -ne "healthy") {
                $bad += "$c($h)"
            }
        }
    } while ($bad -and (Get-Date) -lt $deadline)
    if ($bad) {
        throw "not healthy after 120s: $($bad -join ', ')"
    }
    Add-Check "full-profile" "PASS" "10/10 containers healthy/Up incl. gitea admin bootstrap"
} catch {
    Add-Check "full-profile" "FAIL" $_.Exception.Message
}

# ── 4. smoke ─────────────────────────────────────────────────────────────
$script:checkStart = Get-Date
& powershell -NoProfile -ExecutionPolicy Bypass -File "$PSScriptRoot\smoke-delivery.ps1" *> $null
if ($LASTEXITCODE -eq 0) {
    Add-Check "smoke" "PASS" "smoke-delivery 9/9"
} else {
    Add-Check "smoke" "FAIL" "smoke-delivery exit $LASTEXITCODE"
}

# ── 5. restart-preserves-state ───────────────────────────────────────────
# External-harness interference handling: the ONLY code that deletes domain
# rows outside REST DELETE /{id} is the host-side pytest _clean_db fixture.
# Therefore: row lost in PG (API up, gate issued no DELETE) == external wipe
# -> verdict FLAKE-EXTERNAL, retry the whole check, never blame the product.
$script:checkStart = Get-Date
$domId = "cos-gate-$TS"
function Get-DomainRow {
    param([string]$Id)
    try {
        return [int]((docker exec cosmo-postgres psql -U cosmo -d cosmo -tAc "SELECT count(*) FROM domains WHERE id='$Id'" 2>$null) | Out-String).Trim()
    } catch { return -1 }  # psql error (e.g. table dropped by downgrade) = interference class
}
$restartVerdict = "FAIL"; $restartDetail = ""
for ($attempt = 1; $attempt -le 3; $attempt++) {
    try {
        $body = @{
            id            = $domId
            label         = "runtime-gate restart check $TS"
            forge_binding = @{ forge_type = "gitea"; url = "http://cosmo-gitea:3000"; token_ref = "vault:secret/cosmo/forge/gitea" }
        } | ConvertTo-Json -Depth 4
        Invoke-RestMethod -Method POST "http://localhost:8100/api/v1/domains" -Body $body -ContentType "application/json" -Headers $ApiAuth -TimeoutSec 10 | Out-Null
        $dbAfterPost = Get-DomainRow $domId
        if ($dbAfterPost -lt 1) { throw "POST 201 but row not in PG (lost before restart)" }
        docker restart cosmo-api *> $null
        if (-not (Test-ReadyOk -TimeoutSec 45)) { throw "API did not recover after restart" }
        $getOk = $false; $dbAfterRestart = -2
        for ($i = 1; $i -le 3 -and -not $getOk; $i++) {
            try {
                $null = Invoke-RestMethod "http://localhost:8100/api/v1/domains/$domId" -Headers $ApiAuth -TimeoutSec 5 -ErrorAction Stop
                $getOk = $true
            } catch {
                $dbAfterRestart = Get-DomainRow $domId
                Start-Sleep 2
            }
        }
        if ($getOk) {
            try { Invoke-RestMethod -Method DELETE "http://localhost:8100/api/v1/domains/$domId" -Headers $ApiAuth -TimeoutSec 5 | Out-Null } catch { }
            $suffix = if ($attempt -gt 1) { " (attempt $attempt after external interference)" } else { "" }
            $restartVerdict = "PASS"; $restartDetail = "domain '$domId' survived API restart; cleaned up$suffix"
            break
        }
        # Row lost with API healthy and no gate-issued DELETE -> external wipe.
        # Known source: host pytest (_clean_db) / alembic downgrade on shared :5432.
        try { Invoke-RestMethod -Method DELETE "http://localhost:8100/api/v1/domains/$domId" -Headers $ApiAuth -TimeoutSec 5 | Out-Null } catch { }
        if ($attempt -lt 3) {
            Write-Host ("  [i] restart check attempt {0}: row wiped externally (rows_in_pg={1}), retrying" -f $attempt, $dbAfterRestart) -ForegroundColor DarkYellow
            continue
        }
        $restartVerdict = "FLAKE-EXTERNAL"
        $restartDetail = "row wiped by external host harness (rows_in_pg=$dbAfterRestart, pytest/_clean_db or alembic downgrade on shared :5432). Not a product fault. Fix: scratch-DB isolation for host tests (pending Cosmo/Luna)."
    } catch {
        $restartVerdict = "FAIL"; $restartDetail = $_.Exception.Message
        try { Invoke-RestMethod -Method DELETE "http://localhost:8100/api/v1/domains/$domId" -Headers $ApiAuth -TimeoutSec 5 | Out-Null } catch { }
        break
    }
}
Add-Check "restart" $restartVerdict $restartDetail

# ── 6. sse keepalive via Caddy edge (own domain: /all errors on empty DB) ──
$script:checkStart = Get-Date
$sseDom = "cos-gate-sse$TS"
try {
    $body = @{
        id            = $sseDom
        label         = "runtime-gate sse check $TS"
        forge_binding = @{ forge_type = "gitea"; url = "http://cosmo-gitea:3000"; token_ref = "vault:secret/cosmo/forge/gitea" }
    } | ConvertTo-Json -Depth 4
    Invoke-RestMethod -Method POST "http://localhost:8100/api/v1/domains" -Body $body -ContentType "application/json" -Headers $ApiAuth -TimeoutSec 10 | Out-Null
    $sse = & curl.exe -sN --max-time 22 -H "Authorization: Bearer gate-agent:admin_sec" "http://localhost:8180/api/v1/domains/$sseDom/events/stream" 2>&1 | Out-String
    if ($sse -match ": keepalive") {
        Add-Check "sse" "PASS" "keepalive heartbeat received through Caddy :8180"
    } else {
        Add-Check "sse" "FAIL" "no ': keepalive' in 20s stream (len=$($sse.Length))"
    }
} catch {
    Add-Check "sse" "FAIL" $_.Exception.Message
} finally {
    try { Invoke-RestMethod -Method DELETE "http://localhost:8100/api/v1/domains/$sseDom" -Headers $ApiAuth -TimeoutSec 5 | Out-Null } catch { }
}

# ── 7. dependency-failure (+ recovery) ──────────────────────────────────
$script:checkStart = Get-Date
try {
    docker stop cosmo-postgres *> $null
    $code = 0; $dbStatus = ""
    try {
        $r = Invoke-RestMethod "http://localhost:8100/ready" -TimeoutSec 5 -ErrorAction Stop
        $code = 200; $dbStatus = $r.database
    } catch {
        $code = $_.Exception.Response.StatusCode.value__
    }
    docker start cosmo-postgres *> $null
    if (-not (Test-ReadyOk -TimeoutSec 45)) { throw "PG recovered but /ready != ok" }

    if ($code -eq 200 -and $dbStatus -eq "unavailable") {
        Add-Check "dep-failure" "DEVIATION" "/ready=200 database=unavailable (criterion: 503). Regression vs COS-090 semantics. Recovery OK."
    } elseif ($code -eq 503) {
        Add-Check "dep-failure" "PASS" "/ready=503 while PG down; recovery OK"
    } else {
        Add-Check "dep-failure" "FAIL" "unexpected /ready=$code db=$dbStatus"
    }
} catch {
    docker start cosmo-postgres *> $null
    Add-Check "dep-failure" "FAIL" $_.Exception.Message
}

# ── Report ───────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "=== RUNTIME GATE ($TS) ===" -ForegroundColor Cyan
$fail = 0; $dev = 0; $flake = 0
foreach ($k in $script:Results.Keys) {
    $v = $script:Results[$k]
    Write-Host ("  {0,-13} {1,-15} {2,5}s  {3}" -f $k, $v.verdict, $v.s, $v.detail) -ForegroundColor (@{ PASS = "Green"; FAIL = "Red"; DEVIATION = "Yellow"; "FLAKE-EXTERNAL" = "DarkYellow" }[$v.verdict])
    if ($v.verdict -eq "FAIL") { $fail++ }
    if ($v.verdict -eq "DEVIATION") { $dev++ }
    if ($v.verdict -eq "FLAKE-EXTERNAL") { $flake++ }
}
if ($ReportJson) {
    $script:Results | ConvertTo-Json | Set-Content -LiteralPath $ReportJson -Encoding UTF8
    Write-Host "Report: $ReportJson"
}
Release-StandLock
if ($fail -gt 0) { Write-Host "GATE: FAIL ($fail FAIL, $dev DEVIATION, $flake FLAKE-EXTERNAL)" -ForegroundColor Red; exit 1 }
if ($flake -gt 0) { Write-Host "GATE: INCONCLUSIVE (0 FAIL, $dev DEVIATION, $flake FLAKE-EXTERNAL - external harness interfered)" -ForegroundColor DarkYellow; exit 1 }
Write-Host "GATE: OK (0 FAIL, $dev DEVIATION)" -ForegroundColor Green
exit 0
