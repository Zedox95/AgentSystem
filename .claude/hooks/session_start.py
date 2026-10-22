"""SessionStart — load minimal state.

Deliberately sparse: only open tasks, active locks, a possible checkpoint,
and hints about stale experience entries. Neither the run ledger nor logs
are loaded into the context (AGENTS.md section 23).
"""

from __future__ import annotations

import hooklib

MAX_TASKS = 5
MAX_LOCKS = 8


def main() -> None:
    data = hooklib.read_input()

    from agentsys import experience, ledger, locks

    lines: list[str] = []

    session_id = data.get("session_id")
    if not isinstance(session_id, str) or not session_id.strip():
        hooklib.emit_nothing()
    checkpoint = ledger.read_checkpoint(session_id)
    if checkpoint:
        lines.append(
            "Interrupted process found — checkpoint: "
            f"task {checkpoint.get('task_id', '?')}, "
            f"last step {checkpoint.get('last_step', '?')}, "
            f"next step {checkpoint.get('next_step', '?')}, "
            f"written {checkpoint.get('written_utc', '?')}. "
            "Before new work, check whether a rollback or a continuation is needed."
        )

    try:
        open_tasks = ledger.open_tasks()
        if session_id:
            with ledger.connect() as connection:
                own = {row[0] for row in connection.execute(
                    "SELECT DISTINCT task_id FROM events WHERE session_id = ? AND task_id IS NOT NULL",
                    (session_id,),
                )}
            if checkpoint and checkpoint.get("task_id"):
                own.add(checkpoint["task_id"])
            open_tasks = [task for task in open_tasks if task["task_id"] in own]
    except Exception:  # noqa: BLE001
        open_tasks = []
    if open_tasks:
        lines.append(f"Open tasks ({len(open_tasks)}):")
        for task in open_tasks[:MAX_TASKS]:
            lines.append(
                f"  - {task['task_id']} [{task['state']}] {task['risk_class']}: "
                f"{task['goal'][:110]}"
            )
        if len(open_tasks) > MAX_TASKS:
            lines.append(f"  … and {len(open_tasks) - MAX_TASKS} more")

    try:
        held = locks.list_locks()
    except Exception:  # noqa: BLE001
        held = []
    if held:
        lines.append(f"Active resource locks ({len(held)}):")
        for lock in held[:MAX_LOCKS]:
            status = "stale" if lock.get("stale") else "held"
            lines.append(
                f"  - {lock.get('resource', '?')} ({lock.get('agent', '?')}, {status})"
            )

    try:
        stale = experience.stale_entries()
    except Exception:  # noqa: BLE001
        stale = []
    if stale:
        lines.append(
            f"{len(stale)} experience entries have a diverging environment "
            "and must not be preferred without review."
        )

    if not lines:
        hooklib.emit_nothing()

    hooklib.additional_context(
        data.get("hook_event_name", "SessionStart"),
        "Agent system state:\n" + "\n".join(lines),
    )


hooklib.safe(main)
