"""Deterministic evals and append-only KPI capture."""

from __future__ import annotations

import json
import os
import statistics
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable

from . import ledger, locks, paths
from .contracts import ContractError, EvalCase, MetricEvent, ensure_no_secret


def _eval_from_dict(payload: dict[str, Any]) -> EvalCase:
    allowed = set(EvalCase.__dataclass_fields__)
    unknown = set(payload) - allowed
    if unknown:
        raise ContractError(f"Unbekannte Eval-Felder: {sorted(unknown)}")
    return EvalCase(**payload).validate()


def load_cases(directory: str | Path = paths.EVALS_DIR) -> list[EvalCase]:
    root = Path(directory)
    if not root.is_dir():
        return []
    cases: list[EvalCase] = []
    seen: set[str] = set()
    for source in sorted(root.rglob("*.json")):
        payload = json.loads(source.read_text(encoding="utf-8"))
        entries = payload if isinstance(payload, list) else [payload]
        if not all(isinstance(entry, dict) for entry in entries):
            raise ContractError(f"Eval-Datei enthaelt Nicht-Objekte: {source}")
        for entry in entries:
            case = _eval_from_dict(entry)
            if case.eval_id in seen:
                raise ContractError(f"Doppelte eval_id: {case.eval_id}")
            seen.add(case.eval_id)
            cases.append(case)
    return sorted(cases, key=lambda case: case.eval_id)


def score(case: EvalCase, output: str) -> dict[str, Any]:
    """Checks explicit text criteria; no AI grades its own answer."""
    case.validate()
    normalized = output.casefold()
    missing = [term for term in case.must_include if term.casefold() not in normalized]
    forbidden = [term for term in case.must_not_include if term.casefold() in normalized]
    return {
        "eval_id": case.eval_id,
        "status": "PASS" if not missing and not forbidden else "FAIL",
        "missing": missing,
        "forbidden": forbidden,
    }


def run_outputs(outputs: dict[str, str], *, directory: str | Path = paths.EVALS_DIR) -> dict[str, Any]:
    results = []
    for case in load_cases(directory):
        if case.eval_id not in outputs:
            results.append({"eval_id": case.eval_id, "status": "INCONCLUSIVE",
                            "missing": ["output"], "forbidden": []})
        else:
            results.append(score(case, outputs[case.eval_id]))
    return {
        "status": "PASS" if results and all(item["status"] == "PASS" for item in results)
        else ("INCONCLUSIVE" if not results else "FAIL"),
        "results": results,
    }


def record_metric(event: MetricEvent | dict[str, Any], *,
                  destination: str | Path = paths.METRIC_EVENTS_FILE) -> dict[str, Any]:
    if isinstance(event, MetricEvent):
        entry = event.validate()
    else:
        allowed = set(MetricEvent.__dataclass_fields__)
        unknown = set(event) - allowed
        if unknown:
            raise ContractError(f"Unbekannte Metrik-Felder: {sorted(unknown)}")
        entry = MetricEvent(**event).validate()
    payload = asdict(entry)
    ensure_no_secret(payload)
    encoded = (json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    target = Path(destination)
    target.parent.mkdir(parents=True, exist_ok=True)
    resource = "agentsystem:metrics" if target.resolve() == paths.METRIC_EVENTS_FILE.resolve() \
        else f"metrics:{target.resolve()}"
    with locks.held(resource, agent="metrics-recorder", owner="process"):
        descriptor = os.open(target, os.O_CREAT | os.O_APPEND | os.O_WRONLY)
        try:
            os.write(descriptor, encoded)
        finally:
            os.close(descriptor)
    ledger.log_event("METRIC_RECORDED", task_id=entry.task_id, run_id=entry.run_id,
                     detail={"task_class": entry.task_class, "outcome": entry.outcome})
    return payload


def load_metrics(source: str | Path = paths.METRIC_EVENTS_FILE) -> list[MetricEvent]:
    path = Path(source)
    if not path.is_file():
        return []
    result: list[MetricEvent] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
            allowed = set(MetricEvent.__dataclass_fields__)
            if set(payload) - allowed:
                raise ContractError("unbekannte Felder")
            result.append(MetricEvent(**payload).validate())
        except (json.JSONDecodeError, TypeError, ContractError) as error:
            raise ContractError(f"Ungueltige Metrikzeile {number}: {error}") from error
    return result


def _rates(events: Iterable[MetricEvent]) -> dict[str, Any]:
    entries = list(events)
    count = len(entries)
    if not count:
        return {
            "tasks": 0, "pass_rate": None, "first_pass_rate": None,
            "user_correction_rate": None, "critical_error_rate": None,
            "knowledge_reuse_rate": None, "regression_recurrence_rate": None,
            "median_tool_calls": None, "median_duration_ms": None,
        }
    rate = lambda field: round(sum(bool(getattr(item, field)) for item in entries) / count, 4)
    return {
        "tasks": count,
        "pass_rate": round(sum(item.outcome == "PASS" for item in entries) / count, 4),
        "first_pass_rate": rate("first_pass"),
        "user_correction_rate": rate("user_corrected"),
        "critical_error_rate": rate("critical_error"),
        "knowledge_reuse_rate": rate("knowledge_reused"),
        "regression_recurrence_rate": rate("regression_recurrence"),
        "median_tool_calls": statistics.median(item.tool_calls for item in entries),
        "median_duration_ms": statistics.median(item.duration_ms for item in entries),
    }


def kpi_report(source: str | Path = paths.METRIC_EVENTS_FILE) -> dict[str, Any]:
    events = load_metrics(source)
    classes = sorted({event.task_class for event in events})
    return {
        "schema_version": 1,
        "overall": _rates(events),
        "by_task_class": {
            task_class: _rates(event for event in events if event.task_class == task_class)
            for task_class in classes
        },
    }
