"""Resource Locks.

Verhindert, dass zwei schreibende Vorgänge gleichzeitig dieselbe Ressource
ändern. Ein Lock ist eine Datei in `state/locks/`, deren Name aus der
Ressourcen-ID abgeleitet wird.

Die Erstellung nutzt `O_EXCL`, ist also atomar: zwei gleichzeitige Versuche
können nicht beide gewinnen.

## Zwei Besitzarten

Ein Lock gehört entweder einem **Prozess** oder einem **Task**. Der Unterschied
entscheidet, wann es als verwaist gilt:

* `process` — der haltende Prozess lebt. Passt für einen laufenden Vorgang,
  der das Lock über einen Kontextmanager hält.
* `task` — der Vorgang ist über mehrere kurzlebige Aufrufe verteilt. Genau so
  arbeitet die Kommandozeile: `agentctl lock acquire` endet sofort, der Task
  läuft aber weiter. Würde hier die Prozesslebendigkeit zählen, wäre jedes
  Lock unmittelbar nach dem Setzen verwaist und damit wirkungslos.

Ein Task-Lock wird deshalb **nur** freigegeben durch ausdrückliches `release`
oder wenn der zugehörige Task nachweislich abgeschlossen ist
(`COMMITTED`, `FAILED`, `ROLLED_BACK`). Zeitablauf allein genügt nie.
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
    """Die Ressource ist bereits von einem anderen Vorgang gesperrt."""

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
    """Prüft plattformunabhängig, ob eine PID noch existiert."""
    if pid <= 0:
        return False
    if os.name == "nt":
        import subprocess
        try:
            # errors="replace": tasklist gibt unter deutschem Locale Bytes aus,
            # die sich nicht als cp1252 dekodieren lassen. Ein Decodierfehler
            # darf hier niemals zum Abbruch führen.
            completed = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                capture_output=True, text=True, errors="replace",
                timeout=10, check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return True  # Im Zweifel als lebend behandeln, nie fälschlich freigeben.
        # `tasklist` kann in eingeschränkten Windows-Sandboxes mit
        # "Zugriff verweigert" und leerer Standardausgabe enden. Das ist kein
        # Nachweis, dass der Prozess tot ist. Fail-safe bleibt das Lock dann
        # gehalten; nur eine erfolgreiche Abfrage darf "nicht gefunden"
        # ergeben.
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
    """Gibt die Metadaten eines gehaltenen Locks zurück, sonst None."""
    path = _lock_path(resource)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"resource": resource, "corrupt": True}


def _task_finished(task_id: str | None) -> bool:
    """True, wenn der Task nachweislich abgeschlossen ist."""
    if not task_id:
        return False
    try:
        from . import ledger
        task = ledger.get_task(task_id)
    except Exception:  # noqa: BLE001
        return False
    if task is None:
        # Unbekannter Task: nicht als abgeschlossen behandeln. Im Zweifel
        # bleibt das Lock bestehen.
        return False
    return task.get("state") in ("COMMITTED", "FAILED", "ROLLED_BACK")


def is_stale(lock_data: dict[str, Any]) -> bool:
    """Entscheidet, ob ein gehaltenes Lock freigegeben werden darf."""
    if lock_data.get("corrupt"):
        return True
    if lock_data.get("owner") == "task":
        return _task_finished(lock_data.get("task_id"))
    return not _process_alive(int(lock_data.get("pid") or 0))


def acquire(resource: str, *, agent: str, task_id: str | None = None,
            reason: str = "", owner: str = "process") -> Lock:
    """Belegt eine Ressource oder wirft LockUnavailable.

    `owner="task"` für Vorgänge über mehrere kurzlebige Aufrufe hinweg,
    `owner="process"` für ein Lock, das ein laufender Prozess hält.
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
    """Gibt ein Lock frei. Nur der Inhaber des Tokens darf freigeben."""
    path = _lock_path(lock.resource)
    current = read_lock(lock.resource)
    if current is None:
        return False
    if current.get("token") != lock.token:
        return False
    path.unlink(missing_ok=True)
    return True


def list_locks() -> list[dict[str, Any]]:
    """Alle aktuell gehaltenen Locks mit Angabe, ob der Halter noch lebt."""
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
    """Kontextmanager: `with locks.held("windows:network", agent="windows-agent"):`"""

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
