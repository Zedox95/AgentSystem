"""Gemeinsame Basis aller Hooks.

Ein Hook läuft bei jedem Werkzeugaufruf. Er muss deshalb schnell starten, darf
nie unkontrolliert werfen und darf den Ablauf niemals wegen eines eigenen
Fehlers blockieren — außer, er blockiert absichtlich.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

# Die Kernbibliothek liegt außerhalb des Hook-Verzeichnisses.
_BIN = Path(__file__).resolve().parents[2] / "bin"
if str(_BIN) not in sys.path:
    sys.path.insert(0, str(_BIN))


def read_input() -> dict[str, Any]:
    """Liest die Hook-Eingabe von stdin. Bei Unlesbarkeit: leeres Dict."""
    try:
        raw = sys.stdin.read()
        return json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, OSError, ValueError):
        return {}


def emit(payload: dict[str, Any]) -> None:
    """Schreibt eine JSON-Antwort und beendet mit 0."""
    sys.stdout.write(json.dumps(payload, ensure_ascii=False))
    sys.stdout.flush()
    sys.exit(0)


def emit_nothing() -> None:
    sys.exit(0)


def block(reason: str) -> None:
    """Exit 2 blockiert die Aktion; stderr ist die Begründung."""
    sys.stderr.write(reason)
    sys.stderr.flush()
    sys.exit(2)


def pre_tool_decision(verdict: str, reason: str) -> None:
    """Antwortformat für PreToolUse."""
    emit({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": verdict,      # allow | deny | escalate
            "permissionDecisionReason": reason,
        }
    })


def permission_decision(decision: str, reason: str) -> None:
    """Antwortformat für PermissionRequest."""
    emit({
        "hookSpecificOutput": {
            "hookEventName": "PermissionRequest",
            "decision": decision,               # allow | deny | ask
            "permissionDecisionReason": reason,
        }
    })


def additional_context(event: str, text: str) -> None:
    """Stellt Claude zusätzlichen Kontext bereit."""
    emit({
        "hookSpecificOutput": {
            "hookEventName": event,
            "additionalContext": text,
        }
    })


def safe(main) -> None:
    """Führt einen Hook aus. Interne Fehler beenden mit 1 = nicht blockierend."""
    try:
        main()
    except SystemExit:
        raise
    except Exception as error:  # noqa: BLE001
        sys.stderr.write(f"[agentsys-hook] interner Fehler: {error!r}")
        sys.exit(1)
