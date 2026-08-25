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

## Second Brain: lernendes, quellenbelegtes Wissen

Das System merkt sich nicht einfach Chatverlauf. Neue Erkenntnisse laufen
über einen kontrollierten Single-Writer-Pfad, bevor sie als Fakt gelten:

```
Beobachtung -> Knowledge Candidate -> Archivist-Prüfung -> verwaltete Notiz
                                              |
                  Nur-Lese-Suche -> Context Builder -> Quellenpaket
```

- Jeder Fakt startet als `pending`-Kandidat mit Quelle, Datei-Hash und
  Vertrauensstufe — nie direkt als bestätigt.
- Nur eine geprüfte Freigabe (`knowledge approve`) schreibt in den
  Wissensspeicher; sie verlangt einen offenen Task, ein Entity-Lock und bei
  bestehenden Notizen den aktuell gemessenen Hash.
- Schwächere Quellen überschreiben stärkere nie — ältere Werte bleiben als
  `superseded` erhalten statt gelöscht zu werden.
- Vor jedem Task-Abschluss ist eine Knowledge Review Pflicht: `none`,
  `captured` oder `deferred`, dokumentiert im Ledger.

Details, CLI-Befehle und Sicherheitsgrenzen in
[Second Brain](docs/second-brain-architecture.md).

## Voraussetzungen

- Windows mit [Claude Code](https://claude.com/product/claude-code) und/oder
  [Codex CLI](https://github.com/openai/codex)
- Python 3.11+, Node.js 20+
- Optional: [UFO²](https://github.com/microsoft/UFO) für Windows-GUI-
  Automatisierung, [Playwright](https://playwright.dev/) für Browser-Aufgaben

## Installation

```powershell
git clone https://github.com/Zedox95/AgentSystem.git
cd AgentSystem
.\setup.ps1
```

`setup.ps1` passt die fest verdrahteten Pfade an den tatsächlichen Klon-Ort
an (egal wo du klonst) und fragt der Reihe nach:

- **Second Brain / Obsidian** — bestehenden Vault-Pfad angeben, oder leer
  lassen und einen neuen Vault mit der erwarteten Ordnerstruktur anlegen
  lassen. Nein → der `shared-memory`-MCP-Server wird aus `.mcp.json` entfernt.
- **UFO² (Windows-GUI-Automatisierung)** — Pfad zu einer bestehenden
  UFO²-Installation. Nein → der `ufo`-MCP-Server wird entfernt, der Skill
  `ufo-windows` bleibt ungenutzt.
- **Playwright (Browser-Automatisierung)** — bei Ja installiert das Skript
  `npm install` und lädt Chromium herunter. Nein → der `playwright`-Eintrag
  wird entfernt.
- **Codex-Anbindung** — bei Ja bekommst du die drei nötigen Schritte im
  Terminal genannt (`/plugin marketplace add`, `/plugin install`,
  `/codex:setup`); das Skript selbst installiert keine Claude-Code-Plugins.

Alle vier Fragen mit Nein/Enter beantwortet ergibt ein lauffähiges System
ganz ohne die optionalen Komponenten. Nicht-interaktiv geht es auch, z. B.
für Skripte:

```powershell
.\setup.ps1 -VaultPath 'D:\Notizen\Vault' -InstallPlaywright:$true -SkipUfo -SkipCodexHint
```

**Was der Installer nicht abnehmen kann** — Policy oder technische Grenze,
kein Nachlässigkeitsfehler:

1. **Anmeldungen selbst durchführen:** Claude Code beim Anthropic-Account,
   Codex-CLI bei ChatGPT (`authMethod: chatgpt`), ggf. `gh auth login` bei
   GitHub. Alles Browser-/Device-Code-Logins — kein Werkzeug dieses Systems
   tippt Zugangsdaten.
2. **Keine LLM-API-Keys setzen.** `.claude/settings.json` blockiert
   `ANTHROPIC_API_KEY`/`OPENAI_API_KEY`/`CODEX_API_KEY` absichtlich — nötig
   sind nur die Abos (Claude Pro/Code, ChatGPT Plus), keine Pay-as-you-go-API.
3. **Projektvertrauen einmalig bestätigen**, wenn Claude Code oder das
   Codex-Plugin beim ersten Öffnen nach Hooks/`settings.json` fragt.
4. Zugangsdaten für Weboberflächen, die der `browser-admin`-Skill anspricht —
   tippst grundsätzlich du selbst.

Danach:

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
