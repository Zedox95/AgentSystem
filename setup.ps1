<#
.SYNOPSIS
    Interactive setup for AgentSystem: adapts fixed paths to the actual
    clone location and asks about optional components (Second Brain/Obsidian,
    UFO2, Playwright, Codex integration).

.DESCRIPTION
    None of this is required to use the repo - anyone who answers all
    questions with No/Enter gets a working system without the optional
    components. The script only writes files inside this repo
    (.claude/settings.json, .mcp.json) and, where sensible, persistent
    user environment variables. It installs no software without asking,
    unless you confirm the respective step.

.EXAMPLE
    .\setup.ps1
    Interactive, with prompts.

.EXAMPLE
    .\setup.ps1 -VaultPath 'D:\Notizen\Vault' -InstallPlaywright:$true -SkipUfo -SkipCodexHint
    Non-interactive for scripts/CI.
#>
[CmdletBinding()]
param(
    [string]$VaultPath,
    [switch]$SkipVault,
    [string]$UfoRoot,
    [switch]$SkipUfo,
    [Nullable[bool]]$InstallPlaywright,
    [switch]$SkipCodexHint
)

$ErrorActionPreference = 'Stop'
$RepoRoot = $PSScriptRoot
$SettingsPath = Join-Path $RepoRoot '.claude\settings.json'
$McpPath = Join-Path $RepoRoot '.mcp.json'

function Read-YesNo {
    param([string]$Prompt, [string]$Default = 'n')
    $suffix = if ($Default -eq 'j') { '[Y/n]' } else { '[y/N]' }
    $answer = Read-Host "$Prompt $suffix"
    if ([string]::IsNullOrWhiteSpace($answer)) { $answer = $Default }
    return $answer -match '^[jJyY]'
}

function Set-Utf8NoBom {
    # Set-Content -Encoding utf8 always writes a BOM under PowerShell 5.1.
    # Claude Code's settings.json/.mcp.json are read by strict JSON parsers
    # that reject a BOM (e.g. Python's json module) - so write without a
    # BOM here deliberately.
    param([string]$Path, [string]$Content)
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Content, $utf8NoBom)
}

Write-Host "=== AgentSystem Setup ===" -ForegroundColor Cyan
Write-Host "Repo root: $RepoRoot"
Write-Host ""

if (-not (Test-Path $SettingsPath) -or -not (Test-Path $McpPath)) {
    throw "Expected files are missing ($SettingsPath / $McpPath). The script must be run from the repo root."
}

# --- 1. Set AGENTSYSTEM_ROOT to the actual clone location -----------------
[Environment]::SetEnvironmentVariable('AGENTSYSTEM_ROOT', $RepoRoot, 'User')
$env:AGENTSYSTEM_ROOT = $RepoRoot
Write-Host "AGENTSYSTEM_ROOT (user environment variable) -> $RepoRoot" -ForegroundColor Green

# settings.json: replace only known literal path forms, no structural JSON
# reformatting - that keeps hooks/permissions untouched.
# A backslash in the repo path becomes two backslashes in the JSON text (\\
# encodes a \). Caution: -replace takes a regex pattern on the left, a
# literal pattern on the right.
$settingsText = Get-Content $SettingsPath -Raw -Encoding utf8
$forwardOld = 'C:/AgentSystem'
$forwardNew = ($RepoRoot -replace '\\', '/')
$backslashOld = 'C:\\AgentSystem'
$backslashNew = ($RepoRoot -replace '\\', '\\')
$settingsText = $settingsText.Replace($forwardOld, $forwardNew).Replace($backslashOld, $backslashNew)

# Adapt DENY/ALLOW rules that, as a template, point to a placeholder
# username (credential files, default vault path) to the user actually
# installing - otherwise the DENY rules protect the wrong profile.
$settingsText = $settingsText.Replace('C:\\Users\\YOURUSERNAME\\', "C:\\Users\\$env:USERNAME\\")

