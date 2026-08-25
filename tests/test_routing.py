"""Tests der Modell-Routung.

Die Fälle hier sind nicht ausgedacht, sondern beim Aufbau tatsächlich
danebengegangen. Jeder einzelne steht für einen Fehler, der ohne diesen Test
beim nächsten Nachschärfen der Muster stillschweigend zurückkäme:

* deutsche Wortbeugung — `vergleich\\b` trifft "Vergleiche" nicht
* trennbare Verben — "Starte den Spooler **neu**"
* Komposita — "Drucker**spooler**", "Grafik**treiber**"
* Handlung vor Objekt — "Treiber **prüfen**" ist keine Änderung

Der Hook wird als echter Prozess aufgerufen, nicht nur importiert.

    python C:\\AgentSystem\\tests\\test_routing.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(r"C:\AgentSystem")
HOOK = ROOT / ".claude" / "hooks" / "prompt_router.py"

sys.path.insert(0, str(ROOT / "bin"))

_TMP = tempfile.mkdtemp(prefix="agentsys-routing-")
os.environ["AGENTSYSTEM_ROOT"] = _TMP

from agentsys import routing  # noqa: E402

FAILURES: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        FAILURES.append(message)


# --------------------------------------------------------------------------
# Klassifikation: (Auftrag, Modell, Risiko, Domäne oder None)
# --------------------------------------------------------------------------
CASES: tuple[tuple[str, str, str, str | None], ...] = (
    # Routine — abfragend, nichts wird angefasst
    ("Zeig mir den Status des Agentensystems", "sonnet", "R0", None),
    ("Lies mir die Datei config.yaml vor", "sonnet", "R0", None),
    ("Wie viele Dateien liegen im Projektverzeichnis?", "sonnet", "R0", None),

    # Handlung vor Objekt: prüfen ist keine Änderung, auch nicht bei Treibern
    ("Pruefe meinen PC auf Fehler und veraltete Treiber", "sonnet", "R0", "windows"),
    ("Zeig mir alle laufenden Dienste", "sonnet", "R0", "windows"),

    # Echte Änderungen
    ("Installiere den neuen NVIDIA-Treiber", "sonnet", "R2", "windows"),
    ("Aktiviere die Firewall-Regel fuer Port 25565", "sonnet", "R2", None),
    ("Aktualisiere den Grafiktreiber", "sonnet", "R2", "windows"),

    # Trennbare Verben: die Partikel steht am Satzende
    ("Starte den Druckerspooler neu", "sonnet", "R2", "windows"),
    ("Fahre die virtuelle Maschine herunter", "sonnet", "R1", "infrastruktur"),

    # Komposita
    ("Deaktiviere den Systemdienst Spooler", "sonnet", "R2", "windows"),

    # Schwer umkehrbar
    ("Loesche die Partition D und formatiere sie neu", "opus", "R3", None),
    ("Entferne die alten Savegames vom ARK-Server", "opus", "R3", "gaming"),
    ("Setze den Router auf Werkseinstellungen zurueck", "opus", "R3", "browser"),

    # Denkarbeit — Beugung muss greifen
    ("Vergleiche Proxmox und Docker und empfiehl mir eins", "opus", "R0", "infrastruktur"),
    ("Warum startet der Minecraft-Server nicht mehr?", "opus", "R0", "gaming"),
    ("Die Portfreigabe am Router funktioniert nicht, finde die Ursache",
     "opus", "R0", "browser"),
    ("Analysiere, wieso die Verbindung dauernd abbricht", "opus", "R0", None),
)

for prompt, expected_model, expected_risk, expected_domain in CASES:
    result = routing.classify(prompt)
    check(result.model == expected_model,
          f"Modell: {prompt[:44]!r} -> {result.model}, erwartet {expected_model}")
    check(result.risk == expected_risk,
          f"Risiko: {prompt[:44]!r} -> {result.risk}, erwartet {expected_risk}")
    if expected_domain is not None:
        check(result.domain == expected_domain,
              f"Domäne: {prompt[:44]!r} -> {result.domain}, erwartet {expected_domain}")

# Ein Subagent gehört zu jeder erkannten Domäne.
for prompt, _, _, expected_domain in CASES:
    result = routing.classify(prompt)
    if expected_domain:
        check(result.agent is not None,
              f"Domäne {result.domain} ohne zuständigen Agenten: {prompt[:40]!r}")

# Unsicherheit wird gemeldet, statt sie zu verschweigen.
short = routing.classify("mach mal")
check(any("unsicher" in r for r in short.reasons),
      "Ein sehr kurzer Auftrag muss als unsicher gekennzeichnet werden")

# Der Klassifizierer darf nie abstürzen.
for edge in ("", "   ", "?" * 300, "ä" * 50, "Lösche\nalles\tsofort"):
    try:
        routing.classify(edge)
    except Exception as error:  # noqa: BLE001
        FAILURES.append(f"classify({edge[:20]!r}) wirft {error!r}")

# --------------------------------------------------------------------------
# Eskalation
# --------------------------------------------------------------------------
model, effort, _ = routing.escalate("sonnet", verifier_verdict="INCONCLUSIVE")
check((model, effort) == ("sonnet", "high"),
      f"INCONCLUSIVE darf das Modell nicht wechseln, war {model}/{effort}")

model, effort, _ = routing.escalate("sonnet", verifier_verdict="FAIL")
check((model, effort) == ("opus", "high"),
      f"FAIL muss auf opus eskalieren, war {model}/{effort}")

model, effort, _ = routing.escalate("opus", verifier_verdict="FAIL")
check((model, effort) == ("opus", "xhigh"),
      f"Bereits opus: Effort erhöhen statt Modell wechseln, war {model}/{effort}")

model, effort, _ = routing.escalate("sonnet", failed_attempts=2)
check(model == "opus", "Zwei gescheiterte Ansätze müssen eskalieren")

model, effort, _ = routing.escalate("sonnet", verifier_verdict="PASS")
check(model == "sonnet", "PASS darf nicht eskalieren")

# --------------------------------------------------------------------------
# Der Hook als echter Prozess
# --------------------------------------------------------------------------


def run_hook(prompt: str) -> tuple[int, dict | None]:
    completed = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps({"session_id": "test", "user_input": prompt}),
        capture_output=True, text=True, errors="replace", timeout=60,
        env={**os.environ, "AGENTSYSTEM_ROOT": _TMP, "PYTHONIOENCODING": "utf-8"},
        cwd=str(HOOK.parent),
    )
    try:
        return completed.returncode, json.loads(completed.stdout)
    except json.JSONDecodeError:
        return completed.returncode, None


code, payload = run_hook("Loesche die Partition D und formatiere sie neu")
check(code == 0, f"Der Hook darf nie blockieren, war {code}")
context = (payload or {}).get("hookSpecificOutput", {}).get("additionalContext", "")
check("R3" in context, "Bei R3 muss der Hook die Risikoklasse nennen")
check("preflight-change" in context, "Bei R3 muss der Hook auf preflight-change verweisen")
check("Freigabe" in context, "Bei R3 muss der Hook die Benutzerfreigabe erwähnen")
check("Hinweis, keine Anweisung" in context,
      "Der Hook muss kennzeichnen, dass seine Einordnung nicht bindend ist")

code, payload = run_hook("ok")
check(code == 0, "Ein sehr kurzer Prompt darf nicht blockieren")
check(not payload, "Bei einem sehr kurzen Prompt soll der Hook schweigen")

code, payload = run_hook("Zeig mir bitte einmal den aktuellen Status an")
check(code == 0, "Ein Routineprompt darf nicht blockieren")
check(not payload, "Bei einer reinen Routineaufgabe soll der Hook schweigen")

code, payload = run_hook("Warum funktioniert die Netzwerkverbindung nicht mehr?")
context = (payload or {}).get("hookSpecificOutput", {}).get("additionalContext", "")
check("opus" in context, "Bei einer offenen Frage muss opus empfohlen werden")

# --------------------------------------------------------------------------
print(json.dumps({
    "status": "FAIL" if FAILURES else "PASS",
    "faelle": len(CASES),
    "failures": FAILURES,
}, ensure_ascii=False, indent=2))
sys.exit(1 if FAILURES else 0)
