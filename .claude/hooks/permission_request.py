"""PermissionRequest — bekannte lesende Aktionen effizient zulassen.

Nur eindeutig lesende Einzelkommandos werden automatisch erlaubt. Alles andere
geht ausdrücklich an den Benutzer (`ask`). Es werden **keine** pauschalen
Schreibrechte erteilt.
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
            "deny", f"Policy Guard: {decision.reason} (Regel: {decision.rule})"
        )

    if decision.rule == "readonly-allowlist":
        hooklib.permission_decision(
            "allow", "Bekanntes lesendes Kommando ohne Seiteneffekt (R0)"
        )

    hooklib.permission_decision(
        "ask", f"Bestätigung erforderlich ({decision.reason})"
    )


hooklib.safe(main)
