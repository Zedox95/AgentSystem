"""Exercise the personal Codex plugin hooks as real subprocesses."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HOOKS = Path.home() / "plugins" / "kevin-agent-system" / "hooks"
TEMP_ROOT = Path(tempfile.mkdtemp(prefix="agentsys-codex-hooktest-"))
FAILURES: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        FAILURES.append(message)


def run(script: str, payload: dict) -> tuple[int, dict, str]:
    environment = dict(os.environ)
    environment["AGENTSYSTEM_ROOT"] = str(TEMP_ROOT)
    environment["PYTHONIOENCODING"] = "utf-8"
    completed = subprocess.run(
        [sys.executable, str(HOOKS / script)],
        input=json.dumps(payload), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=30, env=environment,
    )
    try:
        output = json.loads(completed.stdout) if completed.stdout.strip() else {}
    except json.JSONDecodeError:
        output = {}
        FAILURES.append(f"{script}: ungültiges JSON: {completed.stdout[:300]}")
    return completed.returncode, output, completed.stderr


def specific(output: dict) -> dict:
    return output.get("hookSpecificOutput", {})


code, output, _ = run("session_start.py", {
    "hook_event_name": "SessionStart", "source": "startup",
})
check(code == 0, "SessionStart muss mit 0 enden")
check("AgentSystem is active" in specific(output).get("additionalContext", ""),
      "SessionStart liefert keinen AgentSystem-Kontext")

code, output, _ = run("prompt_router.py", {
    "hook_event_name": "UserPromptSubmit",
    "prompt": "Installiere und konfiguriere einen Windows-Dienst mit Backup.",
})
check(code == 0, "UserPromptSubmit muss mit 0 enden")
check("preflight-change" in specific(output).get("additionalContext", ""),
      "R2-Prompt fordert den Preflight nicht an")

code, output, _ = run("policy_guard.py", {
    "hook_event_name": "PreToolUse", "permission_mode": "default",
    "tool_name": "Bash", "tool_input": {"command": "rm -rf /"},
})
check(specific(output).get("permissionDecision") == "deny",
      "destruktives Kommando wird nicht blockiert")

code, output, _ = run("policy_guard.py", {
    "hook_event_name": "PreToolUse", "permission_mode": "default",
    "tool_name": "PowerShell",
    "tool_input": {"command": "Stop-Service -Name Spooler"},
})
block = specific(output)
check("additionalContext" in block, "R2-Kommando liefert keine Risikowarnung")
check("permissionDecision" not in block,
      "Codex-inkompatibles ask/escalate darf nicht ausgegeben werden")

code, output, _ = run("policy_guard.py", {
    "hook_event_name": "PreToolUse", "permission_mode": "bypassPermissions",
    "tool_name": "PowerShell",
    "tool_input": {"command": "Stop-Service -Name Spooler"},
})
check(specific(output).get("permissionDecision") == "deny",
      "R2-Kommando im Bypass-Modus wird nicht blockiert")

code, output, _ = run("policy_guard.py", {
    "hook_event_name": "PreToolUse", "permission_mode": "default",
    "tool_name": "apply_patch",
    "tool_input": {"command": "*** Update File: C:\\AgentSystem\\AGENTS.md"},
})
check(specific(output).get("permissionDecision") == "deny",
      "Control-Plane-Patch ohne formalen Task/Lock wird nicht blockiert")

code, _, _ = run("subagent_stop.py", {
    "hook_event_name": "SubagentStop", "agent_type": "verification_agent",
    "last_assistant_message": "Alles erledigt.",
})
check(code == 2, "unstrukturiertes Verifier-Ergebnis muss blockiert werden")

good = (
    "STATUS: PASS\nEVIDENCE: raw\nCHANGES: none\nTESTS: rerun\n"
    "RISKS: none\nNEXT_ACTION: finish"
)
code, _, _ = run("subagent_stop.py", {
    "hook_event_name": "SubagentStop", "agent_type": "verification_agent",
    "last_assistant_message": good,
})
check(code == 0, "strukturiertes Verifier-Ergebnis muss passieren")

print(json.dumps({
    "status": "FAIL" if FAILURES else "PASS",
    "hook_dir": str(HOOKS),
    "failures": FAILURES,
}, ensure_ascii=False, indent=2))
sys.exit(1 if FAILURES else 0)

