"""PreToolUse — deterministischer Policy Guard.

Kein Modell entscheidet hier mit. Die Regeln liegen in `agentsys.policy` und
sind ohne Netzwerkzugriff auswertbar.

* `deny`     — destruktiv und schwer umkehrbar, gehört dem Benutzer
* `escalate` — legitim, aber ab R2: der Benutzer bestätigt
* `allow`    — keine Regel getroffen oder bekannte lesende Aktion

`allow` wird bewusst nur für die Allowlist ausgegeben. In allen anderen Fällen
antwortet der Hook gar nicht, damit der reguläre Berechtigungsfluss greift und
der Hook keine Rechte erteilt, die er nicht erteilen soll.
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
            f"Policy Guard: {decision.reason} (Regel: {decision.rule}). "
            "Diese Aktion ist R3 und muss vom Benutzer selbst durchgeführt "
            "oder ausdrücklich freigegeben werden.",
        )

    if decision.verdict == policy.ASK:
        _record(data, decision, "ASK")
        hooklib.pre_tool_decision(
            "escalate",
            f"Policy Guard: {decision.reason} (Regel: {decision.rule}). "
            "Bestätigung erforderlich.",
        )

    if decision.rule == "readonly-allowlist":
        hooklib.pre_tool_decision("allow", "Bekanntes lesendes Kommando (R0)")

    # Keine Regel getroffen: normaler Berechtigungsfluss.
    hooklib.emit_nothing()


def _record(data: dict, decision, verdict: str) -> None:
    """Protokolliert nur Deny/Ask - der Normalfall bleibt ohne Schreiblast."""
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
    except Exception:  # noqa: BLE001 - Protokollierung darf nie blockieren
        pass


hooklib.safe(main)
