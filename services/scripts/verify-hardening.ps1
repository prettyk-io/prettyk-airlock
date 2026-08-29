# Cosmoport 2.0 - Pre-Production Hardening Gate (COS-103)
#
# Pre-release security audit: ports, secrets, Caddy TLS+rate-limit, health probe sanitization.
# Exit 0 = all checks passed. Exit 1 = vulnerabilities found (listed in output).
#
# Usage:
#   .\services\scripts\verify-hardening.ps1                              # local (HTTP)
#   .\services\scripts\verify-hardening.ps1 -Mode production -BaseUrl https://prettyk.io
#   .\services\scripts\verify-hardening.ps1 -SkipPortScan -SkipSecretScan
param(
    [ValidateSet("local", "production", "airgap")]
    [string]$Mode = "local",
    [string]$BaseUrl = $null,
    [int]$CaddyPort = 443,
    [switch]$SkipPortScan,
    [switch]$SkipSecretScan,
    [switch]$SkipCaddyCheck,
    [switch]$SkipHealthProbe,
    [string]$ConfigDir = $null
)

$ErrorActionPreference = "Continue"
$ProgressPreference = "SilentlyContinue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$ScriptRoot = Split-Path -Parent $PSCommandPath
$RepoRoot = Resolve-Path (Join-Path $ScriptRoot "..\..")
if (-not $ConfigDir) { $ConfigDir = Join-Path $RepoRoot "services" }
if (-not $BaseUrl) {
    $BaseUrl = if ($Mode -eq "local") { "http://127.0.0.1:8080" } else { "https://127.0.0.1:443" }
}

$Passed = 0
$Failed = 0
$Findings = [System.Collections.ArrayList]::new()

# ── Production port exposure policy ──────────────────────────────────────
$PROD_ALLOWED_PORTS = @(443, 80)       # Only Caddy-facing ports
$PROD_ALLOWED_INTERNAL = @(5432, 6379, 8200, 9000)  # OK internally, NOT on 0.0.0.0
$DEV_INFRA_PORTS = @(5432, 6379, 8200, 9000, 9001, 3000, 8000, 8100, 5174)

# Default secrets - must NOT appear in production configs
$DEFAULT_SECRETS = @(
    "prettyk-minio-dev",
    "cosmo-minio-dev",
    "dev-agent-secret-change-me",
    "cosmo-bao-root-dev",
    "prettyk-password",
    "admin123",
    "password123"
)

function Write-Check {
    param([string]$Name, [string]$Status, [string]$Detail = "")
    $icon = if ($Status -eq "PASS") { "[PASS]" } elseif ($Status -eq "WARN") { "[WARN]" } else { "[FAIL]" }
    $color = if ($Status -eq "PASS") { "Green" } elseif ($Status -eq "WARN") { "Yellow" } else { "Red" }
    Write-Host ($icon + " " + $Name) -ForegroundColor $color
    if ($Detail) { Write-Host "       $Detail" -ForegroundColor DarkGray }
    if ($Status -eq "PASS") { $script:Pased++ } elseif ($Status -eq "FAIL") { $script:Failed++ }
}

function Add-Finding {
    param([string]$Check, [string]$Severity, [string]$Finding, [string]$File = "")
    $null = $Findings.Add(@{ check = $Check; severity = $Severity; finding = $Finding; file = $File })
}

# ══════════════════════════════════════════════════════════════════════════════

Write-Host ""
Write-Host "=== Cosmo Security Hardening Gate ===" -ForegroundColor Cyan
Write-Host "  Mode   : $Mode" -ForegroundColor White
Write-Host "  Target : $BaseUrl" -ForegroundColor White
Write-Host "  Config : $ConfigDir" -ForegroundColor White
Write-Host ""

# �═════════════════════════════════════════════════════════════════════════════════
# Check 1: Port Exposure
# �═════════════════════════════════════════════════════════════════════════════════

