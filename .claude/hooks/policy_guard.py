"""PreToolUse — deterministic policy guard.

No model has a say here. The rules live in `agentsys.policy` and are
evaluable without network access.

* `deny`     — destructive and hard to reverse, belongs to the user
* `escalate` — legitimate, but from R2 on: the user confirms
* `allow`    — no rule matched, or a known read-only action

`allow` is deliberately only emitted for the allowlist. In all other cases
the hook does not respond at all, so the regular permission flow takes over
and the hook never grants rights it should not grant.
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
        _record(data, decision, "DENY")
        hooklib.pre_tool_decision(
            "deny",
            f"Policy Guard: {decision.reason} (rule: {decision.rule}). "
            "This action is R3 and must be performed by the user themself "
            "or explicitly approved.",
        )

    if decision.verdict == policy.ASK:
        _record(data, decision, "ASK")
        hooklib.pre_tool_decision(
            "escalate",
            f"Policy Guard: {decision.reason} (rule: {decision.rule}). "
            "Confirmation required.",
        )

    if decision.rule == "readonly-allowlist":
        hooklib.pre_tool_decision("allow", "Known read-only command (R0)")

    # No rule matched: normal permission flow.
    hooklib.emit_nothing()


def _record(data: dict, decision, verdict: str) -> None:
    """Logs only Deny/Ask - the normal case stays free of write load."""
    try:
        from agentsys import ledger
        ledger.log_event(
            f"POLICY_{verdict}",
            session_id=data.get("session_id"),
            tool=data.get("tool_name"),
            detail={
                "rule": decision.rule,
                "reason": decision.reason,
                "command": (data.get("tool_input") or {}).get("command"),
                "file_path": (data.get("tool_input") or {}).get("file_path"),
                "tool_use_id": data.get("tool_use_id"),
            },
        )
    except Exception:  # noqa: BLE001 - logging must never block
        pass


hooklib.safe(main)