Set-Utf8NoBom -Path $SettingsPath -Content $settingsText
Write-Host "settings.json: hook paths and AGENTSYSTEM_ROOT adjusted." -ForegroundColor Green
Write-Host ""

# --- 2. Load .mcp.json in a structured way ---------------------------------
$mcp = Get-Content $McpPath -Raw -Encoding utf8 | ConvertFrom-Json

# --- 3. Second Brain / Obsidian --------------------------------------------
if ($SkipVault) {
    $wantVault = $false
} elseif ($PSBoundParameters.ContainsKey('VaultPath')) {
    $wantVault = $true
} else {
    $wantVault = Read-YesNo -Prompt "Set up Second Brain (a learning, source-backed knowledge store in Obsidian)?"
}

if ($wantVault) {
    if (-not $VaultPath) {
        $VaultPath = Read-Host "Path to an existing Obsidian vault (empty = create a new vault next to the repo)"
    }
    if ([string]::IsNullOrWhiteSpace($VaultPath)) {
        $VaultPath = Join-Path (Split-Path $RepoRoot -Parent) 'AgentSystem-Vault'
        foreach ($sub in '01 Inbox', '03 Bereiche', '04 Ressourcen', '05 Daily Notes') {
            New-Item -ItemType Directory -Force -Path (Join-Path $VaultPath $sub) | Out-Null
        }
        Write-Host "New vault created: $VaultPath" -ForegroundColor Green
    } elseif (-not (Test-Path $VaultPath)) {
        Write-Warning "Path does not exist: $VaultPath - please create it before first use."
    }
    [Environment]::SetEnvironmentVariable('AGENTSYSTEM_VAULT', $VaultPath, 'User')
    $mcp.mcpServers.'shared-memory'.env.AGENTSYSTEM_VAULT = $VaultPath
    $mcp.mcpServers.'shared-memory'.env | Add-Member -NotePropertyName AGENTSYSTEM_ROOT -NotePropertyValue $RepoRoot -Force
    $mcp.mcpServers.'shared-memory'.args = @((Join-Path $RepoRoot 'adapters\memory\memory_mcp.py'))

    # Move the vault read-ALLOW rule in settings.json to the actually chosen
    # path, if it differs from the default.
    $defaultVault = "C:\Users\$env:USERNAME\Documents\Obsidian Vault"
    if ((Resolve-Path -LiteralPath $VaultPath -ErrorAction SilentlyContinue).Path -ne
        (Resolve-Path -LiteralPath $defaultVault -ErrorAction SilentlyContinue).Path) {
        $settingsText = Get-Content $SettingsPath -Raw -Encoding utf8
        $defaultVaultJson = ($defaultVault -replace '\\', '\\')
        $chosenVaultJson = ($VaultPath -replace '\\', '\\')
        $settingsText = $settingsText.Replace($defaultVaultJson, $chosenVaultJson)
        Set-Utf8NoBom -Path $SettingsPath -Content $settingsText
    }
    Write-Host "Second Brain active, vault: $VaultPath" -ForegroundColor Green
} else {
    $mcp.mcpServers.PSObject.Properties.Remove('shared-memory')
    Write-Host "Second Brain skipped - MCP entry 'shared-memory' removed." -ForegroundColor Yellow
}
Write-Host ""

# --- 4. UFO2 (Windows GUI automation) --------------------------------------
if ($SkipUfo) {
    $wantUfo = $false
} elseif ($PSBoundParameters.ContainsKey('UfoRoot')) {
    $wantUfo = $true
} else {
    $wantUfo = Read-YesNo -Prompt "Set up UFO2 (Windows GUI automation)?"
}

