"""TaskCompleted — Erfolg ohne erfülltes Commit-Gate verhindern.

Exit 2 verhindert, dass ein Task als abgeschlossen markiert wird.

Sobald an einem formalen R1-, R2- oder R3-Task Änderungen begonnen wurden,
darf Claude Code den übergeordneten Task erst abschließen, wenn der Ledger den
Vorgang als commit-ready bestätigt oder ein terminaler Fehler-/Rollbackzustand
erreicht ist. Damit kann ein voreiliges COMMITTED nicht durch eine bloße
Agentenaussage oder einen Exit-Code ersetzt werden.
"""

from __future__ import annotations

import sys

import hooklib

# Zustände, in denen bereits Änderungen erfolgt sein können.
CHANGED_STATES = ("EXECUTING", "OBJECTIVE_TEST", "FAILED_STEP",
                  "INDEPENDENT_VERIFY", "DIAGNOSING",
                  "RETRY_ALTERNATIVE", "ROLLING_BACK")


def main() -> None:
    data = hooklib.read_input()

    from agentsys import ledger

    try:
        open_tasks = ledger.open_tasks()
    except Exception:  # noqa: BLE001
        hooklib.emit_nothing()

    unresolved = [
        task for task in open_tasks
        if task.get("state") in CHANGED_STATES
        and str(task.get("risk_class", "")).upper() in ("R1", "R2", "R3")
    ]
    blocked: list[tuple[dict, list[str]]] = []
    for task in unresolved:
        readiness = ledger.completion_readiness(task["task_id"])
        if task.get("state") == "INDEPENDENT_VERIFY" and readiness["ready"]:
            continue
        blocked.append((task, readiness["reasons"]))

    ledger.log_event(
        "CC_TASK_COMPLETED",
        session_id=data.get("session_id"),
        detail={
            "task_id": data.get("task_id"),
            "task_status": data.get("task_status"),
            "blocked_tasks": [task["task_id"] for task, _ in blocked],
        },
    )

    if blocked:
        listing = "; ".join(
            f"{task['task_id']} [{task['risk_class']}/{task['state']}]: "
            f"{', '.join(reasons[:3])}"
            for task, reasons in blocked
        )
        sys.stderr.write(
            "Abschluss verhindert: Mindestens ein verändernder R1-R3-Task erfüllt "
            f"das Commit-Gate nicht — {listing}. Erforderlich sind gültige "
            "Zustandsfolge, Objective-Test-Evidenz, explizites Verifier-PASS und "
            "eine dokumentierte Knowledge Review; alternativ ein vollständiger Rollback."
        )
        sys.exit(2)

    hooklib.emit_nothing()


hooklib.safe(main)
