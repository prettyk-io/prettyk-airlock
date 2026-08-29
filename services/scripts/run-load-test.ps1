# Cosmoport 2.0 — Load Test Runner (COS-068)
#
# Запускает Locust нагрузочный тест через Caddy.
#   .\services\scripts\run-load-test.ps1
#
# Параметры:
#   -Users 100       virtual users (default 100)
#   -Duration 60     test duration in seconds (default 60)
#   -SpawnRate 10    users spawned per second (default 10)
#   -Host http://127.0.0.1:8080   target URL (Caddy)
#   -SkipSeed        skip data seeding (use if already seeded)
#   -SkipCleanup     leave seed data after test
#
# Пороги:
#   p95 latency < 300ms
#   Error rate < 0.5%
#
# Перед запуском:
#   docker compose up -d cosmo-postgres cosmo-valkey cosmo-api cosmo-caddy
param(
    [int]$Users = 100,
    [int]$Duration = 60,
    [int]$SpawnRate = 10,
    [string]$Host = "http://127.0.0.1:8080",
    [switch]$SkipSeed,
    [switch]$SkipCleanup
)

$ErrorActionPreference = "Stop"
$ScriptRoot = Split-Path -Parent $PSCommandPath
$RepoRoot = Resolve-Path (Join-Path $ScriptRoot "..\..")
$LocustFile = Join-Path $RepoRoot "services\load_tests\locustfile.py"
$ReportDir = Join-Path $RepoRoot "reports"
$Timestamp = Get-Date -Format "yyyy-MM-dd_HHmm"
$CsvPrefix = "$ReportDir\load-test-$Timestamp"

# ── Ensure reports dir ───────────────────────────────────────────────
New-Item -ItemType Directory -Force -Path $ReportDir | Out-Null

# ── Smoke: API alive? ────────────────────────────────────────────────
Write-Host "=== Cosmoport 2.0 Load Test ===" -ForegroundColor Cyan
Write-Host "  Users: $Users | Duration: ${Duration}s | Spawn: ${SpawnRate}/s"
Write-Host "  Target: $Host"
Write-Host ""

Write-Host "[pre-flight] Smoke check API..." -ForegroundColor Cyan
try {
    $r = Invoke-WebRequest -Uri "$Host/live" -UseBasicParsing -TimeoutSec 5
    Write-Host "  API live: OK (HTTP $($r.StatusCode))" -ForegroundColor Green
} catch {
    Write-Host "  API live: FAIL — $($_.Exception.Message)" -ForegroundColor Red
    Write-Host "  Is docker compose up -d cosmo-api cosmo-caddy running?" -ForegroundColor Yellow
    exit 1
}

# ── Seed data ────────────────────────────────────────────────────────
if (-not $SkipSeed) {
    Write-Host "[seed] Creating test entities..." -ForegroundColor Cyan
    $seedScript = @"
import sys; sys.path.insert(0, r'$RepoRoot\services\load_tests')
from locustfile import seed_load_test_data
ok = seed_load_test_data('$Host')
sys.exit(0 if ok else 1)
"@
    $seedResult = & python -c $seedScript 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  Seed FAIL: $seedResult" -ForegroundColor Red
        exit 1
    }
    Write-Host "  Seed OK" -ForegroundColor Green
} else {
    Write-Host "[seed] SKIPPED (-SkipSeed)" -ForegroundColor Yellow
}

# ── Проверка что Locust установлен ──────────────────────────────────
Write-Host "[check] Locust installation..." -ForegroundColor Cyan
$locustCheck = & python -c "import locust; print(locust.__version__)" 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "  Locust NOT installed. Installing..." -ForegroundColor Yellow
    & pip install locust 2>&1 | Select-Object -Last 1
    if ($LASTEXITCODE -ne 0) { throw "Failed to install locust" }
}
Write-Host "  Locust ready" -ForegroundColor Green

# ── Run Locust ───────────────────────────────────────────────────────
Write-Host ""
Write-Host "[load] Running Locust — $Users users × ${Duration}s..." -ForegroundColor Cyan
Write-Host "  This will take ~$Duration seconds..." -ForegroundColor DarkGray

$locustArgs = @(
    "-f", $LocustFile,
    "--host", $Host,
    "--users", $Users,
    "--spawn-rate", $SpawnRate,
    "--run-time", "${Duration}s",
    "--headless",
    "--csv", $CsvPrefix,
    "--html", "$CsvPrefix.html",
    "--only-summary"
)

