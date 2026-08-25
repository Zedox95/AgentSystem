"""Run Ledger — append-only Protokoll aller relevanten Vorgänge.

SQLite mit WAL, damit gleichzeitige Hook-Prozesse schreiben können, ohne sich
zu blockieren. Bestehende Zeilen werden nie verändert; Zustandswechsel eines
Tasks werden als zusätzliche Ereignisse angehängt.

Es werden ausdrücklich **keine** Secrets protokolliert. Kommandotexte werden
vor dem Schreiben durch `redact()` geführt.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from . import paths

SCHEMA_VERSION = 1

_SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS schema_info (
    version INTEGER NOT NULL
);

-- Ein Task ist ein Benutzerziel mit Vertrag. Zustandswechsel landen in events.
CREATE TABLE IF NOT EXISTS tasks (
    task_id             TEXT PRIMARY KEY,
    created_utc         TEXT NOT NULL,
    goal                TEXT NOT NULL,
    target_resource     TEXT,
    desired_state       TEXT,
    risk_class          TEXT NOT NULL,
    planned_method      TEXT,
    alternative_method  TEXT,
    acceptance_criteria TEXT,
    rollback_plan       TEXT,
    state               TEXT NOT NULL,
    fingerprint         TEXT
);

-- Ein Run ist eine konkrete Ausführung innerhalb eines Tasks.
CREATE TABLE IF NOT EXISTS runs (
    run_id            TEXT PRIMARY KEY,
    task_id           TEXT,
    started_utc       TEXT NOT NULL,
    finished_utc      TEXT,
    agent             TEXT,
    tool              TEXT,
    method            TEXT,
    risk_class        TEXT,
    locks             TEXT,
    baseline_ref      TEXT,
    change_summary    TEXT,
    objective_tests   TEXT,
    verification      TEXT,
    outcome           TEXT,
    duration_ms       INTEGER,
    retries           INTEGER DEFAULT 0,
    error             TEXT,
    rollback          TEXT,
    fingerprint       TEXT,
    FOREIGN KEY (task_id) REFERENCES tasks(task_id)
);

-- Append-only Ereignisstrom. Nichts hier wird je aktualisiert.
CREATE TABLE IF NOT EXISTS events (
    event_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_utc       TEXT NOT NULL,
    task_id      TEXT,
    run_id       TEXT,
    session_id   TEXT,
    event_type   TEXT NOT NULL,
    agent        TEXT,
    tool         TEXT,
    detail       TEXT
);

CREATE INDEX IF NOT EXISTS idx_events_task ON events(task_id);
CREATE INDEX IF NOT EXISTS idx_events_ts   ON events(ts_utc);
CREATE INDEX IF NOT EXISTS idx_runs_task   ON runs(task_id);
CREATE INDEX IF NOT EXISTS idx_tasks_state ON tasks(state);
"""

# Zustände der Task State Machine aus AGENTS.md Abschnitt 8.
STATES = (
    "RECEIVED", "PLANNED", "PREFLIGHT", "LOCKED", "BASELINED", "BACKED_UP",
    "EXECUTING", "OBJECTIVE_TEST", "INDEPENDENT_VERIFY", "COMMITTED",
    "FAILED_STEP", "DIAGNOSING", "RETRY_ALTERNATIVE",
    "ROLLING_BACK", "ROLLED_BACK", "FAILED",
)

TERMINAL_STATES = ("COMMITTED", "FAILED", "ROLLED_BACK")
OPEN_STATES = tuple(s for s in STATES if s not in TERMINAL_STATES)

# Nur diese Übergänge entsprechen der State Machine aus AGENTS.md. Ein
# erneutes Setzen desselben Zustands ist separat als idempotente Reassertion
# erlaubt, damit Resume-Pfade nicht an einer bereits erfolgten Aktion scheitern.
ALLOWED_TRANSITIONS = {
    "RECEIVED": {"PLANNED", "FAILED"},
    "PLANNED": {"PREFLIGHT", "FAILED"},
    "PREFLIGHT": {"LOCKED", "FAILED_STEP", "FAILED"},
    "LOCKED": {"BASELINED", "FAILED_STEP", "ROLLING_BACK"},
    "BASELINED": {"BACKED_UP", "FAILED_STEP", "ROLLING_BACK"},
    "BACKED_UP": {"EXECUTING", "FAILED_STEP", "ROLLING_BACK"},
    "EXECUTING": {"OBJECTIVE_TEST", "FAILED_STEP", "ROLLING_BACK"},
    "OBJECTIVE_TEST": {"INDEPENDENT_VERIFY", "FAILED_STEP", "DIAGNOSING", "ROLLING_BACK"},
    "INDEPENDENT_VERIFY": {"COMMITTED", "FAILED_STEP", "DIAGNOSING", "ROLLING_BACK"},
    "FAILED_STEP": {"DIAGNOSING", "ROLLING_BACK", "FAILED"},
    "DIAGNOSING": {"RETRY_ALTERNATIVE", "ROLLING_BACK", "FAILED"},
    "RETRY_ALTERNATIVE": {"EXECUTING", "FAILED_STEP", "ROLLING_BACK"},
    "ROLLING_BACK": {"ROLLED_BACK", "FAILED"},
    "ROLLED_BACK": set(),
    "FAILED": set(),
    "COMMITTED": set(),
}

