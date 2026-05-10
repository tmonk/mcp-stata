# Pester 5 E2E Tests
$RepoRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
$InstallPs1 = Join-Path $RepoRoot "plugin\install.ps1"

Describe "install.ps1 E2E Tests" {
    # Modern Pester 5: Run phase for setup
    BeforeAll {
        $script:RepoRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
        $script:InstallPs1 = Join-Path $script:RepoRoot "plugin\install.ps1"
        $env:MCP_STATA_TELEMETRY_ENABLED = 0
    }

    AfterAll {
        Remove-Item env:MCP_STATA_TELEMETRY_ENABLED -ErrorAction SilentlyContinue
    }

    Context "CLI Interface" {
        It "shows help information correctly" {
            $output = & powershell -ExecutionPolicy Bypass -File $script:InstallPs1 --help *>&1
            $text = "$output"
            $text | Should -BeLike "*mcp-stata installer*"
            $text | Should -BeLike "*Usage:*"
            $LASTEXITCODE | Should -Be 0
        }

        It "completes a dry-run install" {
            $output = & powershell -ExecutionPolicy Bypass -File $script:InstallPs1 --agent cursor --dry-run *>&1
            $text = "$output"
            $text | Should -BeLike "*Installation complete*"
            $LASTEXITCODE | Should -Be 0
        }
    }

    Context "Telemetry Resilience" {
        It "succeeds even if telemetry endpoint is unreachable" {
            $env:MCP_STATA_TELEMETRY_ENABLED = 1
            $env:MCP_STATA_TELEMETRY_URL = "http://255.255.255.255/unreachable"
            $env:MCP_STATA_TELEMETRY_RETRIES = 1
            $env:MCP_STATA_TELEMETRY_TIMEOUT_SECS = 1
            
            try {
                $output = & powershell -ExecutionPolicy Bypass -File $script:InstallPs1 --agent cursor --dry-run *>&1
                $text = "$output"
                $text | Should -BeLike "*Installation complete*"
                $LASTEXITCODE | Should -Be 0
            } finally {
                $env:MCP_STATA_TELEMETRY_ENABLED = 0
            }
        }
    }
}
