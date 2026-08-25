"""Deterministische Negativ- und Positivtests für das Completion-Gate."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(r"C:\AgentSystem")
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
        FAILURES.append(f"Commit hätte blockieren müssen: {expected}")
    except ValueError as error:
        check(expected in str(error), f"Blockgrund {expected!r} fehlt: {error}")


def advance(task_id: str, *, stop: str = "INDEPENDENT_VERIFY") -> None:
    for state in (
        "PLANNED", "PREFLIGHT", "LOCKED", "BASELINED", "BACKED_UP",
        "EXECUTING", "OBJECTIVE_TEST", "INDEPENDENT_VERIFY",
    ):
        ledger.set_state(task_id, state)
        if state == stop:
            return


task_id = ledger.create_task(
    goal="Completion-Gate testen", risk_class="R2",
    target_resource="test:completion", desired_state="Gate ist wirksam",
    planned_method="isolierter Test", alternative_method="Rollback im Temp-Verzeichnis",
    acceptance_criteria="Negativtests blockieren, Positivtest committed",
    rollback_plan="Temp-Verzeichnis entfernen",
)

try:
    knowledge.review_task(task_id, decision="none", reason="Absichtlich zu früh")
    FAILURES.append("Knowledge Review vor INDEPENDENT_VERIFY muss blockieren")
except ValueError as error:
    check("INDEPENDENT_VERIFY" in str(error), "Frühe Review braucht einen klaren Blockgrund")

try:
    ledger.set_state(task_id, "EXECUTING")
    FAILURES.append("RECEIVED -> EXECUTING muss blockieren")
except ValueError as error:
    check("Ungültiger Zustandswechsel" in str(error), "Transition-Fehler muss verständlich sein")

advance(task_id)
expect_block(task_id, "Kein abgeschlossener Run")

run_no_evidence = ledger.start_run(task_id, "implementation-agent", "test", "none", "R2")
ledger.finish_run(run_no_evidence, "PASS", change_summary="Änderung")
expect_block(task_id, "Objective-Test-Evidenz fehlt")

run_failed = ledger.start_run(task_id, "implementation-agent", "test", "failed", "R2")
ledger.finish_run(
    run_failed, "FAIL", change_summary="Änderung", objective_tests="Messung vorhanden",
    verification="PASS: Text ist absichtlich widersprüchlich",
)
expect_block(task_id, "outcome=PASS")

run_bad_verdict = ledger.start_run(task_id, "implementation-agent", "test", "verdict", "R2")
ledger.finish_run(
    run_bad_verdict, "PASS", change_summary="Änderung", objective_tests="Messung vorhanden",
    verification="Verifier meldete später PASS",
)
expect_block(task_id, "Verifikation fehlt")

run_good = ledger.start_run(task_id, "implementation-agent", "test", "complete", "R2")
ledger.finish_run(
    run_good, "PASS", change_summary="Gate isoliert getestet",
    objective_tests="Ungültige Übergänge und fehlende Evidenz wurden abgewiesen",
    verification="PASS: unabhängiger deterministischer Test",
)
expect_block(task_id, "Knowledge Review")

review = knowledge.review_task(
    task_id, decision="none",
    reason="Der isolierte Temp-Test erzeugt kein dauerhaftes Nutzerwissen",
)
check(review["decision"] == "none", "Knowledge Review muss none dokumentieren")
readiness = ledger.completion_readiness(task_id)
check(readiness["ready"], f"Vollständiger Task muss commit-ready sein: {readiness}")

# Ein später beendeter Run macht die vorherige Review absichtlich veraltet.
newer_run = ledger.start_run(task_id, "implementation-agent", "test", "newer", "R2")
ledger.finish_run(
    newer_run, "PASS", change_summary="Spätere Änderung",
    objective_tests="Späterer Objective Test", verification="PASS: späterer Verifier",
)
stale = ledger.completion_readiness(task_id)
check(not stale["ready"] and any("älter" in item for item in stale["reasons"]),
      "Ein späterer Run muss die vorherige Knowledge Review ungültig machen")
knowledge.review_task(
    task_id, decision="none",
    reason="Auch der spätere isolierte Run erzeugt kein dauerhaftes Nutzerwissen",
)
readiness = ledger.completion_readiness(task_id)
check(readiness["ready"], f"Erneuerte Review muss commit-ready sein: {readiness}")
ledger.set_state(task_id, "COMMITTED")
check(ledger.get_task(task_id)["state"] == "COMMITTED", "Commit muss erfolgreich sein")

try:
    ledger.set_state(task_id, "EXECUTING")
    FAILURES.append("Terminaler COMMITTED-Task darf nicht wieder geöffnet werden")
except ValueError:
    pass

incomplete = ledger.create_task(
    goal="Unvollständiger Vertrag", risk_class="R1",
    acceptance_criteria="x", rollback_plan="y",
)
advance(incomplete)
incomplete_run = ledger.start_run(incomplete, "test", "test", "test", "R1")
ledger.finish_run(
    incomplete_run, "PASS", change_summary="x", objective_tests="x",
    verification="PASS: test",
)
knowledge.review_task(incomplete, decision="none", reason="Keine Fakten")
report = ledger.completion_readiness(incomplete)
check(not report["ready"] and any("Task Contract" in item for item in report["reasons"]),
      "Unvollständiger R1-Task-Contract muss den Commit blockieren")

print(json.dumps({
    "status": "FAIL" if FAILURES else "PASS",
    "task_id": task_id,
    "readiness": readiness,
    "failures": FAILURES,
    "temp_root": str(TMP),
}, ensure_ascii=False, indent=2))
sys.exit(1 if FAILURES else 0)
