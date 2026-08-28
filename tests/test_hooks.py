"""Hook tests: the hooks are invoked as real processes with JSON on stdin.

This checks what actually happens at runtime - not just the library
behind it. Invocation:

    python C:\\AgentSystem\\tests\\test_hooks.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
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
    ("Bash", "echo hallo && python build.py", None),          # no rule -> no response
]
for tool, command, expected in cases:
    code, out, _ = run_hook("policy_guard.py", {
        "session_id": "test", "tool_name": tool,
        "tool_input": {"command": command}, "tool_use_id": "t1",
    })
    got = decision_of(out)
    check(code == 0, f"policy_guard should end with 0 for {command!r}, was {code}")
    check(got == expected,
          f"policy_guard: {command!r} -> expected {expected}, was {got}")

# Control plane protection via the hook. The hook's own AGENTSYSTEM_ROOT is
# redirected to _TMP for isolation (see run_hook), so the path under test
# must be _TMP's control plane, not this test file's own repo root.
code, out, _ = run_hook("policy_guard.py", {
    "tool_name": "Write",
    "tool_input": {"file_path": str(Path(_TMP) / ".claude" / "settings.json")},
})
check(decision_of(out) == "escalate", "Writing to settings.json must yield escalate")

# Direct vault writes bypass the mandatory candidate/archivist path and
# must be blocked independently of Claude permissions.
code, out, _ = run_hook("policy_guard.py", {
    "tool_name": "Write",
    "tool_input": {
        "file_path": str(Path.home() / "Documents" / "Obsidian Vault" / "03 Bereiche" / "test.md")
    },
})
check(decision_of(out) == "deny", "Direct write into the vault must yield deny")

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
          f"readonly_guard: {command!r} -> expected {expected}, was {got}")

# --------------------------------------------------------------------------
# permission_request
# --------------------------------------------------------------------------
code, out, _ = run_hook("permission_request.py", {
    "tool_name": "Bash", "tool_input": {"command": "git status"},
})
check(decision_of(out) == "allow", "PermissionRequest must allow git status")

code, out, _ = run_hook("permission_request.py", {
    "tool_name": "PowerShell", "tool_input": {"command": "Stop-Service -Name Spooler"},
})
check(decision_of(out) == "ask", "PermissionRequest must ask for Stop-Service")

code, out, _ = run_hook("permission_request.py", {
    "tool_name": "Bash", "tool_input": {"command": "qm destroy 103"},
})
check(decision_of(out) == "deny", "PermissionRequest must deny qm destroy")

# --------------------------------------------------------------------------
# subagent_stop
# --------------------------------------------------------------------------
code, _, err = run_hook("subagent_stop.py", {
    "agent_type": "verification-agent",
    "last_assistant_message": "All done, it worked.",
})
check(code == 2, f"Result without structure must block (exit 2), was {code}")
check("AGENTS.md" in err, "Block message must reference the format")

good = ("STATUS: PASS\nEVIDENCE: Get-Service returned Running\n"
        "CHANGES: none\nTESTS: service status read back\n"
        "RISKS: none\nNEXT_ACTION: close out")
code, _, _ = run_hook("subagent_stop.py", {
    "agent_type": "verification-agent", "last_assistant_message": good,
})
check(code == 0, f"Complete result must not block, was {code}")

bad_status = good.replace("STATUS: PASS", "STATUS: ERLEDIGT")
code, _, err = run_hook("subagent_stop.py", {
    "agent_type": "verification-agent", "last_assistant_message": bad_status,
})
check(code == 2, "Invalid STATUS value must block")

code, _, _ = run_hook("subagent_stop.py", {
    "agent_type": "Explore", "last_assistant_message": "irgendwas",
})
check(code == 0, "Unrelated agents must not be blocked")

# --------------------------------------------------------------------------
# config_guard
# --------------------------------------------------------------------------
code, _, err = run_hook("config_guard.py", {
    "config_source": "project_settings", "config_key": "hooks", "new_value": "{}",
})
check(code == 2, f"Change to hooks must block, was {code}")

code, _, _ = run_hook("config_guard.py", {
    "config_source": "project_settings", "config_key": "outputStyle",
    "new_value": "explanatory",
})
check(code == 0, "Non-critical setting must not block")

code, _, _ = run_hook("config_guard.py", {
    "config_source": "policy_settings", "config_key": "permissions", "new_value": "{}",
})
check(code == 0, "policy_settings is not blockable per the documentation")

# --------------------------------------------------------------------------
# tool_failure — a second identical failure must warn
# --------------------------------------------------------------------------
failure_payload = {
    "session_id": "test", "tool_name": "Bash",
    "tool_input": {"command": "systemctl restart nginx"},
    "error": "Failed to restart nginx.service: Unit not found",
}
code_first, _, _ = run_hook("tool_failure.py", failure_payload)
check(code_first == 0, f"First failure must not warn, was {code_first}")
code_second, _, err_second = run_hook("tool_failure.py", failure_payload)
check(code_second == 2, f"Second identical failure must warn, was {code_second}")
check("Retry Budget" in err_second, "Warning must name the retry budget")

# A different failure must not count as a repeat.
code_other, _, _ = run_hook("tool_failure.py", {
    **failure_payload, "error": "Permission denied while opening socket"
})
check(code_other == 0, "A different failure must not count as a repeat")

# --------------------------------------------------------------------------
# task_completed — an open R3 task blocks completion
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
check(code == 2, f"Open R3 task must block completion, was {code}")
check("R3" in err, "Block message must name the R3 task")

ledger.set_state(r3, "ROLLING_BACK")
ledger.set_state(r3, "ROLLED_BACK")
code, _, _ = run_hook("task_completed.py", {"task_id": "cc-1", "task_status": "completed"})
check(code == 0, "Must no longer block after rollback")

# R1 too may only be completed after a fully evidenced gate.
r1 = ledger.create_task(
    "R1 commit gate", "R1", target_resource="test:r1",
    desired_state="Verified and completed",
    planned_method="Isolated hook test",
    alternative_method="Discard the test",
    acceptance_criteria="TaskCompleted only lets a commit-ready task pass",
    rollback_plan="Remove the temp directory",
)
for state in (
    "PLANNED", "PREFLIGHT", "LOCKED", "BASELINED", "BACKED_UP",
    "EXECUTING", "OBJECTIVE_TEST", "INDEPENDENT_VERIFY",
):
    ledger.set_state(r1, state)
r1_run = ledger.start_run(r1, "test", "Python", "Check hook gate", "R1")
ledger.finish_run(
    r1_run, "PASS", change_summary="Created hook test state",
    objective_tests="TaskCompleted run before and after review",
    verification="PASS: deterministic hook test",
)
code, _, err = run_hook("task_completed.py", {"task_id": "cc-r1", "task_status": "completed"})
check(code == 2 and "Knowledge Review" in err,
      "R1 without knowledge review must be blocked by the hook")
knowledge.review_task(
    r1, decision="none", reason="Isolierter Test erzeugt kein produktives Wissen",
)
code, _, _ = run_hook("task_completed.py", {"task_id": "cc-r1", "task_status": "completed"})
check(code == 0, "A commit-ready R1 must pass the hook")
ledger.set_state(r1, "COMMITTED")

# --------------------------------------------------------------------------
# session_start — context for an open task
# --------------------------------------------------------------------------
open_task = ledger.create_task("Offener Testvorgang", "R2")
for state in ("PLANNED", "PREFLIGHT", "LOCKED", "BASELINED", "BACKED_UP", "EXECUTING"):
    ledger.set_state(open_task, state)
code, out, _ = run_hook("session_start.py", {"hook_event_name": "SessionStart"})
check(code == 0, "session_start must never block")
context = json.loads(out).get("hookSpecificOutput", {}).get("additionalContext", "") if out.strip() else ""
check(open_task in context, "Open task must appear in the SessionStart context")

# --------------------------------------------------------------------------
print(json.dumps({
    "status": "FAIL" if FAILURES else "PASS",
    "failures": FAILURES,
    "temp_root": _TMP,
}, ensure_ascii=False, indent=2))
sys.exit(1 if FAILURES else 0)
