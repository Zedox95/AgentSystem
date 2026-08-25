---
name: ufo-windows
description: Bedient die Windows-Oberfläche über UFO² per Kommandozeile - Fenster auflisten, Steuerelemente auslesen, klicken, Text eingeben, Tasten senden, scrollen, Schrittfolgen ausführen - und verifiziert jede Aktion unabhängig über die UI-Automation-Schnittstelle. Einsetzen, wenn eine Windows-Aufgabe tatsächlich eine grafische Oberfläche erfordert und keine API, kein Cmdlet und keine CLI sie zuverlässiger löst.
allowed-tools: Bash(C:\UFO\.venv\Scripts\python.exe C:\AgentSystem\adapters\ufo\ufoctl.py *), Read, Grep, Glob
---

# Windows-GUI über UFO²

Claude ist das Gehirn, UFO² nur die Hand. UFOs eigene Agentenschleife wird
nicht benutzt — sie braucht ein Sprachmodell, das dieses System bewusst nicht
vorhält.

## CLI oder MCP?

Beide Wege existieren nebeneinander und lösen verschiedene Aufgaben.

**`ufoctl` (dieser Skill) — der Normalfall.** Für bekannte, wiederholbare
Abläufe. Jeder Aufruf ist in sich geschlossen, deterministisch skriptbar,
einzeln verifizierbar, mit kleiner Kontextausgabe und ohne laufenden Prozess.

**MCP-Server `ufo` — für exploratives Arbeiten.** Wenn du dich erst durch eine
unbekannte Anwendung tasten musst, hält der Server den Fensterzustand über
viele Schritte hinweg, statt ihn bei jedem Aufruf neu aufzubauen. Werkzeuge:
`mcp__ufo__ui_*` zum Lesen, `mcp__ufo__host_select_application_window` zum
Aktivieren, `mcp__ufo__app_*` zum Handeln.

Faustregel: **Erkunden über MCP, wiederholen über die CLI.** Was du im MCP-Modus
herausgefunden hast, gehört anschliessend als `plan`-Datei oder Skript in die
CLI — dann ist es reproduzierbar.

Auch im MCP-Modus gilt: **verifiziert wird mit `ufoctl inspect`**, nie mit UFOs
eigener Steuerelementliste.

## Zuerst: Ist die GUI wirklich nötig?

Prüfe in dieser Reihenfolge, bevor du UFO anfasst: CIM/WMI → PowerShell-Cmdlet
→ COM → Registry oder Konfigurationsdatei. Eine GUI-Aktion ist langsamer,
brüchiger und schlechter verifizierbar als jede dieser Ebenen.

UFO ist **keine** Abkürzung um Rechte, Dateisystem oder eine fehlende API.

## Aufruf

```bash
C:\UFO\.venv\Scripts\python.exe C:\AgentSystem\adapters\ufo\ufoctl.py windows
```

Jeder Aufruf ist in sich geschlossen: Fenster auflösen, auswählen, handeln,
zurücklesen. UFOs Fensterauswahl lebt nur im Prozess — eine Auswahl aus einem
früheren Aufruf existiert nicht.

## Ablauf

**1. Fenster finden.**

```bash
… ufoctl.py windows
```

**2. Steuerelemente auslesen — immer vor jeder Aktion.**

```bash
… ufoctl.py controls --window "Einstellungen" --type Edit
… ufoctl.py controls --window "Editor" --contains "Speichern"
```

Das liefert je Element `label`, `control_text` und `control_type`. Das `label`
ist die Kennung, mit der du handelst. Ohne diesen Schritt kennt UFO die
Elemente nicht und jede Aktion scheitert.

**3. Handeln — über das Label, nicht über Koordinaten.**

```bash
… ufoctl.py click  --window "Editor" --control 12
… ufoctl.py type   --window "Editor" --control 6 --text "Inhalt"
… ufoctl.py keys   --window "Editor" --control 6 --keys "^s"
… ufoctl.py scroll --window "Editor" --control 8 --dist -5
```

`--control` akzeptiert das Label oder einen eindeutigen Textausschnitt. Ist der
Ausschnitt mehrdeutig, meldet die CLI alle Treffer, statt zu raten.

**4. Unabhängig verifizieren — der wichtigste Schritt.**

```bash
… ufoctl.py inspect --window "Einstellungen" --type Edit --expect "erwarteter Text"
```

`inspect` geht **an UFO vorbei** direkt über pywinauto an die
UI-Automation-Schnittstelle und liefert `value` und `window_text` des lebenden
Steuerelements.

**Das ist zwingend.** UFOs eigene Steuerelementliste meldet bei Eingabefeldern
den Accessible Name statt des tatsächlichen Inhalts und kann veraltete Werte
liefern. Eine Aktion mit UFOs eigener Liste zu bestätigen wäre der Executor,
der sich selbst beurteilt. Siehe `docs/known-issues.md`.

## Schrittfolgen

Für wiederkehrende Abläufe eine Plandatei statt vieler Einzelaufrufe — ein
Fensterkontext, eine Ausführung:

```json
{
  "window": "Editor",
  "steps": [
    {"action": "type",  "control": "Text-Editor", "text": "Inhalt"},
    {"action": "keys",  "control": "Text-Editor", "keys": "^s"},
    {"action": "wait",  "seconds": 1},
    {"action": "read",  "control": "Text-Editor"}
  ]
}
```

```bash
… ufoctl.py plan --file plan.json
```

Der Plan bricht beim ersten Fehlschlag ab und meldet, welche Schritte bereits
liefen. Ein halb ausgeführter Plan gilt **nie** als Erfolg — prüfe danach den
tatsächlichen Zustand und entscheide über Fortsetzung oder Rollback.

## Risiko

GUI-Aktionen sind mindestens **R1**. Sobald sie Konfiguration, Dateien oder
Systemeinstellungen ändern, sind sie **R2** — dann zuerst `preflight-change`
mit Baseline und Backup.

Koordinatenbasierte Aktionen (`app_click_on_coordinates`,
`app_drag_on_coordinates`) sind absichtlich nicht als CLI-Befehl exponiert.
Sie sind nicht reproduzierbar und brechen bei jeder Layoutänderung.

## Fallstricke

- **Immer erst `controls`, dann handeln.** Sonst: „No application windows
  available."
- **Fenster mehrdeutig?** Die CLI nennt alle Treffer — nimm die ID.
- **Leere Steuerelementliste?** Die CLI wartet und wiederholt begrenzt; das ist
  ein bekanntes Rennen nach dem Fensterwechsel, keine blinde Wiederholung.
- **Nie mit `controls` verifizieren, immer mit `inspect`.**
- Das Auswählen eines Fensters bringt es in den Vordergrund. Auf einem
  benutzten Rechner ist das sichtbar — plane GUI-Arbeit entsprechend.

## Erfahrung verbuchen

```bash
python C:\AgentSystem\bin\agentctl.py exp record --key windows.gui.<aufgabe> --method "ufoctl:<befehl>" --success --duration <ms> --agent windows-agent
```
