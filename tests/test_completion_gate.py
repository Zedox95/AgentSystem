"""Deterministic negative and positive tests for the completion gate."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="agentsys-completion-"))
os.environ["AGENTSYSTEM_ROOT"] = str(TMP / "system")
os.environ["AGENTSYSTEM_VAULT"] = str(TMP / "vault")
sys.path.insert(0, str(ROOT / "bin"))

from agentsys import knowledge, ledger  # noqa: E402

FAILURES: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        FAILURES.append(message)


def expect_block(task_id: str, expected: str) -> None:
    try:
        ledger.set_state(task_id, "COMMITTED")
        FAILURES.append(f"Commit should have been blocked: {expected}")
    except ValueError as error:
        check(expected in str(error), f"Block reason {expected!r} missing: {error}")


def advance(task_id: str, *, stop: str = "INDEPENDENT_VERIFY") -> None:
    for state in (
        "PLANNED", "PREFLIGHT", "LOCKED", "BASELINED", "BACKED_UP",
        "EXECUTING", "OBJECTIVE_TEST", "INDEPENDENT_VERIFY",
    ):
        ledger.set_state(task_id, state)
        if state == stop:
            return


task_id = ledger.create_task(
    goal="Test the completion gate", risk_class="R2",
    target_resource="test:completion", desired_state="Gate is effective",
    planned_method="isolated test", alternative_method="rollback in the temp directory",
    acceptance_criteria="negative tests block, positive test commits",
    rollback_plan="remove the temp directory",
)

try:
    knowledge.review_task(task_id, decision="none", reason="Deliberately too early")
    FAILURES.append("Knowledge Review before INDEPENDENT_VERIFY must block")
except ValueError as error:
    check("INDEPENDENT_VERIFY" in str(error), "Early review needs a clear block reason")

try:
    ledger.set_state(task_id, "EXECUTING")
    FAILURES.append("RECEIVED -> EXECUTING must block")
except ValueError as error:
    check("Invalid state transition" in str(error), "Transition error must be understandable")

advance(task_id)
expect_block(task_id, "No completed run")

run_no_evidence = ledger.start_run(task_id, "implementation-agent", "test", "none", "R2")
ledger.finish_run(run_no_evidence, "PASS", change_summary="Change")
expect_block(task_id, "Objective test evidence missing")

run_failed = ledger.start_run(task_id, "implementation-agent", "test", "failed", "R2")
ledger.finish_run(
    run_failed, "FAIL", change_summary="Change", objective_tests="Measurement present",
    verification="PASS: text is deliberately contradictory",
)
expect_block(task_id, "outcome=PASS")

run_bad_verdict = ledger.start_run(task_id, "implementation-agent", "test", "verdict", "R2")
ledger.finish_run(
    run_bad_verdict, "PASS", change_summary="Change", objective_tests="Measurement present",
    verification="Verifier reported PASS later",
)
expect_block(task_id, "verification missing")

run_good = ledger.start_run(task_id, "implementation-agent", "test", "complete", "R2")
ledger.finish_run(
    run_good, "PASS", change_summary="Gate tested in isolation",
    objective_tests="Invalid transitions and missing evidence were rejected",
    verification="PASS: independent deterministic test",
)
expect_block(task_id, "Knowledge Review")

review = knowledge.review_task(
    task_id, decision="none",
    reason="The isolated temp test produces no durable user knowledge",
)
check(review["decision"] == "none", "Knowledge review must document none")
readiness = ledger.completion_readiness(task_id)
check(readiness["ready"], f"Complete task must be commit-ready: {readiness}")

# A later-finished run deliberately makes the previous review stale.
newer_run = ledger.start_run(task_id, "implementation-agent", "test", "newer", "R2")
ledger.finish_run(
    newer_run, "PASS", change_summary="Later change",
    objective_tests="Later objective test", verification="PASS: later verifier",
)
stale = ledger.completion_readiness(task_id)
check(not stale["ready"] and any("older" in item for item in stale["reasons"]),
      "A later run must invalidate the previous knowledge review")
knowledge.review_task(
    task_id, decision="none",
    reason="The later isolated run also produces no durable user knowledge",
)
readiness = ledger.completion_readiness(task_id)
check(readiness["ready"], f"Renewed review must be commit-ready: {readiness}")
ledger.set_state(task_id, "COMMITTED")
check(ledger.get_task(task_id)["state"] == "COMMITTED", "Commit must be successful")

try:
    ledger.set_state(task_id, "EXECUTING")
    FAILURES.append("A terminal COMMITTED task must not be reopened")
except ValueError:
    pass

incomplete = ledger.create_task(
    goal="Incomplete contract", risk_class="R1",
    acceptance_criteria="x", rollback_plan="y",
)
advance(incomplete)
incomplete_run = ledger.start_run(incomplete, "test", "test", "test", "R1")
ledger.finish_run(
    incomplete_run, "PASS", change_summary="x", objective_tests="x",
    verification="PASS: test",
)
knowledge.review_task(incomplete, decision="none", reason="No facts")
report = ledger.completion_readiness(incomplete)
check(not report["ready"] and any("Task Contract" in item for item in report["reasons"]),
      "An incomplete R1 task contract must block the commit")

print(json.dumps({
    "status": "FAIL" if FAILURES else "PASS",
    "task_id": task_id,
    "readiness": readiness,
    "failures": FAILURES,
    "temp_root": str(TMP),
}, ensure_ascii=False, indent=2))
sys.exit(1 if FAILURES else 0)
