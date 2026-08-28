"""Shared base for all hooks.

A hook runs on every tool call. It must therefore start fast, must never
throw uncontrolled, and must never block the flow because of its own
error — unless it is blocking intentionally.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

# The core library lives outside the hooks directory.
_BIN = Path(__file__).resolve().parents[2] / "bin"
if str(_BIN) not in sys.path:
    sys.path.insert(0, str(_BIN))


def read_input() -> dict[str, Any]:
    """Reads the hook input from stdin. If unreadable: empty dict."""
    try:
        raw = sys.stdin.read()
        return json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, OSError, ValueError):
        return {}


def emit(payload: dict[str, Any]) -> None:
    """Writes a JSON response and exits with 0."""
    sys.stdout.write(json.dumps(payload, ensure_ascii=False))
    sys.stdout.flush()
    sys.exit(0)


def emit_nothing() -> None:
    sys.exit(0)


def block(reason: str) -> None:
    """Exit 2 blocks the action; stderr carries the reason."""
    sys.stderr.write(reason)
    sys.stderr.flush()
    sys.exit(2)


def pre_tool_decision(verdict: str, reason: str) -> None:
    """Response format for PreToolUse."""
    emit({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": verdict,      # allow | deny | escalate
            "permissionDecisionReason": reason,
        }
    })


def permission_decision(decision: str, reason: str) -> None:
    """Response format for PermissionRequest."""
    emit({
        "hookSpecificOutput": {
            "hookEventName": "PermissionRequest",
            "decision": decision,               # allow | deny | ask
            "permissionDecisionReason": reason,
        }
    })


def additional_context(event: str, text: str) -> None:
    """Provides Claude with additional context."""
    emit({
        "hookSpecificOutput": {
            "hookEventName": event,
            "additionalContext": text,
        }
    })


def safe(main) -> None:
    """Runs a hook. Internal errors exit with 1 = non-blocking."""
    try:
        main()
    except SystemExit:
        raise
    except Exception as error:  # noqa: BLE001
        sys.stderr.write(f"[agentsys-hook] interner Fehler: {error!r}")
        sys.exit(1)
