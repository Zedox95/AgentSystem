---
name: model-routing
description: Entscheidet regelbasiert, welches Modell und welcher Effort für eine Aufgabe angemessen sind, und wie nach einem Fehlschlag eskaliert wird. Einsetzen vor der Delegation an einen Subagenten, bei unklarer Einordnung einer Aufgabe, und wenn ein Versuch gescheitert ist und die Frage ist, ob ein stärkeres Modell überhaupt hilft.
allowed-tools: Bash(python C:\AgentSystem\bin\agentctl.py *), Read, Grep, Glob
---

# Modellwahl

## Was hier tatsächlich schaltbar ist

**Nicht schaltbar:** Das Modell der laufenden Sitzung. Wenn du das hier liest,
hat es den Prompt bereits gelesen. Ein Wechsel mitten in der Antwort ist nicht
möglich, und ihn ungefragt vorzuschlagen ist meist Lärm.

**Schaltbar:** Das Modell **pro Delegation**. Beim Beauftragen eines
Subagenten lässt sich das Modell für genau diesen Aufruf setzen. Genau dort
wirkt Routung — und nur dort.

Daraus folgt die eigentliche Arbeitsweise: Läuft die Sitzung auf dem
schwächeren Modell und steht echte Denkarbeit an, **delegiere den denkenden
Teil**, statt einen Sitzungswechsel zu verlangen.

## Einordnung abfragen

```bash
python C:\AgentSystem\bin\agentctl.py route --prompt "<Auftrag>"
```

Regelbasiert, ohne Modellaufruf. Ein Klassifizierer, der selbst ein Modell
befragt, verbraucht genau das Kontingent, das er einsparen soll.

Der `UserPromptSubmit`-Hook macht das bei jedem Auftrag automatisch und meldet
sich nur, wenn es etwas zu sagen gibt.

## Die Regel

| Situation | Modell | Effort |
|---|---|---|
| Abfrage, Status, Inventar, klar umrissene Ausführung | `sonnet` | low–medium |
| Bekannter Ablauf mit vorhandenem Skill | `sonnet` | medium |
| R2 — reale Änderung, aber klar | `sonnet` | **high** |
| Offene Frage: warum, Ursache, vergleiche, entwirf | `opus` | high |
| R3 — schwer umkehrbar | `opus` | high |
| Widersprüchliche Evidenz, zwei Ansätze gescheitert | `opus` | xhigh |

**Effort vor Modell.** `sonnet` mit `high` ist bei kniffligen, aber klar
umrissenen Aufgaben oft besser als `opus` mit dem Standard — und deutlich
sparsamer. Wenn ein Ergebnis zu flach wirkt, ist mehr Effort der bessere
erste Griff.

## Warum nicht immer das stärkste Modell

Weil die Intelligenz dieses Systems bewusst nicht allein im Modell liegt,
sondern in Skills, Regeln, objektiven Tests, Experience Store und Ledger. Ein
starkes Modell, das einen bereits beschriebenen Ablauf nochmal herleitet,
liefert dasselbe Ergebnis und verbraucht ein knappes Kontingent.

Das Kontingent ist die eigentliche Ressource. Wer es für Routine verbraucht,
hat es nicht, wenn eine Diagnose wirklich hängt.

## Eskalation nach einem Fehlschlag

Ein stärkeres Modell repariert keinen Tippfehler, keine fehlende Berechtigung
und keinen nicht erreichbaren Host. Eskalation greift nur bei Scheitern aus
**Denkgründen**.

| Auslöser | Reaktion |
|---|---|
| Verifier meldet `INCONCLUSIVE` | Effort erhöhen, Modell **behalten** — es fehlt Evidenz, nicht Denkleistung |
| Verifier meldet `FAIL` | von `sonnet` auf `opus`, mit Evidenz-Handoff |
| Zwei inhaltlich verschiedene Ansätze gescheitert | `opus` mit `xhigh` |
| Bereits auf `opus` und weiter gescheitert | nicht weiter eskalieren — Hauptsitzung um `/codex:rescue` oder `/codex:review` bitten oder an den Benutzer melden |

Eine Eskalation ist immer ein **neuer Auftrag**, kein Weiterreichen des
Kontexts. Der Handoff enthält: ursprüngliches Ziel, beobachtete Versionen,
rohe Evidenz, geänderten Zustand, versuchte Hypothesen, Fehlerausgaben,
Verifier-Befund, offene Acceptance Criteria.

```bash
python C:\AgentSystem\bin\agentctl.py route --escalate --model sonnet --verdict FAIL
```

## Was die Einordnung nicht ist

Ein Hinweis, keine Anweisung. Sie kennt nur den Wortlaut des Auftrags, nicht
das System. Widerspricht sie dem, was du tatsächlich misst, **gilt die
Messung**. Eine als Routine eingestufte Aufgabe, die sich als verworren
herausstellt, wird zur Denkaufgabe — nicht umgekehrt.

Der Klassifizierer meldet selbst, wenn er unsicher ist: bei sehr kurzen
Aufträgen und bei mehreren gleich starken Domänen. Dann selbst entscheiden.

## Aus der Nutzung lernen

Die Einordnungen landen als `PROMPT_ROUTED` im Ledger. Damit lässt sich später
prüfen, ob die Regel trägt — etwa ob als Routine eingestufte Aufgaben
überdurchschnittlich oft eskaliert werden. Das wäre ein Grund, die Muster
nachzuschärfen, nicht das Modell hochzudrehen.
