# Installation auf einem weiteren Rechner

Jede Person verwendet ihre eigenen Anmeldungen, Abonnements und ihren eigenen Obsidian-Vault. Persönliche Notizen, Zugangsdaten und der Ordner state/ werden nicht vom ursprünglichen Rechner übernommen.

## Vorbereitung

- Python 3.11 oder neuer und Git installieren.
- Für Codex beziehungsweise Claude Code den gewünschten Client installieren und mit dem eigenen Konto anmelden.
- Obsidian installieren und einen eigenen Vault auswählen oder bei der Einrichtung neu anlegen lassen.
- Node.js wird nur für die optionale Browserautomatisierung benötigt.

## Einrichtung

```powershell
git clone https://github.com/Zedox95/AgentSystem.git
cd AgentSystem
.\setup.ps1
```

Falls die lokale PowerShell-Richtlinie das Skript nicht ausführen lässt, kann der gleiche Einrichtungsweg direkt über Python gestartet werden:

```powershell
python bin/setup_agent.py install --vault "C:/Users/DEINNAME/Documents/Obsidian Vault"
```

Die Einrichtung konfiguriert dieses Projekt. Sie ändert keine globalen Vollzugriffsmodi und kopiert keine fremden Konten. Bestehende fremde Einstellungen bleiben erhalten; bei Konflikten wird abgebrochen.

Diesen Ordner als vertrauenswürdiges Projekt in Codex oder Claude Code öffnen. In Codex die neuen Hooks über /hooks ansehen und freigeben. Eine vorhandene Hook-Datei allein beweist noch nicht, dass der Client sie ausführt.

## Prüfung

```powershell
python bin/setup_agent.py doctor
python tests/run-all.py
```

doctor prüft Konfiguration, Dateistände und Erreichbarkeit des Vault-Verzeichnisses. Die Tests verwenden einen isolierten Test-Vault. Anschließend im gewünschten Client eine bekannte verwaltete Information suchen und eine harmlose Testinformation über den kontrollierten Speicherweg schreiben und wieder lesen.

## ChatGPT

templates/chatgpt-core.md in die verfügbaren benutzerdefinierten Anweisungen übernehmen. Für Obsidian ist eine zusätzliche unterstützte Plugin-/MCP-Verbindung nötig; die lokale Einrichtung meldet sich nicht automatisch in ChatGPT an. Details: chatgpt-setup.md.

Vorhandene Erinnerungen als Text/JSON bereitstellen und zuerst prüfen:

`python bin/assistantctl.py import-memory --file erinnerungen.json`

Mit --stage werden die Vorschläge vorgemerkt. Sie werden nicht automatisch zu bestätigten aktuellen Fakten. Der vollständige interne ChatGPT-Erinnerungsspeicher ist damit nicht automatisch exportiert.

## Tägliche Nutzung

Eine zusammenhängende Aufgabe pro Sitzung. Rückfragen bleiben darin; ein unabhängiges Thema beginnt in einer neuen Sitzung. Der eigene Obsidian-Vault liefert das gemeinsame relevante Wissen. Subagents werden gezielt eingesetzt; objektive Prüfungen und unabhängige Kontrolle richten sich nach den Risikoregeln.

## Rückweg

Die Einrichtung nennt einen privaten Backup-Pfad. Rücknahme:

`python bin/setup_agent.py rollback --backup "<angezeigter Manifest-Pfad>"`

Nachträglich geänderte Dateien werden nicht still überschrieben. Vorhandene Notizen und neu angelegte Vault-Verzeichnisse werden nicht gelöscht.
