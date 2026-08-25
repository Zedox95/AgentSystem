"""Tests fuer Skill-Kandidaten ohne automatische Produktivschaltung."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(r"C:\AgentSystem")
TMP = Path(tempfile.mkdtemp(prefix="agentsys-skills-"))
os.environ["AGENTSYSTEM_ROOT"] = str(TMP / "system")
sys.path.insert(0, str(ROOT / "bin"))

from agentsys import experience, paths, skills_pipeline  # noqa: E402
from agentsys.contracts import ContractError  # noqa: E402

FAILURES: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        FAILURES.append(message)


entry = experience.Experience(
    key="windows.service.diagnose", method="powershell-status",
    success_count=2, failure_count=1, environment={"os": "test"},
)
experience.save(entry)
draft = (
    "---\nname: service-diagnose\n"
    "description: Diagnostiziert wiederkehrende Dienstfehler reproduzierbar.\n"
    "---\n\n# Ablauf\n\nStatus lesen, Ursache pruefen, Ergebnis testen.\n"
)
created = skills_pipeline.create_candidate(
    name="service-diagnose",
    rationale="Drei gleichartige, gemessene Durchlaeufe",
    source_experience_keys=["windows.service.diagnose"],
    draft_skill_md=draft,
)
duplicate = skills_pipeline.create_candidate(
    name="service-diagnose",
    rationale="Drei gleichartige, gemessene Durchlaeufe",
    source_experience_keys=["windows.service.diagnose"],
    draft_skill_md=draft,
)
check(created["status"] == "CANDIDATE" and created["activation"] == "MANUAL_REVIEW_REQUIRED",
      "Candidate darf nicht automatisch aktiviert werden")
check(duplicate["duplicate"], "Identischer Entwurf muss dedupliziert werden")
check(not hasattr(skills_pipeline, "promote"),
      "Pipeline darf keine automatische Promote-Funktion anbieten")
check(not (paths.SKILLS_DIR / "service-diagnose").exists(),
      "Entwurf darf nicht im produktiven Skill-Verzeichnis landen")

try:
    skills_pipeline.create_candidate(
        name="service-diagnose",
        rationale="Falscher Zielbereich",
        source_experience_keys=["windows.service.diagnose"],
        draft_skill_md=draft,
        target_scope="hooks",
    )
    FAILURES.append("Control-Plane-Zielbereich muss abgelehnt werden")
except ContractError:
    pass

before = sorted(str(path.relative_to(paths.ROOT)) for path in paths.ROOT.rglob("*"))
report = skills_pipeline.capability_report()
after = sorted(str(path.relative_to(paths.ROOT)) for path in paths.ROOT.rglob("*"))
check(before == after and report["mutations_performed"] == 0,
      "Capability Report muss strikt read-only sein")
check(report["candidate_opportunities"][0]["key"] == "windows.service.diagnose",
      "Wiederholte, unbestaetigte Erfahrung muss als Chance erscheinen")

print(json.dumps({
    "status": "FAIL" if FAILURES else "PASS",
    "candidate_id": created["candidate_id"],
    "candidate_count": len(report["skill_candidates"]),
    "opportunities": report["candidate_opportunities"],
    "failures": FAILURES,
    "temp_root": str(TMP),
}, ensure_ascii=False, indent=2))
sys.exit(1 if FAILURES else 0)
