"""Contract tests for knowledge candidates, context, evals, and metrics."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_TMP = tempfile.mkdtemp(prefix="agentsys-contracts-")
os.environ["AGENTSYSTEM_ROOT"] = _TMP
sys.path.insert(0, str(ROOT / "bin"))

from agentsys.contracts import (  # noqa: E402
    ContextItem, ContextPackage, ContractError, EvalCase,
    KnowledgeCandidate, MetricEvent, SkillCandidate,
)

FAILURES: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        FAILURES.append(message)


def must_fail(fn, message: str) -> None:
    try:
        fn()
    except ContractError:
        return
    FAILURES.append(message)


schema_dir = ROOT / "schemas"
expected = {
    "knowledge-candidate.schema.json", "context-package.schema.json",
    "eval-case.schema.json", "metric-event.schema.json",
    "skill-candidate.schema.json",
}
found = {path.name for path in schema_dir.glob("*.json")}
check(expected <= found, f"Contract schemas missing: {expected - found}")
for path in schema_dir.glob("*.json"):
    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        FAILURES.append(f"{path.name} is not JSON: {error}")
        continue
    check(schema.get("$schema", "").endswith("2020-12/schema"),
          f"{path.name}: draft 2020-12 missing")
    check(schema.get("additionalProperties") is False,
          f"{path.name}: unknown fields must be forbidden")


candidate = KnowledgeCandidate(
    entity="router-speedport-smart4", fact_key="firmware.version",
    value="12.0.1", status="current", confidence="high",
    source_type="measurement", source_ref="local-check:2026-08-23",
    valid_from="2026-08-23", last_verified="2026-08-23",
).validate()
check(candidate.candidate_id.startswith("kc-"), "Candidate ID missing")
same = KnowledgeCandidate.from_dict(candidate.to_dict())
check(same.candidate_id == candidate.candidate_id,
      "Canonical candidate ID is not reproducible")
newer = KnowledgeCandidate(
    entity="router-speedport-smart4", fact_key="firmware.version",
    value="12.0.1", status="current", confidence="high",
    source_type="measurement", source_ref="local-check:2026-08-23",
    valid_from="2026-08-23", last_verified="2026-08-24",
).validate()
check(newer.candidate_id != candidate.candidate_id,
      "Changed versioning fields need a new candidate ID")
must_fail(lambda: KnowledgeCandidate.from_dict({
    **candidate.to_dict(), "candidate_id": "", "schema_version": 999,
}), "Unknown candidate schema version must fail")

must_fail(lambda: KnowledgeCandidate(
    entity="router-speedport-smart4", fact_key="credential",
    value="api_key=sk-abcdefghijklmnop", status="current", confidence="high",
    source_type="measurement", source_ref="local", valid_from="2026-08-23",
    last_verified="2026-08-23").validate(),
    "Secrets must be rejected in the candidate")
must_fail(lambda: KnowledgeCandidate(
    entity="router-speedport-smart4", fact_key="maybe", value=True,
    status="current", confidence="low", source_type="hypothesis",
    source_ref="agent", valid_from="2026-08-23",
    last_verified="2026-08-23").validate(),
    "A hypothesis must not be current")
must_fail(lambda: KnowledgeCandidate(
    entity="router-speedport-smart4", fact_key="path", value=True,
    status="current", confidence="high", source_type="measurement",
    source_ref="local", valid_from="2026-08-23",
    last_verified="2026-08-23", target_note="..\\privat.md").validate(),
    "Path traversal must be rejected")

item = ContextItem(
    source_path="03 Bereiche/router.md", source_sha256="a" * 64,
    excerpt="Firmware ist 12.0.1", score=120,
    entity="router-speedport-smart4", status="current",
    last_verified="2026-08-23",
)
package = ContextPackage(
    query="Welche Firmware hat der Router?", token_budget=500,
    items=[item], estimated_tokens=12,
).validate()
check(package.package_id.startswith("ctx-"), "Context package ID missing")
must_fail(lambda: ContextPackage(
    query="x", token_budget=128, items=[], estimated_tokens=1,
    schema_version=999).validate(),
    "Unknown context schema version must fail")
must_fail(lambda: ContextPackage(
    query="x", token_budget=128, items=[item], estimated_tokens=129).validate(),
    "Context package must not exceed its budget")

EvalCase(
    eval_id="router.read-status", task_class="router.status",
    prompt="Zeige den Status", risk_class="R0",
    must_include=["OBSERVED"], must_not_include=["Passwort"],
).validate()
must_fail(lambda: EvalCase(
    eval_id="router.version", task_class="router.status",
    prompt="x", risk_class="R0", schema_version=999).validate(),
    "Unknown eval schema version must fail")
must_fail(lambda: EvalCase(
    eval_id="router.bad", task_class="router.status",
    prompt="x", risk_class="R9").validate(),
    "Unknown risk class must fail")

MetricEvent(
    task_class="router.status", outcome="PASS", first_pass=True,
    user_corrected=False, critical_error=False, knowledge_reused=True,
    regression_recurrence=False, tool_calls=2, duration_ms=400,
).validate()
must_fail(lambda: MetricEvent(
    task_class="router.status", outcome="PASS", first_pass=True,
    user_corrected=False, critical_error=False, knowledge_reused=True,
    regression_recurrence=False, tool_calls=1, duration_ms=1,
    schema_version=999).validate(),
    "Unknown metric schema version must fail")

SkillCandidate(
    candidate_id="skill-router-status-v2", name="router-status",
    rationale="Wiederholbarer Ablauf", source_experience_keys=["router.status"],
).validate()
must_fail(lambda: SkillCandidate(
    candidate_id="skill-router-v3", name="router-status",
    rationale="Versionstest", source_experience_keys=["router.status"],
    schema_version=999).validate(),
    "Unknown skill schema version must fail")
must_fail(lambda: SkillCandidate(
    candidate_id="policy-v2", name="global-policy",
    rationale="automatisch", source_experience_keys=["x"],
    target_scope="policy").validate(),
    "Automatic candidate pipeline must not change policy")

print(json.dumps({
    "status": "FAIL" if FAILURES else "PASS",
    "schemas": len(expected),
    "candidate_example": candidate.candidate_id,
    "context_example": package.package_id,
    "failures": FAILURES,
    "temp_root": _TMP,
}, ensure_ascii=False, indent=2))
sys.exit(1 if FAILURES else 0)
