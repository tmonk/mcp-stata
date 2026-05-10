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
$ProgressPreference = 'SilentlyContinue'

# ── Configuration ─────────────────────────────────────────────────────────────
$InstallHost = 'mcp-stata-install.tdmonk.com'
$InstallUrlSh = "https://${InstallHost}/install.sh"
$InstallUrlPs1 = "https://${InstallHost}/install.ps1"
$TelemetryUrl = "https://${InstallHost}/telemetry"

# GitHub fallback
$GithubRepoUrl = 'https://github.com/tmonk/mcp-stata'
$GithubRawUrl = 'https://raw.githubusercontent.com/tmonk/mcp-stata/main/plugin'
$InstallFallbackSh = "${GithubRawUrl}/install.sh"
$InstallFallbackPs1 = "${GithubRawUrl}/install.ps1"
$ScriptVersion = '3.2.8'

# Pull dynamic config from GitHub (optional, best-effort)
try {
    $dynamicConfig = Invoke-RestMethod -Uri "${GithubRawUrl}/installer.json" -TimeoutSec 2 -ErrorAction SilentlyContinue
    if ($dynamicConfig -and $dynamicConfig.urls -and $dynamicConfig.urls.primary) {
        $InstallHost = $dynamicConfig.urls.primary.base.Replace('https://', '')
        $InstallUrlSh = $dynamicConfig.urls.primary.sh
        $InstallUrlPs1 = $dynamicConfig.urls.primary.ps1
        $TelemetryUrl = $dynamicConfig.urls.primary.telemetry
    }
} catch {}

if (-not [Runtime.InteropServices.RuntimeInformation]::IsOSPlatform([Runtime.InteropServices.OSPlatform]::Windows)) {
    Write-Host '✖ This installer is for Windows only.' -ForegroundColor Red
    Write-Host ':: Please use install.sh for Linux or macOS:' -ForegroundColor Cyan
    Write-Host "   curl -fsSL ${InstallUrlSh} | bash" -ForegroundColor Cyan
    Write-Host "   (Fallback: curl -fsSL ${InstallFallbackSh} | bash)" -ForegroundColor DarkGray
    if ($MyInvocation.MyCommand.Path) { exit 1 } else { return }
}

$RepoUrl = if ($env:MCP_STATA_REPO_URL) { $env:MCP_STATA_REPO_URL } else { 'https://github.com/tmonk/mcp-stata' }
$Ref     = if ($env:MCP_STATA_REF) { $env:MCP_STATA_REF } else { 'main' }
$ZipUrl  = "${RepoUrl}/archive/${Ref}.zip"
$ActionLabel = if ($PassthroughArgs -contains '--uninstall') { 'Uninstall' } else { 'Installation' }
$AuthorName = 'Thomas Monk'
$AuthorAffiliation = 'London School of Economics'
$AuthorEmail = 't.d.monk@lse.ac.uk'
# Note: Version is derived dynamically in Get-Version after bootstrap
$VerboseMode = $PassthroughArgs -contains '--verbose'

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

function Get-MachineId {
    try {
        $id = (Get-CimInstance Win32_ComputerSystemProduct -ErrorAction SilentlyContinue).UUID
        if ($id) { return $id }
    } catch {}
    return 'unknown'
}

function Get-Version {
    if ($env:MCP_STATA_SCRIPT_VERSION) { return $env:MCP_STATA_SCRIPT_VERSION }
    return $ScriptVersion
}

# ── Logging ────────────────────────────────────────────────────────────────
$TempPath = [System.IO.Path]::GetTempPath()
$RandomSuffix = -join ((48..57) + (97..122) | Get-Random -Count 6 | ForEach-Object { [char]$_ })
$LogFile = Join-Path $TempPath ("mcp-stata-install-" + (Get-Date -Format 'yyyyMMdd-HHmmss') + "-" + $RandomSuffix + ".log")
$env:MCP_STATA_INSTALL_LOG_FILE = $LogFile
Start-Transcript -Path $LogFile -Append -ErrorAction SilentlyContinue | Out-Null

