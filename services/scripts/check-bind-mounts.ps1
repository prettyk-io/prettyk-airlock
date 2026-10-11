# COS-195 (PK-C-010): bind-mount гигиена — в compose только относительные пути.
#
# Почему: абсолютный host-путь в контейнере — мина. При `docker start`/
# рестарте Docker материализует отсутствующий host-путь заново (фантомные
# папки по мёртвым путям после переноса репо — см. PK-C-010). Правило: в
# compose репозитория — только относительные bind-mount'ы (./dir, ../dir) или
# named volumes. Единственное исключение-allowlist: /var/run/docker.sock
# (канал Docker API — у него нет относительной формы).
#
# При переносе репо контейнеры ПЕРЕСОЗДАЮТСЯ (docker compose up -d
# --force-recreate), а не `docker start` старых — иначе старый абсолютный
# путь воскресает.
#
# Usage:  .\services\scripts\check-bind-mounts.ps1
# Exit:   0 — нарушений нет; 1 — найдены абсолютные host-пути.
$ErrorActionPreference = "Stop"
$ServicesDir = Resolve-Path (Join-Path $PSScriptRoot "..")

$Allowlist = @("/var/run/docker.sock")

$files = Get-ChildItem $ServicesDir -Filter "docker-compose*.yml" | Sort-Object Name
$violations = @()
$absoluteEntries = 0

foreach ($f in $files) {
    $lines = Get-Content $f.FullName
    for ($i = 0; $i -lt $lines.Count; $i++) {
        $line = $lines[$i].Trim()
        if (-not $line -or $line.StartsWith("#")) { continue }

        $candidate = $null
        # short-form: "- /abs/path:/container" | "- C:\abs:/container" | "- ./rel:/container"
        if ($line -match '^-\s+([^:\s]+):') { $candidate = $Matches[1].Trim('"', "'") }
        # long-form: "source: /abs/path"
        elseif ($line -match '^source:\s*(.+)$') { $candidate = $Matches[1].Trim('"', "'") }
        if (-not $candidate) { continue }

        $isAbsolute = ($candidate -match '^/') -or ($candidate -match '^[A-Za-z]:[\\/]')
        if (-not $isAbsolute) { continue }

        $absoluteEntries++
        if ($Allowlist -contains $candidate) { continue }
        $violations += [pscustomobject]@{ File = $f.Name; Line = $i + 1; Path = $candidate }
    }
}

Write-Host "check-bind-mounts: $($files.Count) compose file(s), $absoluteEntries absolute mount(s), allowlist: $($Allowlist -join ', ')"
if ($violations.Count -gt 0) {
    Write-Host "[FAIL] absolute bind-mount paths (use relative):" -ForegroundColor Red
    foreach ($v in $violations) { Write-Host "  $($v.File):$($v.Line)  $($v.Path)" }
    exit 1
}
Write-Host "[OK] no violations"
exit 0
