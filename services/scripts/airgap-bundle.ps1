# Cosmoport 2.0 — airgap bundle builder.
#
# Собирает самодостаточный offline-бандл для чистой airgap-машины:
#   .\services\scripts\airgap-bundle.ps1 [-Version 0.2.0]
#
# Формат бандла:
#   cosmoport2-vX.Y.Z-airgap.tar.gz
#   ├── manifest.json            # версии + checksums + совместимость
#   ├── images/                  # OCI-образы (.tar)
#   ├── compose/                 # docker-compose.yml + Caddyfile
#   ├── scripts/                 # install.ps1 / install.sh / verify-bundle.sh
#   ├── sbom/                    # supply-chain.cdx.json + license-report.json
#   └── checksums.sha256
#
# Инвариант: 0 внешних сетевых запросов при установке.
# pip install / npm install / playwright install — только на этапе сборки.
param(
    [string]$Version = "0.2.0",
    [string]$OutDir = "bundle-out"
)

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$ServicesDir = Join-Path $RepoRoot "services"
$BundleWork = Join-Path $RepoRoot $OutDir
$BundleName = "cosmoport2-v$Version-airgap"

# ═══════════════════════════════════════════════════════════════════════
# Карта образов
# ═══════════════════════════════════════════════════════════════════════

# Внешние образы (pull с Docker Hub / ghcr)
$PullImages = @(
    @{ Name = "postgres";              Tag = "16-alpine" },
    @{ Name = "valkey/valkey";         Tag = "8-alpine" },
    @{ Name = "openbao/openbao";       Tag = "2.2" },
    @{ Name = "minio/minio";           Tag = "RELEASE.2025-03-12T18-04-18Z" },
    @{ Name = "gitea/gitea";           Tag = "1.22.6" },
    @{ Name = "woodpeckerci/woodpecker-server"; Tag = "v3.5" },
    @{ Name = "woodpeckerci/woodpecker-agent";  Tag = "v3.5" },
    @{ Name = "caddy";                 Tag = "2.9-alpine" }
)

# Build-образы (локальная сборка)
$BuildImages = @(
    @{ Name = "cosmo-api";      Tag = "local"; Dockerfile = "services/cosmo-api.Dockerfile";      Context = ".." },
    @{ Name = "cosmo-frontend"; Tag = "local"; Dockerfile = "frontend/Dockerfile";                 Context = "../frontend" }
)

# Лицензии
$LicenseMap = @{
    "postgres"                            = @{ spdx = "PostgreSQL"; url = "https://www.postgresql.org/about/licence/" }
    "valkey/valkey"                       = @{ spdx = "BSD-3-Clause"; url = "https://github.com/valkey-io/valkey/blob/unstable/LICENSE" }
    "openbao/openbao"                     = @{ spdx = "MPL-2.0"; url = "https://github.com/openbao/openbao/blob/main/LICENSE" }
    "minio/minio"                         = @{ spdx = "AGPL-3.0"; url = "https://github.com/minio/minio/blob/master/LICENSE" }
    "gitea/gitea"                         = @{ spdx = "MIT"; url = "https://github.com/go-gitea/gitea/blob/main/LICENSE" }
    "woodpeckerci/woodpecker-server"      = @{ spdx = "Apache-2.0"; url = "https://github.com/woodpecker-ci/woodpecker/blob/main/LICENSE" }
    "caddy"                               = @{ spdx = "Apache-2.0"; url = "https://github.com/caddyserver/caddy/blob/master/LICENSE" }
    "cosmo-api"                           = @{ spdx = "MIT"; url = "https://prettyk.io" }
    "cosmo-frontend"                      = @{ spdx = "MIT"; url = "https://prettyk.io" }
}

Write-Host "=== Cosmoport 2.0 Airgap Bundle v$Version ==="

# 1. Подготовка
if (Test-Path $BundleWork) { Remove-Item -Recurse -Force $BundleWork }
New-Item -ItemType Directory -Path "$BundleWork\images" -Force | Out-Null
New-Item -ItemType Directory -Path "$BundleWork\compose" -Force | Out-Null
New-Item -ItemType Directory -Path "$BundleWork\scripts" -Force | Out-Null
New-Item -ItemType Directory -Path "$BundleWork\sbom" -Force | Out-Null

