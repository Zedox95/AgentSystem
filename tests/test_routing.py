"""Tests for model routing.

The cases here aren't made up — they actually went wrong while this was
being built. Each one stands for a bug that would silently come back the
next time the patterns get refined, without this test:

* German word inflection — `vergleich\\b` doesn't match "Vergleiche"
* separable verbs — "Starte den Spooler **neu**" (restart)
* compounds — "Drucker**spooler**" (print spooler), "Grafik**treiber**" (graphics driver)
* action before object — "Treiber **prüfen**" (check driver) is not a change

The hook is invoked as a real process, not just imported.

    python C:\\AgentSystem\\tests\\test_routing.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
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
# Classification: (prompt, model, risk, domain or None)
# --------------------------------------------------------------------------
CASES: tuple[tuple[str, str, str, str | None], ...] = (
    # Routine — inquiring, nothing is touched
    ("Zeig mir den Status des Agentensystems", "sonnet", "R0", None),
    ("Lies mir die Datei config.yaml vor", "sonnet", "R0", None),
    ("Wie viele Dateien liegen im Projektverzeichnis?", "sonnet", "R0", None),

    # Action before object: checking is not a change, not even for drivers
    ("Pruefe meinen PC auf Fehler und veraltete Treiber", "sonnet", "R0", "windows"),
    ("Zeig mir alle laufenden Dienste", "sonnet", "R0", "windows"),

    # Real changes
    ("Installiere den neuen NVIDIA-Treiber", "sonnet", "R2", "windows"),
    ("Aktiviere die Firewall-Regel fuer Port 25565", "sonnet", "R2", None),
    ("Aktualisiere den Grafiktreiber", "sonnet", "R2", "windows"),

    # Separable verbs: the particle sits at the end of the sentence
    ("Starte den Druckerspooler neu", "sonnet", "R2", "windows"),
    ("Fahre die virtuelle Maschine herunter", "sonnet", "R1", "infrastruktur"),

    # Compounds
    ("Deaktiviere den Systemdienst Spooler", "sonnet", "R2", "windows"),

    # Hard to reverse
    ("Loesche die Partition D und formatiere sie neu", "opus", "R3", None),
    ("Entferne die alten Savegames vom ARK-Server", "opus", "R3", "gaming"),
    ("Setze den Router auf Werkseinstellungen zurueck", "opus", "R3", "browser"),

    # Reasoning work — inflection must be caught
    ("Vergleiche Proxmox und Docker und empfiehl mir eins", "opus", "R0", "infrastruktur"),
    ("Warum startet der Minecraft-Server nicht mehr?", "opus", "R0", "gaming"),
    ("Die Portfreigabe am Router funktioniert nicht, finde die Ursache",
     "opus", "R0", "browser"),
    ("Analysiere, wieso die Verbindung dauernd abbricht", "opus", "R0", None),
)

for prompt, expected_model, expected_risk, expected_domain in CASES:
    result = routing.classify(prompt)
    check(result.model == expected_model,
          f"Model: {prompt[:44]!r} -> {result.model}, expected {expected_model}")
    check(result.risk == expected_risk,
          f"Risk: {prompt[:44]!r} -> {result.risk}, expected {expected_risk}")
    if expected_domain is not None:
        check(result.domain == expected_domain,
              f"Domain: {prompt[:44]!r} -> {result.domain}, expected {expected_domain}")

# A subagent belongs to every recognized domain.
for prompt, _, _, expected_domain in CASES:
    result = routing.classify(prompt)
    if expected_domain:
        check(result.agent is not None,
              f"Domain {result.domain} without a responsible agent: {prompt[:40]!r}")

# Uncertainty is reported, not hidden.
short = routing.classify("mach mal")
check(any("uncertain" in r for r in short.reasons),
      "A very short prompt must be flagged as uncertain")

# The classifier must never crash.
for edge in ("", "   ", "?" * 300, "ä" * 50, "Lösche\nalles\tsofort"):
    try:
        routing.classify(edge)
    except Exception as error:  # noqa: BLE001
        FAILURES.append(f"classify({edge[:20]!r}) raises {error!r}")

# --------------------------------------------------------------------------
# Escalation
# --------------------------------------------------------------------------
model, effort, _ = routing.escalate("sonnet", verifier_verdict="INCONCLUSIVE")
check((model, effort) == ("sonnet", "high"),
      f"INCONCLUSIVE must not change the model, was {model}/{effort}")

model, effort, _ = routing.escalate("sonnet", verifier_verdict="FAIL")
check((model, effort) == ("opus", "high"),
      f"FAIL must escalate to opus, was {model}/{effort}")

model, effort, _ = routing.escalate("opus", verifier_verdict="FAIL")
check((model, effort) == ("opus", "xhigh"),
      f"Already opus: raise effort instead of switching model, was {model}/{effort}")

model, effort, _ = routing.escalate("sonnet", failed_attempts=2)
check(model == "opus", "Two failed attempts must escalate")

model, effort, _ = routing.escalate("sonnet", verifier_verdict="PASS")
check(model == "sonnet", "PASS must not escalate")

# --------------------------------------------------------------------------
# The hook as a real process
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
check(code == 0, f"The hook must never block, was {code}")
context = (payload or {}).get("hookSpecificOutput", {}).get("additionalContext", "")
check("R3" in context, "For R3 the hook must name the risk class")
check("preflight-change" in context, "For R3 the hook must reference preflight-change")
check("approval" in context, "For R3 the hook must mention user approval")
check("a hint, not an instruction" in context,
      "The hook must indicate that its classification is not binding")

code, payload = run_hook("ok")
check(code == 0, "A very short prompt must not block")
check(not payload, "For a very short prompt the hook should stay silent")

code, payload = run_hook("Zeig mir bitte einmal den aktuellen Status an")
check(code == 0, "A routine prompt must not block")
check(not payload, "For a purely routine task the hook should stay silent")

code, payload = run_hook("Warum funktioniert die Netzwerkverbindung nicht mehr?")
context = (payload or {}).get("hookSpecificOutput", {}).get("additionalContext", "")
check("opus" in context, "For an open-ended question, opus must be recommended")

# --------------------------------------------------------------------------
print(json.dumps({
    "status": "FAIL" if FAILURES else "PASS",
    "faelle": len(CASES),
    "failures": FAILURES,
}, ensure_ascii=False, indent=2))
sys.exit(1 if FAILURES else 0)
