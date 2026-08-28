"""TaskCompleted — prevent success without a satisfied commit gate.

Exit 2 prevents a task from being marked complete.

Once changes have begun on a formal R1, R2, or R3 task, Claude Code may
only close the parent task once the ledger confirms the process as
commit-ready, or a terminal failure/rollback state has been reached. This
way a premature COMMITTED cannot be substituted by a mere agent statement
or an exit code.
"""

from __future__ import annotations

import sys

import hooklib

# States in which changes may already have occurred.
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
            "Completion blocked: at least one change-making R1-R3 task does not "
            f"satisfy the commit gate — {listing}. Required are a valid "
            "state sequence, objective-test evidence, an explicit verifier PASS, and "
            "a documented knowledge review; alternatively a complete rollback."
        )
        sys.exit(2)

    hooklib.emit_nothing()


hooklib.safe(main)
