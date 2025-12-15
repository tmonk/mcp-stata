# To run:
# powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File scripts\clean_test.ps1

param(
    [string]$StataPath = "",
    [string]$TestArgs = "tests -vv -s"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Resolve-Tool {
    param([string[]]$Candidates)
    foreach ($c in $Candidates) {
        try {
            $cmd = Get-Command $c -ErrorAction Stop
            return $cmd.Source
        } catch {
            continue
        }
    }
    return $null
}

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$venvPath = Join-Path $repoRoot ".venv-clean"

$uvCmd = Resolve-Tool @("uv", "uv.exe")
if (-not $uvCmd) {
    throw "uv not found. Install uv (https://docs.astral.sh/uv/) and ensure 'uv' is on PATH."
}
$uvDir = Split-Path $uvCmd

# Prefer explicit 3.11, then any python, then py launcher (used only to run pytest from the env).
$pythonCmd = Resolve-Tool @("python3.11", "python", "py -3.11", "py -3", "py")

# Minimize env noise for this run
$originalPath = $env:PATH
$env:PATH = "$uvDir;$env:SystemRoot;$env:SystemRoot\System32"
$varsToClear = @(
    "PYTHONPATH",
    "PYTHONHOME",
    "VIRTUAL_ENV",
    "CONDA_PREFIX",
    "STATA_PATH",
    "UV_PROJECT_ENVIRONMENT",
    "PYTEST_ADDOPTS",
    "PYTEST_PLUGINS",
    "PYTEST_DISABLE_PLUGIN_AUTOLOAD"
)
foreach ($v in $varsToClear) { Remove-Item Env:$v -ErrorAction SilentlyContinue }

if (Test-Path $venvPath) { Remove-Item $venvPath -Recurse -Force }

Push-Location $repoRoot
try {
    # Install deps with uv in a clean project environment, without installing the project itself.
    $env:UV_PROJECT_ENVIRONMENT = $venvPath
    & $uvCmd sync --extra dev --no-install-project

    $venvPython = Join-Path $venvPath "Scripts\python.exe"
    if (-not (Test-Path $venvPython)) {
        throw "Virtual env missing python at $venvPython. Ensure Python 3.11+ is available."
    }

    if ($StataPath) { $env:STATA_PATH = $StataPath } else { Remove-Item Env:STATA_PATH -ErrorAction SilentlyContinue }

    $pytestArgs = @()
    if ($TestArgs) { $pytestArgs = $TestArgs -split "\s+" }
    if (-not $pytestArgs) { $pytestArgs = @("tests", "-vv", "-s") }

    Write-Host "[clean-test] pytest args: $($pytestArgs -join ' ')" -ForegroundColor Cyan
    & $venvPython -m pytest @pytestArgs
}
finally {
    Pop-Location
    $env:PATH = $originalPath
    Remove-Item Env:UV_PROJECT_ENVIRONMENT -ErrorAction SilentlyContinue
}
