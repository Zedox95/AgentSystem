---
name: knowledge-review
description: Prüft vor COMMITTED automatisch, ob eine abgeschlossene AgentSystem-Aufgabe dauerhaft relevantes Wissen für Kevins Obsidian-Vault erzeugt hat, dedupliziert es über die bestehende Entity-Suche und dokumentiert entweder captured, deferred oder none. Für jeden formalen Task Contract nach Objective Tests und Verifier-PASS ausführen; das Commit-Gate blockiert ohne diese Prüfung.
allowed-tools: Bash(python C:\AgentSystem\bin\agentctl.py *), Read, Grep, Glob, Write
---

# Knowledge Review vor dem Commit

Diese Prüfung ist semantisch: Der Hook erzwingt, **dass** sie stattfindet; du
entscheidest anhand der Evidenz, **was** dauerhaft relevant ist. Schreibe nie
direkt in den Vault. Verwende ausschließlich Knowledge Candidates und den
Archivist-Pfad.

## Zeitpunkt

Nach abgeschlossenem Run mit Objective Tests und einem unabhängigen `PASS`,
aber vor `COMMITTED`.
Der Task muss dabei noch offen sein, damit der Archivist unter demselben Task
mit Entity-Lock, Backup und Optimistic Concurrency arbeiten kann.

## Relevanzprüfung

Aufnehmen:

- neue oder geänderte Systeme, Geräte und Projekte,
- abgeschlossene Projektschritte und belegte Laufzeitstände,
- Entscheidungen mit dauerhaft nützlicher Begründung,
- offene Punkte, die eine spätere Session fortsetzen muss,
- bestätigte Nutzerpräferenzen für wiederkehrende Arbeit.

Nicht aufnehmen:

- flüchtige Ausgaben, einmalige Kommandos oder reine Gesprächsnacherzählung,
- unbelegte Vermutungen als Fakt,
- Secrets, Zugangsdaten, private Notizen oder Daily Notes,
- Informationen, die bereits mit gleich starker oder stärkerer Quelle vorhanden sind.

## Ablauf

1. Lies Task Contract, Run-Evidenz und Verifier-Urteil.
2. Suche jede betroffene Entität mit `agentctl knowledge search`.
3. Wenn nichts dauerhaft relevant ist, dokumentiere das begründet:

```powershell
python C:\AgentSystem\bin\agentctl.py knowledge review `
  --task-id <task-id> --decision none `
  --reason "Nur flüchtige Ausführung; kein neuer dauerhafter Fakt"
```

4. Für relevante Fakten lies
   `C:\AgentSystem\schemas\knowledge-candidate.schema.json`, erstelle kleine
   atomare Candidates, reiche sie mit `knowledge submit` ein und lasse sie
   über `knowledge approve` übernehmen.
5. Dokumentiere alle erfolgreich übernommenen Candidate-IDs:

```powershell
python C:\AgentSystem\bin\agentctl.py knowledge review `
  --task-id <task-id> --decision captured `
  --review-candidate-id kc-... `
  --reason "Bestätigter neuer Systemstand wurde in die bestehende Entität übernommen"
```

6. Kann ein relevanter Candidate wegen Konflikt oder fehlender Bestätigung
   nicht übernommen werden, lasse ihn pending oder lehne ihn nachvollziehbar
   ab und dokumentiere `deferred` mit der Candidate-ID. Erfinde keinen
   konfliktfreien Ersatz.

## Abschlussreihenfolge

1. Run mit `outcome=PASS`, nicht leerer Objective-Test-Evidenz,
   Änderungszusammenfassung und `verification="PASS: ..."` beenden.
2. Danach die Knowledge Review ausführen; eine Review vor dem letzten
   abgeschlossenen Run gilt als veraltet.
3. `agentctl task readiness --task-id <task-id>` ausführen.
4. Nur bei `ready: true` den Task auf `COMMITTED` setzen.

`FAIL` oder `INCONCLUSIVE` ist niemals commit-ready.
