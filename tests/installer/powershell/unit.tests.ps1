# Pester 5 Unit Tests
$RepoRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
$InstallPs1 = Join-Path $RepoRoot "plugin\install.ps1"

Describe "install.ps1 Unit Tests" {
    BeforeAll {
        $global:TestLogFile = Join-Path $env:TEMP "pester_unit_test.log"
        $script:RepoRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
        $script:InstallPs1 = Join-Path $script:RepoRoot "plugin\install.ps1"
        . $script:InstallPs1
    }

    Context "Version Logic" {
        It "returns MCP_STATA_SCRIPT_VERSION if set" {
            $env:MCP_STATA_SCRIPT_VERSION = "5.0.0-p5"
            try {
                Get-Version | Should -Be "5.0.0-p5"
            } finally {
                Remove-Item env:MCP_STATA_SCRIPT_VERSION -ErrorAction SilentlyContinue
            }
        }

        It "falls back to hardcoded version when all else fails" {
            Mock Get-Command { return $null } -ParameterFilter { $Name -eq 'git' }
            Mock Test-Path { return $false }
            
            Get-Version | Should -Be "3.1.2-direct"
        }
    }

    Context "User Identity" {
        It "generates a valid user ID format" {
            New-UserId | Should -Match "^[a-z]+-[a-z]+-[a-z]+$"
        }

        It "persists and retrieves user ID" {
            $oldLocal = $env:LOCALAPPDATA
            $env:LOCALAPPDATA = $env:TEMP
            try {
                $dir = Join-Path $env:TEMP "mcp-stata"
                $file = Join-Path $dir "telemetry_user_id"
                if (Test-Path $file) { Remove-Item $file -Force }
                
                $id = Get-UserId
                $id | Should -Not -BeNullOrEmpty
                Test-Path $file | Should -Be $true
                Get-UserId | Should -Be $id
            } finally {
                $env:LOCALAPPDATA = $oldLocal
            }
        }
    }

    Context "Output Formatting" {
        BeforeEach {
            if (Test-Path $global:TestLogFile) { Remove-Item $global:TestLogFile }
        }

        Mock Write-Host { 
            param($Object) 
            if ($Object) { $Object.ToString() | Out-File -Append -FilePath $global:TestLogFile }
        }

        $TestData = @(
            @{ Input = "[STEP] Initializing"; Expected = ">> Initializing" },
            @{ Input = "  [SUCCESS] Done"; Expected = "+ Done" },
            @{ Input = "  [WARNING] Alert"; Expected = "! Alert" },
            @{ Input = "  [ERROR] Crash"; Expected = "x Crash" }
        )

        It "formats '<Input>' correctly" -ForEach $TestData {
            Format-ToolkitLine $_.Input
            $content = if (Test-Path $global:TestLogFile) { Get-Content $global:TestLogFile -Raw } else { "" }
            $content | Should -Match ([regex]::Escape($_.Expected))
        }
        
        It "formats completion box" {
            Format-ToolkitLine "=== Setup Complete ==="
            $content = if (Test-Path $global:TestLogFile) { Get-Content $global:TestLogFile -Raw } else { "" }
            $content | Should -Match "SETUP COMPLETE"
        }
    }

    Context "Cleanup" {
        It "safely handles null TempDir" {
            # Directly set the variable in the scope where it was dot-sourced
            Set-Variable -Name TempDir -Value $null -Scope 1
            { Remove-TempDir } | Should -Not -Throw
        }

        It "deletes existing TempDir" {
            $testPath = Join-Path $env:TEMP "pester5-cleanup-$([guid]::NewGuid().ToString('N'))"
            New-Item -ItemType Directory -Path $testPath | Out-Null
            Set-Variable -Name TempDir -Value $testPath -Scope 1
            Remove-TempDir
            Test-Path $testPath | Should -Be $false
        }
    }
}
