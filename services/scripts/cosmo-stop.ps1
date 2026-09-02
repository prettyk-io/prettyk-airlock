# COS-059: Cosmoport graceful shutdown.
# Usage: .\services\scripts\cosmo-stop.ps1 [-Full] [-Wipe]
# Default: stop core containers (data volumes preserved).
# -Full : also stop profile:full services.
# -Wipe : ALSO DELETE VOLUMES (PostgreSQL/Valkey state DESTROYED). Requires -ConfirmWipe.
param(
    [switch]$Full,
    [switch]$Wipe,
    [switch]$ConfirmWipe,
    [string]$ComposeFile = "$PSScriptRoot\..\docker-compose.yml"
)
$ErrorActionPreference = "Stop"

$args_ = @("compose", "-f", $ComposeFile)
if ($Full -or $Wipe) { $args_ += "--profile", "full" }
$args_ += "down"
if ($Wipe) {
    if (-not $ConfirmWipe) {
        Write-Error "-Wipe destroys PostgreSQL/Valkey volumes. Re-run with -Wipe -ConfirmWipe to proceed."
        exit 1
    }
    $args_ += "-v"
}

# PS 5.1: docker writes progress to stderr; with EAP=Stop any stderr line
# becomes a terminating error on a perfectly healthy shutdown.
$ErrorActionPreference = "Continue"
& docker @args_ 2>&1 | ForEach-Object { "$_" }
if ($LASTEXITCODE -ne 0) {
    Write-Host "[FAIL] docker compose down exit $LASTEXITCODE. Partial state:" -ForegroundColor Red
    docker ps -a --filter "name=cosmo-" --format "{{.Names}}  {{.Status}}"
    exit 1
}

if ($Wipe) {
    Write-Host "=== Cosmoport DOWN, volumes WIPED ===" -ForegroundColor Red
} else {
    Write-Host "=== Cosmoport DOWN (state preserved) ===" -ForegroundColor Green
}
exit 0