# ── Telemetry ──────────────────────────────────────────────────────────────
# What is sent: event type, OS/arch, MCP client name(s), install duration, a
# unique run ID, and — on failure — the last 100 lines of the install log so
# errors can be diagnosed. No file contents, credentials, or paths are included.
$InstallId = [guid]::NewGuid().ToString()
$InstallStart = Get-Date
$InstallStage = 'init'
$InstallSource = if ($env:MCP_STATA_INSTALL_SOURCE) { $env:MCP_STATA_INSTALL_SOURCE } else { 'direct' }  # workbench|direct
$TelemetryEnabled = if ($env:MCP_STATA_TELEMETRY_ENABLED) { [int]$env:MCP_STATA_TELEMETRY_ENABLED } else { 1 }
$TelemetryRetries = if ($env:MCP_STATA_TELEMETRY_RETRIES) { [int]$env:MCP_STATA_TELEMETRY_RETRIES } else { 3 }
$TelemetryTimeoutSec = if ($env:MCP_STATA_TELEMETRY_TIMEOUT_SECS) { [int]$env:MCP_STATA_TELEMETRY_TIMEOUT_SECS } else { 5 }
$TelemetryDebug = if ($env:MCP_STATA_TELEMETRY_DEBUG) { [int]$env:MCP_STATA_TELEMETRY_DEBUG } else { 0 }
# Trailing-log capture size for failures. Sized so a worst-case JSON-escaped
# value (lots of newlines/tabs) still lands well under the worker's 4000-char
# log_tail cap and the 8 KB total payload cap.
$TelemetryLogTailBytes = if ($env:MCP_STATA_LOG_TAIL_BYTES) { [int]$env:MCP_STATA_LOG_TAIL_BYTES } else { 3500 }
$DryRun = $PassthroughArgs -contains '--dry-run'
$UserId = ''

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
    if ([Runtime.InteropServices.RuntimeInformation]::IsOSPlatform([Runtime.InteropServices.OSPlatform]::Windows)) {
        Write-Host ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name)
    } else {
        Write-Host $env:USER
    }
    Write-Host ('version'.PadRight(8)) -ForegroundColor DarkGray -NoNewline
    Write-Host (Get-Version)
    Write-Host ('args'.PadRight(8)) -ForegroundColor DarkGray -NoNewline
    if ($PassthroughArgs.Count -gt 0) {
        Write-Host ($PassthroughArgs -join ' ')
    } else {
        Write-Host '(none)'
    }
}

