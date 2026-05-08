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
$ActionLabel = if ($PassthroughArgs -contains '--uninstall') { 'Uninstall' } else { 'Installation' }
$AuthorName = 'Tom Monk'
$AuthorAffiliation = 'London School of Economics'
$AuthorEmail = 't.d.monk@lse.ac.uk'
$VerboseMode = $PassthroughArgs -contains '--verbose'

# ── Logging ────────────────────────────────────────────────────────────────
$LogFile = Join-Path $env:TEMP ("mcp-stata-install-" + (Get-Date -Format 'yyyyMMdd-HHmmss') + ".log")
$env:MCP_STATA_INSTALL_LOG_FILE = $LogFile
Start-Transcript -Path $LogFile -Append -ErrorAction SilentlyContinue | Out-Null

# ── Telemetry ──────────────────────────────────────────────────────────────
$TelemetryUrl = 'https://mcp-stata-install.tdmonk.com/telemetry'
$InstallId = [guid]::NewGuid().ToString()
$InstallStart = Get-Date
$InstallStage = 'init'
$InstallSource = if ($env:MCP_STATA_INSTALL_SOURCE) { $env:MCP_STATA_INSTALL_SOURCE } else { 'direct' }  # workbench|direct

# ── Formatting ─────────────────────────────────────────────────────────────
function Write-Rule {
    param(
        [string]$Color = 'Magenta'
    )
    Write-Host ('=' * 70) -ForegroundColor $Color
}

function Write-BoxedTitle {
    param(
        [string]$Title,
        [string]$Color = 'Blue'
    )
    Write-Host ''
    Write-Rule -Color $Color
    Write-Host $Title -ForegroundColor $Color
    Write-Rule -Color $Color
}

function Write-Step {
    param($Message)
    Write-Host ''
    Write-Host '>>' -ForegroundColor Magenta -NoNewline
    Write-Host " $Message" -ForegroundColor Magenta
}

function Write-Ok {
    param($Message)
    Write-Host '   +' -ForegroundColor Green -NoNewline
    Write-Host " $Message" -ForegroundColor Green
}

function Write-Warn {
    param($Message)
    Write-Host '   !' -ForegroundColor Yellow -NoNewline
    Write-Host " $Message" -ForegroundColor Yellow
}

function Show-Header {
    Write-Rule -Color Magenta
    Write-Host '                                    __        __' -ForegroundColor Cyan
    Write-Host '   ____ ___  _________        _____/ /_____ _/ /_____ _' -ForegroundColor Cyan
    Write-Host '  / __ `__ \/ ___/ __ \______/ ___/ __/ __ `/ __/ __ `/' -ForegroundColor Cyan
    Write-Host ' / / / / / / /__/ /_/ /_____(__  ) /_/ /_/ / /_/ /_/ /' -ForegroundColor Cyan
    Write-Host '/_/ /_/ /_/\___/ .___/     /____/\__/\__,_/\__/\__,_/' -ForegroundColor Cyan
    Write-Host '              /_/                                        installer' -ForegroundColor Cyan
    Write-Rule -Color Magenta
    Write-Host ('AUTHOR '.PadRight(8)) -ForegroundColor Yellow -NoNewline
    Write-Host $AuthorName
    Write-Host ('AT '.PadRight(8)) -ForegroundColor Yellow -NoNewline
    Write-Host $AuthorAffiliation
    Write-Host ('CONTACT'.PadRight(8)) -ForegroundColor Yellow -NoNewline
    Write-Host $AuthorEmail
    Write-Host ('note'.PadRight(8)) -ForegroundColor DarkGray -NoNewline
    Write-Host 'Questions, bugs, or weird installs: please get in touch.'
    Write-Host ''
    Write-Host ('log'.PadRight(8)) -ForegroundColor DarkGray -NoNewline
    Write-Host $LogFile
    Write-Host ('host'.PadRight(8)) -ForegroundColor DarkGray -NoNewline
    Write-Host ([System.Environment]::OSVersion.VersionString)
    Write-Host ('shell'.PadRight(8)) -ForegroundColor DarkGray -NoNewline
    Write-Host "PowerShell $($PSVersionTable.PSVersion)"
    Write-Host ('user'.PadRight(8)) -ForegroundColor DarkGray -NoNewline
    Write-Host ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name)
    Write-Host ('args'.PadRight(8)) -ForegroundColor DarkGray -NoNewline
    if ($PassthroughArgs.Count -gt 0) {
        Write-Host ($PassthroughArgs -join ' ')
    } else {
        Write-Host '(none)'
    }
}

