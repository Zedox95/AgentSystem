<#
.SYNOPSIS
    Portable per-user setup for Claude Code, Codex and ChatGPT guidance.
    Run from a fresh checkout on each user's computer. No global trust bypass,
    credential copying, paid LLM API, or persistent environment changes.
#>
[CmdletBinding()]
param(
    [string]$VaultPath,
    [switch]$SkipVault,
    [string]$UfoRoot,
    [switch]$SkipUfo,
    [Nullable[bool]]$InstallPlaywright,
    [switch]$SkipCodexHint,
    [switch]$NonInteractive,
    [ValidateSet('claude','codex','chatgpt')][string[]]$Providers = @('claude','codex','chatgpt')
)
$ErrorActionPreference = 'Stop'
$RepoRoot = $PSScriptRoot
$Python = (Get-Command python -ErrorAction Stop).Source
$VersionText = & $Python --version
if ($LASTEXITCODE -ne 0 -or $VersionText -notmatch 'Python 3\.(\d+)' -or [int]$Matches[1] -lt 11) {
    throw 'Python 3.11 or newer is required. No installation was changed.'
}
if (-not $NonInteractive -and -not $SkipVault -and -not $VaultPath) {
    $Answer = Read-Host 'Use Obsidian as shared memory? [Y/n]'
    if ($Answer -match '^[nN]') { $SkipVault = $true }
    else {
        $VaultPath = Read-Host 'Vault directory (empty = a new AgentSystem-Vault next to this checkout)'
        if (-not $VaultPath) { $VaultPath = Join-Path (Split-Path $RepoRoot -Parent) 'AgentSystem-Vault' }
    }
}
if ($InstallPlaywright -eq $true) {
    Push-Location (Join-Path $RepoRoot 'adapters\playwright')
    try {
        & npm ci
        if ($LASTEXITCODE -ne 0) { throw 'npm ci failed; AgentSystem configuration was not changed.' }
        & npx playwright install chromium
        if ($LASTEXITCODE -ne 0) { throw 'Chromium installation failed; AgentSystem configuration was not changed.' }
    } finally { Pop-Location }
}
$SetupArgs = @((Join-Path $RepoRoot 'bin\setup_agent.py'), 'install')
foreach ($Provider in $Providers) { $SetupArgs += @('--provider', $Provider) }
if ($SkipVault) { $SetupArgs += '--skip-vault' }
elseif ($VaultPath) { $SetupArgs += @('--vault', $VaultPath) }
if ($UfoRoot -and -not $SkipUfo) { $SetupArgs += @('--ufo-root', $UfoRoot) }
& $Python @SetupArgs
if ($LASTEXITCODE -ne 0) { throw 'Setup failed. Inspect the reported error; no success is claimed.' }
Write-Host 'Open this checkout as a trusted project. In Codex review new hooks with /hooks.'
Write-Host 'ChatGPT: follow docs/chatgpt-setup.md; account instructions and tools need a separate connection.'
Write-Host 'Check configuration with: python bin/setup_agent.py doctor'
