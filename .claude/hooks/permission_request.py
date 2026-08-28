"""PermissionRequest — efficiently allow known read-only actions.

Only clearly read-only single commands are allowed automatically. Everything
else goes explicitly to the user (`ask`). **No** blanket write permissions
are ever granted.
"""

from __future__ import annotations

import hooklib


def main() -> None:
    data = hooklib.read_input()
    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input") or {}

    from agentsys import policy

    decision = policy.evaluate(tool_name, tool_input)

    if decision.verdict == policy.DENY:
        hooklib.permission_decision(
            "deny", f"Policy Guard: {decision.reason} (rule: {decision.rule})"
        )

    if decision.rule == "readonly-allowlist":
        hooklib.permission_decision(
            "allow", "Known read-only command with no side effect (R0)"
        )

    hooklib.permission_decision(
        "ask", f"Confirmation required ({decision.reason})"
    )


hooklib.safe(main)
