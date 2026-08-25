# Systemdokumentation

Alle Angaben sind am Rechner gemessen, nicht angenommen.

---

## 1. Entstehung

Dieses System entstand als Nachfolger eines vorherigen, lokalen Multi-Agenten-
Setups aus mehreren lokalen LLM-Werkzeugen, UFO² und einem eigenen
Orchestrierungs-Overlay. Übernommen wurden daraus:

- Der Operating Contract — inhaltlich überarbeitet, anbieterneutral
  formuliert und um Rollback, Locks und Task Contract erweitert
- Die Agentenbeschreibungen, verdichtet auf sechs Claude-Subagenten
- Routing- und Learning-Konzept: Klassifikation, Eskalation nur als Neu-Spawn
  mit Evidenz, verifier-gated Learning
- Knowledge- und Metrik-Schemata
- Das Restore-Point-Muster mit SHA256-Manifest und Dry-Run-Restore
- Codex als zweites Frontier-Modell über eine read-only-Sandbox mit aktiv
  entfernten API-Schlüsseln
- UFO² als Windows-Aktionsschicht

Lokale LLM-Werkzeuge, die nicht mehr gebraucht wurden, wurden vollständig
deinstalliert; nur Upstream-Komponenten von UFO² blieben unverändert erhalten.

## 2. Aufbau

```
Repo-Wurzel
├── AGENTS.md                     anbieterneutrale Systempolicy, 24 Abschnitte
├── CLAUDE.md                     kurz; bindet AGENTS.md über @AGENTS.md ein
├── .claude/
│   ├── settings.json             Berechtigungen und Hooks
│   ├── agents/                   6 Subagenten
│   ├── skills/                   12 Skills
│   └── hooks/                    Hook-Skripte + hooklib
├── bin/
│   ├── agentsys/                 paths, policy, ledger, locks, fingerprint, experience, ...
│   └── agentctl.py               Kommandozeile der Control Plane
├── adapters/
│   ├── ufo/                      ufoctl.py (CLI) + ufo_mcp.py (MCP)
│   ├── playwright/                pwctl.mjs (CLI) + @playwright/mcp
│   └── memory/                   MCP-Zugriff auf den verwalteten Second-Brain-Speicher
├── .mcp.json                     MCP-Server fuer exploratives Arbeiten
├── schemas/                      JSON-Schemata fuer Knowledge/Context/Eval/Metric
├── evals/                        Eval-Faelle fuer Regressionspruefung
├── tests/                        Testsuiten, run-all.py
└── docs/
```

`state/` (Ledger, Locks, Erfahrungen, Known-Good, Backups) ist Laufzeitzustand
eines konkreten Betreibers und deshalb nicht Teil dieses Repos — siehe
`.gitignore`.

### Subagenten

`windows-agent` · `infrastructure-agent` · `browser-agent` · `gaming-agent` ·
`implementation-agent` · `verification-agent`

Keiner verdrahtet ein Modell — das erzwingt `tests/test_config.py`. Der
`verification-agent` führt `Write`, `Edit` und `NotebookEdit` in
`disallowedTools` und hat zusätzlich einen eigenen `PreToolUse`-Hook, der
schreibende Shell-Kommandos verweigert. Werkzeugbeschränkungen allein hätten
die Shell nicht erfasst.

### Skills

**Ablauf:** `preflight-change`, `verify-change`, `diagnose-failure`,
`rollback-change`
**Routing:** `windows-admin`, `browser-admin`, `infrastructure-admin`
**Ausführung:** `ufo-windows`, `playwright-web`
**Lernen:** `knowledge-review`, `model-routing`
**Wartung:** `update-agent-stack`

### Hooks

| Ereignis | Zweck |
|---|---|
| `SessionStart` | offene Tasks, Locks, Checkpoint, veraltete Erfahrungen |
| `PreToolUse` | Policy Guard, deterministisch |
| `PermissionRequest` | lesende Kommandos erlauben, Rest nachfragen |
| `PostToolUseFailure` | Fehlerfingerabdruck, warnt bei Wiederholung |
| `TaskCreated` | erinnert bei riskanten Aufgaben an den Task Contract |
| `TaskCompleted` | blockiert Abschluss bei offenem, geändertem R3-Vorgang |
| `SubagentStop` | erzwingt strukturiertes Ergebnis |
| `ConfigChange` | schützt Hooks, Berechtigungen, Umgebungsvariablen |
| `UserPromptSubmit` | Routing-Hinweise für die aktuelle Anfrage |

