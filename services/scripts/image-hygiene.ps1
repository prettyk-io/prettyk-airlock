# COS-195 (PK-C-010): рутинная гигиена Docker — dangling-образы + BuildKit cache.
#
# Политика build-cache: по умолчанию — полный sweep нереференсного кэша
# (docker builder prune -f). Пол = слои, расшаренные с существующими образами
# (их снести нельзя, и не нужно). Опционально -ReserveCacheGB N резервирует
# N GB cache для скорости пересборок (--reserved-space).
#
# Грабли (проверено живьём на Docker 29.6.2 / BuildKit 0.31.2):
#   - старый флаг --keep-storage deprecated и переназван в --reserved-space
#     («минимум, который НЕ вытесняется»), а НЕ в «лимит»;
#   - --max-used-space в этом Docker на практике no-op (кэш сверх лимита не
#     вытесняет — проверено трижды) — не используем.
#
# Что делает:
#   1) docker image prune -f — сносит ТОЛЬКО dangling (<none>); чужие образы и
#      используемые контейнерами не трогает;
#   2) docker builder prune -f [--reserved-space N] — вытесняет нереференсный кэш.
#
# Запускать регулярно (после крупных сборок / раз в день).
#
# Usage:
#   .\services\scripts\image-hygiene.ps1                    # dangling + full cache sweep
#   .\services\scripts\image-hygiene.ps1 -ReserveCacheGB 2  # сохранить 2 GB cache
#   .\services\scripts\image-hygiene.ps1 -DryRun            # только показать числа
param(
    [int]$ReserveCacheGB = 0,
    [switch]$DryRun
)
$ErrorActionPreference = "Continue"

function Get-DockerNumbers {
    $dangling = @(docker images -q -f dangling=true 2>$null)
    $df = docker system df --format "{{.Type}}|{{.Size}}|{{.Reclaimable}}" 2>$null
    $images = ($df | Where-Object { $_ -match '^(Images|Образы)' } | Select-Object -First 1)
    $cache = ($df | Where-Object { $_ -match '^(Build Cache|Кэш сборки)' } | Select-Object -First 1)
    [pscustomobject]@{
        Dangling   = $dangling.Count
        Images     = ($images -split '\|')[1..2] -join ' reclaim='
        BuildCache = ($cache -split '\|')[1..2] -join ' reclaim='
    }
}

$before = Get-DockerNumbers
Write-Host "=== image-hygiene (reserve: ${ReserveCacheGB}GB) ==="
Write-Host "[before] dangling=$($before.Dangling)  images=$($before.Images)  build-cache=$($before.BuildCache)"

if ($DryRun) {
    Write-Host "[dry-run] nothing deleted"
    exit 0
}

Write-Host "[prune] dangling images..."
docker image prune -f 2>&1 | ForEach-Object { "  $_" }

if ($ReserveCacheGB -gt 0) {
    Write-Host "[prune] build cache (reserved-space ${ReserveCacheGB}GB keeps recent cache)..."
    docker builder prune -f --reserved-space "${ReserveCacheGB}GB" 2>&1 | ForEach-Object { "  $_" }
} else {
    Write-Host "[prune] build cache (full sweep of unreferenced)..."
    docker builder prune -f 2>&1 | ForEach-Object { "  $_" }
}

$after = Get-DockerNumbers
Write-Host "[after]  dangling=$($after.Dangling)  images=$($after.Images)  build-cache=$($after.BuildCache)"