# 2. Сборка локальных образов
Write-Host "[bundle] build local images"
Push-Location $RepoRoot
try {
    foreach ($img in $BuildImages) {
        Write-Host "  build $($img.Name):$($img.Tag) from $($img.Dockerfile)"
        docker build -f $img.Dockerfile -t "$($img.Name):$($img.Tag)" $img.Context
        if ($LASTEXITCODE -ne 0) { throw "build failed: $($img.Name)" }
    }
} finally {
    Pop-Location
}

# 3. Pull внешних образов + pin digest
Write-Host "[bundle] pull external images"
$DigestTable = @{}
foreach ($img in $PullImages) {
    $full = "$($img.Name):$($img.Tag)"
    Write-Host "  pull $full"
    docker pull $full
    if ($LASTEXITCODE -ne 0) { throw "pull failed: $full" }

    $digest = docker image inspect $full --format '{{index .RepoDigests 0}}' 2>$null
    if (-not $digest) { $digest = $full }
    Write-Host "    digest: $digest"
    $DigestTable[$img.Name] = $digest
}

# 4. Сохранить все образы
Write-Host "[bundle] save images"
foreach ($img in $BuildImages) {
    $tarName = "$($img.Name.Replace('/', '_').Replace(':', '_'))_$($img.Tag).tar"
    Write-Host "  $tarName"
    docker save "$($img.Name):$($img.Tag)" -o "$BundleWork\images\$tarName"
    if ($LASTEXITCODE -ne 0) { throw "save failed: $($img.Name)" }
}
foreach ($img in $PullImages) {
    $tarName = "$($img.Name.Replace('/', '_').Replace(':', '_'))_$($img.Tag).tar"
    Write-Host "  $tarName (digest-pinned)"
    docker save "$($img.Name):$($img.Tag)" -o "$BundleWork\images\$tarName"
    if ($LASTEXITCODE -ne 0) { throw "save failed: $($img.Name)" }
}

# 5. Копировать compose
Write-Host "[bundle] copy compose + configs"
Copy-Item "$ServicesDir\docker-compose.yml" "$BundleWork\compose\" -Force
Copy-Item "$ServicesDir\Caddyfile"           "$BundleWork\compose\" -Force
Copy-Item "$ServicesDir\entrypoint.sh"       "$BundleWork\compose\" -Force
Copy-Item "$ServicesDir\cosmo-api.Dockerfile" "$BundleWork\compose\" -Force

# 6. Копировать install/verify скрипты
Copy-Item "$ServicesDir\scripts\install.ps1"        "$BundleWork\scripts\" -Force -ErrorAction SilentlyContinue
Copy-Item "$ServicesDir\scripts\install.sh"         "$BundleWork\scripts\" -Force -ErrorAction SilentlyContinue
Copy-Item "$ServicesDir\scripts\verify-bundle.sh"   "$BundleWork\scripts\" -Force -ErrorAction SilentlyContinue

# 7. SBOM — CycloneDX 1.5
Write-Host "[bundle] generate supply-chain SBOM"
$allImagesSBOM = @()
foreach ($img in $BuildImages) {
    $license = $LicenseMap[$img.Name]
    $allImagesSBOM += @{
        name = "$($img.Name):$($img.Tag)"
        license_spdx = if ($license) { $license.spdx } else { "UNKNOWN" }
        license_url  = if ($license) { $license.url } else { "" }
    }
}
foreach ($img in $PullImages) {
    $license = $LicenseMap[$img.Name]
    $digest = $DigestTable[$img.Name]
    $allImagesSBOM += @{
        name = "$($img.Name):$($img.Tag)"
        digest = $digest
        license_spdx = if ($license) { $license.spdx } else { "UNKNOWN" }
        license_url  = if ($license) { $license.url } else { "" }
    }
}

