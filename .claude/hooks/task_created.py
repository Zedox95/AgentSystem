"""TaskCreated — sicherheitsrelevante Angaben einfordern.

Fehlt einem neu angelegten Task erkennbar das Ziel, blockiert Exit 2 die
Anlage. Risikoklasse, Acceptance Criteria und Rollback lassen sich aus der
Beschreibung allein nicht zuverlässig ableiten; deshalb wird hier nur
protokolliert und - bei Hinweisen auf eine riskante Aktion - ausdrücklich an
den Task Contract erinnert.

Bewusste Zurückhaltung: dieser Hook soll die Arbeit strukturieren, nicht
alltägliche Aufgaben blockieren.
"""

from __future__ import annotations

import re
import sys

import hooklib

# Hinweise darauf, dass die Aufgabe mindestens R2 ist.
RISKY = re.compile(
    r"\b(treiber|driver|registry|dienst|service|firewall|partition|formatier"
    r"|boot|bios|firmware|migration|löschen|loeschen|delete|entfernen|remove"
    r"|deinstall|uninstall|proxmox|pterodactyl|wings|router|wan|vm\b|snapshot"
    r"|datenbank|database|savegame|welt|world|netzwerk|network|reinstall)\b",
    re.IGNORECASE,
)


def main() -> None:
    data = hooklib.read_input()
    description = str(data.get("task_description", "")).strip()
    task_id = data.get("task_id")

    from agentsys import ledger

    if not description:
        sys.stderr.write(
            "Task ohne Beschreibung wird nicht angelegt. Ein Task braucht ein "
            "beobachtbares Ziel (AGENTS.md Abschnitt 7)."
        )
        sys.exit(2)

    risky = bool(RISKY.search(description))

    ledger.log_event(
        "CC_TASK_CREATED",
        session_id=data.get("session_id"),
        detail={"task_id": task_id, "description": description[:400], "risky": risky},
    )

    if risky:
        # Exit 2 würde die Anlage zurückrollen. Das ist hier nicht gewollt -
        # stattdessen ein sichtbarer Hinweis über hookSpecificOutput.
        hooklib.additional_context(
            "TaskCreated",
            "Diese Aufgabe berührt Bereiche ab Risikoklasse R2. Vor der ersten "
            "Änderung gehören dazu: Task Contract im Ledger (Ziel, Zielressource, "
            "Desired State, Risikoklasse, Methode, Alternative, Acceptance "
            "Criteria, Rollback-Plan), Resource Lock, Baseline und Backup. "
            "Danach Objective Tests und der verification-agent, bevor Erfolg "
            "gemeldet wird.",
        )

    hooklib.emit_nothing()


hooklib.safe(main)
