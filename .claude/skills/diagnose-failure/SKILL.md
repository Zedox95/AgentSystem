---
name: diagnose-failure
description: Systematische Root-Cause-Analyse nach einem Fehlschlag - Fehlerdaten erfassen, Fehlerklasse bestimmen, Hypothesen bilden und einzeln widerlegen, Version und Konfiguration prüfen, Experience Store befragen, dann gezielt einen zweiten Versuch oder einen Methodenwechsel entscheiden. Einsetzen, wenn ein Kommando, ein Dienst, ein Server oder eine Änderung fehlgeschlagen ist, statt es blind zu wiederholen.
allowed-tools: Bash(python C:\AgentSystem\bin\agentctl.py *), Read, Grep, Glob
context: fork
---

# Root-Cause-Analyse

Keine blinde Wiederholung. Dieselbe Methode wird höchstens zweimal versucht,
und der zweite Versuch nur mit **korrigierter Ursache**.

## 1. Fehlerdaten vollständig erfassen

Exakte Fehlermeldung im Wortlaut, Exit-Code, das tatsächlich ausgeführte
Kommando, Zeitpunkt, betroffene Ressource, Rechtekontext. Dazu die
Logausschnitte **um den Zeitpunkt herum** — nicht das ganze Log.

Eine paraphrasierte Fehlermeldung ist wertlos. Nimm den Originaltext.

## 2. Fehlerklasse bestimmen

| Klasse | Erkennungsmerkmal | Typische Ursache |
|---|---|---|
| Syntax/Aufruf | „unknown option", „unrecognized", Parserfehler | falsche Version, erfundenes Flag |
| Rechte | „access denied", „permission denied", 401/403 | fehlende Elevation, falscher Benutzer, ACL |
| Nicht gefunden | „not found", „no such file", 404 | falscher Pfad, Dienst existiert nicht, falsche Version |
| Zustand | „already exists", „in use", „locked" | Ressource belegt, Vorbedingung fehlt |
| Netzwerk | Timeout, „connection refused", DNS | Dienst aus, Firewall, falscher Port |
| Schema/Format | Validierungsfehler, Parse-Fehler | Datenformat passt nicht zur Version |
| Ressourcen | OOM, „no space", VRAM | Kapazität |

Die Klasse bestimmt, wo du suchst. Ein Rechtefehler wird nicht durch eine
andere Syntax gelöst.

## 3. Versionsannahme prüfen

Der häufigste Fehler ist eine Annahme aus dem Gedächtnis. Prüfe in dieser
Reihenfolge (AGENTS.md Abschnitt 3): installierte Version → lokale
`--help`-Ausgabe → tatsächliche Konfigurationsdatei → lokales README →
installierter Quellcode → offizielle Primärdokumentation.

Auf diesem Rechner besonders häufig: `powershell.exe` ist **5.1**, kein
`pwsh`. `Test-Json`, `&&`, `||`, `??` und `?:` gibt es dort nicht.

## 4. Hypothesen bilden und widerlegen

Formuliere zwei bis drei konkrete Hypothesen und versuche, jede **zu
widerlegen** — nicht, sie zu bestätigen. Ändere dabei jeweils nur eine
Variable. Die Hypothese, die alle Beobachtungen erklärt und die du nicht
widerlegen konntest, ist die Arbeitshypothese.

Achte auf Beobachtungen, die deine bevorzugte Hypothese **nicht** erklärt.
Genau dort steckt meist die echte Ursache.

## 5. Erfahrung befragen

```bash
python C:\AgentSystem\bin\agentctl.py exp list
python C:\AgentSystem\bin\agentctl.py exp best --key <aufgabenart>
```

Ist der Fehler bekannt? Gibt es eine Methode, die hier nachweislich
funktioniert hat — und passt deren Environment noch?

## 6. Entscheiden

- **Ursache gefunden und korrigierbar** → zweiter Versuch mit korrigierter
  Ursache, gleiche Methode
- **Gleicher Fehler erneut** → Methodenwechsel nach AGENTS.md Abschnitt 10
- **Auch die Alternative scheitert** → anderen Agenten oder Cross-Model-Prüfung
  durch Codex
- **Zustand unklar oder teilweise geändert** → Rollback über `rollback-change`
- **Ursache liegt außerhalb des Zugriffs** → an den Benutzer melden, mit
  genauer Angabe, was fehlt

Der `PostToolUseFailure`-Hook meldet sich, wenn derselbe Fehlerfingerabdruck
zum zweiten Mal auftritt. Das ist das Signal zum Methodenwechsel, nicht zur
dritten Wiederholung.

## 7. Verbuchen

```bash
python C:\AgentSystem\bin\agentctl.py exp record --key <aufgabenart> --method <methode> --error "<Originalfehler>" --root-cause "<gefundene Ursache>" --agent <agent>
```

Eine Methode, die reproduzierbar an derselben Ursache scheitert, gehört auf
`DEPRECATED` — dann wird sie künftig nicht mehr vorgeschlagen.

## Ergebnis

Melde: Originalfehler, Fehlerklasse, geprüfte Hypothesen mit dem jeweiligen
Widerlegungsversuch, festgestellte Root Cause, gewählte nächste Aktion und
warum. Wenn die Ursache **nicht** gefunden wurde, sag das deutlich — eine
plausible Vermutung ist keine Diagnose.
