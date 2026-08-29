# Cosmoport 2.0 — airgap installer (Windows)
#
# На чистой airgap-машине (без интернета):
#   1. tar -xzf cosmoport2-vX.Y.Z-airgap.tar.gz
#   2. .\scripts\install.ps1
#
# Инвариант: 0 внешних сетевых запросов.
param(
    [string]$DataDir = "cosmo-data"
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $PSCommandPath
$BundleRoot = Resolve-Path (Join-Path $ScriptDir "..")

Write-Host "=== Cosmoport 2.0 Airgap Install ==="

# 1. Проверить Docker
$dockerVersion = & docker version --format '{{.Server.Version}}' 2>$null
if ($LASTEXITCODE -ne 0) {
    throw "Docker Engine not available."
}
Write-Host "Docker $dockerVersion OK"

# 2. Загрузить образы
Write-Host "[install] load images"
Get-ChildItem "$BundleRoot\images\*.tar" | ForEach-Object {
    Write-Host "  $($_.Name)"
    docker load -i $_.FullName
    if ($LASTEXITCODE -ne 0) { throw "docker load failed: $($_.Name)" }
}

# 3. Стартовать все 10 сервисов
Write-Host "[install] start Cosmo stack"
docker compose -f "$BundleRoot\compose\docker-compose.yml" up -d
if ($LASTEXITCODE -ne 0) { throw "compose up failed" }

Write-Host "=== install OK ==="
Write-Host "  API:       https://localhost/api/live"
Write-Host "  Dashboard: https://localhost/"
Write-Host "  Forge:     https://localhost/forge/"
Write-Host "  Artifacts: https://localhost/artifacts/"