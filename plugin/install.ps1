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
$RepoUrl = if ($env:MCP_STATA_REPO_URL) { $env:MCP_STATA_REPO_URL } else { 'https://github.com/tmonk/mcp-stata' }
$ZipUrl  = "${RepoUrl}/archive/refs/heads/main.zip"

# ── Formatting ────────────────────────────────────────────────────────────────
function Write-Step { param($msg) Write-Host "[INFO]  $msg" -ForegroundColor Cyan }
function Write-Ok   { param($msg) Write-Host "[OK]    $msg" -ForegroundColor Green }
function Write-Warn { param($msg) Write-Host "[WARN]  $msg" -ForegroundColor Yellow }
function Write-Fail { 
    param($msg) 
    [Console]::Error.WriteLine("[ERROR] $msg")
    exit 1 
}

# ── Paths ─────────────────────────────────────────────────────────────────────
# Handle execution context (local file vs piped iex)
if ($MyInvocation.MyCommand.Path) {
    $ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
    $RepoRoot  = Split-Path -Parent $ScriptDir
} else {
    $RepoRoot = (Get-Location).Path
}

$InstallRepoRoot = $RepoRoot
$TempDir = $null

function Remove-TempDir {
    if ($TempDir -and (Test-Path $TempDir)) {
        Remove-Item -Recurse -Force $TempDir -ErrorAction SilentlyContinue
    }
}

function Initialize-RepoRoot {
    if (Test-Path (Join-Path $RepoRoot 'scripts\setup_toolkit.py')) { return }

    Write-Step "Fetching mcp-stata source..."
    $script:TempDir = Join-Path ([System.IO.Path]::GetTempPath()) ("mcp-stata-install-" + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $script:TempDir | Out-Null
    
    $zipFile = Join-Path $script:TempDir "source.zip"
    Invoke-WebRequest -Uri $ZipUrl -OutFile $zipFile -UseBasicParsing
    
    $extractDir = Join-Path $script:TempDir "extract"
    Expand-Archive -Path $zipFile -DestinationPath $extractDir
    
    # Github zips contain a nested folder (mcp-stata-main)
    $innerDir = Get-ChildItem -Path $extractDir -Directory | Select-Object -First 1
    $script:InstallRepoRoot = $innerDir.FullName
    Write-Ok "Source extracted"
}

# ── Bootstrap uv ──────────────────────────────────────────────────────────────
function Initialize-Uv {
    # Call the official installer. It is idempotent.
    Write-Step "Ensuring uv is installed..."

    # Ensure scripts can run for the current user (if not managed by GPO)
    try {
        $policy = Get-ExecutionPolicy -Scope CurrentUser
        if ($policy -in @('Restricted', 'Undefined')) {
            Write-Step "Attempting to set execution policy to RemoteSigned..."
            Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser -Force
        }
    } catch {
        Write-Warn "Could not set execution policy. If installation fails, run: Set-ExecutionPolicy RemoteSigned -Scope CurrentUser"
    }

    Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression

    # Refresh PATH from machine/user scopes for current process to catch new 'uv' install
    $machinePath = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
    # Merge carefully to avoid duplicates but ensure current session sees it
    $env:Path = (@($env:Path, $machinePath, $userPath) -join ';' -split ';' | Where-Object { $_ } | Select-Object -Unique) -join ';'

    # Search for uv in common locations if not on Path yet
    $CandidatePaths = @(
        (Join-Path $env:APPDATA 'uv\bin'),
        (Join-Path $env:USERPROFILE '.local\bin'),
        $env:XDG_BIN_HOME
    )

    foreach ($Path in $CandidatePaths) {
        if ($Path -and (Test-Path $Path)) {
            $env:PATH = "$Path;$env:PATH"
            if (Get-Command uv -ErrorAction SilentlyContinue) { break }
        }
    }

    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        Write-Fail "uv is not on PATH. Please add it manually and re-run."
    }
}

# ── Entry point ───────────────────────────────────────────────────────────────
try {
    # Check if running as Administrator
    $currentPrincipal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    if ($currentPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        Write-Warn "Running as Administrator. Installation will be local to the admin profile."
    }

    Initialize-RepoRoot
    Initialize-Uv
    Write-Step "Launching mcp-stata installer..."
    & uv run --python 3.11 (Join-Path $InstallRepoRoot "scripts\setup_toolkit.py") @PassthroughArgs
    exit $LASTEXITCODE
} catch {
    Write-Fail $_.Exception.Message
} finally {
    Remove-TempDir
}
