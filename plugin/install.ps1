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
$Ref     = if ($env:MCP_STATA_REF) { $env:MCP_STATA_REF } else { 'main' }
$ZipUrl  = "${RepoUrl}/archive/${Ref}.zip"

# ── Logging ────────────────────────────────────────────────────────────────
$LogFile = Join-Path $env:TEMP ("mcp-stata-install-" + (Get-Date -Format 'yyyyMMdd-HHmmss') + ".log")
Start-Transcript -Path $LogFile -Append -ErrorAction SilentlyContinue | Out-Null

Write-Host "── mcp-stata installer ──"
Write-Host "Log:        $LogFile"
Write-Host "OS:         $([System.Environment]::OSVersion.VersionString)"
Write-Host "PS Version: $($PSVersionTable.PSVersion)"
Write-Host "Args:       $($PassthroughArgs -join ' ')"
Write-Host "──"

# ── Telemetry ──────────────────────────────────────────────────────────────
$TelemetryUrl = 'https://mcp-stata-install.tdmonk.com/telemetry'
$InstallId = [guid]::NewGuid().ToString()
$InstallStart = Get-Date
$InstallStage = 'init'

function Send-Telemetry {
    param($Event, $ErrorCode = '')
    try {
        $payload = @{
            event = $Event
            stage = $InstallStage
            error_code = $ErrorCode
            os = 'windows'
            distro = "windows-$([System.Environment]::OSVersion.Version.Major).$([System.Environment]::OSVersion.Version.Build)"
            arch = $env:PROCESSOR_ARCHITECTURE.ToLower()
            duration_ms = [int]((Get-Date) - $InstallStart).TotalMilliseconds
            install_id = $InstallId
            file = 'install.ps1'
        } | ConvertTo-Json -Compress
        Invoke-RestMethod -Uri $TelemetryUrl -Method Post -Body $payload `
            -ContentType 'application/json' -TimeoutSec 3 `
            -ErrorAction SilentlyContinue | Out-Null
    } catch {}
}

# ── Network Helpers ───────────────────────────────────────────────────────────
function Invoke-WithRetry {
    param(
        [ScriptBlock]$Script,
        [int]$MaxRetries = 3,
        [int]$DelaySeconds = 2
    )
    $attempt = 0
    while ($true) {
        try {
            return &$Script
        } catch {
            $attempt++
            if ($attempt -ge $MaxRetries) { throw }
            Write-Host "[WARN]  Request failed (attempt $attempt/$MaxRetries). Retrying in $DelaySeconds seconds..." -ForegroundColor Yellow
            Start-Sleep -Seconds $DelaySeconds
        }
    }
}

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
    if (Test-Path (Join-Path $RepoRoot 'scripts\install\setup_toolkit.py')) { return }

    Write-Step "Fetching mcp-stata source..."
    $script:TempDir = Join-Path ([System.IO.Path]::GetTempPath()) ("mcp-stata-install-" + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $script:TempDir | Out-Null
    
    $zipFile = Join-Path $script:TempDir "source.zip"
    Invoke-WithRetry { Invoke-WebRequest -Uri $ZipUrl -OutFile $zipFile -UseBasicParsing }
    
    $extractDir = Join-Path $script:TempDir "extract"
    Expand-Archive -Path $zipFile -DestinationPath $extractDir
    
    # Github zips contain a nested folder (mcp-stata-main)
    $innerDir = Get-ChildItem -Path $extractDir -Directory | Select-Object -First 1
    $script:InstallRepoRoot = $innerDir.FullName
    Write-Ok "Source extracted"
}

# ── Bootstrap uv ──────────────────────────────────────────────────────────────
function Initialize-Uv {
    Write-Step "Ensuring uv is installed..."

    # Fast path: uv already on PATH — nothing to do.
    if (Get-Command uv -ErrorAction SilentlyContinue) {
        $uvVer = (uv --version 2>$null) -join ''
        Write-Ok "uv already installed ($uvVer)"
        return
    }

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

    Invoke-WithRetry { Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression }

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
    $InstallStage = 'ensure_uv'
    Initialize-Uv
    Write-Step "Launching mcp-stata installer..."
    $InstallStage = 'setup_toolkit'
    & uv run --python 3.11 (Join-Path $InstallRepoRoot "scripts\install\setup_toolkit.py") @PassthroughArgs
    if ($LASTEXITCODE -ne 0) { throw "Python installer failed with exit code $LASTEXITCODE" }
    
    $event = if ($PassthroughArgs -contains '--uninstall') { 'uninstall_success' } else { 'install_success' }
    Send-Telemetry $event
    exit $LASTEXITCODE
} catch {
    Send-Telemetry 'install_failure' $_.Exception.Message
    [Console]::Error.WriteLine("[ERROR] $($_.Exception.Message)")
    [Console]::Error.WriteLine(@"

──────────────────────────────────────────────────────────────────
Installation failed. Full log saved to:
  $LogFile

Please open a bug report and paste the log contents:
  https://github.com/tmonk/mcp-stata/issues/new?template=install-failure.yml

Copy log to clipboard:
  Get-Content '$LogFile' | Set-Clipboard
──────────────────────────────────────────────────────────────────
"@)
    exit 1
} finally {
    Remove-TempDir
    Stop-Transcript -ErrorAction SilentlyContinue | Out-Null
}