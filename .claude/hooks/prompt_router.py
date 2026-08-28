"""UserPromptSubmit — classifies every task before it is handled.

The hook **cannot** switch the running session's model — by the time it
fires, that model has already read the prompt. Its purpose is different: it
ensures the classification happens **deterministically** instead of being
left to the gut feeling of the model that is currently responding.

The recommendation can take effect in two places:

1. The lead agent delegates the task to a subagent and sets the model per
   call — that is where the routing actually applies.
2. On a clear mismatch, the user gets a hint that a session switch is
   worthwhile.

Deliberately restrained: the hook only speaks up when it has something to
contribute. A note on every prompt would be noise and would soon be
ignored.
"""

from __future__ import annotations

import hooklib

# Below this length, classification isn't worthwhile — "yes", "go on", "thanks".
MIN_LENGTH = 25


def main() -> None:
    data = hooklib.read_input()
    prompt = str(data.get("user_input") or "").strip()

    if len(prompt) < MIN_LENGTH:
        hooklib.emit_nothing()

    from agentsys import routing

    result = routing.classify(prompt)

    # The normal case stays silent: routine task, no risk, no
    # subagent — there is nothing to say about that.
    if (not result.needs_stronger_model and result.risk in ("R0", "R1")
            and result.agent is None):
        _record(data, result)
        hooklib.emit_nothing()

    lines = [f"Classification (rule-based, no model call): "
             f"**{result.domain} · {result.risk} · recommended {result.model} "
             f"with effort {result.effort}**"]

    if result.reasons:
        lines.append("Reason: " + "; ".join(result.reasons))

    if result.agent:
        lines.append(
            f"`{result.agent}` would be responsible. On delegation, set the model per "
            f"call to `{result.model}` — that is where the routing "
            "actually applies."
        )

    if result.risk in ("R2", "R3"):
        lines.append(
            f"{result.risk}: before the first change, `preflight-change` — "
            "task contract, lock, baseline, backup, rollback plan."
            + (" R3 additionally needs the user's explicit approval."
               if result.risk == "R3" else "")
        )

    if result.needs_stronger_model:
        lines.append(
            "If this session is running on the weaker model: either delegate "
            "the reasoning-intensive parts to a subagent with `model: opus`, "
            "or suggest a session switch to the user. "
            "The classification alone is not a reason to switch unprompted."
        )

    lines.append(
        "This classification is a hint, not an instruction. If it contradicts "
        "what you observe on the system, the observation prevails."
    )

    _record(data, result)
    hooklib.additional_context("UserPromptSubmit", "\n".join(lines))


def _record(data: dict, result) -> None:
    """Logs only the classification; prompt content stays out of the ledger."""
    try:
        from agentsys import ledger
        ledger.log_event(
            "PROMPT_ROUTED",
            session_id=data.get("session_id"),
            detail={
                "domain": result.domain,
                "agent": result.agent,
                "risk": result.risk,
                "model": result.model,
                "effort": result.effort,
                "reasons": result.reasons,
            },
        )
    except Exception:  # noqa: BLE001 - logging must never block
        pass


hooklib.safe(main)
