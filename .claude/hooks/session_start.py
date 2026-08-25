"""SessionStart — minimalen Zustand laden.

Bewusst sparsam: nur offene Tasks, aktive Locks, ein etwaiger Checkpoint und
Hinweise auf veraltete Erfahrungen. Weder das Run Ledger noch Logs werden in
den Kontext geladen (AGENTS.md Abschnitt 23).
"""

from __future__ import annotations

import hooklib

MAX_TASKS = 5
MAX_LOCKS = 8


def main() -> None:
    data = hooklib.read_input()

    from agentsys import experience, ledger, locks

    lines: list[str] = []

    checkpoint = ledger.read_checkpoint()
    if checkpoint:
        lines.append(
            "Unterbrochener Vorgang gefunden — Checkpoint: "
            f"Task {checkpoint.get('task_id', '?')}, "
            f"letzter Schritt {checkpoint.get('last_step', '?')}, "
            f"nächster Schritt {checkpoint.get('next_step', '?')}, "
            f"geschrieben {checkpoint.get('written_utc', '?')}. "
            "Vor neuer Arbeit prüfen, ob ein Rollback oder eine Fortsetzung nötig ist."
        )

    try:
        open_tasks = ledger.open_tasks()
    except Exception:  # noqa: BLE001
        open_tasks = []
    if open_tasks:
        lines.append(f"Offene Tasks ({len(open_tasks)}):")
        for task in open_tasks[:MAX_TASKS]:
            lines.append(
                f"  - {task['task_id']} [{task['state']}] {task['risk_class']}: "
                f"{task['goal'][:110]}"
            )
        if len(open_tasks) > MAX_TASKS:
            lines.append(f"  … und {len(open_tasks) - MAX_TASKS} weitere")

    try:
        held = locks.list_locks()
    except Exception:  # noqa: BLE001
        held = []
    if held:
        lines.append(f"Aktive Resource Locks ({len(held)}):")
        for lock in held[:MAX_LOCKS]:
            status = "Halter läuft" if lock.get("holder_alive") else "VERWAIST"
            lines.append(
                f"  - {lock.get('resource', '?')} ({lock.get('agent', '?')}, {status})"
            )

    try:
        stale = experience.stale_entries()
    except Exception:  # noqa: BLE001
        stale = []
    if stale:
        lines.append(
            f"{len(stale)} Erfahrungseinträge haben eine abweichende Umgebung "
            "und dürfen nicht ungeprüft bevorzugt werden."
        )

    if not lines:
        hooklib.emit_nothing()

    hooklib.additional_context(
        data.get("hook_event_name", "SessionStart"),
        "Agentensystem-Zustand:\n" + "\n".join(lines),
    )


hooklib.safe(main)
