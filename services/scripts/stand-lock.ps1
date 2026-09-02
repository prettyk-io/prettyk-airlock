# COS-073: stand-lock — serialized access to the shared dev stand.
#
# The stand (compose stack + live cosmo DB) is a single-user resource:
# runtime-gate restarts/wipes containers, deploys migrate, manual checks
# poke the API. Two agents on the stand at once = cross-contamination
# (proven by PG log: concurrent harness DELETE series kill each other's
# rows). One lock file, first writer wins, stale locks expire.
#
# Tests do NOT need the lock: pytest runs against the isolated test PG
# (:5433, docker-compose.test-pg.yml) and never touches the stand.
#
# Usage:
#   stand-lock.ps1 acquire  -Owner "buddy"  -Purpose "COS-073 acceptance gate"
#   stand-lock.ps1 status
#   stand-lock.ps1 release  -Owner "buddy"
#   stand-lock.ps1 force-release -Owner "buddy" -Reason "stale after crash"
#
# Exit codes: 0 = ok; 1 = lock held by someone else (acquire) / not found or
# foreign (release); 2 = usage error.
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('acquire', 'release', 'status', 'force-release')]
    [string]$Action,

    [string]$Owner = $env:USERNAME,
    [string]$Purpose = "",
    [int]$TtlMinutes = 240,
    [string]$Reason = ""
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

# Stand discipline is a per-host runtime contract: the lock lives NEXT to the
# repo working tree, never inside it (stays out of git status/commits).
$LockFile = Join-Path $env:TEMP "cosmo-stand-lock.json"
$TtlMinutes = [Math]::Max(1, $TtlMinutes)

function Read-Lock {
    if (-not (Test-Path -LiteralPath $LockFile)) { return $null }
    try {
        return Get-Content -LiteralPath $LockFile -Raw -Encoding UTF8 | ConvertFrom-Json
    } catch {
        # Corrupted lock = stale garbage; treat as expired.
        return $null
    }
}

function Test-Expired {
    param($Lock)
    if ($null -eq $Lock) { return $true }
    $exp = [datetime]::MinValue
    if (-not [datetime]::TryParse($Lock.expires_at, [ref]$exp)) { return $true }
    return (Get-Date) -gt $exp
}

function Show-Lock {
    param($Lock, [string]$State)
    if ($null -eq $Lock) {
        Write-Host "[$State] no lock ($LockFile)"
        return
    }
    Write-Host ("[{0}] {1} | owner={2} pid={3} purpose='{4}' acquired={5} expires={6}" -f `
        $State, $LockFile, $Lock.owner, $Lock.pid, $Lock.purpose, $Lock.acquired_at, $Lock.expires_at)
}

switch ($Action) {

    'status' {
        $lock = Read-Lock
        if ($null -eq $lock) {
            Show-Lock $null "STATUS"
        } elseif (Test-Expired $lock) {
            Show-Lock $lock "STALE-EXPIRED"
            Write-Host "  -> lock is expired, anyone may take it (acquire will steal it)"
        } else {
            Show-Lock $lock "HELD"
        }
        exit 0
    }

    'acquire' {
        $lock = Read-Lock
        if ($null -ne $lock -and -not (Test-Expired $lock)) {
            Show-Lock $lock "BUSY"
            Write-Host "STAND LOCKED: wait for the owner to release, or coordinate via PO." -ForegroundColor Red
            exit 1
        }
        if ($null -ne $lock) {
            Show-Lock $lock "STOLEN (expired)"
        }
        $now = (Get-Date).ToUniversalTime()
        @{ owner = $Owner; purpose = $Purpose; pid = $PID;
           acquired_at = $now.ToString("o"); expires_at = $now.AddMinutes($TtlMinutes).ToString("o") } |
            ConvertTo-Json | Set-Content -LiteralPath $LockFile -Encoding UTF8
        Show-Lock (Read-Lock) "ACQUIRED"
        exit 0
    }

    'release' {
        $lock = Read-Lock
        if ($null -eq $lock) {
            Write-Host "[i] no lock to release"; exit 0
        }
        if ($lock.owner -ne $Owner) {
            Show-Lock $lock "FOREIGN"
            Write-Host "RELEASE DENIED: lock belongs to '$($lock.owner)', not '$Owner'. Use force-release if you own the stand window." -ForegroundColor Red
            exit 1
        }
        Remove-Item -LiteralPath $LockFile -Force
        Write-Host "[ok] released by $Owner"
        exit 0
    }

    'force-release' {
        if (-not $Reason) {
            Write-Host "force-release requires -Reason (audit trail)"; exit 2
        }
        $lock = Read-Lock
        if ($null -ne $lock) { Show-Lock $lock "FORCE-RELEASED" }
        else { Write-Host "[i] no lock present" }
        Remove-Item -LiteralPath $LockFile -Force -ErrorAction SilentlyContinue
        Write-Host "[ok] force-released: $Reason"
        exit 0
    }
}