# Muster, deren Wert vor dem Protokollieren entfernt wird.
_SECRET_PATTERNS = (
    re.compile(r"(?i)\b((?:api[_-]?key|token|password|passwd|secret|bearer|authorization)"
               r"\s*[:=]\s*)(\S+)"),
    re.compile(r"(?i)(-p\s+)(\S+)"),
    re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{16,}|sk-[A-Za-z0-9_-]{16,})\b"),
)


def redact(text: str | None) -> str | None:
    """Entfernt erkennbare Credential-Werte aus einem Text."""
    if not text:
        return text
    result = text
    result = _SECRET_PATTERNS[0].sub(r"\1<REDACTED>", result)
    result = _SECRET_PATTERNS[1].sub(r"\1<REDACTED>", result)
    result = _SECRET_PATTERNS[2].sub("<REDACTED>", result)
    return result


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


def connect() -> sqlite3.Connection:
    """Öffnet die Ledger-Datenbank und stellt das Schema sicher."""
    paths.ensure_dirs()
    connection = sqlite3.connect(paths.LEDGER_DB, timeout=10.0)
    connection.row_factory = sqlite3.Row
    connection.executescript(_SCHEMA)
    row = connection.execute("SELECT version FROM schema_info").fetchone()
    if row is None:
        connection.execute("INSERT INTO schema_info(version) VALUES (?)", (SCHEMA_VERSION,))
    connection.commit()
    return connection


def log_event(
    event_type: str,
    *,
    task_id: str | None = None,
    run_id: str | None = None,
    session_id: str | None = None,
    agent: str | None = None,
    tool: str | None = None,
    detail: Any = None,
) -> None:
    """Hängt ein Ereignis an. Fehlerhafte Protokollierung darf nie den Ablauf stoppen."""
    try:
        payload = detail
        if payload is not None and not isinstance(payload, str):
            payload = json.dumps(payload, ensure_ascii=False, default=str)
        with connect() as connection:
            connection.execute(
                "INSERT INTO events(ts_utc, task_id, run_id, session_id, event_type,"
                " agent, tool, detail) VALUES (?,?,?,?,?,?,?,?)",
                (utcnow(), task_id, run_id, session_id, event_type,
                 agent, tool, redact(payload)),
            )
    except Exception:  # noqa: BLE001 - Protokollierung darf nie werfen
        pass


def create_task(
    goal: str,
    risk_class: str,
    *,
    target_resource: str | None = None,
    desired_state: str | None = None,
    planned_method: str | None = None,
    alternative_method: str | None = None,
    acceptance_criteria: str | None = None,
    rollback_plan: str | None = None,
    fingerprint: str | None = None,
) -> str:
    """Legt einen Task Contract an und gibt die Task-ID zurück."""
    task_id = new_id("task")
    with connect() as connection:
        connection.execute(
            "INSERT INTO tasks(task_id, created_utc, goal, target_resource, desired_state,"
            " risk_class, planned_method, alternative_method, acceptance_criteria,"
            " rollback_plan, state, fingerprint) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (task_id, utcnow(), goal, target_resource, desired_state, risk_class,
             planned_method, alternative_method, acceptance_criteria, rollback_plan,
             "RECEIVED", fingerprint),
        )
    log_event("TASK_CREATED", task_id=task_id, detail={"goal": goal, "risk": risk_class})
    return task_id