function Show-Help {
    @"
mcp-stata installer (PowerShell)

Usage:
  install.ps1 [--agent <name>] [--scope <user|project>] [--dry-run] [--uninstall] [--verbose] ...

Notes:
  - This script delegates the heavy lifting to scripts\install\setup_toolkit.py
  - Telemetry is best-effort and never affects exit status.

Local checkout (uv run --directory … instead of uvx):
  --install-repo DIR          Passed through to setup_toolkit.py
  MCP_STATA_INSTALL_REPO      Same effect if set in the environment

Examples:
  irm ${InstallUrlPs1} | iex
  # Fallback: irm ${InstallFallbackPs1} | iex
  powershell -ExecutionPolicy Bypass -File install.ps1 --agent cursor --dry-run
  `$env:MCP_STATA_INSTALL_REPO = 'C:\src\mcp-stata'; .\install.ps1 --agent cursor
  .\install.ps1 --install-repo 'C:\src\mcp-stata' --agent cursor --dry-run
"@ | Write-Host
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
    Write-Host ''
    Write-Host 'TO UPDATE' -ForegroundColor Cyan -NoNewline
    Write-Host ''
    Write-Host "   irm ${InstallUrlPs1} | iex" -ForegroundColor Cyan
    Write-Host "   (Fallback: irm ${InstallFallbackPs1} | iex)" -ForegroundColor DarkGray
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
    
    # Temporarily lower ErrorActionPreference to prevent termination when uv 
    # writes status/progress information to stderr (captured by 2>&1).
    $oldEAP = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    
    try {
        if ($VerboseMode) {
            & uv run --no-project --no-progress --python 3.11 "$pythonInstaller" @Arguments
            $exitCode = $LASTEXITCODE
        } else {
            $output = & uv run --no-project --no-progress --python 3.11 "$pythonInstaller" @Arguments 2>&1
            $exitCode = $LASTEXITCODE
            foreach ($line in $output) {
                Format-ToolkitLine ([string]$line)
            }
        }
    } finally {
        $ErrorActionPreference = $oldEAP
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

function New-UserId {
    # Anonymous word-only id. Example: amber-otter-sprout
    $adjectives = @(
        'amber','aqua','brisk','calm','cedar','coral','dawn','dapper','dune','ember','fern','frosty','glowy',
        'hazel','ivy','jade','jolly','keen','kind','lemon','lilac','lucid','lucky','lunar','maple','mellow',
        'misty','mossy','nimble','noble','ocean','olive','opal','peach','pine','plum','polar','quartz','quick',
        'rosy','sage','sandy','satin','silver','simple','snowy','solar','spring','sunny','swift','thyme',
        'velvet','vivid','warm','windy','wisteria','zesty'
    )
    $nouns = @(
        'otter','panda','fox','koala','penguin','capybara','gecko','puffin','kitten','badger','rabbit',
        'sparrow','heron','falcon','dolphin','whale','turtle','lizard','yak','bison','alpaca',
        'comet','river','forest','meadow','canyon','summit','harbor','pebble','lantern','compass',
        'sprout','acorn','fernleaf','snowflake','raindrop','starlight','moonbeam','sunburst',
        'gadget','widget','pixel','prisma','orbit','drift','ripple'
    )
    $a = $adjectives | Get-Random
    $n1 = $nouns | Get-Random
    $n2 = $nouns | Get-Random
    if ($n2 -eq $n1) { $n2 = $nouns | Get-Random }
    return "$a-$n1-$n2"
}

function Get-UserId {
    if ($env:MCP_STATA_USER_ID) { return [string]$env:MCP_STATA_USER_ID }
    if ($DryRun) { return 'dryrun' }

    $base = if ($env:XDG_STATE_HOME) { $env:XDG_STATE_HOME } else { Join-Path $env:LOCALAPPDATA 'mcp-stata' }
    if (-not $base) { $base = Join-Path $env:TEMP 'mcp-stata' }
    $dir = $base
    $file = Join-Path $dir 'telemetry_user_id'

    try {
        if (Test-Path $file) {
            $v = (Get-Content $file -TotalCount 1 -ErrorAction SilentlyContinue)
            if ($v) { return [string]$v }
        }
    } catch {}

    try { New-Item -ItemType Directory -Path $dir -Force -ErrorAction SilentlyContinue | Out-Null } catch {}
    $new = New-UserId
    try { Set-Content -Path $file -Value $new -NoNewline -ErrorAction SilentlyContinue } catch {}
    return $new
}

function Send-Telemetry {
    param($Event, $ErrorCode = '')
    try {
        if ($TelemetryEnabled -ne 1) { return }
        $action = if ($Event -like 'uninstall_*') { 'uninstall' } else { 'install' }
        $client = ''
        $scope = ''
        $install_ref = if ($env:MCP_STATA_REF) { $env:MCP_STATA_REF } else { '' }
        $install_repo = if ($env:MCP_STATA_REPO_URL) { $env:MCP_STATA_REPO_URL } else { '' }
        $script_version = if ($env:MCP_STATA_SCRIPT_VERSION) { $env:MCP_STATA_SCRIPT_VERSION } else { '' }

        for ($i = 0; $i -lt $PassthroughArgs.Count; $i++) {
            $arg = $PassthroughArgs[$i]
            if ($arg -eq '--agent' -and ($i + 1) -lt $PassthroughArgs.Count) {
                $newAgent = $PassthroughArgs[$i + 1]
                $client = if ($client) { "$client,$newAgent" } else { $newAgent }
            }
            if ($arg -like '--agent=*') {
                $newAgent = $arg.Substring(8)
                $client = if ($client) { "$client,$newAgent" } else { $newAgent }
            }
            if ($arg -eq '--scope' -and ($i + 1) -lt $PassthroughArgs.Count) { $scope = $PassthroughArgs[$i + 1] }
            if ($arg -like '--scope=*') { $scope = $arg.Substring(8) }
        }

        # Capture trailing portion of the install log ONLY for failures.
        # Use byte-based slicing (not -Tail N) so a single very long line
        # (e.g. uv installer dumping a stack trace) still fits the worker's
        # log_tail cap. The catch block flushes Stop-Transcript before this
        # runs, so the file already contains everything up to the failure.
        $logTail = ''
        if ($Event -like '*failure*' -and $LogFile -and (Test-Path $LogFile)) {
            try {
                $allText = Get-Content $LogFile -Raw -ErrorAction SilentlyContinue
                if ($allText) {
                    if ($allText.Length -gt $TelemetryLogTailBytes) {
                        $logTail = $allText.Substring($allText.Length - $TelemetryLogTailBytes)
                    } else {
                        $logTail = $allText
                    }
                }
            } catch {}
        }

        $telemetryUser = 'unknown'
        if ([Runtime.InteropServices.RuntimeInformation]::IsOSPlatform([Runtime.InteropServices.OSPlatform]::Windows)) {
            $telemetryUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
        } else {
            $telemetryUser = $env:USER
        }

        if ($env:MCP_STATA_TELEMETRY_USERNAME) {
            $telemetryUser = $env:MCP_STATA_TELEMETRY_USERNAME
        }
        elseif ($env:GITHUB_ACTIONS -eq 'true') {
            $telemetryUser = 'runner-mcp'
        }

        $payload = @{
            event = $Event
            action = $action
            client = $client
            install_source = $InstallSource
            scope = $scope
            user_id = $UserId
            username = $telemetryUser
            machine_id = Get-MachineId
            install_ref = $install_ref
            install_repo = $install_repo
            script_version = Get-Version
            stage = $InstallStage
            error_code = $ErrorCode
            os = 'windows'
            distro = "windows-$([System.Environment]::OSVersion.Version.Major).$([System.Environment]::OSVersion.Version.Build)"
            arch = $env:PROCESSOR_ARCHITECTURE.ToLower()
            duration_ms = [int]((Get-Date) - $InstallStart).TotalMilliseconds
            install_id = $InstallId
            file = 'install.ps1'
            log_tail = $logTail
        } | ConvertTo-Json -Compress
        for ($attempt = 1; $attempt -le $TelemetryRetries; $attempt++) {
            try {
                $resp = Invoke-RestMethod -Uri $TelemetryUrl -Method Post -Body $payload `
                    -ContentType 'application/json' -TimeoutSec $TelemetryTimeoutSec `
                    -ErrorAction Stop
                if ($TelemetryDebug -eq 1) {
                    Write-Warn ("Telemetry debug: ok event=$Event" )
                }
                break
            } catch {
                if ($TelemetryDebug -eq 1) {
                    Write-Warn ("Telemetry debug: failed event=$Event attempt=$attempt/$TelemetryRetries")
                    Write-Warn ($_.Exception.Message)
                }
                if ($attempt -lt $TelemetryRetries) { Start-Sleep -Milliseconds 200 }
            }
        }
    } catch {}
}


function Remove-TempDir {
    if ($TempDir -and (Test-Path $TempDir)) {
        Remove-Item -Recurse -Force $TempDir -ErrorAction SilentlyContinue
    }
}

function Initialize-RepoRoot {
    Write-BoxedTitle -Title 'BOOTSTRAP SOURCE' -Color Blue
    if (Test-Path (Join-Path $RepoRoot 'scripts\install\setup_toolkit.py')) {
        Remove-Item Env:MCP_STATA_TRANSIENT_INSTALL_SOURCE -ErrorAction SilentlyContinue
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
    $env:MCP_STATA_TRANSIENT_INSTALL_SOURCE = '1'
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
        if ($policy -notin @('RemoteSigned', 'Unrestricted', 'Bypass')) {
            Write-Step "Attempting to set execution policy to RemoteSigned (current: $policy)"
            Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser -Force -ErrorAction SilentlyContinue
        }
    } catch {
        Write-Warn 'Could not set execution policy. If installation fails, run: Set-ExecutionPolicy RemoteSigned -Scope CurrentUser'
    }

    $oldEAP = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        Invoke-WithRetry { Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression }
    } finally {
        $ErrorActionPreference = $oldEAP
    }

    $machinePath = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
    # Combine and deduplicate PATH, preserving order (env:Path first)
    $env:Path = (@($env:Path, $userPath, $machinePath) -join ';' -split ';' | Where-Object { $_ } | Select-Object -Unique) -join ';'

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

if ($MyInvocation.InvocationName -ne '.') {
    function Invoke-Main {
        try {
            # 1. Identity & Early Metadata
            $script:UserId = Get-UserId
            $startEvent = if ($PassthroughArgs -contains '--uninstall') { 'uninstall_start' } else { 'install_start' }

            # 2. Emit start event IMMEDIATELY
            Send-Telemetry $startEvent

            if ($PassthroughArgs -contains '--help' -or $PassthroughArgs -contains '-h') {
                Show-Help
                return 0
            }

            if ([Runtime.InteropServices.RuntimeInformation]::IsOSPlatform([Runtime.InteropServices.OSPlatform]::Windows)) {
                $currentPrincipal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
                if ($currentPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
                    Write-Warn "Running as Administrator. $ActionLabel will be local to the admin profile."
                }
            }

            # Telemetry-only mode: test end-to-end telemetry without mutating the machine.
            if ($env:MCP_STATA_TELEMETRY_ONLY -eq '1') {
                $InstallStage = 'telemetry_only'
                $endEvent = if ($PassthroughArgs -contains '--uninstall') { 'uninstall_success' } else { 'install_success' }
                Send-Telemetry $endEvent
                Write-Ok 'Telemetry-only mode complete'
                Write-Host '   •' -ForegroundColor DarkGray -NoNewline
                Write-Host " install_id=$InstallId" -ForegroundColor DarkGray
                return 0
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
            return 0
        } catch {
            $failEvent = if ($PassthroughArgs -contains '--uninstall') { 'uninstall_failure' } else { 'install_failure' }
            # Ensure log is flushed to disk before sending telemetry
            try { Stop-Transcript -ErrorAction SilentlyContinue | Out-Null } catch {}
            Send-Telemetry $failEvent $_.Exception.Message
            Show-Failure $_.Exception.Message
            return 1
        } finally {
            Remove-TempDir
            Stop-Transcript -ErrorAction SilentlyContinue | Out-Null
        }
    }

    Show-Header
    $exitCode = Invoke-Main
    if ($MyInvocation.MyCommand.Path) { exit $exitCode }
}

