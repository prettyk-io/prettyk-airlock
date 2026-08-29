# Cosmoport 2.0 — Rate Limit Verification Script (COS-067)
#
# Before running:
#   docker compose -f docker-compose.yml up -d cosmo-caddy cosmo-api
param(
    [string]$BaseUrl = "http://127.0.0.1:8080",
    [int]$RateLimitPerMinute = 100
)

$ErrorActionPreference = "Continue"
$Passed = 0
$Failed = 0

Write-Host "=== Cosmo Rate Limit Test ===" -ForegroundColor Cyan
Write-Host "Target: $BaseUrl (limit: $RateLimitPerMinute req/min)" -ForegroundColor Cyan
Write-Host ""

# Test 1: Health endpoints UNLIMITED
Write-Host "Test 1: Health endpoints UNLIMITED" -ForegroundColor Cyan

$healthUris = @("/live", "/ready", "/health")
$okCount = 0
foreach ($uri in $healthUris) {
    for ($i = 0; $i -lt 5; $i++) {
        try {
            $r = Invoke-WebRequest -Uri "$BaseUrl$uri" -UseBasicParsing -TimeoutSec 2
            if ($r.StatusCode -eq 200) { $okCount++ }
        } catch {}
    }
}
Write-Host "  Health probes: $okCount/15 OK" -ForegroundColor White
if ($okCount -eq 15) {
    Write-Host "  PASS: All health probes pass (unlimited)" -ForegroundColor Green
    $Passed++
} else {
    Write-Host "  FAIL: Health probes rate-limited ($okCount/15)" -ForegroundColor Red
    $Failed++
}
Write-Host ""

# Test 2: /api/* rate-limited
Write-Host "Test 2: /api/* rate-limited at $RateLimitPerMinute req/min" -ForegroundColor Cyan

$apiUri = "$BaseUrl/api/v1/domains"
$successCount = 0
$rateLimitedCount = 0
$totalRequests = $RateLimitPerMinute + 20

for ($i = 0; $i -lt $totalRequests; $i++) {
    try {
        $r = Invoke-WebRequest -Uri $apiUri -UseBasicParsing -TimeoutSec 2
        $successCount++
    } catch {
        $sc = $_.Exception.Response.StatusCode.value__
        if ($sc -eq 429) { $rateLimitedCount++ }
    }
}

Write-Host "  Results: $successCount OK, $rateLimitedCount rate-limited" -ForegroundColor White
if ($rateLimitedCount -gt 0) {
    Write-Host "  PASS: Rate limiting active ($rateLimitedCount rejections)" -ForegroundColor Green
    $Passed++
} else {
    Write-Host "  FAIL: All $successCount passed - no rate limiting" -ForegroundColor Red
    $Failed++
}
Write-Host ""

# Test 3: Retry-After header on 429
Write-Host "Test 3: HTTP 429 has Retry-After header" -ForegroundColor Cyan

try {
    $r = Invoke-WebRequest -Uri $apiUri -UseBasicParsing -TimeoutSec 3
    Write-Host "  Request passed (zone may have reset)" -ForegroundColor Yellow
    $ra = $r.Headers["Retry-After"]
    if ($ra) {
        Write-Host "  PASS: Retry-After = $ra" -ForegroundColor Green
        $Passed++
    } else {
        Write-Host "  FAIL: No Retry-After header" -ForegroundColor Red
        $Failed++
    }
} catch {
    $sc = $_.Exception.Response.StatusCode.value__
    if ($sc -eq 429) {
        Write-Host "  Got HTTP 429" -ForegroundColor White
        $headers = $_.Exception.Response.Headers
        $ra = $headers["Retry-After"]
        if ($ra) {
            Write-Host "  PASS: Retry-After = $ra" -ForegroundColor Green
            $Passed++
        } else {
            Write-Host "  FAIL: No Retry-After on 429" -ForegroundColor Red
            Write-Host "  Available: $($headers.Keys -join ', ')" -ForegroundColor Yellow
            $Failed++
        }
    } else {
        Write-Host "  FAIL: Expected 429, got $sc" -ForegroundColor Red
        $Failed++
    }
}
Write-Host ""

# Summary
Write-Host "=== Results ===" -ForegroundColor Cyan
Write-Host "  Passed: $Passed" -ForegroundColor Green
Write-Host "  Failed: $Failed" -ForegroundColor $(if ($Failed -gt 0) { "Red" } else { "Green" })

if ($Failed -gt 0) { exit 1 } else { Write-Host "All tests passed!" -ForegroundColor Green; exit 0 }