<#
.SYNOPSIS
    Interaktives Setup fuer AgentSystem: passt feste Pfade an den tatsaechlichen
    Klon-Ort an und fragt optionale Komponenten ab (Second Brain/Obsidian,
    UFO2, Playwright, Codex-Anbindung).

.DESCRIPTION
    Nichts davon ist Pflicht, um das Repo zu nutzen - wer alle Fragen mit
    Nein/Enter beantwortet, bekommt ein lauffaehiges System ohne die
    optionalen Komponenten. Das Skript schreibt nur Dateien innerhalb dieses
    Repos (.claude/settings.json, .mcp.json) und, wo sinnvoll, dauerhafte
    User-Umgebungsvariablen. Es installiert keine Software ohne Rueckfrage,
    ausser du bestaetigst den jeweiligen Schritt.

.EXAMPLE
    .\setup.ps1
    Interaktiv, mit Rueckfragen.

.EXAMPLE
    .\setup.ps1 -VaultPath 'D:\Notizen\Vault' -InstallPlaywright:$true -SkipUfo -SkipCodexHint
    Nicht-interaktiv fuer Skripte/CI.
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
    $suffix = if ($Default -eq 'j') { '[J/n]' } else { '[j/N]' }
    $answer = Read-Host "$Prompt $suffix"
    if ([string]::IsNullOrWhiteSpace($answer)) { $answer = $Default }
    return $answer -match '^[jJyY]'
}

function Set-Utf8NoBom {
    # Set-Content -Encoding utf8 schreibt unter PowerShell 5.1 immer eine BOM.
    # Claude Codes settings.json/.mcp.json werden von strikten JSON-Parsern
    # gelesen, die eine BOM ablehnen (z.B. Pythons json-Modul) - deshalb hier
    # bewusst ohne BOM schreiben.
    param([string]$Path, [string]$Content)
    $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [System.IO.File]::WriteAllText($Path, $Content, $utf8NoBom)
}

Write-Host "=== AgentSystem Setup ===" -ForegroundColor Cyan
Write-Host "Repo-Wurzel: $RepoRoot"
Write-Host ""

if (-not (Test-Path $SettingsPath) -or -not (Test-Path $McpPath)) {
    throw "Erwartete Dateien fehlen ($SettingsPath / $McpPath). Skript muss aus der Repo-Wurzel laufen."
}

# --- 1. AGENTSYSTEM_ROOT auf den tatsaechlichen Klon-Ort setzen -----------
[Environment]::SetEnvironmentVariable('AGENTSYSTEM_ROOT', $RepoRoot, 'User')
$env:AGENTSYSTEM_ROOT = $RepoRoot
Write-Host "AGENTSYSTEM_ROOT (User-Umgebungsvariable) -> $RepoRoot" -ForegroundColor Green

# settings.json: nur bekannte literale Pfadformen ersetzen, keine
# strukturelle JSON-Umformung - das haelt Hooks/Permissions unangetastet.
# Ein Backslash im Repo-Pfad wird zu zwei Backslashes im JSON-Text (\\ kodiert
# ein \). Vorsicht: -replace nimmt links ein Regex-, rechts ein Literalmuster.
$settingsText = Get-Content $SettingsPath -Raw -Encoding utf8
$forwardOld = 'C:/AgentSystem'
$forwardNew = ($RepoRoot -replace '\\', '/')
$backslashOld = 'C:\\AgentSystem'
$backslashNew = ($RepoRoot -replace '\\', '\\')
$settingsText = $settingsText.Replace($forwardOld, $forwardNew).Replace($backslashOld, $backslashNew)

# DENY-/ALLOW-Regeln, die als Vorlage auf einen Platzhalter-Benutzernamen
# zeigen (Credential-Dateien, Standard-Vault-Pfad), an den tatsaechlich
# installierenden Benutzer anpassen - sonst schuetzen die DENY-Regeln das
# falsche Profil.
$settingsText = $settingsText.Replace('C:\\Users\\YOURUSERNAME\\', "C:\\Users\\$env:USERNAME\\")

