"""PostToolUseFailure — capture errors and prevent blind retries.

Every tool error lands in the run ledger with a fingerprint. If the same
fingerprint recurs, Claude gets an explicit hint to switch methods instead
of trying the exact same thing again (AGENTS.md section 15).
"""

from __future__ import annotations

import hashlib
import re
import sys

import hooklib

# Strip volatile parts so the same error produces the same
# fingerprint: timestamps, PIDs, paths with random components, addresses.
_NOISE = re.compile(
    r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}\S*"
    r"|0x[0-9a-f]{4,}"
    r"|\b\d{3,}\b"
    r"|[a-f0-9]{16,}",
    re.IGNORECASE,
)


def fingerprint_error(tool: str, command: str, error: str) -> str:
    canonical = _NOISE.sub("#", f"{tool}|{command[:200]}|{error[:400]}").lower()
    return hashlib.sha256(canonical.encode("utf-8", "replace")).hexdigest()[:16]


def main() -> None:
    data = hooklib.read_input()
    tool = data.get("tool_name", "")
    tool_input = data.get("tool_input") or {}
    command = str(tool_input.get("command") or tool_input.get("file_path") or "")
    error = str(data.get("error") or "")

    digest = fingerprint_error(tool, command, error)

    from agentsys import ledger

    ledger.log_event(
        "TOOL_FAILURE",
        session_id=data.get("session_id"),
        tool=tool,
        detail={
            "fingerprint": digest,
            "command": command[:500],
            "error": error[:1000],
            "tool_use_id": data.get("tool_use_id"),
        },
    )

    # How many times has exactly this error already occurred?
    try:
        with ledger.connect() as connection:
            occurrences = connection.execute(
                "SELECT COUNT(*) FROM events WHERE event_type = 'TOOL_FAILURE'"
                " AND detail LIKE ?",
                (f'%"fingerprint": "{digest}"%',),
            ).fetchone()[0]
    except Exception:  # noqa: BLE001
        occurrences = 1

    if occurrences >= 2:
        # Exit 2 shows Claude the message without aborting the flow -
        # the tool has already failed anyway.
        sys.stderr.write(
            f"Retry Budget: this error has already occurred {occurrences} times with "
            f"an identical fingerprint ({digest}). "
            "AGENTS.md section 15: do not try the same method again unchanged. "
            "Diagnose the cause, then switch method, "
            "if needed a different agent or a rollback."
        )
        sys.exit(2)

    hooklib.emit_nothing()


hooklib.safe(main)
