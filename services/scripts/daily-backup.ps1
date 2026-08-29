# Cosmoport 2.0 - Automated Daily Backup (COS-108)
#
# 1. PostgreSQL: pg_dump -Fc (custom format, compressible, restorable)
# 2. MinIO S3: mirror cosmo-evidence bucket via mc (MinIO Client)
# 3. SHA-256 checksums for every backup file
# 4. Retention: 7 daily + 4 weekly (Sunday) - oldest beyond policy deleted
# 5. Audit: reports/backup-audit.log
#
# Usage:
#   .\services\scripts\daily-backup.ps1                           # default: PG+MinIO
#   .\services\scripts\daily-backup.ps1 -SkipMinIO               # PG only
#   .\services\scripts\daily-backup.ps1 -SkipPG                  # MinIO only
#   .\services\scripts\daily-backup.ps1 -DryRun                  # validate + no write
#
# Requires:
#   - Docker running (cosmo-postgres for pg_dump via docker exec)
#   - mc (MinIO Client - choco install minio-client / brew install minio/stable/minio)
param(
    [string]$BackupRoot = "backups",
    [string]$PgUser = "cosmo",
    [string]$PgPassword = "cosmo",
    [string]$PgHost = "127.0.0.1",
    [int]$PgPort = 5432,
    [string]$PgDb = "cosmo",
    [string]$PgContainer = "cosmo-postgres",
    [string]$MinioAlias = "cosmo-local",
    [string]$MinioUrl = "http://127.0.0.1:9000",
    [string]$MinioAccessKey = "cosmo",
    [string]$MinioSecretKey = "cosmo-minio-dev",
    [string]$MinioBucket = "cosmo-evidence",
    [int]$RetentionDaily = 7,
    [int]$RetentionWeekly = 4,
    [switch]$SkipPG,
    [switch]$SkipMinIO,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$ScriptRoot = Split-Path -Parent $PSCommandPath
$RepoRoot = Resolve-Path (Join-Path $ScriptRoot "..\..")
$BackupDir = Join-Path $RepoRoot $BackupRoot
$AuditLog = Join-Path $RepoRoot "reports\backup-audit.log"

# ── Ensure dirs ────────────────────────────────────────────────────────
$date = Get-Date -Format "yyyy-MM-dd"
$dayOfWeek = (Get-Date).DayOfWeek.value__
$isWeekly = ($dayOfWeek -eq 0)  # Sunday = 0
$tag = if ($isWeekly) { "${date}_weekly" } else { "${date}_daily" }
$pgBackupDir = Join-Path $BackupDir "pg"
$minioBackupDir = Join-Path $BackupDir "minio_$tag"
$checksumDir = Join-Path $BackupDir "checksums"

foreach ($d in @($BackupDir, $pgBackupDir, $minioBackupDir, $checksumDir, (Join-Path $RepoRoot "reports"))) {
    New-Item -ItemType Directory -Force -Path $d | Out-Null
}

function Write-Audit {
    param([string]$Message)
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $line = "[$ts] $Message"
    Write-Host $line
    Add-Content -Path $AuditLog -Value $line -Encoding UTF8
}

# ══════════════════════════════════════════════════════════════════════════════
Write-Audit "=== Cosmo Daily Backup started ==="
Write-Audit "  Date=$date  Weekly=$isWeekly  DryRun=$DryRun"
Write-Host ""

# �═════════════════════════════════════════════════════════════════════════════════
# 1. PostgreSQL dump
# �═════════════════════════════════════════════════════════════════════════════════

if (-not $SkipPG) {
    Write-Audit "--- PostgreSQL Backup ---"

    $pgDumpFile = "pg_cosmo_$tag.dump"
    $pgDumpPath = Join-Path $pgBackupDir $pgDumpFile

    if (Test-Path $pgDumpPath) {
        Write-Audit "  SKIP: $pgDumpFile already exists (idempotent - not overwriting)"
    } elseif ($DryRun) {
        Write-Audit "  DRY-RUN: would run pg_dump -Fc $PgDb > $pgDumpFile"
    } else {
        Write-Audit "  Dumping PostgreSQL: $PgDb → $pgDumpFile"

        $pgDumpCmd = "pg_dump -h $PgHost -p $PgPort -U $PgUser -d $PgDb -Fc -f /tmp/$pgDumpFile"
        if ($PgContainer) {
            $result = docker exec $PgContainer sh -c "PGPASSWORD=$PgPassword $pgDumpCmd" 2>&1
            docker cp "${PgContainer}:/tmp/$pgDumpFile" $pgDumpPath 2>&1 | Out-Null
        } else {
            $env:PGPASSWORD = $PgPassword
            & pg_dump -h $PgHost -p $PgPort -U $PgUser -d $PgDb -Fc -f $pgDumpPath 2>&1 | Out-Null
        }

        if ($LASTEXITCODE -ne 0 -or -not (Test-Path $pgDumpPath)) {
            Write-Audit "  FAIL: pg_dump failed - $result"
            throw "PostgreSQL backup failed"
        }

        $pgSize = (Get-Item $pgDumpPath).Length
        Write-Audit "  OK: $pgDumpFile ($([math]::Round($pgSize/1KB, 1)) KB)"
    }

    # Checksum
    if (Test-Path $pgDumpPath) {
        $pgChecksum = (Get-FileHash -Path $pgDumpPath -Algorithm SHA256).Hash.ToLower()
        $pgChecksum | Set-Content -Path (Join-Path $checksumDir "$pgDumpFile.sha256") -NoNewline
        Write-Audit "  SHA256: $pgChecksum"
    }
}

# �═════════════════════════════════════════════════════════════════════════════════
# 2. MinIO mirror
# �═════════════════════════════════════════════════════════════════════════════════

if (-not $SkipMinIO) {
    Write-Audit ""
    Write-Audit "--- MinIO Backup ---"

    if ($DryRun) {
        Write-Audit "  DRY-RUN: would mirror $MinioBucket → $minioBackupDir"
    } else {
        # Configure mc alias (idempotent)
        $mcAlias = $MinioAlias
        & mc alias set $mcAlias $MinioUrl $MinioAccessKey $MinioSecretKey 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Write-Audit "  WARN: mc alias set failed (mc may not be installed)"
            Write-Audit "  Fallback: trying docker-based mc..."
            # Docker-based mc fallback
            $mcResult = docker run --rm --network cosmo-net `
                -v "${BackupDir}:/backups" `
                minio/mc:latest `
                mirror "$MinioUrl/$MinioBucket" "/backups/minio_$tag" `
                --overwrite 2>&1 | Out-Null
            if ($LASTEXITCODE -eq 0) {
                Write-Audit "  OK: docker mc mirror completed (fallback)"
            } else {
                Write-Audit "  WARN: mc docker fallback also failed - try: choco install minio-client"
            }
        } else {
            $mcResult = & mc mirror --overwrite "$mcAlias/$MinioBucket" $minioBackupDir 2>&1
            if ($LASTEXITCODE -eq 0) {
                Write-Audit "  OK: mc mirror completed"
            } else {
                Write-Audit "  WARN: mc mirror had issues: $mcResult"
            }
        }
    }

    # Checksum for entire minio backup dir
    if (Test-Path $minioBackupDir) {
        $minioFiles = Get-ChildItem -Path $minioBackupDir -Recurse -File -ErrorAction SilentlyContinue
        $minioCount = $minioFiles.Count
        $minioSize = ($minioFiles | Measure-Object -Property Length -Sum).Sum
        Write-Audit "  Files: $minioCount, Size: $([math]::Round($minioSize/1MB, 1)) MB"

        if ($minioCount -gt 0) {
            $minioChecksum = ""
            $minioFiles | Sort-Object FullName | ForEach-Object {
                $minioChecksum += (Get-FileHash -Path $_.FullName -Algorithm SHA256).Hash.ToLower()
            }
            $minioChecksumFinal = [System.BitConverter]::ToString(
                [System.Security.Cryptography.SHA256]::Create().ComputeHash(
                    [System.Text.Encoding]::UTF8.GetBytes($minioChecksum)
            )).Replace("-", "").ToLower()
            $minioChecksumFinal | Set-Content -Path (Join-Path $checksumDir "minio_$tag.sha256") -NoNewline
            Write-Audit "  Combined SHA256: $minioChecksumFinal"
        }
    }
}

