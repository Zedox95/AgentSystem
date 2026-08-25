"""SubagentStop — strukturiertes Ergebnis erzwingen.

„Alles erledigt" ohne Evidenz ist keine gültige Antwort (AGENTS.md Abschnitt 24).
Fehlen Pflichtabschnitte, verhindert Exit 2 das Beenden, damit der Subagent
nachliefert.

Der `verification-agent` wird zusätzlich darauf geprüft, dass er genau eine der
drei zulässigen Bewertungen abgibt.
"""

from __future__ import annotations

import re
import sys

import hooklib

REQUIRED = ("STATUS:", "EVIDENCE:", "TESTS:", "NEXT_ACTION:")
VALID_STATUS = ("PASS", "FAIL", "INCONCLUSIVE")

# Subagenten, für die das strikte Format gilt.
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
            problems.append("fehlende Abschnitte: " + ", ".join(missing))
        if status is None:
            problems.append("kein auswertbares STATUS-Feld")
        elif bad_status:
            problems.append(
                f"STATUS '{status}' ist unzulässig — erlaubt sind "
                + " / ".join(VALID_STATUS)
            )
        sys.stderr.write(
            f"Ergebnisformat unvollständig ({'; '.join(problems)}). "
            "Antworte nach AGENTS.md Abschnitt 24 mit STATUS, EVIDENCE, CHANGES, "
            "TESTS, RISKS und NEXT_ACTION. Unter EVIDENCE gehören die tatsächlich "
            "ausgeführten Kommandos und deren rohe Ausgabe — keine Zusammenfassung."
        )
        sys.exit(2)

    hooklib.emit_nothing()


hooklib.safe(main)