def latest_knowledge_review(task_id: str) -> dict[str, Any] | None:
    """Liest die letzte dokumentierte Wissensprüfung eines Tasks."""
    with connect() as connection:
        row = connection.execute(
            "SELECT detail FROM events WHERE task_id = ? AND event_type = ? "
            "ORDER BY event_id DESC LIMIT 1",
            (task_id, "KNOWLEDGE_REVIEWED"),
        ).fetchone()
    if row is None or not row["detail"]:
        return None
    try:
        payload = json.loads(row["detail"])
    except (TypeError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def record_knowledge_review(task_id: str, *, decision: str, reason: str,
                            candidate_ids: list[str] | None = None) -> dict[str, Any]:
    """Protokolliert die semantische Wissensprüfung vor dem Commit.

    Die Validierung der Candidate-Buckets geschieht in knowledge.review_task;
    der Ledger hält nur das append-only Ergebnis fest.
    """
    task = get_task(task_id)
    if task is None:
        raise KeyError(f"Unbekannter Task: {task_id}")
    if task.get("state") in TERMINAL_STATES:
        raise ValueError("Knowledge Review braucht einen offenen Task")
    if task.get("state") != "INDEPENDENT_VERIFY":
        raise ValueError(
            "Knowledge Review ist erst im Zustand INDEPENDENT_VERIFY zulässig"
        )
    normalized = decision.strip().lower()
    if normalized not in ("none", "captured", "deferred"):
        raise ValueError(f"Unbekannte Knowledge-Review-Entscheidung: {decision}")
    if not reason.strip():
        raise ValueError("Knowledge Review braucht eine Begründung")
    payload = {
        "decision": normalized,
        "reason": reason.strip(),
        "candidate_ids": list(dict.fromkeys(candidate_ids or [])),
        "reviewed_utc": utcnow(),
    }
    log_event("KNOWLEDGE_REVIEWED", task_id=task_id, agent="archivist", detail=payload)
    return payload


def _verification_passed(value: str | None) -> bool:
    """Akzeptiert nur ein explizites PASS-Urteil, keine beiläufige Erwähnung."""
    if not value or not value.strip():
        return False
    text = value.strip()
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        payload = None
    if isinstance(payload, dict):
        verdict = payload.get("verdict", payload.get("status"))
        return str(verdict or "").strip().upper() == "PASS"
    return re.match(r"(?i)^PASS(?:\b|\s*[:\-])", text) is not None


def completion_readiness(task_id: str) -> dict[str, Any]:
    """Prüft deterministisch, ob ein Task auf COMMITTED wechseln darf."""
    task = get_task(task_id)
    if task is None:
        return {"task_id": task_id, "ready": False,
                "reasons": [f"Unbekannter Task: {task_id}"]}

    reasons: list[str] = []
    if task.get("state") != "INDEPENDENT_VERIFY":
        reasons.append(
            f"Aktueller Zustand ist {task.get('state')}; erforderlich ist INDEPENDENT_VERIFY"
        )

    if str(task.get("risk_class", "")).upper() in ("R1", "R2", "R3"):
        required_contract = (
            "target_resource", "desired_state", "planned_method",
            "alternative_method", "acceptance_criteria", "rollback_plan",
        )
        missing = [field for field in required_contract if not str(task.get(field) or "").strip()]
        if missing:
            reasons.append("Task Contract unvollständig: " + ", ".join(missing))

    with connect() as connection:
        run = connection.execute(
            "SELECT * FROM runs WHERE task_id = ? AND finished_utc IS NOT NULL "
            "ORDER BY finished_utc DESC, rowid DESC LIMIT 1",
            (task_id,),
        ).fetchone()
    run_data = dict(run) if run else None
    if run_data is None:
        reasons.append("Kein abgeschlossener Run vorhanden")
    else:
        if str(run_data.get("outcome") or "").upper() != "PASS":
            reasons.append("Der letzte abgeschlossene Run hat nicht outcome=PASS")
        if not str(run_data.get("objective_tests") or "").strip():
            reasons.append("Objective-Test-Evidenz fehlt")
        if not _verification_passed(run_data.get("verification")):
            reasons.append("Unabhängige Verifikation fehlt oder ist nicht explizit PASS")
        if str(task.get("risk_class", "")).upper() in ("R1", "R2", "R3") \
                and not str(run_data.get("change_summary") or "").strip():
            reasons.append("Änderungszusammenfassung fehlt")

    review = latest_knowledge_review(task_id)
    if review is None:
        reasons.append("Knowledge Review wurde nicht dokumentiert")
    else:
        decision = str(review.get("decision") or "").lower()
        reason = str(review.get("reason") or "").strip()
        candidate_ids = review.get("candidate_ids")
        structurally_valid = (
            decision in ("none", "captured", "deferred")
            and bool(reason)
            and isinstance(candidate_ids, list)
            and ((decision == "none" and not candidate_ids)
                 or (decision in ("captured", "deferred") and bool(candidate_ids)))
        )
        if not structurally_valid:
            reasons.append("Knowledge Review ist strukturell ungültig")
        if run_data is not None:
            try:
                reviewed = datetime.fromisoformat(str(review.get("reviewed_utc") or ""))
                finished = datetime.fromisoformat(str(run_data.get("finished_utc") or ""))
            except ValueError:
                reasons.append("Knowledge Review enthält keinen gültigen Zeitpunkt")
            else:
                if reviewed <= finished:
                    reasons.append(
                        "Knowledge Review ist älter als der letzte abgeschlossene Run"
                    )

    return {
        "task_id": task_id,
        "state": task.get("state"),
        "ready": not reasons,
        "reasons": reasons,
        "run_id": run_data.get("run_id") if run_data else None,
        "knowledge_review": review,
    }


def set_state(task_id: str, state: str, detail: Any = None) -> None:
    """Setzt den Task-Zustand nur entlang der erlaubten State Machine."""
    if state not in STATES:
        raise ValueError(f"Unbekannter Zustand: {state}")
    task = get_task(task_id)
    if task is None:
        raise KeyError(f"Unbekannter Task: {task_id}")
    current = str(task.get("state"))
    if state == current:
        log_event("STATE_REASSERTED", task_id=task_id,
                  detail={"state": state, "detail": detail})
        return
    if state not in ALLOWED_TRANSITIONS.get(current, set()):
        raise ValueError(f"Ungültiger Zustandswechsel: {current} -> {state}")
    if state == "COMMITTED":
        readiness = completion_readiness(task_id)
        if not readiness["ready"]:
            raise ValueError("Commit-Gate blockiert: " + "; ".join(readiness["reasons"]))
    with connect() as connection:
        cursor = connection.execute(
            "UPDATE tasks SET state = ? WHERE task_id = ? AND state = ?",
            (state, task_id, current),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("Taskzustand wurde parallel verändert; erneut lesen")
    log_event("STATE_CHANGE", task_id=task_id, detail={"state": state, "detail": detail})


def get_task(task_id: str) -> dict[str, Any] | None:
    with connect() as connection:
        row = connection.execute(
            "SELECT * FROM tasks WHERE task_id = ?", (task_id,)
        ).fetchone()
    return dict(row) if row else None


def open_tasks() -> list[dict[str, Any]]:
    """Tasks, die weder committed noch endgültig fehlgeschlagen sind."""
    placeholders = ",".join("?" for _ in OPEN_STATES)
    with connect() as connection:
        rows = connection.execute(
            f"SELECT * FROM tasks WHERE state IN ({placeholders}) ORDER BY created_utc DESC",
            OPEN_STATES,
        ).fetchall()
    return [dict(row) for row in rows]


def start_run(task_id: str | None, agent: str, tool: str, method: str,
              risk_class: str, locks: str | None = None) -> str:
    run_id = new_id("run")
    with connect() as connection:
        connection.execute(
            "INSERT INTO runs(run_id, task_id, started_utc, agent, tool, method,"
            " risk_class, locks) VALUES (?,?,?,?,?,?,?,?)",
            (run_id, task_id, utcnow(), agent, tool, method, risk_class, locks),
        )
    return run_id


def finish_run(run_id: str, outcome: str, **fields: Any) -> None:
    """Schließt einen Run ab. Erlaubte Felder entsprechen den Spalten von runs."""
    allowed = {
        "change_summary", "objective_tests", "verification", "duration_ms",
        "retries", "error", "rollback", "baseline_ref", "fingerprint",
    }
    updates = {key: value for key, value in fields.items() if key in allowed}
    for key, value in list(updates.items()):
        if isinstance(value, str):
            updates[key] = redact(value)
        elif value is not None and not isinstance(value, (int, float)):
            updates[key] = redact(json.dumps(value, ensure_ascii=False, default=str))
    assignments = ", ".join(f"{key} = ?" for key in updates)
    clause = f", {assignments}" if assignments else ""
    with connect() as connection:
        connection.execute(
            f"UPDATE runs SET finished_utc = ?, outcome = ?{clause} WHERE run_id = ?",
            (utcnow(), outcome, *updates.values(), run_id),
        )
    log_event("RUN_FINISHED", run_id=run_id, detail={"outcome": outcome})


def write_checkpoint(data: dict[str, Any]) -> None:
    """Sichert den Fortsetzungspunkt für Neustart oder Kontingentende."""
    paths.ensure_dirs()
    payload = dict(data)
    payload["written_utc"] = utcnow()
    payload["pid"] = os.getpid()
    temporary = paths.CHECKPOINT_FILE.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(paths.CHECKPOINT_FILE)


def read_checkpoint() -> dict[str, Any] | None:
    if not paths.CHECKPOINT_FILE.exists():
        return None
    try:
        return json.loads(paths.CHECKPOINT_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def recent_events(limit: int = 20) -> list[dict[str, Any]]:
    with connect() as connection:
        rows = connection.execute(
            "SELECT * FROM events ORDER BY event_id DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(row) for row in rows]


class timed:
    """Kontextmanager, der die Dauer eines Abschnitts in Millisekunden misst."""

    def __enter__(self) -> "timed":
        self._start = time.monotonic()
        self.duration_ms = 0
        return self

    def __exit__(self, *exc: Any) -> None:
        self.duration_ms = int((time.monotonic() - self._start) * 1000)