`tests/test_config.py` hält die Liste der real existierenden Hook-Ereignisse
und schlägt bei einem erfundenen Namen an.

### Policy Guard

Regelbasiert, ohne Modellaufruf, ohne Netzwerk. DENY-Regeln (Datenträger,
Partitionen, Bootloader, Firmware, Datenbank- und Kontolöschung, destruktives
Git, SSH-Schlüssel, API-Schlüssel, Berechtigungsumgehung), ASK-Regeln
(Dienste, Registry, Treiber, Firewall, Netzwerk, Pakete, Elevation, Neustart),
und eine Allowlist bekannter lesender Kommandos.

Eine Kommandoverkettung hebt die Allowlist auf: `git status; rm -rf /` wird
verweigert, nicht erlaubt.

Der Control-Plane-Schutz greift auch dann, wenn die konfigurierte
Installationswurzel umgebogen wird — die feste Wurzel wird immer mitgeprüft.

### Run Ledger und Zustand

SQLite mit WAL: `tasks`, `runs`, `events`. Ereignisse werden nur angehängt, nie
verändert. Kommandotexte laufen vor dem Schreiben durch eine Redaction für
API-Keys, Tokens und Passwörter.

Zustände: `RECEIVED → PLANNED → PREFLIGHT → LOCKED → BASELINED → BACKED_UP →
EXECUTING → OBJECTIVE_TEST → INDEPENDENT_VERIFY → COMMITTED`, Fehlerpfad
`FAILED_STEP → DIAGNOSING → RETRY_ALTERNATIVE → ROLLING_BACK → ROLLED_BACK →
FAILED`.

### Resource Locks

Atomar über `O_EXCL`. Zwei Besitzarten:

- `process` — verwaist, wenn der haltende Prozess nicht mehr läuft
- `task` — verwaist **nur**, wenn der Task abgeschlossen ist

Diese Unterscheidung entstand aus einem Fehler, den erst der Smoke-Test
aufdeckte: CLI-Locks waren sofort verwaist, weil der setzende Prozess endet.
Der Schutz war wirkungslos. Siehe `known-issues.md`.

### Experience Store

`CANDIDATE → VERIFIED → DEPRECATED`. Jeder Eintrag trägt einen Environment
Fingerprint (Windows-Build, Claude-Code, UFO-Commit, Playwright, Python, Node,
npm, Git, Docker, Codex). `best_method` sortiert nach Status, dann Erfolgsrate,
erst dann Dauer — Zuverlässigkeit vor Geschwindigkeit. Erfahrungen mit
abweichender Umgebung werden ausgeschlossen und beim Sessionstart gemeldet.

## 3. Adapter

**UFO²** (`ufoctl.py`) — `windows`, `controls`, `tree`, `texts`, `click`,
`type`, `keys`, `scroll`, `screenshot`, `plan`, `tools`, `inspect`.
Der Shell-Executor von UFO ist ausdrücklich **nicht** exponiert: Shell läuft
über Bash und PowerShell durch den Policy Guard, ein zweiter Weg würde ihn
umgehen. `inspect` misst über pywinauto an UFO vorbei — nötig, weil UFOs eigene
Steuerelementliste den Accessible Name statt des lebenden Werts meldet.

**Playwright** (`pwctl.mjs`) — `snapshot`, `text`, `http`, `click`, `fill`,
`login`, `screenshot`, `plan`. Lokal installiert statt global `latest`.
Lokalisierung über Accessibility-Rollen; Selektoren sind letzte Wahl,
Screenshots Fallback. Mehrdeutige Lokalisierer brechen ab, statt zu raten.

**Codex** — über ein offizielles, projektweites Plugin angebunden. Delegation
und Sitzungsübergabe laufen über eigene Slash-Befehle. Die Projektumgebung
neutralisiert `OPENAI_API_KEY` und `CODEX_API_KEY`, damit kein
kostenpflichtiger API-Zugang automatisch übernommen wird.

## 4. Second Brain

Siehe `second-brain-architecture.md` für den vollständigen Knowledge-
Candidate-Ablauf: Beobachtung → Kandidat → Archivist-Prüfung → verwaltete
Notiz, mit Single-Writer-Pfad, Quellenpriorität und Optimistic Concurrency.

## 5. Backup und Rollback

Ein Betreiber-Repo ist ein Git-Repo: Rollback über `git revert`, nicht über
`reset --hard` — der Policy Guard verweigert Letzteres. Vor riskanten
Änderungen entstehen zusätzlich dateisystemseitige Restore-Points mit
SHA-256-Manifest, außerhalb der Versionskontrolle.