if ($wantUfo) {
    if (-not $UfoRoot) {
        $UfoRoot = Read-Host "Path to an existing UFO2 installation (e.g. C:\UFO; empty = add manually later)"
    }
    if ([string]::IsNullOrWhiteSpace($UfoRoot)) {
        Write-Host "UFO2 not yet present. Source: https://github.com/microsoft/UFO" -ForegroundColor Yellow
        Write-Host "Afterwards, set UFO_ROOT and run this script again with -UfoRoot <path>."
        $mcp.mcpServers.PSObject.Properties.Remove('ufo')
    } else {
        $ufoPython = Join-Path $UfoRoot '.venv\Scripts\python.exe'
        if (-not (Test-Path $ufoPython)) {
            Write-Warning "No venv Python found under $ufoPython - path set in .mcp.json anyway, check before use."
        }
        [Environment]::SetEnvironmentVariable('UFO_ROOT', $UfoRoot, 'User')
        $mcp.mcpServers.ufo.command = $ufoPython
        $mcp.mcpServers.ufo.args = @((Join-Path $RepoRoot 'adapters\ufo\ufo_mcp.py'))
        $mcp.mcpServers.ufo.env.UFO_ROOT = $UfoRoot
        Write-Host "UFO2 active, root: $UfoRoot" -ForegroundColor Green
    }
} else {
    $mcp.mcpServers.PSObject.Properties.Remove('ufo')
    Write-Host "UFO2 skipped - MCP entry 'ufo' removed." -ForegroundColor Yellow
}
Write-Host ""

# --- 5. Playwright (browser automation) ------------------------------------
$wantPlaywright = $InstallPlaywright
if ($null -eq $wantPlaywright) {
    $wantPlaywright = Read-YesNo -Prompt "Install Playwright (browser automation)? Downloads Chromium."
}

if ($wantPlaywright) {
    $pwDir = Join-Path $RepoRoot 'adapters\playwright'
    Write-Host "Installing Playwright in $pwDir ..."
    Push-Location $pwDir
    try {
        npm install
        npx playwright install chromium
    } finally {
        Pop-Location
    }
    $mcp.mcpServers.playwright.args = @(
        (Join-Path $RepoRoot 'adapters\playwright\node_modules\@playwright\mcp\cli.js'),
        '--user-data-dir', (Join-Path $RepoRoot 'state\browser-profiles\mcp'),
        '--output-dir', (Join-Path $RepoRoot 'logs\playwright-mcp'),
        '--browser', 'chromium',
        '--block-service-workers',
        '--console-level', 'warning'
    )
    Write-Host "Playwright installed." -ForegroundColor Green
} else {
    $mcp.mcpServers.PSObject.Properties.Remove('playwright')
    Write-Host "Playwright skipped - MCP entry 'playwright' removed. adapters/playwright/pwctl.mjs" -ForegroundColor Yellow
    Write-Host "still works standalone once 'npm install' has been run there manually." -ForegroundColor Yellow
}
Write-Host ""

Set-Utf8NoBom -Path $McpPath -Content ($mcp | ConvertTo-Json -Depth 20)
Write-Host "mcp.json written." -ForegroundColor Green
Write-Host ""

# --- 6. Codex integration: pure hint, no file access -----------------------
if (-not $SkipCodexHint) {
    $wantCodex = Read-YesNo -Prompt "Connect Codex as a second model (official plugin)?"
    if ($wantCodex) {
        Write-Host "In Claude Code, in this project directory:" -ForegroundColor Cyan
        Write-Host "  1. /plugin marketplace add openai/codex   (or check the current marketplace name)"
        Write-Host "  2. /plugin install codex@openai-codex"
        Write-Host "  3. /codex:setup   -> confirms 'authMethod: chatgpt', sets no API key"
    }
}
Write-Host ""

# --- 7. Summary --------------------------------------------------------------
Write-Host "=== Done ===" -ForegroundColor Cyan
Write-Host "Open a new shell/session so the user environment variables take effect, then:"
Write-Host "  python bin\agentctl.py status"
Write-Host "  python tests\run-all.py"
Write-Host ""
Write-Host "Open Claude Code or Codex with '$RepoRoot' as the project directory."
