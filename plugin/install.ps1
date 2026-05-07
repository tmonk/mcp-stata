#Requires -Version 5
<#
.SYNOPSIS
    Bootstrap installer for mcp-stata.
    Ensures uv is available, then delegates all setup logic to the Python installer.
#>
[CmdletBinding()]
param(
    [Parameter(ValueFromRemainingArguments)]
    [string[]]$PassthroughArgs
)

$ErrorActionPreference = 'Stop'

# ── Formatting ────────────────────────────────────────────────────────────────
function Write-Step { param($msg) Write-Host "[INFO]  $msg" -ForegroundColor Cyan }
function Write-Ok   { param($msg) Write-Host "[OK]    $msg" -ForegroundColor Green }
function Write-Warn { param($msg) Write-Host "[WARN]  $msg" -ForegroundColor Yellow }
function Write-Fail { param($msg) Write-Host "[ERROR] $msg" -ForegroundColor Red; exit 1 }

# ── Paths ─────────────────────────────────────────────────────────────────────
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot  = Split-Path -Parent $ScriptDir
$UvBinDir  = Join-Path $env:USERPROFILE '.local\bin'

# ── Bootstrap uv ──────────────────────────────────────────────────────────────
function Ensure-Uv {
    if (Get-Command uv -ErrorAction SilentlyContinue) {
        Write-Ok "uv found: $((Get-Command uv).Source)"
        return
    }

    Write-Step "uv not found - installing..."

    # Ensure scripts can run for the current user
    $policy = Get-ExecutionPolicy -Scope CurrentUser
    if ($policy -in @('Restricted', 'Undefined')) {
        Write-Step "Setting execution policy to RemoteSigned for CurrentUser..."
        Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser -Force
    }

    Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression

    # Make uv available in this session
    $env:PATH = "$UvBinDir;$env:PATH"

    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        Write-Fail "uv installed but not on PATH. Add '$UvBinDir' to your PATH and re-run."
    }

    Write-Ok "uv installed: $((Get-Command uv).Source)"
}

# ── Entry point ───────────────────────────────────────────────────────────────
Ensure-Uv
Write-Step "Launching mcp-stata installer..."
& uv run --python 3.11 "$RepoRoot\scripts\setup_toolkit.py" @PassthroughArgs
exit $LASTEXITCODE
