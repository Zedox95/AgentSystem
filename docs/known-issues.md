# Bekannte Fehler und Umgehungen

Gemessene Befunde, keine Vermutungen. Jeder Eintrag nennt, wie er festgestellt
wurde und was daraus für die Arbeitsweise folgt.

---

## UFO² v3.0.8 — `app_texts` deklariert ein falsches Ausgabeschema

**Befund.** Das Werkzeug `texts` in
`ufo/client/mcp/local_servers/ui_mcp_server.py:570` ist als
`-> Annotated[str, …]` deklariert, liefert aber eine Liste. Jeder Aufruf über
einen MCP-Client scheitert an der Ausgabevalidierung:

```
Output validation error: ['Suchfeld, Einstellung suchen'] is not of type 'string'
```

**Festgestellt am** 2026-08-21, UFO-Commit `96983c73`, fastmcp 2.11.3.

**Umgehung.** `adapters/ufo/ufoctl.py` benutzt `app_texts` nicht. Gelesen wird
über `ui_get_app_window_controls_info` beziehungsweise für die Verifikation
über den Befehl `inspect`.

**Nicht** im UFO-Core repariert: der Core bleibt bewusst unverändert, damit
`git pull` und Updates weiter funktionieren.

---

## UFO² v3.0.8 — Steuerelementliste meldet nicht den lebenden Wert

**Befund.** `get_control_info` in
`ufo/automator/ui_control/inspector.py:636` belegt sowohl `control_text` als
auch `control_title` mit `element_info.name`. Bei einem Eingabefeld ist das der
Accessible Name, **nicht** der eingegebene Inhalt. Zusätzlich kann die Liste
aus einer früheren Aufzählung stammen und damit veraltet sein.

**Nachgewiesen so:** Über `ufoctl.py type` wurde ein Testwert in das Suchfeld
der Windows-Einstellungen geschrieben. UFOs Steuerelementliste meldete
weiterhin den alten Platzhaltertext. Eine unabhängige Messung über pywinauto
ergab, dass der geschriebene Wert tatsächlich stand — UFOs eigene Rückmeldung
war falsch.

**Folge für die Arbeitsweise.** Eine mit UFO ausgeführte Aktion wird
**niemals** mit UFOs eigener Steuerelementliste verifiziert. Das wäre der
Executor, der sich selbst bestätigt, und widerspricht AGENTS.md Abschnitt 13.

Verifiziert wird mit:

```bash
python adapters/ufo/ufoctl.py inspect --window "<Fenster>" --type Edit --expect "<erwarteter Inhalt>"
```

Dieser Befehl geht direkt über pywinauto an die UI-Automation-Schnittstelle,
an UFO vorbei.

---

## UFO² — Steuerelemente müssen vor jeder Aktion aufgelistet werden

**Befund.** Ein Aktionswerkzeug ohne vorheriges
`ui_get_app_window_controls_info` scheitert mit:

```
No application windows available. Please call get_desktop_app_info first.
```

Ursache ist UFOs interne `control_dict`, die erst durch die Aufzählung gefüllt
wird.

**Umgehung.** `ufoctl.py` listet in jedem Aktionsbefehl automatisch zuerst die
Steuerelemente auf. Für Aufrufer ist der Befund damit erledigt; er ist hier
dokumentiert, weil er bei direkter Nutzung der UFO-Werkzeuge wieder auftritt.

---

## UFO² — Steuerelementliste ist direkt nach dem Fensterwechsel leer

**Befund.** Unmittelbar nach `host_select_application_window` liefert
`ui_get_app_window_controls_info` gelegentlich eine leere Liste. Ein erneuter
Aufruf nach kurzer Wartezeit liefert die Elemente.

**Umgehung.** `ufoctl.py` wartet nach der Fensterauswahl kurz und wiederholt
die Aufzählung begrenzt. Das ist das Abwarten eines bekannten Rennens, keine
blinde Wiederholung im Sinne von AGENTS.md Abschnitt 15.

---

## UFOs Config-Loader ist vom Arbeitsverzeichnis abhängig

**Befund.** `config/config_loader.py:393` sucht `config/ufo/` relativ zum
aktuellen Arbeitsverzeichnis. Ein Import von außerhalb des UFO-Installations-
verzeichnisses scheitert mit `FileNotFoundError: No configuration found for 'ufo'`.

**Umgehung.** `ufoctl.py` wechselt vor dem Import in dieses Verzeichnis.

---

## Windows PowerShell 5.1 — kein `pwsh` im PATH

