"""SubagentStop — enforce a structured result.

"All done" without evidence is not a valid answer (AGENTS.md section 24).
If required sections are missing, exit 2 prevents finishing so the subagent
supplies them.

The `verification-agent` is additionally checked to ensure it gives exactly
one of the three allowed verdicts.
"""

from __future__ import annotations

import re
import sys

import hooklib

REQUIRED = ("STATUS:", "EVIDENCE:", "TESTS:", "NEXT_ACTION:")
VALID_STATUS = ("PASS", "FAIL", "INCONCLUSIVE")

# Subagents for which the strict format applies.
STRICT_AGENTS = (
    "verification-agent", "windows-agent", "infrastructure-agent",
    "browser-agent", "gaming-agent", "implementation-agent",
)


def main() -> None:
    data = hooklib.read_input()
    agent_type = str(data.get("agent_type", ""))
    message = str(data.get("last_assistant_message", ""))

    from agentsys import ledger

    if agent_type not in STRICT_AGENTS:
        hooklib.emit_nothing()

    missing = [section for section in REQUIRED if section not in message]

    status_match = re.search(r"^STATUS:\s*(\w+)", message, re.MULTILINE)
    status = status_match.group(1).upper() if status_match else None
    bad_status = status is not None and status not in VALID_STATUS

    ledger.log_event(
        "SUBAGENT_RESULT",
        session_id=data.get("session_id"),
        agent=agent_type,
        detail={"status": status, "missing": missing, "agent_id": data.get("agent_id")},
    )

    if missing or bad_status or status is None:
        problems = []
        if missing:
            problems.append("missing sections: " + ", ".join(missing))
        if status is None:
            problems.append("no evaluable STATUS field")
        elif bad_status:
            problems.append(
                f"STATUS '{status}' is not permitted — allowed are "
                + " / ".join(VALID_STATUS)
            )
        sys.stderr.write(
            f"Result format incomplete ({'; '.join(problems)}). "
            "Respond per AGENTS.md section 24 with STATUS, EVIDENCE, CHANGES, "
            "TESTS, RISKS, and NEXT_ACTION. EVIDENCE must contain the actually "
            "executed commands and their raw output — not a summary."
        )
        sys.exit(2)

    hooklib.emit_nothing()


hooklib.safe(main)
