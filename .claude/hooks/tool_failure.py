"""PostToolUseFailure — Fehler erfassen und blinde Wiederholung verhindern.

Jeder Werkzeugfehler landet mit einem Fingerabdruck im Run Ledger. Wiederholt
sich derselbe Fingerabdruck, bekommt Claude einen ausdrücklichen Hinweis, die
Methode zu wechseln statt es erneut gleich zu versuchen (AGENTS.md Abschnitt 15).
"""

from __future__ import annotations

import hashlib
import re
import sys

import hooklib

# Wechselnde Bestandteile entfernen, damit derselbe Fehler denselben
# Fingerabdruck erzeugt: Zeitstempel, PIDs, Pfade mit Zufallsanteil, Adressen.
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

    # Wie oft ist genau dieser Fehler schon aufgetreten?
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
        # Exit 2 zeigt Claude die Meldung an, ohne den Ablauf abzubrechen -
        # das Werkzeug ist ohnehin bereits fehlgeschlagen.
        sys.stderr.write(
            f"Retry Budget: Dieser Fehler ist bereits {occurrences}-mal mit "
            f"identischem Fingerabdruck ({digest}) aufgetreten. "
            "AGENTS.md Abschnitt 15: dieselbe Methode nicht erneut unverändert "
            "versuchen. Ursache diagnostizieren, dann Methode wechseln, "
            "gegebenenfalls anderen Agenten oder Rollback."
        )
        sys.exit(2)

    hooklib.emit_nothing()


hooklib.safe(main)
