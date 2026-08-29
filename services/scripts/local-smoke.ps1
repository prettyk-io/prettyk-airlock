# Cosmoport 2.0 — Local Smoke Automation (COS-098)
#
# Быстрый локальный прогон: старт API → E2E pipeline → таблица фаз → стоп.
#
#   .\services\scripts\local-smoke.ps1
#   .\services\scripts\local-smoke.ps1 -Port 8101 -SkipStart
param(
    [int]$Port = 8100,
    [string]$PyPath = "python",
    [int]$WaitApiSecs = 15,
    [switch]$SkipStart,
    [switch]$KeepAlive
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$ScriptRoot = Split-Path -Parent $PSCommandPath
$RepoRoot = Resolve-Path (Join-Path $ScriptRoot "..\..")
$BaseUrl = "http://127.0.0.1:$Port"
$ApiPid = $null

# ═══════════════════════════════════════════════════════════════════════
# Phase 0: Start API
# ═══════════════════════════════════════════════════════════════════════

if (-not $SkipStart) {
    Write-Host "=== Cosmo Local Smoke ===" -ForegroundColor Cyan
    Write-Host ""

    Write-Host "[smoke] Starting API on :$Port ..." -ForegroundColor Cyan
    $proc = Start-Process -FilePath $PyPath `
        -ArgumentList @("-m", "uvicorn", "orchestrator.cosmo.api.main:app", "--host", "0.0.0.0", "--port", $Port, "--log-level", "warning") `
        -WorkingDirectory $RepoRoot -WindowStyle Hidden -PassThru
    $ApiPid = $proc.Id

    Write-Host -NoNewline "[smoke] Waiting API ..." -ForegroundColor Cyan
    $alive = $false
    for ($i = 0; $i -lt $WaitApiSecs; $i++) {
        Start-Sleep -Seconds 1
        try {
            $r = Invoke-RestMethod -Uri "$BaseUrl/live" -TimeoutSec 2
            if ($r.status -eq "ok") { $alive = $true; break }
        } catch {}
        Write-Host -NoNewline "."
    }
    Write-Host ""
    if (-not $alive) {
        Write-Host "  FAIL: API did not start within ${WaitApiSecs}s" -ForegroundColor Red
        exit 1
    }
    Write-Host "  LIVE: $BaseUrl/live = ok" -ForegroundColor Green
    Write-Host ""
} else {
    Write-Host "=== Cosmo Local Smoke (API already running) ===" -ForegroundColor Cyan
    Write-Host ""
}

# ═══════════════════════════════════════════════════════════════════════
# Phase 1: Run E2E
# ═══════════════════════════════════════════════════════════════════════

$e2eScript = Join-Path $ScriptRoot "run-e2e-pipeline.ps1"
$sw = [Diagnostics.Stopwatch]::StartNew()
& $e2eScript -BaseUrl $BaseUrl 2>&1 | Out-Null
$e2eExit = $LASTEXITCODE
$sw.Stop()

# ═══════════════════════════════════════════════════════════════════════
# Phase 2: Report
# ═══════════════════════════════════════════════════════════════════════

Write-Host ""
Write-Host "=== E2E Results ===" -ForegroundColor Cyan

$reportFile = Join-Path $RepoRoot "reports\e2e-pipeline-report.json"

if (-not (Test-Path $reportFile)) {
    Write-Host "  Report file not found: $reportFile" -ForegroundColor Red
    if (-not $SkipStart -and $ApiPid) { Stop-Process -Id $ApiPid -Force -ErrorAction SilentlyContinue }
    exit 1
}

try {
    $report = Get-Content $reportFile -Raw -Encoding UTF8 | ConvertFrom-Json
} catch {
    Write-Host "  Failed to parse report: $_" -ForegroundColor Red
    if (-not $SkipStart -and $ApiPid) { Stop-Process -Id $ApiPid -Force -ErrorAction SilentlyContinue }
    exit 1
}

# Группировать шаги по фазам
$phaseNames = @(
    @{ id = "Domain";      match = "domain|domains" }
    @{ id = "Apps";        match = "app|apps" }
    @{ id = "Bricks";      match = "brick|bricks" }
    @{ id = "Plan";        match = "plan|compile" }
    @{ id = "Run";         match = "run\b|batch" }
    @{ id = "Gates";       match = "gate\b" }
    @{ id = "GOST";        match = "gost|evidence" }
    @{ id = "Release";     match = "release\b" }
    @{ id = "Transfer";    match = "transfer\b" }
    @{ id = "Verify";      match = "verify|dashboard|status dashboard" }
)

$phaseData = @{}
foreach ($pn in $phaseNames) { $phaseData[$pn.id] = @{ name = $pn.id; pass = 0; fail = 0; skip = 0 } }

foreach ($step in $report.steps) {
    $matched = "Other"
    foreach ($pn in $phaseNames) {
        if ($step.step -match $pn.match) { $matched = $pn.id; break }
    }
    if (-not $phaseData.ContainsKey($matched)) { $phaseData[$matched] = @{ name = $matched; pass = 0; fail = 0; skip = 0 } }
    switch ($step.status) {
        "PASS" { $phaseData[$matched].pass++ }
        "FAIL" { $phaseData[$matched].fail++ }
        "SKIP" { $phaseData[$matched].skip++ }
    }
}

Write-Host ""
Write-Host ("{0,-16} {1,5} {2,5} {3,5} {4}" -f "Phase", "PASS", "FAIL", "SKIP", "Status")
Write-Host ("{0,-16} {1,5} {2,5} {3,5} {4}" -f "----------------", "-----", "-----", "-----", "------")

foreach ($pn in @("Domain", "Apps", "Bricks", "Plan", "Run", "Gates", "GOST", "Release", "Transfer", "Verify")) {
    $d = $phaseData[$pn]
    if ($d) {
        $total = $d.pass + $d.fail
        $pct = if ($total -gt 0) { [math]::Round($d.pass / $total * 100, 0) } else { 100 }
        $status = if ($d.fail -eq 0 -and $total -gt 0) { "OK" } elseif ($total -eq 0) { "---" } else { "$pct%" }
        $color = if ($d.fail -gt 0) { "Red" } elseif ($total -gt 0) { "Green" } else { "Yellow" }
        Write-Host ("{0,-16} {1,5} {2,5} {3,5} " -f $pn, $d.pass, $d.fail, $d.skip) -NoNewline
        Write-Host $status -ForegroundColor $color
    }
}
Write-Host ("{0,-16} {1,5} {2,5} {3,5} {4}" -f "----------------", "-----", "-----", "-----", "------")
Write-Host ("{0,-16} {1,5} {2,5} {3,5} " -f "TOTAL", $report.passed, $report.failed, $report.total) -NoNewline
Write-Host $(if ($report.success) { "PASS" } else { "FAIL" }) -ForegroundColor $(if ($report.success) { "Green" } else { "Red" })

Write-Host ""
Write-Host "  Elapsed: $([math]::Round($sw.Elapsed.TotalSeconds, 1))s" -ForegroundColor White
Write-Host "  Report:  $reportFile" -ForegroundColor DarkGray
Write-Host "  URL:     $BaseUrl" -ForegroundColor DarkGray

# ═══════════════════════════════════════════════════════════════════════
# Cleanup
# ═══════════════════════════════════════════════════════════════════════

if (-not $SkipStart -and -not $KeepAlive -and $ApiPid) {
    Write-Host ""
    Write-Host "[smoke] Stopping API (PID=$ApiPid) ..." -ForegroundColor Cyan
    Stop-Process -Id $ApiPid -Force -ErrorAction SilentlyContinue
    Write-Host "  stopped" -ForegroundColor Green
}

exit $(if ($report.success) { 0 } else { 1 })