$sw = [Diagnostics.Stopwatch]::StartNew()
$locustOutput = & locust @locustArgs 2>&1
$exitCode = $LASTEXITCODE
$sw.Stop()

Write-Host ""
Write-Host "  Elapsed: $([math]::Round($sw.Elapsed.TotalSeconds,1))s" -ForegroundColor White

# ── Parse results ────────────────────────────────────────────────────
Write-Host ""
Write-Host "=== Results ===" -ForegroundColor Cyan

$statsFile = "$CsvPrefix`_stats.csv"
if (Test-Path $statsFile) {
    $stats = Import-Csv $statsFile
    $agg = $stats | Where-Object { $_.Name -eq "Aggregated" }

    if ($agg) {
        $totalReq = [int]$agg."Request Count"
        $failReq = [int]$agg."Failure Count"
        $errorRate = if ($totalReq -gt 0) { [math]::Round($failReq / $totalReq * 100, 2) } else { 0 }
        $p95 = $agg."95%"
        $avg = $agg."Average"

        Write-Host "  Total Requests:  $totalReq" -ForegroundColor White
        Write-Host "  Failures:        $failReq ($errorRate%)" -ForegroundColor $(if ($errorRate -lt 0.5) { "Green" } else { "Red" })
        Write-Host "  Avg Latency:     ${avg}ms" -ForegroundColor White
        Write-Host "  P95 Latency:     ${p95}ms" -ForegroundColor $(if ([double]$p95 -lt 300) { "Green" } else { "Red" })
        Write-Host "  RPS:             $([math]::Round($agg."Requests/s", 1))" -ForegroundColor White
    }

    # Per-endpoint breakdown
    Write-Host ""
    Write-Host "Per-endpoint:" -ForegroundColor DarkGray
    $stats | Where-Object { $_.Type -eq "" -and $_.Name -ne "Aggregated" } | Sort-Object { [int]$_.'Request Count' } -Descending | Select-Object -First 10 | ForEach-Object {
        $color = if ([int]$_.'Failure Count' -gt 0) { "Yellow" } else { "White" }
        Write-Host "  $($_.Name.PadRight(30)) $($_.'Request Count'.PadLeft(6)) req  avg $($_.'Average'.PadLeft(5))ms  p95 $($_.'95%'.PadLeft(5))ms  fail $($_.'Failure Count')" -ForegroundColor $color
    }
}

# ── Threshold check ──────────────────────────────────────────────────
Write-Host ""
Write-Host "=== Thresholds ===" -ForegroundColor Cyan

$p95Pass = $true; $errPass = $true
if ($agg) {
    if ([double]$p95 -lt 300) {
        Write-Host "  PASS: p95 latency ${p95}ms < 300ms" -ForegroundColor Green
    } else {
        Write-Host "  FAIL: p95 latency ${p95}ms >= 300ms" -ForegroundColor Red
        $p95Pass = $false
    }

    if ($errorRate -lt 0.5) {
        Write-Host "  PASS: Error rate ${errorRate}% < 0.5%" -ForegroundColor Green
    } else {
        Write-Host "  FAIL: Error rate ${errorRate}% >= 0.5%" -ForegroundColor Red
        $errPass = $false
    }
} else {
    Write-Host "  WARN: No aggregated stats found" -ForegroundColor Yellow
}

# ── Cleanup ──────────────────────────────────────────────────────────
if (-not $SkipCleanup) {
    Write-Host ""
    Write-Host "[cleanup] Removing test data..." -ForegroundColor Cyan
    $cleanupScript = @"
import sys; sys.path.insert(0, r'$RepoRoot\services\load_tests')
from locustfile import cleanup_load_test_data
cleanup_load_test_data('$Host')
"@
    & python -c $cleanupScript 2>&1 | ForEach-Object { Write-Host "  $_" -ForegroundColor DarkGray }
} else {
    Write-Host "[cleanup] SKIPPED (-SkipCleanup)" -ForegroundColor Yellow
}

# ── Final verdict ────────────────────────────────────────────────────
Write-Host ""
Write-Host "  Report: $CsvPrefix.html" -ForegroundColor Magenta
Write-Host "  CSV:    $CsvPrefix`_stats.csv" -ForegroundColor Magenta

if ($p95Pass -and $errPass) {
    Write-Host "`n=== ALL THRESHOLDS PASSED ===" -ForegroundColor Green
    exit 0
} else {
    Write-Host "`n=== THRESHOLDS FAILED — check report ===" -ForegroundColor Red
    exit 1
}