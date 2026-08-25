---
name: update-agent-stack
description: Führt ein Update einer Systemkomponente kontrolliert durch - Changelog prüfen, Relevanz bewerten, Known-Good festhalten, Backup, isolierter Test, Smoke Tests, Regressionslauf, Verifikation, dann übernehmen oder bei der Known-Good-Version bleiben. Einsetzen für Updates an Claude Code, Codex, UFO², Playwright, Node, Python, MCP-Servern oder am Agentensystem selbst.
allowed-tools: Bash(python C:\AgentSystem\bin\agentctl.py *), Bash(python C:\AgentSystem\tests\*), Read, Grep, Glob
---

# Kontrolliertes Update

Kein blindes `latest`. Eine neue Version wird erst produktiv, wenn sie
nachweislich **nicht schlechter** ist.

## 1. Known-Good festhalten — vor allem anderen

```bash
python C:\AgentSystem\bin\agentctl.py env known-good --name pre-<komponente>-<datum>
```

Damit ist der Rückweg definiert, bevor irgendetwas verändert wird. Ohne diesen
Schritt gibt es später keinen Vergleichspunkt.

## 2. Changelog prüfen und Relevanz bewerten

Lies den tatsächlichen Changelog der Zielversion, nicht die Werbeaussage.
Frage konkret:

- Behebt das Update ein Problem, das wir tatsächlich haben?
- Gibt es Breaking Changes an Schnittstellen, die wir nutzen?
- Ändern sich Konfigurationsschemata, Hook-Namen, CLI-Flags oder API-Verträge?
- Sind gespeicherte `VERIFIED`-Erfahrungen betroffen?

Ein Update ohne erkennbaren Nutzen für uns ist kein Grund für ein Update.

```bash
python C:\AgentSystem\bin\agentctl.py exp stale
```

zeigt, welche Erfahrungen durch eine Umgebungsänderung fraglich werden.

## 3. Backup

Ab R2: vollständiger Restore-Point der betroffenen Konfiguration mit
SHA256-Manifest. Für `C:\AgentSystem` genügt ein sauberer Git-Stand — prüfe,
dass `git status` leer ist, bevor du beginnst.

## 4. Isoliert testen, wo möglich

Bevorzugt in einer Kopie, einer separaten venv, einem Worktree oder einer VM.
Nicht jede Komponente lässt das zu — wenn nicht, sag es deutlich und behandle
das Update entsprechend vorsichtiger.

## 5. Smoke Tests

Die Komponente startet, meldet die erwartete Version, und ihre Kernfunktion
läuft einmal durch. Für dieses System:

```bash
python C:\AgentSystem\bin\agentctl.py env show
python C:\AgentSystem\bin\agentctl.py status
```

## 6. Regressionslauf — Pflicht

```bash
python C:\AgentSystem\tests\run-all.py
```

Regression ist erforderlich nach jeder Änderung an: Skill, Agent-Prompt,
Adapter, Routing, Hook, Tool-Update, UFO-Update, Playwright-Update.

Bewertet wird nicht nur „grün", sondern der Vergleich: Erfolgsrate, Laufzeit,
Retries, Verification-Erfolg, Nebenwirkungen. Eine Version, die grün ist, aber
messbar langsamer oder retry-anfälliger, ist kein Fortschritt.

## 7. Entscheiden

| Ergebnis | Entscheidung |
|---|---|
| Regression grün, keine Verschlechterung | übernehmen, neues Known-Good schreiben |
| Regression grün, aber messbar schlechter | bei Known-Good bleiben, Befund dokumentieren |
| Regression rot | zurückrollen, Ursache über `diagnose-failure` klären |
| Breaking Change an genutzter Schnittstelle | erst Anpassung, dann erneute Regression |

Bei Übernahme:

```bash
python C:\AgentSystem\bin\agentctl.py env known-good --name <komponente>-<version>
```

## 8. Betroffene Erfahrungen nachziehen

Erfahrungen, deren `revalidate_when` durch das Update ausgelöst wurde, sind
**nicht mehr `VERIFIED`**. Entweder neu bestätigen oder auf `DEPRECATED`
setzen — stillschweigend weiterverwenden ist nicht zulässig.

```bash
python C:\AgentSystem\bin\agentctl.py exp deprecate --key <k> --method <m> --reason "Umgebung geändert durch Update auf <version>"
```

## Sonderfall: Änderung an der Control Plane

`settings.json`, `hooks/`, `bin/agentsys/` und die Sicherheitsabschnitte von
`AGENTS.md` sind besonders geschützt. Der `ConfigChange`-Hook blockiert
beiläufige Änderungen. Ein bewusstes Update dort läuft über genau diesen
Ablauf und endet mit einem eigenen Git-Commit, der die Begründung enthält.

Nach einer Hook-Änderung ist `tests/test_hooks.py` zwingend — die Hooks werden
dort als echte Prozesse aufgerufen, nicht nur importiert.

## Ergebnis

Melde: alte und neue Version, geprüfter Changelog-Befund, Testergebnisse im
Vergleich, Entscheidung mit Begründung, neuer Known-Good-Stand, und welche
Erfahrungen nachgezogen wurden.
