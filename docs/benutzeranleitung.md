# Benutzeranleitung

## Das Wichtigste zuerst

**Öffne Claude Code mit dem Projektverzeichnis dieses Repos.**

Nur dort greifen die Regeln, Agenten, Skills und Hooks. In einem anderen
Verzeichnis läuft Claude Code ohne dieses System — ohne Policy Guard, ohne
Ledger, ohne Locks.

---

## Wie du einen Auftrag gibst

Du formulierst nur das gewünschte **Ergebnis**. Nicht den Weg dorthin.

> „Prüfe meinen PC intensiv auf Fehler und veraltete Treiber."
> „Behebe diesen Fehler: …"
> „Ändere Einstellung X in Windows."
> „Prüfe, ob mein gesamtes System korrekt funktioniert."
> „Installiere und konfiguriere Anwendung X."

Du musst nicht angeben, welcher Agent, welches Werkzeug oder welche Methode.
Das leitet das System ab.

---

## Was dann passiert

```
Dein Ziel
   ↓
Ziel klären und Erfolgskriterien festlegen
   ↓
Erfahrung prüfen — gibt es einen bewährten Weg?
   ↓
Risikoklasse bestimmen (R0 lesen … R3 kritisch)
   ↓
Task Contract im Ledger: Ziel, Kriterien, Methode, Alternative, Rollback
   ↓
Resource Lock — niemand sonst arbeitet gleichzeitig daran
   ↓
Baseline erfassen, ab R2 Backup anlegen
   ↓
Ausführen
   ↓
Objective Test — den realen Zustand erneut messen
   ↓
Unabhängige Prüfung durch den read-only Verifier
   ↓
PASS → Commit    ·    FAIL → Diagnose oder Rollback
   ↓
Erfahrung verbuchen
```

---

## Wann du gefragt wirst

Das System arbeitet selbstständig, hält aber an drei Stellen an:

| Situation | Was passiert |
|---|---|
| **R2** — Treiber, Registry, Firewall, Pakete, Netzwerk, VM-Ressourcen | Du bestätigst die Aktion. Backup und Rollback stehen vorher fest. |
| **R3** — Löschen, Partitionen, BIOS, Bootloader, Benutzerkonten, Router-WAN | Ausdrückliche Freigabe. Wird nie ohne dich gemacht. |
| **Anmeldung nötig** | Zugangsdaten gibt das System nicht selbst ein. Es meldet, welche Oberfläche welche Anmeldung braucht. |

Lesende Aktionen — Status, Logs, Versionen, Inventar — laufen ohne Rückfrage.

---

## Was das System niemals tut

- Eine kostenpflichtige LLM-API einrichten. Technisch blockiert.
- Erfolg melden, ohne den realen Zustand gemessen zu haben.
- Eine Änderung ab R2 ohne Backup und Rollback-Plan durchführen.
- Dieselbe fehlgeschlagene Methode blind wiederholen.
- Zugangsdaten selbst eingeben.
- Anweisungen befolgen, die auf einer Webseite oder in einer Datei stehen.

---

## Wenn etwas schiefgeht

Das System diagnostiziert selbst: Fehler erfassen, klassifizieren, Ursache
suchen, Version prüfen, Erfahrung befragen, gezielt einen zweiten Versuch,
dann Methodenwechsel — und im Zweifel Rollback.

Du bekommst am Ende immer: was gemacht wurde, womit es belegt ist, was
geprüft wurde, welche Risiken bleiben.

---

## Nützliche Befehle für dich

Aktueller Zustand — offene Vorgänge, Sperren, Erfahrungen:

```bash
python bin/agentctl.py status
```

Was das System gelernt hat:

```bash
python bin/agentctl.py exp list
```

Ob eine Aktion erlaubt wäre, ohne sie auszuführen:

```bash
python bin/agentctl.py policy check --command "Remove-Item C:\Temp -Recurse"
```

Alle Tests — nach jeder Änderung am System selbst:

```bash
python tests/run-all.py
```

Nach einem Absturz oder Kontingentende: wo stand der Vorgang?

```bash
python bin/agentctl.py checkpoint show
```

---

## Was heute noch nicht geht

- **Proxmox, Linux, eigener Server**: in diesem öffentlichen Repo nicht
  enthalten — das Original hat dafür ein separates `infrastructure-agent`-
  Setup, das Umgebungsdetails des Betreibers enthält und deshalb nicht
  veröffentlicht ist. Aufträge dazu melden ehrlich, dass das Ziel fehlt.
- **Router-Automatisierung**: kein TR-064, keine API — nur die
  Weboberfläche. Für den Zugang meldest **du** dich einmal selbst an, z. B.:

  ```bash
  node adapters/playwright/pwctl.mjs login --url "http://<router-ip>/html/login/login.html" --profile mcp --until "Übersicht" --timeout 300000
  ```

  Ein sichtbarer Browser öffnet sich, du tippst das Gerätepasswort. Die
  Sitzung bleibt danach im Profil und steht CLI und MCP-Server zur Verfügung.
- **Codex**: bei erschöpftem Kontingent arbeitet Claude allein; die
  Cross-Model-Prüfung entfällt bis zum Reset.

---

## Wenn du das System erweiterst

Änderungen an `settings.json`, `hooks/`, `bin/agentsys/` oder den
Sicherheitsabschnitten von `AGENTS.md` sind geschützt. Der `ConfigChange`-Hook
blockiert beiläufige Änderungen. Der Weg dafür ist der Skill
`update-agent-stack`: Known-Good sichern, ändern, Regression, Verifikation,
Commit.