Set-Utf8NoBom -Path $SettingsPath -Content $settingsText
Write-Host "settings.json: Hook-Pfade und AGENTSYSTEM_ROOT angepasst." -ForegroundColor Green
Write-Host ""

# --- 2. .mcp.json strukturiert laden ---------------------------------------
$mcp = Get-Content $McpPath -Raw -Encoding utf8 | ConvertFrom-Json

# --- 3. Second Brain / Obsidian --------------------------------------------
if ($SkipVault) {
    $wantVault = $false
} elseif ($PSBoundParameters.ContainsKey('VaultPath')) {
    $wantVault = $true
} else {
    $wantVault = Read-YesNo -Prompt "Second Brain (lernender, quellenbelegter Wissensspeicher in Obsidian) einrichten?"
}

if ($wantVault) {
    if (-not $VaultPath) {
        $VaultPath = Read-Host "Pfad zu einem bestehenden Obsidian-Vault (leer = neuen Vault neben dem Repo anlegen)"
    }
    if ([string]::IsNullOrWhiteSpace($VaultPath)) {
        $VaultPath = Join-Path (Split-Path $RepoRoot -Parent) 'AgentSystem-Vault'
        foreach ($sub in '01 Inbox', '03 Bereiche', '04 Ressourcen', '05 Daily Notes') {
            New-Item -ItemType Directory -Force -Path (Join-Path $VaultPath $sub) | Out-Null
        }
        Write-Host "Neuer Vault angelegt: $VaultPath" -ForegroundColor Green
    } elseif (-not (Test-Path $VaultPath)) {
        Write-Warning "Pfad existiert nicht: $VaultPath - bitte vor der ersten Nutzung anlegen."
    }
    [Environment]::SetEnvironmentVariable('AGENTSYSTEM_VAULT', $VaultPath, 'User')
    $mcp.mcpServers.'shared-memory'.env.AGENTSYSTEM_VAULT = $VaultPath
    $mcp.mcpServers.'shared-memory'.env | Add-Member -NotePropertyName AGENTSYSTEM_ROOT -NotePropertyValue $RepoRoot -Force
    $mcp.mcpServers.'shared-memory'.args = @((Join-Path $RepoRoot 'adapters\memory\memory_mcp.py'))

    # Read-ALLOW-Regel fuer den Vault in settings.json auf den tatsaechlich
    # gewaehlten Pfad ziehen, falls er vom Standard abweicht.
    $defaultVault = "C:\Users\$env:USERNAME\Documents\Obsidian Vault"
    if ((Resolve-Path -LiteralPath $VaultPath -ErrorAction SilentlyContinue).Path -ne
        (Resolve-Path -LiteralPath $defaultVault -ErrorAction SilentlyContinue).Path) {
        $settingsText = Get-Content $SettingsPath -Raw -Encoding utf8
        $defaultVaultJson = ($defaultVault -replace '\\', '\\')
        $chosenVaultJson = ($VaultPath -replace '\\', '\\')
        $settingsText = $settingsText.Replace($defaultVaultJson, $chosenVaultJson)
        Set-Utf8NoBom -Path $SettingsPath -Content $settingsText
    }
    Write-Host "Second Brain aktiv, Vault: $VaultPath" -ForegroundColor Green
} else {
    $mcp.mcpServers.PSObject.Properties.Remove('shared-memory')
    Write-Host "Second Brain uebersprungen - MCP-Eintrag 'shared-memory' entfernt." -ForegroundColor Yellow
}
Write-Host ""

# --- 4. UFO2 (Windows-GUI-Automatisierung) ---------------------------------
if ($SkipUfo) {
    $wantUfo = $false
} elseif ($PSBoundParameters.ContainsKey('UfoRoot')) {
    $wantUfo = $true
} else {
    $wantUfo = Read-YesNo -Prompt "UFO2 (Windows-GUI-Automatisierung) einrichten?"
}

