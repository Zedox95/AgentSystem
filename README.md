# AgentSystem

Eine anbieterneutrale Steuerungsebene für KI-Coding-Agenten (Claude Code,
Codex) auf einem eigenen Windows-Rechner: eine Systempolicy, sechs
Subagenten, zwölf eigene Skills, neun Hooks und eine kleine Python-Control-
Plane (Ledger, Locks, Policy Guard, Experience Store).

Der Grundsatz: **Ein Auftrag gilt nie deshalb als erfolgreich, weil ein Agent
das behauptet.** Realer Systemzustand und objektive Tests schlagen jede
Agentenaussage — dafür gibt es Risikoklassen, einen Task Contract, Resource
Locks, ein Transaktionsprinzip mit Backup/Rollback und eine unabhängige,
ausschließlich lesende Verifikationsrolle.

Dies ist der veröffentlichte **Kern** eines größeren, privaten Setups: alles,
was hier liegt, ist wiederverwendbar, ohne an einen bestimmten Rechner oder
eine bestimmte Infrastruktur gebunden zu sein. Betreiberspezifischer
Laufzeitzustand (Ledger-Inhalte, Locks, Backups, konkrete Server-/Netzwerk-
Konfiguration) ist bewusst nicht Teil dieses Repos.

## Einstieg

| Dokument | Inhalt |
|---|---|
| [Benutzeranleitung](docs/benutzeranleitung.md) | Wie du einen Auftrag gibst und was dann passiert |
| [Systemdokumentation](docs/systemdokumentation.md) | Aufbau und Entstehung |
| [Second Brain](docs/second-brain-architecture.md) | Lernendes Wissensmanagement mit Quellenbeleg |
| [Globale Provider-Integration](docs/global-provider-integration.md) | Claude Code, Codex, ChatGPT |
| [Bekannte Fehler](docs/known-issues.md) | Gemessene Befunde mit Umgehung |
| [AGENTS.md](AGENTS.md) | Die verbindliche, anbieterneutrale Systempolicy — 24 Abschnitte |

## Aufbau

```
AGENTS.md              anbieterneutrale Systempolicy (Prioritäten, Risikoklassen,
                        Task Contract, Locks, Verifikation, Secrets, Learning)
CLAUDE.md               Claude-Code-spezifische Ergänzung, bindet AGENTS.md ein
.claude/
  agents/                6 Subagenten (Windows, Infrastruktur, Browser, Gaming,
                          Implementierung, Verifikation)
  skills/                 12 eigene Skills
  hooks/                  9 Hook-Skripte (SessionStart, PreToolUse, ConfigChange, ...)
  settings.json            Berechtigungen und Hook-Verdrahtung
bin/
  agentsys/                Ledger, Locks, Policy, Fingerprint, Experience, Knowledge, ...
  agentctl.py              Kommandozeile der Control Plane
adapters/
  ufo/                     Windows-UI-Automation (UFO²) — CLI + MCP
  playwright/              Browser-Automatisierung — CLI + MCP
  memory/                  MCP-Zugriff auf verwaltetes, quellenbelegtes Wissen
schemas/                   JSON-Schemata für Knowledge/Context/Eval/Metric
evals/                     Eval-Fälle für Regressionsprüfung
tests/                     Testsuiten, run-all.py
docs/
```

## Zweites Modell als Kontrolle und Übergabe

Codex ist als zweites Frontier-Modell angebunden, nicht als Ersatz bei
Kontingentende. Aus Claude Code heraus:

- `/codex:rescue` — begrenzte Delegation einer Untersuchung oder eines Fixes,
  Claude bleibt Lead
- `/codex:review` — unabhängige Codex-Prüfung einer Änderung
- `/codex:transfer` — vollständige Sitzungsübergabe: Ziel, bisheriger
  Verlauf und Kontext gehen in einem Befehl an einen Codex-Thread über, der
  danach mit `codex resume <thread-id>` fortgesetzt wird

Kein Schritt davon setzt einen API-Key — alles läuft über die lokal
angemeldete Codex-CLI. Details in AGENTS.md Abschnitt 4 und in
[Systemdokumentation](docs/systemdokumentation.md).

## Voraussetzungen

- Windows mit [Claude Code](https://claude.com/product/claude-code) und/oder
  [Codex CLI](https://github.com/openai/codex)
- Python 3.11+, Node.js 20+
- Optional: [UFO²](https://github.com/microsoft/UFO) für Windows-GUI-
  Automatisierung, [Playwright](https://playwright.dev/) für Browser-Aufgaben

## Los geht's

```bash
python bin/agentctl.py status
python tests/run-all.py
```

Öffne Claude Code oder Codex mit diesem Verzeichnis als Projektverzeichnis —
nur dort greifen Regeln, Agenten, Skills und Hooks. Details in der
[Benutzeranleitung](docs/benutzeranleitung.md) und in
[Globale Provider-Integration](docs/global-provider-integration.md).

## Lizenz

MIT, siehe [LICENSE](LICENSE). Alle Dateien in diesem Repo sind eigenes Werk.
Das private Gesamtsystem bindet zusätzlich einige extern übernommene Skills
Dritter (mit eigener Lizenz und Herkunftsnachweis) ein — die sind bewusst
nicht Teil dieser Veröffentlichung.