Write-Host "[Check 1] Port Exposure" -ForegroundColor Cyan

if (-not $SkipPortScan) {
    $exposed = @()
    if ($Mode -eq "production" -or $Mode -eq "airgap") {
        $checkPorts = $PROD_ALLOWED_PORTS + $DEV_INFRA_PORTS | Sort-Object -Unique
        foreach ($port in $checkPorts) {
            $listening = netstat -ano 2>$null | Select-String "LISTENING" | Select-String ":$port\b"
            if ($listening) {
                foreach ($line in $listening) {
                    $addr = ($line -split '\s+')[1]
                    if ($addr -match '^0\.0\.0\.0' -or $addr -match '^\[::\]') {
                        if ($port -in $PROD_ALLOWED_PORTS) {
                            Write-Check -Name "Port $port ($addr)" -Status "PASS" -Detail "allowed in production profile"
                        } else {
                            $exposed += "[$addr]:$port"
                            Write-Check -Name "Port $port ($addr)" -Status "FAIL" -Detail "INTERNAL PORT EXPOSED TO ALL INTERFACES"
                            Add-Finding -Check "ports" -Severity "CRITICAL" -Finding "Internal port $port bound to $addr - must be 127.0.0.1 or removed in production" -File "docker-compose.yml"
                        }
                    } else {
                        Write-Check -Name "Port $port ($addr)" -Status "PASS" -Detail "bound to $addr (not public)"
                    }
                }
            }
        }
        if ($exposed.Count -eq 0) {
            Write-Check -Name "Port exposure policy" -Status "PASS" -Detail "no internal ports exposed to 0.0.0.0"
        }
    } else {
        # Dev mode: check that the expected ports ARE open
        foreach ($port in $DEV_INFRA_PORTS) {
            $alive = [bool](netstat -ano 2>$null | Select-String "LISTENING" | Select-String ":$port\b")
            $status = if ($alive) { "PASS" } else { "WARN" }
            Write-Check -Name "Dev port :$port" -Status $status -Detail $(if ($alive) { "listening (dev profile)" } else { "not listening - services may be down" })
        }
        Write-Host "  NOTE: $Mode mode - all dev ports are expected to be open" -ForegroundColor DarkGray
    }
} else {
    Write-Check -Name "Port scan" -Status "WARN" -Detail "skipped (-SkipPortScan)"
}

# �═════════════════════════════════════════════════════════════════════════════════
# Check 2: Default Secrets
# �═════════════════════════════════════════════════════════════════════════════════

Write-Host ""
Write-Host "[Check 2] Default Secrets & Hardcoded Credentials" -ForegroundColor Cyan

