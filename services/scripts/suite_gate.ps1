# COS-089: Suite gate - the whole cosmo suite in one command, isolated.
#
# Usage:  .\services\scripts\suite_gate.ps1 [-SkipDockerUp] [-PyPath <path>]
#
# What it does:
#   1. Ensures the isolated test PG (:5433) is up (docker compose test-pg).
#   2. Sets COSMO_TEST_SESSION_DB=1 -> the run gets its OWN database
#      cosmo_test_s<hex> on the test instance (COS-076): schema bootstrap,
#      data and wipe never touch the shared cosmo_test; the session DB is
#      dropped at process exit (atexit). Idempotent from a clean state.
#   3. Runs python -m pytest orchestrator/tests/cosmo -q.
#   4. Prints the verdict (PASS/FAIL + pytest summary) and propagates the
#      pytest exit code as the script exit code.
#
# Exit codes: 0 = suite green; 1 = suite failed; 2 = infra error
#             (docker unreachable / test PG did not come up).
#
# NOTE: ASCII-only on purpose - PowerShell 5.1 reads BOM-less .ps1 as ANSI
# and multibyte UTF-8 punctuation breaks the parser.
param(
    [switch]$SkipDockerUp,
    [string]$PyPath = ""
)
$ErrorActionPreference = "Continue"
$Repo = Resolve-Path "$PSScriptRoot\..\.."   # services/scripts -> repo root
$ComposeTestPg = "$Repo\services\docker-compose.test-pg.yml"

# -- python resolution: explicit -PyPath > PATH > canonical dev path ------
if ($PyPath -eq "") {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd) { $PyPath = $cmd.Source }
    elseif (Test-Path "C:\Users\mails\AppData\Local\Programs\Python\Python313\python.exe") {
        $PyPath = "C:\Users\mails\AppData\Local\Programs\Python\Python313\python.exe"
    } else {
        Write-Host "[FAIL] python not found (use -PyPath)" -ForegroundColor Red
        exit 2
    }
}

# -- 1. test PG up ---------------------------------------------------------
if (-not $SkipDockerUp) {
    docker info *> $null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[FAIL] docker unreachable" -ForegroundColor Red
        exit 2
    }
    # NOTE: no exit-code verdict here - PS5.1 wraps docker stderr warnings
    # (orphan containers etc.) and the real verdict is the TCP probe below.
    docker compose -f $ComposeTestPg up -d *> $null
}
# Probe: test PG port answers (plain TCP connect, no driver import).
& $PyPath -c "import socket; s=socket.socket(); s.settimeout(3); r=s.connect_ex(('127.0.0.1',5433)); s.close(); exit(0 if r == 0 else 1)" *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host "[FAIL] test PG :5433 did not come up" -ForegroundColor Red
    exit 2
}

# -- 2+3. isolated session DB + full suite --------------------------------
$env:COSMO_TEST_SESSION_DB = "1"
Write-Host "[i] COSMO_TEST_SESSION_DB=1 - run isolated in its own test DB" -ForegroundColor DarkCyan
Push-Location $Repo
& $PyPath -m pytest orchestrator/tests/cosmo -q
$SuiteExit = $LASTEXITCODE
Remove-Item Env:\COSMO_TEST_SESSION_DB -ErrorAction SilentlyContinue
Pop-Location

# -- 4. verdict -------------------------------------------------------------
if ($SuiteExit -eq 0) {
    Write-Host "SUITE GATE: PASS" -ForegroundColor Green
} else {
    Write-Host "SUITE GATE: FAIL (pytest exit $SuiteExit)" -ForegroundColor Red
}
exit $SuiteExit
