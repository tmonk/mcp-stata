# Pester 5 Integration Tests
$RepoRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
$InstallPs1 = Join-Path $RepoRoot "plugin\install.ps1"

Describe "install.ps1 Integration Tests" {
    BeforeAll {
        $script:RepoRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
        $script:InstallPs1 = Join-Path $script:RepoRoot "plugin\install.ps1"
        . $script:InstallPs1
    }

    Context "Repository Initialization" {
        It "detects and uses local checkout" {
            $RepoRoot = $script:RepoRoot
            Initialize-RepoRoot
            $InstallRepoRoot | Should -Be $RepoRoot
        }

        It "handles remote download with mocking" {
            $fakeRoot = Join-Path $env:TEMP "mcp5-remote-$([guid]::NewGuid().ToString('N'))"
            New-Item -ItemType Directory -Path $fakeRoot | Out-Null
            $RepoRoot = $fakeRoot
            
            try {
                Mock Invoke-WebRequest { }
                Mock Expand-Archive { 
                    param($Path, $DestinationPath)
                    New-Item -ItemType Directory -Path (Join-Path $DestinationPath "mcp-stata-main") | Out-Null
                }
                
                Initialize-RepoRoot
                $InstallRepoRoot | Should -Match "mcp-stata-install-"
            } finally {
                Remove-TempDir
                Remove-Item $fakeRoot -Recurse -Force -ErrorAction SilentlyContinue
            }
        }
    }

    Context "UV Bootstrap" {
        It "skips installation if uv is on PATH" {
            Mock Get-Command { return @{ Name = "uv" } } -ParameterFilter { $Name -eq 'uv' }
            Mock uv { return "uv 0.1.0" }
            
            $script:called = $false
            Mock Invoke-RestMethod { $script:called = $true; return "Write-Host 'mock'" }
            
            Initialize-Uv
            $script:called | Should -Be $false
        }

        It "installs uv and updates PATH if missing" {
            $script:uv_installed = $false
            
            Mock Get-Command { 
                param($Name)
                if ($script:uv_installed -and $Name -eq 'uv') { return @{ Name = "uv" } }
                return $null
            } -ParameterFilter { $Name -eq 'uv' }
            
            Mock Invoke-RestMethod { 
                $script:uv_installed = $true
                return "Write-Host 'mock uv installer'" 
            }
            Mock Invoke-Expression { }
            Mock Test-Path { return $true }
            
            Initialize-Uv
            $script:uv_installed | Should -Be $true
        }
    }
}