if (-not $SkipSecretScan) {
    $scanDirs = @($ConfigDir, (Join-Path $RepoRoot "orchestrator"))
    $scanExts = @("*.yml", "*.yaml", "*.env", "*.ps1", "*.sh", "*.py", "*.ts", "*.tsx", "*.mjs", "*.json", "*.md")

    $secretHits = @{}
    foreach ($dir in $scanDirs) {
        if (-not (Test-Path $dir)) { continue }
        foreach ($ext in $scanExts) {
            $files = Get-ChildItem -Path $dir -Recurse -Filter $ext -File -ErrorAction SilentlyContinue |
                Where-Object { $_.FullName -notmatch '\\\.venv\\|\\node_modules\\|\\\.git\\|\\reports\\' }
            foreach ($file in $files) {
                $content = Get-Content $file.FullName -Raw -ErrorAction SilentlyContinue
                if (-not $content) { continue }
                foreach ($secret in $DEFAUL_SECRETS) {
                    if ($content -match [regex]::Escape($secret)) {
                        $relPath = $file.FullName.Substring($RepoRoot.Length + 1)
                        if (-not $secretHits.ContainsKey($secret)) { $secretHits[$secret] = @() }
                        $secretHits[$secret] += $relPath
                    }
                }
            }
        }
    }

    if ($secretHits.Count -eq 0) {
        Write-Check -Name "Default secrets scan" -Status "PASS" -Detail "no default secrets found in $($scanDirs.Count) directories"
    } else {
        foreach ($secret in $secretHits.Keys | Sort-Object) {
            $files = $secretHits[$secret] -join ", "
            Write-Check -Name "Secret '$secret'" -Status "FAIL" -Detail "found in: $files"
            Add-Finding -Check "secrets" -Severity "CRITICAL" -Finding "Default secret '$secret' found in codebase" -File $files
        }
    }

    # Also check docker-compose.yml for environment variables with default values
    $composeFile = Join-Path $ConfigDir "docker-compose.yml"
    if (Test-Path $composeFile) {
        $compose = Get-Content $composeFile -Raw
        if ($compose -match ':-prettyk-password\}') {
            Write-Check -Name "Compose: hardcoded PG password" -Status "FAIL" -Detail "prettyk-password in compose defaults"
            Add-Finding -Check "secrets" -Severity "CRITICAL" -Finding "PostgreSQL password default in docker-compose.yml" -File "services/docker-compose.yml"
        }
    }
} else {
    Write-Check -Name "Secret scan" -Status "WARN" -Detail "skipped (-SkipSecretScan)"
}

# �═════════════════════════════════════════════════════════════════════════════════
# Check 3: Caddy Configuration
# �═════════════════════════════════════════════════════════════════════════════════

Write-Host ""
Write-Host "[Check 3] Caddy Configuration" -ForegroundColor Cyan

if (-not $SkipCaddyCheck) {
    $caddyFile = Join-Path $ConfigDir "Caddyfile"

    if (-not (Test-Path $caddyFile)) {
        Write-Check -Name "Caddyfile exists" -Status "FAIL" -Detail "Caddyfile not found at $caddyFile"
        Add-Finding -Check "caddy" -Severity "CRITICAL" -Finding "Caddyfile not found" -File $caddyFile
    } else {
        $caddy = Get-Content $caddyFile -Raw
        Write-Check -Name "Caddyfile exists" -Status "PASS" -Detail $caddyFile

        # Check for rate_limit directive
        if ($caddy -match 'rate_limit') {
            Write-Check -Name "Rate limiting configured" -Status "PASS" -Detail "rate_limit directive present in Caddyfile"
        } else {
            Write-Check -Name "Rate limiting configured" -Status "FAIL" -Detail "NO rate_limit directive found in Caddyfile"
            Add-Finding -Check "caddy" -Severity "HIGH" -Finding "Rate limit not configured - /api/* endpoints are unprotected"
        }

        # Check for TLS (production mode)
        if ($Mode -eq "production" -or $Mode -eq "airgap") {
            $tlsConfigured = $caddy -match 'tls\s+' -or $caddy -match ':\d{3,5}\s*\{' -and $caddy -notmatch ':80\s*\{'
            if ($tlsConfigured) {
                Write-Check -Name "TLS enabled" -Status "PASS" -Detail "TLS directive or :443 block found"
            } else {
                Write-Check -Name "TLS enabled" -Status "FAIL" -Detail "NO TLS configured - production MUST use HTTPS"
                Add-Finding -Check "caddy" -Severity "CRITICAL" -Finding "TLS not configured for production environment" -File "Caddyfile"
            }
        } else {
            Write-Check -Name "TLS check" -Status "WARN" -Detail "skipped - $Mode mode allows HTTP"
        }
    }
} else {
    Write-Check -Name "Caddy check" -Status "WARN" -Detail "skipped (-SkipCaddyCheck)"
}

# �═════════════════════════════════════════════════════════════════════════════════
# Check 4: Health Probe Sanitization
# �═════════════════════════════════════════════════════════════════════════════════

