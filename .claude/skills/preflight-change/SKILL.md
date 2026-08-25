---
name: preflight-change
description: Bereitet eine Systemänderung kontrolliert vor - Ziel und Zielressource klären, Ist-Zustand erfassen, Risikoklasse R0-R3 bestimmen, Methode und Alternative wählen, Resource Lock setzen, Baseline und Backup anlegen, Acceptance Criteria und Rollback-Plan festschreiben. Vor jeder Änderung ab R1 einsetzen, bevor irgendetwas verändert wird.
allowed-tools: Bash(python C:\AgentSystem\bin\agentctl.py *), Read, Grep, Glob
---

# Preflight vor einer Änderung

Nichts wird verändert, bevor dieser Ablauf durch ist. Ergebnis ist ein Task
Contract im Ledger, ein gesetztes Lock und ein geprüfter Rückweg.

## 1. Ziel und Zielressource

Formuliere das **beobachtbare** Ergebnis, nicht die Tätigkeit.
Schlecht: „Treiber aktualisieren." Gut: „`Get-PnpDevice` meldet für die GPU
Status OK und Treiberversion ≥ X, Event Log ohne neue Fehler der Klasse Y."

Benenne die Zielressource so, wie sie später gesperrt wird:
`windows:driver:nvidia` · `proxmox:vm:103` · `pterodactyl:server:<id>` ·
`router:firewall` · `windows:network`

## 2. Ist-Zustand erfassen

Lies den realen Zustand aus, bevor du ihn beschreibst. Für Windows Dienst-,
Registry- oder Treiberzustand; für Linux `systemctl`, Ports, Paketversion; für
Proxmox und Pterodactyl den API-Zustand. Die rohe Ausgabe ist die Baseline.

## 3. Risikoklasse bestimmen

Nach AGENTS.md Abschnitt 5. Im Zweifel die höhere Klasse. **R3 braucht die
ausdrückliche Freigabe des Benutzers, bevor du weitermachst** — frage, statt
anzunehmen.

## 4. Methode und Alternative wählen

Prüfe zuerst die Erfahrung:

```bash
python C:\AgentSystem\bin\agentctl.py exp best --key <aufgabenart>
```

Gibt es eine `VERIFIED`-Methode mit passendem Environment, nimm sie. Sonst
wähle nach der Präferenz aus AGENTS.md Abschnitt 10 und begründe die Wahl.
Benenne **immer** eine Alternative — sie wird gebraucht, wenn die erste
Methode scheitert, und verhindert blinde Wiederholung.

## 5. Task Contract anlegen

```bash
python C:\AgentSystem\bin\agentctl.py task new --goal "<Ziel>" --risk R2 --resource "<lock-id>" --desired-state "<Sollzustand>" --method "<Methode>" --alternative "<Alternative>" --acceptance "<messbare Kriterien>" --rollback "<Rückweg>"
```

Der Befehl endet mit Exit 1, wenn bei R2 oder R3 Acceptance Criteria oder
Rollback-Plan fehlen. Das ist kein Formfehler, sondern ein Stoppsignal.

## 6. Lock setzen

```bash
python C:\AgentSystem\bin\agentctl.py lock acquire --resource "<lock-id>" --agent <agent> --task-id <task-id>
```

Scheitert das Lock, arbeitet ein anderer Vorgang an derselben Ressource. Dann
**nicht** parallel weitermachen — warten oder den anderen Vorgang klären. Zeigt
`lock list` einen Halter mit `holder_alive: false`, ist das Lock verwaist und
darf freigegeben werden.

## 7. Baseline und Backup

Bei R1 genügt die notierte Ist-Ausgabe. Ab **R2** ist ein wiederherstellbares
Backup Pflicht:

- Dateien und Konfiguration: Kopie mit SHA256-Manifest unter
  `C:\AgentSystem-Backups\<datum>-<zweck>\`
- Registry: `reg export` des betroffenen Schlüssels
- Proxmox: Snapshot
- Pterodactyl: Backup über die API
- Savegames: vollständige Kopie, vorher Größe und Dateizahl prüfen

Ein Backup, dessen Wiederherstellung nicht geprüft wurde, ist kein Backup.
Prüfe mindestens, dass die Dateien existieren und die Hashes stimmen.

## 8. Zustand fortschreiben

```bash
python C:\AgentSystem\bin\agentctl.py task state --task-id <id> --state PREFLIGHT
python C:\AgentSystem\bin\agentctl.py task state --task-id <id> --state LOCKED
python C:\AgentSystem\bin\agentctl.py task state --task-id <id> --state BASELINED
python C:\AgentSystem\bin\agentctl.py task state --task-id <id> --state BACKED_UP
```

## Abbruchbedingungen

Brich ab und frage den Benutzer, wenn eines davon fehlt: Freigabe für R3, ein
funktionierendes Backup, ein exaktes Löschziel, ein benötigtes Zugangsdatum,
oder eine Entscheidung, die nur der Benutzer treffen kann.

## Ergebnis

Melde: Task-ID, Risikoklasse, Lock, Baseline-Ort, Backup-Ort, Acceptance
Criteria, Rollback-Plan, gewählte Methode und Alternative.
