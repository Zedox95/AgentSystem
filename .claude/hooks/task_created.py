"""TaskCreated — require safety-relevant information.

If a newly created task is recognizably missing a goal, exit 2 blocks its
creation. Risk class, acceptance criteria, and rollback cannot be reliably
derived from the description alone; so this hook only logs and - on hints
of a risky action - explicitly reminds about the task contract.

Deliberate restraint: this hook is meant to structure the work, not to
block everyday tasks.
"""

from __future__ import annotations

import re
import sys

import hooklib

# Hints that the task is at least R2.
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
            "A task without a description is not created. A task needs an "
            "observable goal (AGENTS.md section 7)."
        )
        sys.exit(2)

    risky = bool(RISKY.search(description))

    ledger.log_event(
        "CC_TASK_CREATED",
        session_id=data.get("session_id"),
        detail={"task_id": task_id, "description": description[:400], "risky": risky},
    )

    if risky:
        # Exit 2 would roll back the creation. That is not desired here -
        # instead a visible hint via hookSpecificOutput.
        hooklib.additional_context(
            "TaskCreated",
            "This task touches areas from risk class R2 upward. Before the first "
            "change, that includes: a task contract in the ledger (goal, target "
            "resource, desired state, risk class, method, alternative, acceptance "
            "criteria, rollback plan), a resource lock, a baseline, and a backup. "
            "Afterward, objective tests and the verification-agent, before success "
            "is reported.",
        )

    hooklib.emit_nothing()


hooklib.safe(main)