function Show-Success {
    Write-BoxedTitle -Title 'MCP-STATA IS LIVE' -Color Green
    Write-Host '✓' -ForegroundColor Green -NoNewline
    Write-Host " $ActionLabel complete"
    Write-Host '::' -ForegroundColor Cyan -NoNewline
    Write-Host ' Verify by asking your agent: Do you have access to mcp-stata, an agentic toolkit for Stata?'
    Write-Host ''
    Write-Host 'FIRST COMMANDS TO TRY' -ForegroundColor Magenta
    Write-Host '   1.' -ForegroundColor Yellow -NoNewline
    Write-Host ' /stata-run sysuse auto, clear'
    Write-Host '   2.' -ForegroundColor Yellow -NoNewline
    Write-Host ' /stata-inspect'
    Write-Host '   3.' -ForegroundColor Yellow -NoNewline
    Write-Host ' /stata-run regress price mpg'
    Write-Host '   4.' -ForegroundColor Yellow -NoNewline
    Write-Host ' /stata-results'
    Write-Host ''
    Write-Host ('log'.PadRight(8)) -ForegroundColor DarkGray -NoNewline
    Write-Host $LogFile
    Write-Host ('contact'.PadRight(8)) -ForegroundColor DarkGray -NoNewline
    Write-Host $AuthorEmail
}

function Show-Failure {
    param(
        [string]$Message
    )
    Write-Host ''
    Write-Host '✖' -ForegroundColor Red -NoNewline
    Write-Host " $Message" -ForegroundColor Red
    Write-BoxedTitle -Title "FAILED: $($ActionLabel.ToUpper()) COULD NOT BE COMPLETED" -Color Red
    [Console]::Error.WriteLine(("log".PadRight(10)) + $LogFile)
    [Console]::Error.WriteLine(("report".PadRight(10)) + 'https://github.com/tmonk/mcp-stata/issues/new?template=install-failure.yml')
    [Console]::Error.WriteLine(("contact".PadRight(10)) + $AuthorEmail)
    [Console]::Error.WriteLine(("clipboard".PadRight(10)) + "Get-Content '$LogFile' | Set-Clipboard")
}

function Format-ToolkitLine {
    param(
        [string]$Line
    )

    switch -Regex ($Line) {
        '^Adding marketplace.*already on disk.*$' {
            Write-Ok 'Marketplace already configured'
            break
        }
        '^Adding marketplace.*Successfully added marketplace: (.+)$' {
            Write-Ok $Matches[1]
            break
        }
        '^Adding marketplace.*$' {
            Write-Host '   >' -ForegroundColor Magenta -NoNewline
            Write-Host ' Adding marketplace' -ForegroundColor Magenta
            break
        }
        '^Installing plugin .*already installed.*$' {
            Write-Ok 'Plugin already installed'
            break
        }
        '^Installing plugin .*Successfully installed plugin: (.+)$' {
            Write-Ok $Matches[1]
            break
        }
        '^Installing plugin .*$' {
            Write-Host '   >' -ForegroundColor Magenta -NoNewline
            Write-Host ' Installing plugin' -ForegroundColor Magenta
            break
        }
        '^=== mcp-stata Toolkit Setup ===$' { break }
        '^\[STEP\] (.+)$' {
            Write-Step $Matches[1]
            break
        }
        '^\s+\[SUCCESS\] (.+)$' {
            Write-Ok $Matches[1]
            break
        }
        '^\s+\[WARNING\] (.+)$' {
            Write-Warn $Matches[1]
            break
        }
        '^\s+\[ERROR\] (.+)$' {
            Write-Host '   x' -ForegroundColor Red -NoNewline
            Write-Host " $($Matches[1])" -ForegroundColor Red
            break
        }
        '^=== Setup Complete ===$' {
            Write-BoxedTitle -Title 'SETUP COMPLETE' -Color Green
            break
        }
        '^Canonical server name: ' { break }
        '^Verify by asking your agent: ' { break }
        '^Quick start: ' { break }
        '^$' {
            Write-Host ''
            break
        }
        default {
            Write-Host "   $Line"
        }
    }
}

function Invoke-ToolkitInstaller {
    param(
        [string[]]$Arguments
    )

    $pythonInstaller = Join-Path $InstallRepoRoot 'scripts\install\setup_toolkit.py'
    if ($VerboseMode) {
        & uv run --python 3.11 $pythonInstaller @Arguments
        $exitCode = $LASTEXITCODE
    } else {
        $output = & uv run --python 3.11 $pythonInstaller @Arguments 2>&1
        $exitCode = $LASTEXITCODE
        foreach ($line in $output) {
            Format-ToolkitLine ([string]$line)
        }
    }
    return $exitCode
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
            Write-Host ''
            Write-Host '   !' -ForegroundColor Yellow -NoNewline
            Write-Host " Request failed (attempt $attempt/$MaxRetries). Retrying in $DelaySeconds seconds..." -ForegroundColor Yellow
            Start-Sleep -Seconds $DelaySeconds
        }
    }
}

