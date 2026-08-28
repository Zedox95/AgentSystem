"""Tests for deterministic evals and KPI aggregation."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
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
check(len(cases) >= 3, "Baseline needs at least three eval cases")
example = EvalCase(
    eval_id="test-case", task_class="unit-test", prompt="Test", risk_class="R0",
    must_include=["Quelle"], must_not_include=["privat"],
).validate()
check(evals.score(example, "Quelle: hash")["status"] == "PASS",
      "Complete output must yield PASS")
check(evals.score(example, "Quelle privat")["status"] == "FAIL",
      "Forbidden content must yield FAIL")

metrics = TMP / "events.jsonl"
for event in (
    MetricEvent("context-builder", "PASS", True, False, False, True, False, 4, 100),
    MetricEvent("context-builder", "FAIL", False, True, True, False, True, 8, 300),
    MetricEvent("knowledge-write", "PASS", True, False, False, True, False, 2, 50),
):
    evals.record_metric(event, destination=metrics)
report = evals.kpi_report(metrics)
check(report["overall"]["tasks"] == 3, "KPI report must count three tasks")
check(report["overall"]["pass_rate"] == 0.6667,
      f"PASS rate wrong: {report['overall']['pass_rate']}")
check(report["overall"]["median_tool_calls"] == 4,
      "Median tool calls is wrong")
check(report["by_task_class"]["context-builder"]["critical_error_rate"] == 0.5,
      "Task class aggregation is wrong")
check(len(metrics.read_text(encoding="utf-8").splitlines()) == 3,
      "Metrics must be append-only as individual JSONL lines")

print(json.dumps({
    "status": "FAIL" if FAILURES else "PASS",
    "eval_cases": len(cases),
    "overall": report["overall"],
    "failures": FAILURES,
    "temp_root": str(TMP),
}, ensure_ascii=False, indent=2))
sys.exit(1 if FAILURES else 0)
