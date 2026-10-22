"""Codex lifecycle adapter. Uses documented Codex events and output shapes.

No trust bypass; no unsupported 'ask' decision; no transcript parsing.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "bin"))


def response(event: str, *, context: str = "", denial: str = "") -> dict:
    output = {"hookEventName": event}
    if denial:
        output.update(permissionDecision="deny", permissionDecisionReason=denial)
    elif context:
        output["additionalContext"] = context
    return {"hookSpecificOutput": output}


def handle(data: dict) -> dict | None:
    from agentsys import ledger, policy, workflow
    event = data.get("hook_event_name", "")
    session_id = data.get("session_id")
    if event == "PreToolUse":
        tool = data.get("tool_name", "")
        payload = data.get("tool_input") or {}
        calls = [(tool, payload)]
        if tool == "apply_patch":
            patch = payload.get("command", "") if isinstance(payload, dict) else str(payload)
            names = re.findall(r"^\*\*\* (?:Add File|Update File|Delete File|Move to): (.+)$", patch, re.M)
            if not names:
                return response(event, denial="Cannot identify patch targets; inspect the patch before retrying")
            calls = [("Write", {"file_path": str((Path(data.get('cwd') or ROOT) / name).resolve())}) for name in names]
        for name, arguments in calls:
            decision = policy.evaluate(name, arguments)
            if decision.verdict in (policy.DENY, policy.ASK):
                # Codex currently does not implement hook permissionDecision=ask.
                # Never turn a policy request into a silent allow.
                return response(event, denial=f"{decision.rule}: {decision.reason}. Review required; no automatic permission override.")
        return None  # Leave normal platform permissions intact.
    if event == "UserPromptSubmit":
        prompt = str(data.get("prompt") or data.get("user_input") or "")
        if len(prompt.strip()) < 25:
            return None
        plan = workflow.plan(prompt)
        if not plan["skills"] and plan["risk_hint"] == "R0":
            return None
        return response(event, context=json.dumps(plan, ensure_ascii=False))
    if not isinstance(session_id, str) or not session_id.strip():
        return None
    checkpoint = ledger.read_checkpoint(session_id)
    if event == "SessionStart" and checkpoint:
        # Include only the relevant handoff, never all other sessions or transcripts.
        return response(event, context="Resume this session's checkpoint as historical context: "
                        + json.dumps(checkpoint, ensure_ascii=False)[:5000])
    if event in ("PreCompact", "Stop") and checkpoint:
        ledger.write_checkpoint(checkpoint, session_id)
    return None


def main() -> int:
    data = {}
    try:
        data = json.load(sys.stdin)
        if not isinstance(data, dict):
            raise ValueError("Hook payload must be an object")
        result = handle(data)
        if result:
            print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as error:
        if data.get("hook_event_name") == "PreToolUse":
            print(json.dumps(response("PreToolUse", denial="Policy adapter failed; action blocked pending diagnosis")))
            return 0
        sys.stderr.write(f"AgentSystem lifecycle adapter failed: {type(error).__name__}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