if ($wantUfo) {
    if (-not $UfoRoot) {
        $UfoRoot = Read-Host "Pfad zu einer bestehenden UFO2-Installation (z.B. C:\UFO; leer = spaeter manuell nachtragen)"
    }
    if ([string]::IsNullOrWhiteSpace($UfoRoot)) {
        Write-Host "UFO2 noch nicht vorhanden. Quelle: https://github.com/microsoft/UFO" -ForegroundColor Yellow
        Write-Host "Danach UFO_ROOT setzen und dieses Skript erneut mit -UfoRoot <pfad> ausfuehren."
        $mcp.mcpServers.PSObject.Properties.Remove('ufo')
    } else {
        $ufoPython = Join-Path $UfoRoot '.venv\Scripts\python.exe'
        if (-not (Test-Path $ufoPython)) {
            Write-Warning "Kein venv-Python unter $ufoPython gefunden - Pfad in .mcp.json trotzdem gesetzt, vor Nutzung pruefen."
        }
        [Environment]::SetEnvironmentVariable('UFO_ROOT', $UfoRoot, 'User')
        $mcp.mcpServers.ufo.command = $ufoPython
        $mcp.mcpServers.ufo.args = @((Join-Path $RepoRoot 'adapters\ufo\ufo_mcp.py'))
        $mcp.mcpServers.ufo.env.UFO_ROOT = $UfoRoot
        Write-Host "UFO2 aktiv, Wurzel: $UfoRoot" -ForegroundColor Green
    }
} else {
    $mcp.mcpServers.PSObject.Properties.Remove('ufo')
    Write-Host "UFO2 uebersprungen - MCP-Eintrag 'ufo' entfernt." -ForegroundColor Yellow
}
Write-Host ""

# --- 5. Playwright (Browser-Automatisierung) -------------------------------
$wantPlaywright = $InstallPlaywright
if ($null -eq $wantPlaywright) {
    $wantPlaywright = Read-YesNo -Prompt "Playwright (Browser-Automatisierung) installieren? Laedt Chromium herunter."
}

if ($wantPlaywright) {
    $pwDir = Join-Path $RepoRoot 'adapters\playwright'
    Write-Host "Installiere Playwright in $pwDir ..."
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
    Write-Host "Playwright installiert." -ForegroundColor Green
} else {
    $mcp.mcpServers.PSObject.Properties.Remove('playwright')
    Write-Host "Playwright uebersprungen - MCP-Eintrag 'playwright' entfernt. adapters/playwright/pwctl.mjs" -ForegroundColor Yellow
    Write-Host "funktioniert trotzdem eigenstaendig, sobald 'npm install' dort manuell lief." -ForegroundColor Yellow
}
Write-Host ""

Set-Utf8NoBom -Path $McpPath -Content ($mcp | ConvertTo-Json -Depth 20)
Write-Host "mcp.json geschrieben." -ForegroundColor Green
Write-Host ""

# --- 6. Codex-Anbindung: reiner Hinweis, kein Dateizugriff -----------------
if (-not $SkipCodexHint) {
    $wantCodex = Read-YesNo -Prompt "Codex als zweites Modell anbinden (offizielles Plugin)?"
    if ($wantCodex) {
        Write-Host "In Claude Code, in diesem Projektverzeichnis:" -ForegroundColor Cyan
        Write-Host "  1. /plugin marketplace add openai/codex   (oder aktuellen Marketplace-Namen pruefen)"
        Write-Host "  2. /plugin install codex@openai-codex"
        Write-Host "  3. /codex:setup   -> bestaetigt 'authMethod: chatgpt', setzt keinen API-Key"
    }
}
Write-Host ""

# --- 7. Zusammenfassung ------------------------------------------------------
Write-Host "=== Fertig ===" -ForegroundColor Cyan
Write-Host "Neue Shell/Session oeffnen, damit die User-Umgebungsvariablen greifen, dann:"
Write-Host "  python bin\agentctl.py status"
Write-Host "  python tests\run-all.py"
Write-Host ""
Write-Host "Claude Code oder Codex mit '$RepoRoot' als Projektverzeichnis oeffnen."
