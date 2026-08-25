---
name: rollback-change
description: Stellt einen bekannten guten Zustand kontrolliert wieder her - Backup-Integrität prüfen, Wiederherstellung planen, ausführen, objektiv verifizieren, Lock freigeben und Ledger auf ROLLED_BACK setzen. Einsetzen, wenn eine Änderung fehlgeschlagen ist, der Verifier FAIL meldet, der Zustand unklar ist oder eine Änderung zurückgenommen werden soll.
allowed-tools: Bash(python C:\AgentSystem\bin\agentctl.py *), Read, Grep, Glob
---

# Kontrollierter Rollback

Ein Rollback ist selbst eine Änderung. Er läuft nach denselben Regeln wie jede
andere — mit Prüfung vorher und Verifikation nachher.

## 1. Zustand feststellen, bevor du etwas anfasst

```bash
python C:\AgentSystem\bin\agentctl.py status
python C:\AgentSystem\bin\agentctl.py task show --task-id <id>
```

Kläre: Welche Änderungen wurden tatsächlich schon wirksam? Ein Rollback von
etwas, das nie passiert ist, richtet mehr Schaden an als er behebt.

Setze den Zustand:

```bash
python C:\AgentSystem\bin\agentctl.py task state --task-id <id> --state ROLLING_BACK
```

## 2. Backup-Integrität prüfen — vor der Wiederherstellung

Ein Backup gilt erst als brauchbar, wenn es geprüft ist:

- Alle im Manifest gelisteten Dateien existieren
- Alle SHA256-Summen stimmen
- Der Umfang ist plausibel (Dateizahl, Gesamtgröße)

Stimmt etwas nicht, **nicht wiederherstellen**. Ein kaputtes Backup über einen
beschädigten Zustand zu legen macht die Lage schlimmer. Dann an den Benutzer
melden.

## 3. Rollback-Weg wählen

| Was | Weg |
|---|---|
| Control Repo `C:\AgentSystem` | `git revert <commit>` — nicht `reset --hard` |
| Dateien/Konfiguration | Kopie aus dem Restore-Point zurückspielen, danach Hashes vergleichen |
| Registry | `reg import` der exportierten `.reg`-Datei |
| Windows-Treiber | vorherige Version über den Geräte-Manager-Rollback oder `pnputil` mit der gesicherten INF |
| Dienst | vorherigen Starttyp und Zustand aus der Baseline wiederherstellen |
| Proxmox | Snapshot-Rollback |
| Pterodactyl | Backup über die API einspielen |
| UFO-Patches | Patch zurücknehmen — **nicht** `git checkout` über den gesamten Baum |
| Paket | vorherige Version gezielt installieren, nicht pauschal deinstallieren |

Der Grundsatz: so gezielt wie möglich. Ein breiter Rücksetzer nimmt fremde
Änderungen mit, die niemand zurücknehmen wollte.

## 4. Ausführen

Ein Schritt nach dem anderen, mit Prüfung dazwischen. Nicht mehrere
Rücknahmen gleichzeitig — sonst ist bei einem Problem nicht zuordenbar, welche
davon es verursacht hat.

## 5. Objektiv verifizieren

Der wiederhergestellte Zustand muss der **Baseline** entsprechen, nicht dem
gewünschten Zielzustand. Vergleiche gegen die vor der Änderung erfasste rohe
Ausgabe: Dienststatus, Registry-Wert, Version, Hash, API-Zustand.

Prüfe zusätzlich, dass keine Reste der fehlgeschlagenen Änderung liegen
geblieben sind — halbe Installationen, verwaiste Dienste, offene Ports,
temporäre Regeln.

## 6. Abschließen

```bash
python C:\AgentSystem\bin\agentctl.py run finish --run-id <run> --outcome ROLLED_BACK --rollback "<was zurückgenommen wurde>" --tests "<Vergleich gegen Baseline>"
python C:\AgentSystem\bin\agentctl.py lock release --resource "<lock-id>" --token <token>
python C:\AgentSystem\bin\agentctl.py task state --task-id <id> --state ROLLED_BACK
python C:\AgentSystem\bin\agentctl.py exp record --key <aufgabenart> --method <methode> --rolled-back --error "<Grund>" --root-cause "<Ursache>"
```

Das Lock wird erst **nach** der verifizierten Wiederherstellung freigegeben.

## Wenn der Rollback selbst scheitert

Nicht improvisieren. Stoppe, sichere den aktuellen Zustand und melde dem
Benutzer: was versucht wurde, was fehlschlug, in welchem Zustand das System
jetzt ist, und welche Optionen bestehen. Ein inkonsistenter Zustand, der
bekannt ist, ist besser als einer, der durch weitere Versuche verschleiert
wird.

## Ergebnis

Melde: was zurückgenommen wurde, gegen welche Baseline verifiziert wurde, mit
welcher rohen Ausgabe, ob Reste gefunden wurden, und den Ledger-Zustand.