$sbom = @{
    bomFormat = "CycloneDX"
    specVersion = "1.5"
    version = 1
    metadata = @{
        timestamp = (Get-Date -Format "yyyy-MM-ddTHH:mm:ssZ")
        component = @{
            type = "application"
            name = "cosmoport2"
            version = $Version
        }
    }
    components = @($allImagesSBOM | ForEach-Object {
        $comp = @{
            type = "container"
            name = $_.name
            version = $Version
        }
        if ($_.digest) {
            $comp.hashes = @(@{ alg = "SHA-256"; content = ($_.digest -split ":")[-1] })
        }
        if ($_.license_spdx -and $_.license_spdx -ne "UNKNOWN") {
            $comp.licenses = @(@{ license = @{ id = $_.license_spdx } })
        }
        return $comp
    })
}
$sbom | ConvertTo-Json -Depth 5 | Set-Content -Path "$BundleWork\sbom\supply-chain.cdx.json" -Encoding UTF8

# 8. Лицензионный отчёт
$licenseReport = @{
    bundle = $BundleName
    version = $Version
    generated_at = (Get-Date -Format "yyyy-MM-ddTHH:mm:ssZ")
    components = @($allImagesSBOM | ForEach-Object {
        @{
            name = $_.name
            license = $_.license_spdx
            url = $_.license_url
        }
    })
}
$licenseReport | ConvertTo-Json -Depth 3 | Set-Content -Path "$BundleWork\sbom\license-report.json" -Encoding UTF8

# 9. Манифест
$manifest = @{
    bundle = "cosmoport2"
    version = $Version
    created = (Get-Date -Format "yyyy-MM-ddTHH:mm:ssZ")
    compatibility = @{
        docker = ">= 24.0"
        os = @("windows", "linux")
        arch = @("amd64")
    }
    sbom = "sbom/supply-chain.cdx.json"
    licenses = "sbom/license-report.json"
    images = @(
        foreach ($img in $BuildImages) {
            $tarName = "$($img.Name.Replace('/', '_').Replace(':', '_'))_$($img.Tag).tar"
            @{ name = "$($img.Name):$($img.Tag)"; file = "images/$tarName" }
        }
        foreach ($img in $PullImages) {
            $tarName = "$($img.Name.Replace('/', '_').Replace(':', '_'))_$($img.Tag).tar"
            @{ name = "$($img.Name):$($img.Tag)"; file = "images/$tarName"; digest = $DigestTable[$img.Name] }
        }
    )
    compose = @(
        @{ file = "compose/docker-compose.yml"; role = "full-stack" }
    )
}
$manifest | ConvertTo-Json -Depth 4 | Set-Content -Path "$BundleWork\manifest.json" -Encoding UTF8

# 10. Checksums
Push-Location $BundleWork
try {
    $checksums = Get-ChildItem -Recurse -File | Where-Object { $_.Name -ne "manifest.json" } | ForEach-Object {
        $hash = (Get-FileHash -Path $_.FullName -Algorithm SHA256).Hash.ToLower()
        $rel = $_.FullName.Substring($BundleWork.Length + 1).Replace('\', '/')
        "$hash  $rel"
    }
    $checksums | Set-Content -Path "$BundleWork\checksums.sha256" -Encoding ASCII
} finally {
    Pop-Location
}

# 11. Упаковать
Write-Host "[bundle] pack $BundleName.tar.gz"
Push-Location $BundleWork
try {
    & tar -czf "$RepoRoot\$BundleName.tar.gz" *
    if ($LASTEXITCODE -ne 0) { throw "tar failed" }
} finally {
    Pop-Location
}

$size = (Get-Item "$RepoRoot\$BundleName.tar.gz").Length
Write-Host "=== done: $BundleName.tar.gz ($([math]::Round($size/1MB,1)) MB) ==="
Write-Host ""
Write-Host "Install: tar -xzf $BundleName.tar.gz"
Write-Host "  docker load < images/*.tar"
Write-Host "  docker compose -f compose/docker-compose.yml up -d"
Write-Host ""
Write-Host "Verify:  ./scripts/verify-bundle.sh"
Write-Host ""
Write-Host "Digest-pinned images:"
foreach ($entry in $DigestTable.GetEnumerator()) {
    Write-Host "  $($entry.Value)"
}