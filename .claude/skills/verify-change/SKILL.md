---
name: verify-change
description: Prüft objektiv, ob eine durchgeführte Änderung wirklich gewirkt hat - wählt die passende messbare Verifikationsmethode für Windows, Linux, Browser, Proxmox oder Pterodactyl, führt sie aus und übergibt danach an den read-only verification-agent. Nach jeder Änderung ab R1 einsetzen, bevor Erfolg gemeldet wird.
allowed-tools: Bash(python C:\AgentSystem\bin\agentctl.py *), Read, Grep, Glob
---

# Verifikation einer Änderung

Ein erfolgreicher Exit-Code ist kein Nachweis. Verifikation heißt: den realen
Zustand erneut auslesen und gegen die vorher festgeschriebenen Acceptance
Criteria halten.

## Reihenfolge

1. **Objective Test** — messbar, ohne Modellbeteiligung
2. **Negativprüfung** — was könnte kaputtgegangen sein?
3. **Unabhängige Verifikation** — `verification-agent`, read-only
4. **Knowledge Review** — `$knowledge-review` ausführen und dokumentieren
5. Erst dann `COMMITTED`

Die Acceptance Criteria dürfen dabei **nicht** angepasst werden. Passt das
Ergebnis nicht zum Kriterium, ist das Ergebnis falsch, nicht das Kriterium.

## Objective Tests nach Domäne

**Windows**
Dienststatus erneut lesen (`Get-Service`), Registry-Wert erneut lesen,
Treiberversion und Gerätecode (`Get-PnpDevice`, `Get-CimInstance
Win32_PnPSignedDriver`), Event Log auf **neue** Einträge seit dem
Änderungszeitpunkt, Datei-Diff oder Hash-Vergleich.

**Linux**
`systemctl is-active` und `is-enabled`, laufende Prozesse, offene Ports,
Konfigurationssyntax (`nginx -t`, `sshd -t`), Paketversion, `journalctl` seit
dem Zeitpunkt der Änderung.

**Browser**
DOM- oder Accessibility-Zustand, HTTP-Statuscode und Antwortkörper. Wo möglich
gegen die API prüfen statt gegen die Oberfläche — eine grüne Meldung in einer
WebUI ist der schwächste denkbare Nachweis.

**Proxmox**
API-Status der VM, zugewiesene Ressourcen, Bootverhalten, Netzwerk, Snapshot-
Liste.

**Pterodactyl**
Serverobjekt vorhanden, Node und Allocation korrekt, Wings erreichbar,
Container läuft, Ports offen, Limits gesetzt, Startup-Log ohne kritische
Fehler — und der Gameserver antwortet tatsächlich.

## Negativprüfung

Frage aktiv: Was könnte diese Änderung kaputt gemacht haben, das niemand
getestet hat? Abhängige Dienste, Autostart-Verhalten, Verhalten nach Neustart,
Rechte, Netzwerkerreichbarkeit von außen, Konfigurationsvorrang zwischen
mehreren Dateien.

Mindestens eine Negativprüfung gehört zu jeder R2-Verifikation.

## Unabhängige Verifikation

Beauftrage den `verification-agent` und gib ihm: ursprüngliches Ziel, Task
Contract, Acceptance Criteria, Vorher-Zustand, Nachher-Zustand, rohe Evidenz.

Gib ihm **nicht** deine Einschätzung mit und formuliere die Aufgabe nicht so,
dass die gewünschte Antwort nahegelegt wird.

Sein Ergebnis ist `PASS`, `FAIL` oder `INCONCLUSIVE`. Bei `FAIL` oder
`INCONCLUSIVE` wird **kein** Erfolg gemeldet; die Aufgabe geht an einen
Executor zurück.

## Abschluss

```bash
python C:\AgentSystem\bin\agentctl.py task state --task-id <id> --state OBJECTIVE_TEST
python C:\AgentSystem\bin\agentctl.py task state --task-id <id> --state INDEPENDENT_VERIFY
python C:\AgentSystem\bin\agentctl.py run finish --run-id <run> --outcome PASS --change "<tatsächliche Änderung>" --tests "<was gemessen wurde>" --verification "PASS: <Verifier und Evidenz>"
python C:\AgentSystem\bin\agentctl.py knowledge review --task-id <id> --decision <none|captured|deferred> --reason "<Ergebnis der Wissensprüfung>"
python C:\AgentSystem\bin\agentctl.py task readiness --task-id <id>
python C:\AgentSystem\bin\agentctl.py task state --task-id <id> --state COMMITTED
python C:\AgentSystem\bin\agentctl.py lock release --resource "<lock-id>" --token <token>
```

Bei bestätigtem Erfolg darf die verwendete Methode als Erfahrung verbucht und
— nach `PASS` — auf `VERIFIED` gehoben werden:

```bash
python C:\AgentSystem\bin\agentctl.py exp record --key <aufgabenart> --method <methode> --success --duration <ms> --agent <agent>
python C:\AgentSystem\bin\agentctl.py exp promote --key <aufgabenart> --method <methode> --revalidate-when "<wann neu prüfen>"
```

## Ergebnis

Melde: welche Objective Tests liefen mit welcher rohen Ausgabe, welche
Negativprüfung erfolgte, das Urteil des Verifiers, und den Ledger-Zustand.
