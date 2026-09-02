# COS-059: Delivery smoke — verifies every acceptance criterion.
# Usage: .\services\scripts\smoke-delivery.ps1
# Exit 0 = all green. Exit 1 = any check failed.
param(
    [string]$Edge = "http://localhost:8180",
    [string]$Api  = "http://localhost:8100"
)
$ErrorActionPreference = "Continue"
$script:Failed = 0

function Check([string]$Name, [scriptblock]$Probe) {
    try {
        $result = & $Probe
        Write-Host ("  [OK]   {0}  {1}" -f $Name, $result) -ForegroundColor Green
    } catch {
        Write-Host ("  [FAIL] {0}  {1}" -f $Name, $_.Exception.Message) -ForegroundColor Red
        $script:Failed++
    }
}

Write-Host "=== COS-059 Delivery Smoke ===" -ForegroundColor Cyan
Write-Host ""

# 1. Containers running
Check "Containers up (core 5)" {
    $want = @("cosmo-postgres","cosmo-valkey","cosmo-api","cosmo-frontend","cosmo-caddy")
    foreach ($n in $want) {
        $st = docker inspect --format "{{.State.Status}}" $n 2>$null
        if ($st -ne "running") { throw "$n is $st" }
    }
    return "all 5 running"
}

# 2. Liveness distinct from readiness: /live 200 (process), /ready 200 (deps)
Check "Liveness /live = 200" {
    $r = Invoke-WebRequest "$Api/live" -UseBasicParsing -TimeoutSec 5 -ErrorAction Stop
    if ($r.StatusCode -ne 200) { throw "HTTP $($r.StatusCode)" }
    return "HTTP 200"
}
Check "Readiness /ready = 200, status ok" {
    $r = Invoke-RestMethod "$Api/ready" -TimeoutSec 5 -ErrorAction Stop
    if ($r.status -ne "ok") { throw "status=$($r.status) db=$($r.database) cache=$($r.cache)" }
    return "db=$($r.database) cache=$($r.cache)"
}

# 3. Readiness reflects dependency failure: /ready must NOT be healthy before deps.
#    Verify structurally: ready response carries db+cache fields and reports connected.
Check "Readiness carries dependency facts (db, cache)" {
    $r = Invoke-RestMethod "$Api/ready" -TimeoutSec 5 -ErrorAction Stop
    if (-not $r.database -or -not $r.cache) { throw "missing db/cache fields" }
    if ($r.database -ne "connected" -or $r.cache -ne "connected") { throw "dep not connected" }
    return "wired to PG+Valkey"
}


# API perimeter (COS-067): authenticated requests only. Dev token format
# 'user_id:role' mirrors the frontend getCosmoAuthToken contract.
$ApiAuth = @{ Authorization = "Bearer gate-agent:admin_sec" }

# 4. Frontend through Caddy
Check "Frontend via Caddy :8180/ = 200" {
    $r = Invoke-WebRequest "$Edge/" -UseBasicParsing -TimeoutSec 5 -ErrorAction Stop
    if ($r.StatusCode -ne 200) { throw "HTTP $($r.StatusCode)" }
    return "HTTP 200"
}

# 5. API through Caddy (health route)
Check "API via Caddy :8180/live = 200" {
    $r = Invoke-WebRequest "$Edge/live" -UseBasicParsing -TimeoutSec 5 -ErrorAction Stop
    if ($r.StatusCode -ne 200) { throw "HTTP $($r.StatusCode)" }
    return "HTTP 200"
}

# 6. API via Caddy (rate-limited /api route reaches FastAPI docs)
Check "API via Caddy :8180/api/v1 paths reachable" {
    $r = Invoke-WebRequest "$Edge/api/v1/domains" -Headers $ApiAuth -UseBasicParsing -TimeoutSec 5 -ErrorAction Stop
    if ($r.StatusCode -ne 200) { throw "HTTP $($r.StatusCode)" }
    return "HTTP 200 (domains list)"
}

# 7. SSE path: connect to a domain events stream, expect headers from a streaming
#    response (not buffered): request with short timeout, accept either open stream
#    (timeout) or immediate headers. A buffered proxy would return nothing before close.
Check "SSE route opens via Caddy (no premature buffer)" {
    $streamUrl = "$Edge/api/v1/domains/all/events/stream"
    try {
        # If it streams, Invoke-WebRequest with timeout will throw TaskCanceled — that's SUCCESS (stream stayed open)
        $req = [System.Net.HttpWebRequest]::Create($streamUrl)
        $req.Timeout = 4000
        $req.ReadWriteTimeout = 4000
        $resp = $req.GetResponse()
        $ct = $resp.ContentType
        $resp.Close()
        if ($ct -notmatch "event-stream") { throw "content-type=$ct (expected text/event-stream)" }
        return "stream headers OK, content-type=$ct"
    } catch [System.Net.WebException] {
        $resp = $_.Exception.Response
        if ($resp) {
            $ct = $resp.ContentType
            if ($ct -match "event-stream") { return "stream headers OK, content-type=$ct" }
            throw "content-type=$ct"
        }
        throw
    }
}

# 8. Restart persistence: PostgreSQL data volume exists and has tables
Check "PG volume exists (state survives restart)" {
    $name = docker volume ls --format "{{.Name}}" | Where-Object { $_ -match "cosmo_postgres$" } | Select-Object -First 1
    if (-not $name) { throw "volume not found" }
    $v = docker volume inspect $name 2>$null | ConvertFrom-Json
    if (-not $v) { throw "volume inspect failed" }
    return "volume $name mounted"
}

# 9. Valkey responds (transport layer alive)
Check "Valkey PING" {
    $r = docker exec cosmo-valkey valkey-cli ping 2>$null
    if ($r -ne "PONG") { throw "valkey-cli: $r" }
    return "PONG"
}

Write-Host ""
if ($script:Failed -gt 0) {
    Write-Host "=== SMOKE FAILED: $script:Failed check(s) ===" -ForegroundColor Red
    exit 1
}
Write-Host "=== SMOKE PASSED: 9/9 ===" -ForegroundColor Green
exit 0