# �═════════════════════════════════════════════════════════════════════════════════════
# 3. Retention: 7 daily + 4 weekly (Sundays)
# �═════════════════════════════════════════════════════════════════════════════════════

Write-Audit ""
Write-Audit "--- Retention Policy ---"
Write-Audit "  Policy: keep $RetentionDaily dailies + $RetentionWeekly weeklies (Sundays)"
Write-Audit ""

# Collect all backup files by type
$allPgDumps = Get-ChildItem -Path $pgBackupDir -Filter "pg_cosmo_*.dump" -ErrorAction SilentlyContinue |
    Sort-Object Name -Descending

$allMinioDirs = Get-ChildItem -Path $BackupDir -Directory -Filter "minio_*" -ErrorAction SilentlyContinue |
    Sort-Object Name -Descending

# Separate daily and weekly for PG
$pgDaily = $allPgDumps | Where-Object { $_.Name -match '_daily\.dump$' }
$pgWeekly = $allPgDumps | Where-Object { $_.Name -match '_weekly\.dump$' }

# Separate daily and weekly for MinIO
$minioDaily = $allMinioDirs | Where-Object { $_.Name -match '_daily$' }
$minioWeekly = $allMinioDirs | Where-Object { $_.Name -match '_weekly$' }

# Delete excess PG dailies
if ($pgDaily.Count -gt $RetentionDaily) {
    $toDelete = $pgDaily | Select-Object -Skip $RetentionDaily
    Write-Audit "  PG dailies to delete: $($toDelete.Count) (keeping newest $RetentionDaily)"
    foreach ($f in $toDelete) {
        if ($DryRun) {
            Write-Audit "    DRY-RUN: would delete $($f.Name)"
        } else {
            Remove-Item $f.FullName -Force
            Remove-Item (Join-Path $checksumDir "$($f.Name).sha256") -Force -ErrorAction SilentlyContinue
            Write-Audit "    Deleted: $($f.Name)"
        }
    }
} else {
    Write-Audit "  PG dailies: $($pgDaily.Count) (limit $RetentionDaily) - no cleanup needed"
}

