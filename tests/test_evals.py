"""Tests fuer deterministische Evals und KPI-Aggregation."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(r"C:\AgentSystem")
TMP = Path(tempfile.mkdtemp(prefix="agentsys-evals-"))
os.environ["AGENTSYSTEM_ROOT"] = str(TMP / "system")
sys.path.insert(0, str(ROOT / "bin"))

from agentsys import evals  # noqa: E402
from agentsys.contracts import EvalCase, MetricEvent  # noqa: E402

FAILURES: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        FAILURES.append(message)


cases = evals.load_cases(ROOT / "evals")
check(len(cases) >= 3, "Baseline braucht mindestens drei Eval-Faelle")
example = EvalCase(
    eval_id="test-case", task_class="unit-test", prompt="Test", risk_class="R0",
    must_include=["Quelle"], must_not_include=["privat"],
).validate()
check(evals.score(example, "Quelle: hash")["status"] == "PASS",
      "Vollstaendiger Output muss PASS ergeben")
check(evals.score(example, "Quelle privat")["status"] == "FAIL",
      "Verbotener Inhalt muss FAIL ergeben")

metrics = TMP / "events.jsonl"
for event in (
    MetricEvent("context-builder", "PASS", True, False, False, True, False, 4, 100),
    MetricEvent("context-builder", "FAIL", False, True, True, False, True, 8, 300),
    MetricEvent("knowledge-write", "PASS", True, False, False, True, False, 2, 50),
):
    evals.record_metric(event, destination=metrics)
report = evals.kpi_report(metrics)
check(report["overall"]["tasks"] == 3, "KPI-Report muss drei Tasks zaehlen")
check(report["overall"]["pass_rate"] == 0.6667,
      f"PASS-Rate falsch: {report['overall']['pass_rate']}")
check(report["overall"]["median_tool_calls"] == 4,
      "Median der Toolaufrufe ist falsch")
check(report["by_task_class"]["context-builder"]["critical_error_rate"] == 0.5,
      "Taskklassen-Aggregation ist falsch")
check(len(metrics.read_text(encoding="utf-8").splitlines()) == 3,
      "Metriken muessen append-only als einzelne JSONL-Zeilen vorliegen")

print(json.dumps({
    "status": "FAIL" if FAILURES else "PASS",
    "eval_cases": len(cases),
    "overall": report["overall"],
    "failures": FAILURES,
    "temp_root": str(TMP),
}, ensure_ascii=False, indent=2))
sys.exit(1 if FAILURES else 0)
