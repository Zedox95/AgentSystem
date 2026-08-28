"""Resource locks.

Prevents two writing operations from changing the same resource at the
same time. A lock is a file in `state/locks/`, whose name is derived from
the resource ID.

Creation uses `O_EXCL`, so it is atomic: two concurrent attempts can never
both win.

## Two ownership kinds

A lock belongs either to a **process** or to a **task**. The difference
decides when it counts as orphaned:

* `process` — the holding process is alive. Fits a running operation that
  holds the lock via a context manager.
* `task` — the operation is spread across several short-lived calls. That's
  exactly how the command line works: `agentctl lock acquire` returns
  immediately, but the task keeps running. If process liveness counted here,
  every lock would become orphaned immediately after being set and thus
  useless.

A task lock is therefore **only** released by an explicit `release` or when
the associated task is verifiably finished
(`COMMITTED`, `FAILED`, `ROLLED_BACK`). Time elapsed alone is never enough.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from . import paths

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


class LockUnavailable(RuntimeError):
    """The resource is already locked by another operation."""

    def __init__(self, resource: str, holder: dict[str, Any]):
        self.resource = resource
        self.holder = holder
        super().__init__(
            f"Ressource '{resource}' ist gesperrt durch "
            f"{holder.get('agent', '?')} (Task {holder.get('task_id', '?')}, "
            f"PID {holder.get('pid', '?')}, seit {holder.get('acquired_utc', '?')})"
        )


@dataclass(frozen=True)
class Lock:
    resource: str
    path: str
    token: str


def _lock_path(resource: str):
    paths.ensure_dirs()
    return paths.LOCKS_DIR / (_SAFE.sub("_", resource) + ".lock")


def _process_alive(pid: int) -> bool:
    """Checks platform-independently whether a PID still exists."""
    if pid <= 0:
        return False
    if os.name == "nt":
        import subprocess
        try:
            # errors="replace": under a German locale, tasklist emits bytes
            # that don't decode as cp1252. A decode error must never cause
            # an abort here.
            completed = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                capture_output=True, text=True, errors="replace",
                timeout=10, check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return True  # When in doubt, treat as alive - never release falsely.
        # In restricted Windows sandboxes, `tasklist` can end with "access
        # denied" and empty stdout. That is not proof the process is dead.
        # Fail-safe, the lock then stays held; only a successful query is
        # allowed to yield "not found".
        if completed.returncode != 0:
            return True
        return str(pid) in completed.stdout
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def read_lock(resource: str) -> dict[str, Any] | None:
    """Returns the metadata of a held lock, otherwise None."""
    path = _lock_path(resource)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"resource": resource, "corrupt": True}


def _task_finished(task_id: str | None) -> bool:
    """True if the task is verifiably finished."""
    if not task_id:
        return False
    try:
        from . import ledger
        task = ledger.get_task(task_id)
    except Exception:  # noqa: BLE001
        return False
    if task is None:
        # Unknown task: don't treat as finished. When in doubt, the lock
        # stays in place.
        return False
    return task.get("state") in ("COMMITTED", "FAILED", "ROLLED_BACK")


def is_stale(lock_data: dict[str, Any]) -> bool:
    """Decides whether a held lock may be released."""
    if lock_data.get("corrupt"):
        return True
    if lock_data.get("owner") == "task":
        return _task_finished(lock_data.get("task_id"))
    return not _process_alive(int(lock_data.get("pid") or 0))


def acquire(resource: str, *, agent: str, task_id: str | None = None,
            reason: str = "", owner: str = "process") -> Lock:
    """Claims a resource or raises LockUnavailable.

    `owner="task"` for operations spread across several short-lived calls,
    `owner="process"` for a lock held by a running process.
    """
    if owner not in ("process", "task"):
        raise ValueError("owner muss 'process' oder 'task' sein")
    if owner == "task" and not task_id:
        raise ValueError("Ein Task-Lock braucht eine task_id — sonst ist nicht "
                         "entscheidbar, wann es freigegeben werden darf")
    path = _lock_path(resource)
    payload = {
        "resource": resource,
        "agent": agent,
        "task_id": task_id,
        "owner": owner,
        "reason": reason,
        "pid": os.getpid(),
        "acquired_utc": datetime.now(timezone.utc).isoformat(),
        "token": os.urandom(8).hex(),
    }
    try:
        handle = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        existing = read_lock(resource) or {}
        if is_stale(existing):
            path.unlink(missing_ok=True)
            return acquire(resource, agent=agent, task_id=task_id,
                           reason=reason, owner=owner)
        raise LockUnavailable(resource, existing) from None
    with os.fdopen(handle, "w", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)
    return Lock(resource=resource, path=str(path), token=payload["token"])


def release(lock: Lock) -> bool:
    """Releases a lock. Only the token holder may release it."""
    path = _lock_path(lock.resource)
    current = read_lock(lock.resource)
    if current is None:
        return False
    if current.get("token") != lock.token:
        return False
    path.unlink(missing_ok=True)
    return True


def list_locks() -> list[dict[str, Any]]:
    """All currently held locks, noting whether the holder is still alive."""
    paths.ensure_dirs()
    result = []
    for path in sorted(paths.LOCKS_DIR.glob("*.lock")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {"resource": path.stem, "corrupt": True}
        data.setdefault("owner", "process")
        data["holder_alive"] = _process_alive(int(data.get("pid") or 0))
        data["stale"] = is_stale(data)
        data["lock_file"] = str(path)
        result.append(data)
    return result


class held:
    """Context manager: `with locks.held("windows:network", agent="windows-agent"):`"""

    def __init__(self, resource: str, *, agent: str, task_id: str | None = None,
                 reason: str = "", owner: str = "process"):
        self._resource = resource
        self._agent = agent
        self._task_id = task_id
        self._reason = reason
        self._owner = owner
        self._lock: Lock | None = None

    def __enter__(self) -> Lock:
        self._lock = acquire(self._resource, agent=self._agent,
                             task_id=self._task_id, reason=self._reason,
                             owner=self._owner)
        return self._lock

    def __exit__(self, *exc: Any) -> None:
        if self._lock is not None:
            release(self._lock)