# Delete excess PG weeklies
if ($pgWeekly.Count -gt $RetentionWeekly) {
    $toDelete = $pgWeekly | Select-Object -Skip $RetentionWeekly
    Write-Audit "  PG weeklies to delete: $($toDelete.Count) (keeping newest $RetentionWeekly)"
    foreach ($f in $toDelete) {
        if ($DryRun) {
            Write-Audit "    DRY-RUN: would delete $($f.Name)"
        } else {
            Remove-Item $f.FullName -Force
            Remove-Item (Join-Path $checksumDir "$($f.Name).sha256") -Force -ErrorAction SilentlyContinue
            Write-Audit "    Deleted: $($f.Name)"
        }
    }
} else {
    Write-Audit "  PG weeklies: $($pgWeekly.Count) (limit $RetentionWeekly) - no cleanup needed"
}

# Delete excess MinIO dailies
if ($minioDaily.Count -gt $RetentionDaily) {
    $toDelete = $minioDaily | Select-Object -Skip $RetentionDaily
    Write-Audit "  MinIO dailies to delete: $($toDelete.Count) (keeping newest $RetentionDaily)"
    foreach ($d in $toDelete) {
        if ($DryRun) {
            Write-Audit "    DRY-RUN: would delete $($d.Name)"
        } else {
            Remove-Item $d.FullName -Recurse -Force
            Remove-Item (Join-Path $checksumDir "minio_$($d.Name -replace 'minio_','').sha256") -Force -ErrorAction SilentlyContinue
            Write-Audit "    Deleted: $($d.Name)"
        }
    }
} else {
    Write-Audit "  MinIO dailies: $($minioDaily.Count) (limit $RetentionDaily) - no cleanup needed"
}

# Delete excess MinIO weeklies
if ($minioWeekly.Count -gt $RetentionWeekly) {
    $toDelete = $minioWeekly | Select-Object -Skip $RetentionWeekly
    Write-Audit "  MinIO weeklies to delete: $($toDelete.Count) (keeping newest $RetentionWeekly)"
    foreach ($d in $toDelete) {
        if ($DryRun) {
            Write-Audit "    DRY-RUN: would delete $($d.Name)"
        } else {
            Remove-Item $d.FullName -Recurse -Force
            Remove-Item (Join-Path $checksumDir "minio_$($d.Name -replace 'minio_','').sha256") -Force -ErrorAction SilentlyContinue
            Write-Audit "    Deleted: $($d.Name)"
        }
    }
} else {
    Write-Audit "  MinIO weeklies: $($minioWeekly.Count) (limit $RetentionWeekly) - no cleanup needed"
}

# �═════════════════════════════════════════════════════════════════════════════════
# 4. Summary
# �═════════════════════════════════════════════════════════════════════════════════

Write-Audit ""
Write-Audit "=== Cosmo Daily Backup Complete ==="
Write-Audit "  PG dumps  : $($allPgDumps.Count) files in $pgBackupDir"
Write-Audit "  MinIO dirs : $($allMinioDirs.Count) dirs  in $BackupDir"
Write-Audit "  Checksums : $checksumDir"
Write-Audit "  Audit log : $AuditLog"

Write-Host ""
Write-Host "=== Backup Complete ===" -ForegroundColor Green
Write-Host "  PG     : $pgBackupDir" -ForegroundColor White
Write-Host "  MinIO  : $BackupDir" -ForegroundColor White
Write-Host "  Audit  : $AuditLog" -ForegroundColor White
Write-Host "  Retained: $RetentionDaily daily + $RetentionWeekly weekly" -ForegroundColor White

exit 0