function Send-Telemetry {
    param($Event, $ErrorCode = '')
    try {
        $action = if ($Event -like 'uninstall_*') { 'uninstall' } else { 'install' }
        $client = ''
        $scope = ''
        $install_ref = if ($env:MCP_STATA_REF) { $env:MCP_STATA_REF } else { '' }
        $install_repo = if ($env:MCP_STATA_REPO_URL) { $env:MCP_STATA_REPO_URL } else { '' }
        $script_version = if ($env:MCP_STATA_SCRIPT_VERSION) { $env:MCP_STATA_SCRIPT_VERSION } else { '' }

        for ($i = 0; $i -lt $PassthroughArgs.Count; $i++) {
            $arg = $PassthroughArgs[$i]
            if ($arg -eq '--agent' -and ($i + 1) -lt $PassthroughArgs.Count) { $client = $PassthroughArgs[$i + 1] }
            if ($arg -like '--agent=*') { $client = $arg.Substring(8) }
            if ($arg -eq '--scope' -and ($i + 1) -lt $PassthroughArgs.Count) { $scope = $PassthroughArgs[$i + 1] }
            if ($arg -like '--scope=*') { $scope = $arg.Substring(8) }
        }

        $payload = @{
            event = $Event
            action = $action
            client = $client
            install_source = $InstallSource
            scope = $scope
            install_ref = $install_ref
            install_repo = $install_repo
            script_version = $script_version
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
    Write-BoxedTitle -Title 'BOOTSTRAP SOURCE' -Color Blue
    if (Test-Path (Join-Path $RepoRoot 'scripts\install\setup_toolkit.py')) {
        Write-Ok "Using local checkout at $RepoRoot"
        return
    }

    Write-Step 'Fetching mcp-stata source'
    Write-Host '   •' -ForegroundColor DarkGray -NoNewline
    Write-Host " $ZipUrl" -ForegroundColor DarkGray
    $script:TempDir = Join-Path ([System.IO.Path]::GetTempPath()) ("mcp-stata-install-" + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $script:TempDir | Out-Null

    $zipFile = Join-Path $script:TempDir 'source.zip'
    Invoke-WithRetry { Invoke-WebRequest -Uri $ZipUrl -OutFile $zipFile -UseBasicParsing }

    $extractDir = Join-Path $script:TempDir 'extract'
    Expand-Archive -Path $zipFile -DestinationPath $extractDir

    $innerDir = Get-ChildItem -Path $extractDir -Directory | Select-Object -First 1
    $script:InstallRepoRoot = $innerDir.FullName
    Write-Ok "Source extracted to $($script:InstallRepoRoot)"
}

# ── Bootstrap uv ──────────────────────────────────────────────────────────────
function Initialize-Uv {
    Write-BoxedTitle -Title 'BOOTSTRAP RUNTIME' -Color Blue

    if (Get-Command uv -ErrorAction SilentlyContinue) {
        $uvVer = (uv --version 2>$null) -join ''
        Write-Ok "uv already installed ($uvVer)"
        return
    }

    Write-Step 'Installing uv'
    Write-Host '   •' -ForegroundColor DarkGray -NoNewline
    Write-Host ' Bootstrap via https://astral.sh/uv/install.ps1' -ForegroundColor DarkGray

    try {
        $policy = Get-ExecutionPolicy -Scope CurrentUser
        if ($policy -in @('Restricted', 'Undefined')) {
            Write-Step 'Attempting to set execution policy to RemoteSigned'
            Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser -Force
        }
    } catch {
        Write-Warn 'Could not set execution policy. If installation fails, run: Set-ExecutionPolicy RemoteSigned -Scope CurrentUser'
    }

    Invoke-WithRetry { Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression }

    $machinePath = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
    $env:Path = (@($env:Path, $machinePath, $userPath) -join ';' -split ';' | Where-Object { $_ } | Select-Object -Unique) -join ';'

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
        throw 'uv is not on PATH. Please add it manually and re-run.'
    }

    $uvVer = (uv --version 2>$null) -join ''
    Write-Ok "uv installed ($uvVer)"
}

Show-Header

# ── Entry point ───────────────────────────────────────────────────────────────
try {
    $currentPrincipal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    if ($currentPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        Write-Warn "Running as Administrator. $ActionLabel will be local to the admin profile."
    }

    $InstallStage = 'ensure_repo_root'
    Initialize-RepoRoot
    $InstallStage = 'ensure_uv'
    Initialize-Uv
    Write-BoxedTitle -Title "$($ActionLabel.ToUpper()) TOOLKIT" -Color Blue
    Write-Host '   •' -ForegroundColor DarkGray -NoNewline
    Write-Host ' Delegating to setup_toolkit.py' -ForegroundColor DarkGray
    $InstallStage = 'setup_toolkit'
    $toolkitExitCode = Invoke-ToolkitInstaller -Arguments $PassthroughArgs
    if ($toolkitExitCode -ne 0) { throw "Python installer failed with exit code $toolkitExitCode" }

    $event = if ($PassthroughArgs -contains '--uninstall') { 'uninstall_success' } else { 'install_success' }
    Send-Telemetry $event
    Show-Success
    exit 0
} catch {
    $failEvent = if ($PassthroughArgs -contains '--uninstall') { 'uninstall_failure' } else { 'install_failure' }
    Send-Telemetry $failEvent $_.Exception.Message
    Show-Failure $_.Exception.Message
    exit 1
} finally {
    Remove-TempDir
    Stop-Transcript -ErrorAction SilentlyContinue | Out-Null
}
