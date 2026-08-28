"""Tests for read-only drift, lock, and checkpoint detection."""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="agentsys-supervisor-"))
SYSTEM = TMP / "system"
VAULT = TMP / "vault"
VAULT.mkdir(parents=True)
os.environ["AGENTSYSTEM_ROOT"] = str(SYSTEM)
os.environ["AGENTSYSTEM_VAULT"] = str(VAULT)
sys.path.insert(0, str(ROOT / "bin"))

from agentsys import knowledge, ledger, paths, supervisor  # noqa: E402

FAILURES: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        FAILURES.append(message)


task_id = ledger.create_task(
    "Terminal test task", "R1",
    target_resource="test:terminal-task",
    desired_state="Verified and completed",
    planned_method="Create isolated test state",
    alternative_method="Discard the test state",
    acceptance_criteria="PASS run and Knowledge Review present",
    rollback_plan="Remove the temp directory",
)
for state in (
    "PLANNED", "PREFLIGHT", "LOCKED", "BASELINED", "BACKED_UP",
    "EXECUTING", "OBJECTIVE_TEST", "INDEPENDENT_VERIFY",
):
    ledger.set_state(task_id, state)
run_id = ledger.start_run(
    task_id, "supervisor-test", "Python", "create isolated fixture", "R1",
)
ledger.finish_run(
    run_id, "PASS", change_summary="Created terminal test task",
    objective_tests="Isolated ledger test",
    verification="PASS: test fixture independently complete",
)
knowledge.review_task(
    task_id, decision="none",
    reason="No productive knowledge change in the test fixture",
)
ledger.set_state(task_id, "COMMITTED")
ledger.write_checkpoint({"task_id": task_id, "state": "RECEIVED", "goal": "kaputt Ã¼"})
paths.LOCKS_DIR.mkdir(parents=True, exist_ok=True)
(paths.LOCKS_DIR / "test.lock").write_text(json.dumps({
    "resource": "test:resource", "owner": "task", "task_id": task_id,
    "pid": 1, "token": "test",
}), encoding="utf-8")
note = VAULT / "router.md"
note.write_text(
    "---\ntype: system_entity\nentity: router-main\nstatus: current\n"
    "confidence: high\nsource_type: local_config\nvalid_from: 2026-08-23\n"
    "last_verified: 2026-08-23\n---\nRouter\n",
    encoding="utf-8",
)
paths.STATE_DIR.mkdir(parents=True, exist_ok=True)
(paths.STATE_DIR / "knowledge-index.json").write_text(
    json.dumps({"router.md": "0" * 64}), encoding="utf-8",
)

# The fixture writes many ledger events. Before the read-only measurement,
# close the test WAL in a controlled way, so that only supervisor accesses
# are compared and not some delayed SQLite cleanup action.
with sqlite3.connect(paths.LEDGER_DB) as fixture_connection:
    fixture_connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
before = {str(path): path.stat().st_mtime_ns for path in SYSTEM.rglob("*") if path.is_file()}
report = supervisor.check(VAULT)
after = {str(path): path.stat().st_mtime_ns for path in SYSTEM.rglob("*") if path.is_file()}
by_name = {item["check"]: item for item in report["checks"]}
changed_files = sorted(path for path in set(before) | set(after)
                       if before.get(path) != after.get(path))
check(before == after and report["read_only"],
      f"Supervisor must stay read-only; changed: {changed_files}")
check(by_name["ledger"]["status"] == "PASS", "SQLite quick_check must be PASS")
check(by_name["checkpoint"]["status"] == "WARN",
      "Terminal/mojibake checkpoint must be detected")
check(by_name["locks"]["evidence"]["stale"] == ["test:resource"],
      "Stale task lock must be detected")
check(by_name["knowledge_index"]["evidence"]["drift"],
      "Changed source hash must yield index drift")

print(json.dumps({
    "status": "FAIL" if FAILURES else "PASS",
    "supervisor_status": report["status"],
    "checks": by_name,
    "failures": FAILURES,
    "temp_root": str(TMP),
}, ensure_ascii=False, indent=2))
sys.exit(1 if FAILURES else 0)
