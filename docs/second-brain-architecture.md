# Second Brain und lernendes Agentensystem

## Zielbild

Die Erweiterung trennt Datenverträge, Wissen, Kontext, Messung und Lernen. Das Second Brain ist
kein ungeprüfter Chatverlauf: Nur strukturierte, quellenbelegte Fakten dürfen über einen
kontrollierten Single-Writer-Pfad produktiv werden.

```text
Beobachtung -> Knowledge Candidate -> Archivist-Prüfung -> verwaltete Vault-Notiz
                                              |
                  Nur-Lese-Suche -> Context Builder -> Quellenpaket
                                              |
                   Eval + Metric Events -> KPI-/Capability-Bericht
                                              |
                           Skill Candidate -> manuelle Prüfung
```

## Sicherheitsgrenzen

- Schemas und Laufzeitverträge liegen in `schemas/` und `bin/agentsys/contracts.py`.
- Neue Fakten starten in `state/knowledge-candidates/pending`.
- Nur `knowledge.approve` schreibt in den verwalteten Wissensspeicher. Es verlangt einen offenen
  R1+-Task, ein Entity-Lock, einen erwarteten Datei-Hash und bei bestehenden Notizen ein
  verifiziertes Backup.
- Schwächere Quellen überschreiben stärkere nicht. Frühere Werte bleiben als `superseded` erhalten.
- Automatisch gelesen werden nur Markdown-Dateien mit vollständigem Status-Frontmatter.
  Unverwaltete Notizen und private Bereiche bleiben ausgeschlossen.
- Context Packages tragen Pfad, SHA-256, Status, Prüfdatum, Ranking und ein festes Tokenbudget.
- Skill-Vorschläge landen nur unter `state/skill-candidates`. Es existiert kein automatischer
  Aktivierungs- oder Promote-Pfad.
- Der Supervisor prüft Ledger, Checkpoint, Locks, Kandidaten, Metriken, Evals, Wissensspeicher und
  Indexdrift ausschließlich lesend. Er repariert nichts selbst.

## Bedienung

Alle Befehle geben maschinenlesbares JSON aus:

```powershell
agentctl knowledge submit --file candidate.json
agentctl knowledge list --bucket pending
agentctl knowledge search --query <suchbegriff> --entity <entity-id>
agentctl knowledge approve --candidate-id kc-... --task-id task-... --expected-sha256 NEW
agentctl knowledge review --task-id task-... --decision captured `
  --review-candidate-id kc-... --reason "Bestätigter Systemstand übernommen"

agentctl context build --query <suchbegriff> --entity <entity-id> --budget 2000
agentctl eval list
agentctl metrics record --file metric.json
agentctl metrics report

agentctl skill-candidate create --name neuer-skill --rationale "..." `
  --source-experience erfahrung.key --draft SKILL.md
agentctl skill-candidate report
agentctl supervisor check
```

`knowledge reject` benötigt zusätzlich `--task-id` und `--reason`. Bei einer bestehenden Notiz im
Wissensspeicher wird für `knowledge approve` der aktuell gemessene SHA-256 statt `NEW` übergeben.

Nach dem letzten abgeschlossenen Run und vor `COMMITTED` ist eine Knowledge Review verpflichtend.
`none` dokumentiert begründet, dass kein
dauerhafter Fakt entstand; `captured` verlangt unter demselben Task akzeptierte Candidate-IDs;
`deferred` verweist auf pending oder rejected Candidates. `agentctl task readiness` zeigt alle noch
fehlenden Commit-Voraussetzungen deterministisch an.

## Objektive Tests

Die zentralen Regressionstests laufen über:

```powershell
python tests/run-all.py
```

Enthalten sind Verträge, Candidate Queue, Single-Writer-Verhalten, Quellenpriorität,
Optimistic Concurrency, Context-Reproduzierbarkeit, Budgetierung, Evals, KPI-Aggregation,
Skill-Isolation, Supervisor-Erkennung und CLI-Smoke-Tests.
