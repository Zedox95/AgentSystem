---
name: windows-admin
description: Wählt für eine Windows-Aufgabe den zuverlässigsten Weg - native API und CIM, PowerShell, COM, UFO² UI Automation oder als letzter Ausweg visuelles Computer Use - und kennt die Besonderheiten dieses Rechners wie PowerShell 5.1 ohne pwsh und die fehlende Elevation. Einsetzen für Systemdiagnose, Treiber, Dienste, Registry, Windows-Einstellungen und GUI-Automatisierung auf diesem PC.
allowed-tools: Bash(python C:\AgentSystem\bin\agentctl.py *), Read, Grep, Glob
---

# Windows-Aufgaben richtig routen

## Umgebung dieses Rechners

Diese Punkte sind gemessen, nicht angenommen:

- Windows 11 Pro 25H2, Build **26200**. Die Registry meldet `ProductName =
  "Windows 10 Pro"` — bekanntes stale-Key-Artefakt. Der Build entscheidet.
- `powershell.exe` ist **Windows PowerShell 5.1**. **Kein `pwsh` im PATH.**
  Dort fehlen: `Test-Json`, `&&`, `||`, `??`, `?.`, `?:`, `-AsHashtable`.
- Die Session läuft **ohne** Administratorrechte.
- Git-Bash steht über das Bash-Tool zur Verfügung, PowerShell über das
  PowerShell-Tool. Beide haben eigene Syntax — nicht vermischen.

## Methodenwahl

Prüfe zuerst die Erfahrung:

```bash
python C:\AgentSystem\bin\agentctl.py exp best --key windows.<aufgabenart>
```

Ohne passenden Eintrag gilt diese Reihenfolge — als Präferenz, nicht als
Zwang:

**1. CIM/WMI und native API.** Strukturiert, maschinenlesbar, verifizierbar.
`Get-CimInstance Win32_PnPSignedDriver`, `Win32_Service`, `Win32_LogicalDisk`.

**2. PowerShell-Cmdlets.** `Get-Service`, `Get-PnpDevice`, `Get-WinEvent`,
`Get-NetAdapter`. Literale Pfade, keine Rateversuche.

**3. COM.** Wenn eine Anwendung ein Automationsmodell hat (Office, Explorer),
ist es zuverlässiger als jede GUI-Bedienung.

**4. UFO² UI Automation** über `adapters/ufo/`. Nur wenn die Aufgabe
tatsächlich eine GUI erfordert und keine der obigen Ebenen sie abdeckt.

**5. Visuelle Erkennung.** Nur wenn UI Automation die Steuerelemente nicht
findet.

**6. Rohe Koordinaten.** Letzter Ausweg. Nicht reproduzierbar, bricht bei
jeder Auflösungs- oder Layoutänderung.

**UFO² ist keine Abkürzung.** Es ist nicht dazu da, Dateisystem, Rechte oder
eine fehlende API zu umgehen. Wenn du erwägst, per GUI zu tun, was ein Cmdlet
kann, ist das die falsche Wahl.

## Elevation

Admin-pflichtig sind unter anderem: Dienständerungen, HKLM-Schreibzugriffe,
Treiberinstallation, Firewall-Regeln, geplante Aufgaben im System-Kontext.

Der Weg ist ein **sichtbarer UAC-Prompt pro Aktion**:
`Start-Process powershell -Verb RunAs -ArgumentList ...`

Kein dauerhaft erhöhter Agentenprozess, keine vorbereitete erhöhte Scheduled
Task für allgemeine Zwecke. Der Benutzer bestätigt jede einzelne Aktion.
Der Policy Guard eskaliert `-Verb RunAs` ohnehin zur Rückfrage.

## Risiko

| Aufgabe | Klasse |
|---|---|
| Inventar, Versionen, Logs lesen, Diagnose | R0 |
| Dienst neu starten, reversible Einstellung | R1 |
| Treiber, Registry-Schreibzugriff, Firewall, Paketentfernung, Netzwerk | R2 |
| Bootloader, BIOS/Firmware, Partitionen, Benutzerkonten, Datenträger | R3 |

Ab R2 zuerst `preflight-change`, danach `verify-change`.

## Verifikation

Immer den realen Zustand erneut auslesen — nicht die Ausgabe des ändernden
Kommandos wiederverwenden. Dazu gehört das Event Log: prüfe auf **neue**
Einträge seit dem Änderungszeitpunkt, nicht auf das Fehlen von Fehlern
überhaupt.

```powershell
Get-WinEvent -FilterHashtable @{ LogName='System'; Level=1,2; StartTime=$zeitpunkt }
```

## Häufige Fallstricke auf diesem Rechner

- `Test-Json` existiert unter 5.1 nicht — Schemaprüfung anders lösen
- `2>&1` bei nativen Programmen erzeugt in 5.1 ErrorRecords und setzt `$?`
  auf `$false`, obwohl das Programm mit 0 endete
- `Set-Content` schreibt ohne `-Encoding utf8` in der ANSI-Codepage
- `New-Item -Force` auf eine bestehende Datei **leert** sie
- `-ErrorAction SilentlyContinue` unterdrückt die Ausgabe, nicht den Exit-Code
- Deutsche Locale-Ausgaben (`tasklist`, `netstat`) sind nicht immer als cp1252
  dekodierbar — beim Weiterverarbeiten in Python `errors="replace"` setzen
