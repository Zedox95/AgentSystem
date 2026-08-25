"""Hook-Tests: die Hooks werden als echte Prozesse mit JSON auf stdin aufgerufen.

Das prüft, was im Betrieb tatsächlich passiert - nicht nur die Bibliothek
dahinter. Aufruf:

    python C:\\AgentSystem\\tests\\test_hooks.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(r"C:\AgentSystem")
HOOKS = ROOT / ".claude" / "hooks"

_TMP = tempfile.mkdtemp(prefix="agentsys-hooktest-")

FAILURES: list[str] = []


def run_hook(script: str, payload: dict) -> tuple[int, str, str]:
    environment = dict(os.environ)
    environment["AGENTSYSTEM_ROOT"] = _TMP
    environment["PYTHONIOENCODING"] = "utf-8"
    completed = subprocess.run(
        [sys.executable, str(HOOKS / script)],
        input=json.dumps(payload),
        capture_output=True, text=True, timeout=60,
        env=environment, cwd=str(HOOKS),
    )
    return completed.returncode, completed.stdout, completed.stderr


def decision_of(stdout: str) -> str | None:
    if not stdout.strip():
        return None
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return None
    block = data.get("hookSpecificOutput", {})
    return block.get("permissionDecision") or block.get("decision")


def check(condition: bool, message: str) -> None:
    if not condition:
        FAILURES.append(message)


# --------------------------------------------------------------------------
# policy_guard
# --------------------------------------------------------------------------
cases = [
    ("Bash", "rm -rf /", "deny"),
    ("PowerShell", "Format-Volume -DriveLetter D", "deny"),
    ("Bash", "git push --force origin main", "deny"),
    ("PowerShell", "Stop-Service -Name Spooler", "escalate"),
    ("Bash", "winget install Foo.Bar", "escalate"),
    ("Bash", "git status", "allow"),
    ("PowerShell", "Get-Service", "allow"),
    ("Bash", "echo hallo && python build.py", None),          # keine Regel -> keine Antwort
]
for tool, command, expected in cases:
    code, out, _ = run_hook("policy_guard.py", {
        "session_id": "test", "tool_name": tool,
        "tool_input": {"command": command}, "tool_use_id": "t1",
    })
    got = decision_of(out)
    check(code == 0, f"policy_guard sollte mit 0 enden bei {command!r}, war {code}")
    check(got == expected,
          f"policy_guard: {command!r} -> erwartet {expected}, war {got}")

# Control-Plane-Schutz über den Hook
code, out, _ = run_hook("policy_guard.py", {
    "tool_name": "Write",
    "tool_input": {"file_path": str(ROOT / ".claude" / "settings.json")},
})
check(decision_of(out) == "escalate", "Schreiben an settings.json muss escalate ergeben")

# Direkte Vault-Schreibzugriffe umgehen den verpflichtenden Candidate-/Archivist-
# Pfad und müssen unabhängig von Claude-Berechtigungen blockiert werden.
code, out, _ = run_hook("policy_guard.py", {
    "tool_name": "Write",
    "tool_input": {
        "file_path": str(Path.home() / "Documents" / "Obsidian Vault" / "03 Bereiche" / "test.md")
    },
})
check(decision_of(out) == "deny", "Direktes Schreiben in den Vault muss deny ergeben")

# --------------------------------------------------------------------------
# readonly_guard (verification-agent)
# --------------------------------------------------------------------------
readonly_cases = [
    ("Get-Service -Name Spooler", "allow"),
    ("git diff --stat", "allow"),
    ("curl -s https://example.com/api", "allow"),
    ("systemctl status nginx", "allow"),
    ("Set-Service -Name Spooler -StartupType Disabled", "deny"),
    ("Remove-Item C:/temp/x -Recurse", "deny"),
    ("git commit -m fix", "deny"),
    ("echo hallo > out.txt", "deny"),
    ("docker run -d nginx", "deny"),
    ("pip install requests", "deny"),
]
for command, expected in readonly_cases:
    code, out, _ = run_hook("readonly_guard.py", {
        "tool_name": "PowerShell", "tool_input": {"command": command},
    })
    got = decision_of(out)
    check(got == expected,
          f"readonly_guard: {command!r} -> erwartet {expected}, war {got}")

# --------------------------------------------------------------------------
# permission_request
# --------------------------------------------------------------------------
code, out, _ = run_hook("permission_request.py", {
    "tool_name": "Bash", "tool_input": {"command": "git status"},
})
check(decision_of(out) == "allow", "PermissionRequest muss git status erlauben")

code, out, _ = run_hook("permission_request.py", {
    "tool_name": "PowerShell", "tool_input": {"command": "Stop-Service -Name Spooler"},
})
check(decision_of(out) == "ask", "PermissionRequest muss Stop-Service nachfragen")

code, out, _ = run_hook("permission_request.py", {
    "tool_name": "Bash", "tool_input": {"command": "qm destroy 103"},
})
check(decision_of(out) == "deny", "PermissionRequest muss qm destroy verweigern")

# --------------------------------------------------------------------------
# subagent_stop
# --------------------------------------------------------------------------
code, _, err = run_hook("subagent_stop.py", {
    "agent_type": "verification-agent",
    "last_assistant_message": "Alles erledigt, hat funktioniert.",
})
check(code == 2, f"Ergebnis ohne Struktur muss blockieren (Exit 2), war {code}")
check("AGENTS.md" in err, "Blockmeldung muss auf das Format verweisen")

good = ("STATUS: PASS\nEVIDENCE: Get-Service gab Running zurück\n"
        "CHANGES: keine\nTESTS: Dienststatus erneut gelesen\n"
        "RISKS: keine\nNEXT_ACTION: abschließen")
code, _, _ = run_hook("subagent_stop.py", {
    "agent_type": "verification-agent", "last_assistant_message": good,
})
check(code == 0, f"Vollständiges Ergebnis darf nicht blockieren, war {code}")

bad_status = good.replace("STATUS: PASS", "STATUS: ERLEDIGT")
code, _, err = run_hook("subagent_stop.py", {
    "agent_type": "verification-agent", "last_assistant_message": bad_status,
})
check(code == 2, "Unzulässiger STATUS-Wert muss blockieren")

code, _, _ = run_hook("subagent_stop.py", {
    "agent_type": "Explore", "last_assistant_message": "irgendwas",
})
check(code == 0, "Fremde Agenten dürfen nicht blockiert werden")

# --------------------------------------------------------------------------
# config_guard
# --------------------------------------------------------------------------
code, _, err = run_hook("config_guard.py", {
    "config_source": "project_settings", "config_key": "hooks", "new_value": "{}",
})
check(code == 2, f"Änderung an hooks muss blockieren, war {code}")

code, _, _ = run_hook("config_guard.py", {
    "config_source": "project_settings", "config_key": "outputStyle",
    "new_value": "explanatory",
})
check(code == 0, "Unkritische Einstellung darf nicht blockieren")

code, _, _ = run_hook("config_guard.py", {
    "config_source": "policy_settings", "config_key": "permissions", "new_value": "{}",
})
check(code == 0, "policy_settings ist laut Dokumentation nicht blockierbar")

# --------------------------------------------------------------------------
# tool_failure — zweiter identischer Fehler muss warnen
# --------------------------------------------------------------------------
failure_payload = {
    "session_id": "test", "tool_name": "Bash",
    "tool_input": {"command": "systemctl restart nginx"},
    "error": "Failed to restart nginx.service: Unit not found",
}
code_first, _, _ = run_hook("tool_failure.py", failure_payload)
check(code_first == 0, f"Erster Fehler darf nicht warnen, war {code_first}")
code_second, _, err_second = run_hook("tool_failure.py", failure_payload)
check(code_second == 2, f"Zweiter identischer Fehler muss warnen, war {code_second}")
check("Retry Budget" in err_second, "Warnung muss das Retry Budget nennen")

# Ein anderer Fehler darf nicht als Wiederholung zählen.
code_other, _, _ = run_hook("tool_failure.py", {
    **failure_payload, "error": "Permission denied while opening socket"
})
check(code_other == 0, "Abweichender Fehler darf nicht als Wiederholung gelten")

# --------------------------------------------------------------------------
# task_completed — offener R3-Vorgang blockiert den Abschluss
# --------------------------------------------------------------------------
sys.path.insert(0, str(ROOT / "bin"))
os.environ["AGENTSYSTEM_ROOT"] = _TMP
from agentsys import knowledge, ledger  # noqa: E402

r3 = ledger.create_task("R3-Testvorgang", "R3")
ledger.set_state(r3, "PLANNED")
ledger.set_state(r3, "PREFLIGHT")
ledger.set_state(r3, "LOCKED")
ledger.set_state(r3, "BASELINED")
ledger.set_state(r3, "BACKED_UP")
ledger.set_state(r3, "EXECUTING")

code, _, err = run_hook("task_completed.py", {"task_id": "cc-1", "task_status": "completed"})
check(code == 2, f"Offener R3-Vorgang muss den Abschluss blockieren, war {code}")
check("R3" in err, "Blockmeldung muss den R3-Vorgang benennen")

ledger.set_state(r3, "ROLLING_BACK")
ledger.set_state(r3, "ROLLED_BACK")
code, _, _ = run_hook("task_completed.py", {"task_id": "cc-1", "task_status": "completed"})
check(code == 0, "Nach Rollback darf nicht mehr blockiert werden")

# Auch R1 darf erst nach einem vollständig belegten Gate abgeschlossen werden.
r1 = ledger.create_task(
    "R1-Commit-Gate", "R1", target_resource="test:r1",
    desired_state="Verifiziert abgeschlossen",
    planned_method="Isolierter Hook-Test",
    alternative_method="Test verwerfen",
    acceptance_criteria="TaskCompleted lässt erst den commit-bereiten Task passieren",
    rollback_plan="Temp-Verzeichnis entfernen",
)
for state in (
    "PLANNED", "PREFLIGHT", "LOCKED", "BASELINED", "BACKED_UP",
    "EXECUTING", "OBJECTIVE_TEST", "INDEPENDENT_VERIFY",
):
    ledger.set_state(r1, state)
r1_run = ledger.start_run(r1, "test", "Python", "Hook-Gate prüfen", "R1")
ledger.finish_run(
    r1_run, "PASS", change_summary="Hook-Testzustand erzeugt",
    objective_tests="TaskCompleted vor und nach Review ausgeführt",
    verification="PASS: deterministischer Hook-Test",
)
code, _, err = run_hook("task_completed.py", {"task_id": "cc-r1", "task_status": "completed"})
check(code == 2 and "Knowledge Review" in err,
      "R1 ohne Knowledge Review muss der Hook blockieren")
knowledge.review_task(
    r1, decision="none", reason="Isolierter Test erzeugt kein produktives Wissen",
)
code, _, _ = run_hook("task_completed.py", {"task_id": "cc-r1", "task_status": "completed"})
check(code == 0, "Commit-bereiter R1 muss den Hook passieren")
ledger.set_state(r1, "COMMITTED")

# --------------------------------------------------------------------------
# session_start — Kontext bei offenem Task
# --------------------------------------------------------------------------
open_task = ledger.create_task("Offener Testvorgang", "R2")
for state in ("PLANNED", "PREFLIGHT", "LOCKED", "BASELINED", "BACKED_UP", "EXECUTING"):
    ledger.set_state(open_task, state)
code, out, _ = run_hook("session_start.py", {"hook_event_name": "SessionStart"})
check(code == 0, "session_start darf nie blockieren")
context = json.loads(out).get("hookSpecificOutput", {}).get("additionalContext", "") if out.strip() else ""
check(open_task in context, "Offener Task muss im SessionStart-Kontext auftauchen")

# --------------------------------------------------------------------------
print(json.dumps({
    "status": "FAIL" if FAILURES else "PASS",
    "failures": FAILURES,
    "temp_root": _TMP,
}, ensure_ascii=False, indent=2))
sys.exit(1 if FAILURES else 0)
