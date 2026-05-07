$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$marketplaceName = 'mcp-stata-marketplace'

if (Get-Command claude -ErrorAction SilentlyContinue) {
  claude plugin marketplace add $repoRoot --scope project
  claude plugin install "mcp-stata@$marketplaceName" --scope project
}
else {
  Write-Warning 'Claude CLI not found; skipped Claude marketplace install.'
}

if (Get-Command codex -ErrorAction SilentlyContinue) {
  codex plugin marketplace add (Join-Path $repoRoot '.agents/plugins')
}
else {
  Write-Warning 'Codex CLI not found; skipped Codex marketplace install.'
}

Write-Host 'Done. If Codex is already open, restart it to pick up the marketplace.'