Write-Host ""
Write-Host "[Check 4] Health Probe Sanitization" -ForegroundColor Cyan

if (-not $SkipHealthProbe) {
    $healthUrl = "$BaseUrl/api/health"
    try {
        $response = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 5
        Write-Check -Name "GET $healthUrl" -Status "PASS" -Detail "HTTP 200"

        # Check for leaked credentials in response
        $rawResponse = $response | ConvertTo-Json -Depth 4 -Compress

        $leaked = @()
        $sensitivePatterns = @(
            @{ pattern = "postgresql://[^@]+@"; label = "DSN/PostgreSQL connection string" },
            @{ pattern = "token\s*[=:]\s*[\w-]{20,}"; label = "likely token" },
            @{ pattern = "password\s*[=:]\s*[\w!@#\$%^&*()-]+"; label = "password value" },
            @{ pattern = "secret\s*[=:]\s*[\w!@#\$%^&*()-]+"; label = "secret value" },
            @{ pattern = "squ_[a-zA-Z0-9]{20,}"; label = "SonarQube token" },
            @{ pattern = "sk-[a-zA-Z0-9]{20,}"; label = "API key" },
            @{ pattern = 'BEGIN\s+(RSA|EC|DSA|OPENSSH)\s+PRIVATE\s+KEY'; label = "private key" },
            @{ pattern = 'Traceback \(most recent call last\)'; label = "Python traceback" },
            @{ pattern = 'File\s+".*",\s+line\s+\d+'; label = "source file path in error" }
        )

        foreach ($sp in $sensitivePatterns) {
            if ($rawResponse -match $sp.pattern) {
                $leaked += $sp.label
            }
        }

        if ($leaked.Count -eq 0) {
            Write-Check -Name "Response sanitization" -Status "PASS" -Detail "no credentials, DSN, tokens, or tracebacks in /api/health"
        } else {
            foreach ($item in $leaked) {
                Write-Check -Name "$item exposed" -Status "FAIL" -Detail "/api/health response contains sensitive data"
                Add-Finding -Check "health_probe" -Severity "HIGH" -Finding "$item found in health endpoint response - must be redacted"
            }
        }
    } catch {
        Write-Check -Name "GET $healthUrl" -Status "FAIL" -Detail "unable to reach API: $($_.Exception.Message)"
        Add-Finding -Check "health_probe" -Severity "CRITICAL" -Finding "Health endpoint unreachable - API may be down"
    }
} else {
    Write-Check -Name "Health probe" -Status "WARN" -Detail "skipped (-SkipHealthProbe)"
}

# �═════════════════════════════════════════════════════════════════════════════════
# Summary
# �═════════════════════════════════════════════════════════════════════════════════

Write-Host ""
Write-Host "=== Hardening Gate Summary ===" -ForegroundColor Cyan
Write-Host "  Passed : $Passed" -ForegroundColor Green
Write-Host "  Failed : $Failed" -ForegroundColor $(if ($Failed -gt 0) { "Red" } else { "Green" })

if ($Findings.Count -gt 0) {
    Write-Host ""
    Write-Host "=== Findings ===" -ForegroundColor Red
    foreach ($f in $Findings) {
        Write-Host "  [$($f.severity)] $($f.check): $($f.finding)" -ForegroundColor $(if ($f.severity -eq "CRITICAL") { "Red" } else { "Yellow" })
        if ($f.file) { Write-Host "         File: $($f.file)" -ForegroundColor DarkGray }
    }
}

if ($Failed -gt 0) {
    Write-Host ""
    Write-Host "=== HARDENING GATE FAILED ===" -ForegroundColor Red
    Write-Host "  Fix the issues above before deploying to production."
    Write-Host "  Checklist: services/scripts/HARDENING_CHECKLIST.md"
    exit 1
}

Write-Host ""
Write-Host "=== HARDENING GATE PASSSED ===" -ForegroundColor Green
exit 0