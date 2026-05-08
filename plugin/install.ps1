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
$RepoUrl = 'https://github.com/tmonk/mcp-stata.git'

# ── Formatting ────────────────────────────────────────────────────────────────
function Write-Step { param($msg) Write-Host "[INFO]  $msg" -ForegroundColor Cyan }
function Write-Ok   { param($msg) Write-Host "[OK]    $msg" -ForegroundColor Green }
function Write-Warn { param($msg) Write-Host "[WARN]  $msg" -ForegroundColor Yellow }
function Write-Fail { param($msg) Write-Host "[ERROR] $msg" -ForegroundColor Red; exit 1 }

# ── Paths ─────────────────────────────────────────────────────────────────────
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot  = Split-Path -Parent $ScriptDir
$UvBinDir  = Join-Path $env:USERPROFILE '.local\bin'
$InstallRepoRoot = $RepoRoot
$TempCloneDir = $null

function Cleanup-TempClone {
    if ($TempCloneDir -and (Test-Path $TempCloneDir)) {
        Remove-Item -Recurse -Force $TempCloneDir -ErrorAction SilentlyContinue
    }
}

function Ensure-Git {
    if (Get-Command git -ErrorAction SilentlyContinue) {
        Write-Ok "git found: $((Get-Command git).Source)"
        return
    }

    Write-Step "git not found - attempting to install..."

    if (Get-Command winget -ErrorAction SilentlyContinue) {
        winget install --id Git.Git -e --accept-package-agreements --accept-source-agreements
    } elseif (Get-Command choco -ErrorAction SilentlyContinue) {
        choco install git -y
    } else {
        Write-Fail "git is required but neither winget nor choco was found. Install git and re-run."
    }

    # Refresh PATH from machine/user scopes for current process
    $machinePath = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
    $env:Path = "$machinePath;$userPath"

    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        Write-Fail "git installation did not succeed. Install git and re-run."
    }

    Write-Ok "git installed: $((Get-Command git).Source)"
}

function Ensure-RepoRoot {
    if (Test-Path (Join-Path $RepoRoot 'scripts\setup_toolkit.py')) { return }

    Ensure-Git
    $script:TempCloneDir = Join-Path ([System.IO.Path]::GetTempPath()) ("mcp-stata-install-" + [guid]::NewGuid().ToString('N'))
    Write-Step "Cloning mcp-stata into temporary directory..."
    git clone --depth 1 $RepoUrl $script:TempCloneDir
    $script:InstallRepoRoot = $script:TempCloneDir
    Write-Ok "Repository cloned"
}

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

    # Make uv available in this session. uv installer defaults to $env:APPDATA\uv\bin 
    # or $env:USERPROFILE\.local\bin or $env:XDG_BIN_HOME
    $CandidatePaths = @(
        (Join-Path $env:APPDATA 'uv\bin'),
        (Join-Path $env:USERPROFILE '.local\bin'),
        $env:XDG_BIN_HOME
    )

    foreach ($Path in $CandidatePaths) {
        if ($Path -and (Test-Path $Path)) {
            $env:PATH = "$Path;$env:PATH"
            if (Get-Command uv -ErrorAction SilentlyContinue) {
                Write-Ok "uv installed and found in $Path"
                return
            }
        }
    }

    Write-Fail "uv installed but not found on PATH. Please add it manually and re-run."
}

# ── Entry point ───────────────────────────────────────────────────────────────
try {
    Ensure-RepoRoot
    Ensure-Uv
    Write-Step "Launching mcp-stata installer..."
    & uv run --python 3.11 "$InstallRepoRoot\scripts\setup_toolkit.py" @PassthroughArgs
    exit $LASTEXITCODE
} finally {
    Cleanup-TempClone
}
