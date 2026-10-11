# COS-195 (PK-C-010): immutable release-сборка образов Cosmo.
#
# Схема: релиз НИКОГДА не переиспользует тег. Каждая сборка получает уникальный
# immutable-тег `git-<short-sha>` — прошлые образы сохраняют имена, <none> не
# плодятся. Dev-цикл (монтирование исходников, `:local`) — docker-compose.dev.yml.
#
# Usage:
#   .\services\scripts\build-release.ps1                    # tag = git-<short12 HEAD>
#   .\services\scripts\build-release.ps1 -Tag v0.3.0        # явный immutable-тег
#   .\services\scripts\build-release.ps1 -KeepN 5           # показать retention (keep 5)
#   .\services\scripts\build-release.ps1 -KeepN 5 -Prune    # удалить git-* теги старше N
#
# Запуск стенда на релизном теге:
#   $env:COSMO_API_TAG='git-...'; $env:COSMO_FRONTEND_TAG='git-...'
#   docker compose -f services\docker-compose.yml up -d --no-deps cosmo-api cosmo-frontend
param(
    [string]$Tag = "",
    [int]$KeepN = 5,
    [switch]$Prune
)
# PS 5.1 + native stderr (docker build) при EAP=Stop даёт ложный terminating
# error на здоровом прогрессе; вердикт — по $LASTEXITCODE (стиль airgap-bundle.ps1).
$ErrorActionPreference = "Continue"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")

$Images = @(
    @{ Name = "cosmo-api";      Dockerfile = "services\cosmo-api.Dockerfile"; Context = "$RepoRoot" },
    @{ Name = "cosmo-frontend"; Dockerfile = "frontend\Dockerfile";           Context = "$RepoRoot\frontend" }
)

# 1. Immutable tag (по умолчанию — git sha текущего HEAD)
if (-not $Tag) {
    Push-Location $RepoRoot
    $sha = (git rev-parse --short=12 HEAD 2>$null | Out-String).Trim()
    $dirty = ((git status --porcelain 2>$null | Measure-Object -Line).Lines -gt 0)
    Pop-Location
    if (-not $sha) { throw "[build-release] git rev-parse failed (not a git repository?)" }
    $Tag = "git-$sha"
    if ($dirty) {
        Write-Host "[!] working tree dirty - tag embeds uncommitted state (commit before release)" -ForegroundColor Yellow
    }
}

# 2. Immutability guard: существующий тег НЕ перезаписываем
foreach ($img in $Images) {
    docker image inspect "$($img.Name):$Tag" *> $null
    if ($LASTEXITCODE -eq 0) {
        throw "[build-release] immutable tag already exists: $($img.Name):$Tag - pick another tag (tags are never overwritten)"
    }
}

# 3. Build (уникальный тег => прошлые сборки остаются именованными => нет <none>)
Write-Host "=== build-release: $Tag ==="
foreach ($img in $Images) {
    Write-Host "  build $($img.Name):$Tag  ($($img.Dockerfile))"
    docker build -f (Join-Path $RepoRoot $img.Dockerfile) -t "$($img.Name):$Tag" $img.Context 2>&1 |
        ForEach-Object { "$_" }
    if ($LASTEXITCODE -ne 0) { throw "[build-release] build failed: $($img.Name)" }
}

# 4. Итог
Write-Host ""
Write-Host "[OK] release images:"
foreach ($img in $Images) {
    $id = (docker image inspect "$($img.Name):$Tag" --format '{{.Id}}' 2>$null | Out-String).Trim()
    Write-Host "  $($img.Name):$Tag  $id"
}
Write-Host "  deploy: `$env:COSMO_API_TAG='$Tag'; `$env:COSMO_FRONTEND_TAG='$Tag'; docker compose -f services\docker-compose.yml up -d --no-deps cosmo-api cosmo-frontend"

# 5. Retention: keep N newest git-* тегов (репозиторий cosmo-api как референс)
$releaseTags = @()
$out = docker image ls cosmo-api --format "{{.Tag}}|{{.CreatedAt}}" 2>$null
foreach ($line in ($out | Where-Object { $_ -match '^git-' })) {
    $parts = $line -split '\|'
    $releaseTags += [pscustomobject]@{ Tag = $parts[0]; CreatedAt = $parts[1] }
}
$releaseTags = @($releaseTags | Sort-Object CreatedAt -Descending)

Write-Host ""
Write-Host "[retention] release tags (keep $KeepN):"
foreach ($t in $releaseTags) { Write-Host "  $($t.Tag)  $($t.CreatedAt)" }

if ($releaseTags.Count -gt $KeepN) {
    $old = @($releaseTags[$KeepN..($releaseTags.Count - 1)])
    if ($Prune) {
        foreach ($t in $old) {
            Write-Host "[retention] prune $($t.Tag)"
            docker image rm "cosmo-api:$($t.Tag)" "cosmo-frontend:$($t.Tag)" 2>&1 |
                ForEach-Object { "$_" }
        }
    } else {
        Write-Host "[retention] older than N: $(($old | ForEach-Object { $_.Tag }) -join ', ') - rerun with -Prune to delete"
    }
}