**Befund.** `powershell.exe` ist Windows PowerShell 5.1. Ein `pwsh` gibt es im
PATH nicht.

Dort fehlen: `Test-Json`, `&&`, `||`, `??`, `?.`, `?:`,
`ConvertFrom-Json -AsHashtable`.

Eine eingebettete PowerShell 7 kann an eine andere lokale Installation
gebunden sein und ist deshalb **kein** verlässlicher Pfad für eigene Skripte.

**Folge.** Eigene Skripte sind 5.1-kompatibel zu schreiben.

---

## Deutsche Locale-Ausgaben sind nicht als cp1252 dekodierbar

**Befund.** `tasklist` und vergleichbare Windows-Kommandos liefern unter
deutschem Locale Bytes, die Pythons Standarddekodierung sprengen:

```
UnicodeDecodeError: 'charmap' codec can't decode byte 0x81
```

**Umgehung.** Bei jedem `subprocess.run(..., text=True)` zusätzlich
`errors="replace"` setzen. Umgesetzt in `bin/agentsys/locks.py` und
`bin/agentsys/fingerprint.py`.

---

## `subprocess` startet keine `.cmd`-Wrapper über den bloßen Namen

**Befund.** `subprocess.run(["npm", "--version"])` scheitert unter Windows,
obwohl `shutil.which("npm")` den Pfad findet. `npm` und `npx` sind
`.cmd`-Wrapper, und `CreateProcess` sucht nach `npm.exe`.

**Umgehung.** Den von `shutil.which()` aufgelösten vollen Pfad übergeben.
Umgesetzt in `bin/agentsys/fingerprint.py`.

---

## Playwright 1.62 — `page.accessibility` existiert nicht mehr

**Befund.** Die frühere API `page.accessibility.snapshot()` ist entfernt:

```
Cannot read properties of undefined (reading 'snapshot')
```

**Umgehung.** `adapters/playwright/pwctl.mjs` benutzt `locator.ariaSnapshot()`.
Das liefert einen kompakten YAML-Baum aus Rollen, Namen und Verlinkungen und
ist für einen Agentenkontext ohnehin besser geeignet als der frühere JSON-Baum.

---

## Router-Weboberflächen: Inhalt wird erst nach dem Laden aufgebaut

**Befund.** Mit dem Standard `domcontentloaded` liefert die Startseite einer
JavaScript-lastigen Router-Weboberfläche einen praktisch leeren Accessibility-
Baum (`- text: Keine Einträge vorhanden`). Erst mit `--wait networkidle`
erscheint die tatsächliche Struktur.

**Umgehung.** Bei JavaScript-Oberflächen `--wait networkidle` und ein
erhöhtes Timeout setzen.

---

## Eigener Fehler: Versionsprüfung wertete Fehlermeldungen aus

**Befund.** `fingerprint._probe` las die Version auch aus fehlgeschlagenen
Aufrufen. `npx --no-install playwright --version` meldet bei fehlendem Paket
`npx canceled due to missing packages: ["playwright@1.62.1"]` — die
Versionsnummer im Fehlertext wurde als installierte Version gewertet.

Ergebnis: Der Fingerprint meldete `playwright: 1.62.1`, obwohl Playwright
überhaupt nicht installiert war.

**Behoben.** `_probe` wertet nur noch Aufrufe mit Rückgabecode 0 aus.

**Lehre.** Eine Umgebungserfassung, die nicht installierte Werkzeuge als
vorhanden meldet, ist schlimmer als gar keine — sie führt zu Erfahrungen mit
falschem Environment Match.

---

## Eigener Fehler: CLI-Locks waren sofort verwaist

**Befund.** Ursprünglich galt ein Lock als verwaist, sobald der Prozess mit der
gespeicherten PID nicht mehr lief. Bei der Kommandozeile endet dieser Prozess
aber unmittelbar nach `lock acquire`. Ergebnis: **jedes über die CLI gesetzte
Lock war ab der nächsten Sekunde übernehmbar** — der Schutz gegen gleichzeitige
Schreibzugriffe war wirkungslos.

**Wie gefunden.** Im Abschluss-Smoke-Test nach AGENTS.md: zwei Agenten forderten
nacheinander dieselbe Ressource an. Der zweite bekam sie, obwohl der erste sie
hielt.

**Behoben.** Ein Lock hat jetzt eine Besitzart:

* `process` — verwaist, wenn der haltende Prozess nicht mehr läuft
* `task` — verwaist **nur**, wenn der zugehörige Task nachweislich abgeschlossen
  ist (`COMMITTED`, `FAILED`, `ROLLED_BACK`)

Über die Kommandozeile gesetzte Locks sind Task-Locks und brauchen zwingend
eine `task_id`; ohne sie wäre nicht entscheidbar, wann sie freigegeben werden
dürfen. Zeitablauf allein gibt nie frei.

**Lehre.** Ein Sicherungsmechanismus, der nur in der Theorie greift, ist
gefährlicher als gar keiner — man verlässt sich auf ihn. Nur der Smoke-Test
gegen das echte System hat das aufgedeckt, die Unit-Tests nicht: dort lief
alles in einem Prozess.

---

## Ein dauerhaft gesetzter LLM-API-Schlüssel in der Benutzerumgebung ist ein Risiko

**Befund.** Ein `OPENAI_API_KEY` als **User**-Umgebungsvariable bleibt von
jedem Werkzeug lesbar, das ihn erwartet — und kann dann kostenpflichtig
abrechnen, ohne dass es auffällt. Das widerspricht der Kostenpolitik in
AGENTS.md Abschnitt 4, die ausschließlich Abo-Zugänge erlaubt.

**Gegenmaßnahme.** Die Projektkonfiguration (`.claude/settings.json`) setzt
`OPENAI_API_KEY` und `CODEX_API_KEY` für Claude Code und das offizielle
Codex-Plugin ausdrücklich leer, sodass ein vorhandener Benutzer-Key nicht
automatisch übernommen wird. Der Policy Guard verweigert außerdem jeden
Versuch, einen dieser Schlüssel per `setx` oder `export` neu zu setzen. Das
Entfernen des Schlüssels selbst aus der Benutzerumgebung ist eine
Entscheidung, die nur der Benutzer trifft — kein Werkzeug tut das automatisch.

---

## Codex-Kontingent kann erschöpft sein

**Befund.** Ein Testaufruf kann mit einer Kontingent-Fehlermeldung enden, die
einen Reset-Zeitpunkt nennt.

**Umgang.** Ein solcher Fall wird korrekt als `QUOTA` klassifiziert, **nicht**
automatisch wiederholt, und es wird **keine** API als Ersatz konfiguriert.
Claude arbeitet bis zum Reset allein weiter; Taskzustände bleiben im Ledger
erhalten.

---

## Zwei Codex-Versionen können sich einen `CODEX_HOME` teilen

**Befund.** Sind CLI- und Desktop-Version von Codex unterschiedlich aktuell,
kann die ältere Binary beim Start mit einem Fehler wie

```
ERROR codex_models_manager::cache: failed to load models cache:
missing field `base_instructions` at line 97 column 5
```

abbrechen, weil die neuere Version den gemeinsamen `~/.codex/models_cache.json`
in einem Format schreibt, das die ältere nicht kennt.

**Auswirkung.** Für den Lauf folgenlos — Codex arbeitet danach normal weiter.
Es ist aber ein sichtbarer Beleg dafür, dass beide Versionen denselben
`CODEX_HOME` teilen; welche Binary benutzt wird, ist beim Aufruf ausdrücklich
festzulegen.

---

## Lehre aus einer Router-Recherche: negativer Portscan ist kein Beleg für Abwesenheit

**Befund.** Eine erste Bewertung eines Heimrouters kam zum Ergebnis, ein
bestimmtes Fernwartungsprotokoll sei „nicht verfügbar und nicht
freischaltbar", und wurde als `VERIFIED` abgelegt. **Das war falsch.**

Zwei Fehler führten dazu:

1. Der Portscan prüfte nur den bei einem anderen Hersteller üblichen
   Standardport. Der tatsächliche Hersteller nutzt andere Ports.
2. Als Ersatz für die fehlende Messung wurde Forendokumentation über ein
   verwandtes, aber verschiedenes Protokoll herangezogen und damit vermengt.

Die geräteeigene Seite mit der Liste aktiver Dienste war die richtige Quelle
und wurde erst nach der Anmeldung erreichbar.

**Lehre.** Das Geräte-eigene Dienstinventar schlägt sowohl einen
unvollständigen Portscan als auch Herstellerforen. Wo ein Gerät seine Dienste
selbst auflistet, ist alles andere Indizienbeweis. Die falsche Erfahrung wurde
auf `DEPRECATED` gesetzt und die korrigierte Erfahrung trägt die Methode
„geräteeigene Dienste-Seite".
