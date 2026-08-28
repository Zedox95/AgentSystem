"""Safe proposal pipeline for learning skills.

The pipeline exclusively writes drafts to ``state/skill-candidates``. There
is deliberately no promote, install, or control-plane function here.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any

from . import experience, paths
from .contracts import (
    ContractError, SkillCandidate, atomic_write_json, content_hash,
    ensure_no_secret,
)

_FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _validate_draft(name: str, draft: str) -> None:
    if not isinstance(draft, str) or not draft.strip():
        raise ContractError("Skill Candidate braucht einen SKILL.md-Entwurf")
    match = _FRONTMATTER.match(draft)
    if not match:
        raise ContractError("SKILL.md-Entwurf braucht YAML-Frontmatter")
    fields: dict[str, str] = {}
    for line in match.group(1).splitlines():
        key, separator, value = line.partition(":")
        if separator:
            fields[key.strip()] = value.strip().strip("\"'")
    if fields.get("name") != name or not fields.get("description"):
        raise ContractError("Skill-Frontmatter braucht passenden name und description")
    ensure_no_secret(draft)


def _experience_index() -> dict[str, list[experience.Experience]]:
    result: dict[str, list[experience.Experience]] = {}
    for entry in experience.all_entries():
        result.setdefault(entry.key, []).append(entry)
    return result


def create_candidate(*, name: str, rationale: str,
                     source_experience_keys: list[str], draft_skill_md: str,
                     target_scope: str = "skill") -> dict[str, Any]:
    """Creates a deduplicated draft without activating it in production."""
    keys = sorted(set(source_experience_keys))
    if not keys:
        raise ContractError("Mindestens eine Quellerfahrung ist erforderlich")
    index = _experience_index()
    missing = [key for key in keys if key not in index]
    if missing:
        raise ContractError(f"Unbekannte Quellerfahrungen: {missing}")
    repeated = {
        key: sum(entry.attempts for entry in index[key])
        for key in keys
    }
    if max(repeated.values()) < 2:
        raise ContractError("Skill-Lernen erfordert mindestens eine wiederholte Erfahrung")
    _validate_draft(name, draft_skill_md)
    identity = {
        "name": name,
        "rationale": rationale,
        "source_experience_keys": keys,
        "draft_sha256": content_hash(draft_skill_md),
    }
    candidate_id = "skill-" + content_hash(identity)[:16]
    candidate = SkillCandidate(
        candidate_id=candidate_id,
        name=name,
        rationale=rationale,
        source_experience_keys=keys,
        target_scope=target_scope,
    ).validate()
    paths.ensure_dirs()
    directory = paths.SKILL_CANDIDATES_DIR / candidate_id
    try:
        directory.mkdir(parents=False)
        duplicate = False
    except FileExistsError:
        duplicate = True
    manifest = directory / "candidate.json"
    draft_path = directory / "SKILL.md"
    if duplicate:
        if not manifest.is_file() or not draft_path.is_file():
            raise ContractError("Vorhandener Skill Candidate ist unvollstaendig")
        existing = json.loads(manifest.read_text(encoding="utf-8"))
        if existing.get("candidate_id") != candidate_id \
                or draft_path.read_text(encoding="utf-8") != draft_skill_md:
            raise ContractError("Skill-Candidate-ID-Kollision")
    else:
        try:
            atomic_write_json(manifest, asdict(candidate), exclusive=True)
            draft_path.write_text(draft_skill_md, encoding="utf-8", newline="\n")
        except Exception:
            for child in directory.iterdir():
                child.unlink(missing_ok=True)
            directory.rmdir()
            raise
    return {
        "candidate_id": candidate_id,
        "status": "CANDIDATE",
        "duplicate": duplicate,
        "path": str(directory),
        "activation": "MANUAL_REVIEW_REQUIRED",
    }


def list_candidates() -> list[dict[str, Any]]:
    if not paths.SKILL_CANDIDATES_DIR.is_dir():
        return []
    result = []
    for manifest in sorted(paths.SKILL_CANDIDATES_DIR.glob("skill-*/candidate.json")):
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            candidate = SkillCandidate(**payload).validate()
            draft_exists = (manifest.parent / "SKILL.md").is_file()
            result.append({**asdict(candidate), "draft_exists": draft_exists,
                           "path": str(manifest.parent)})
        except (OSError, json.JSONDecodeError, TypeError, ContractError) as error:
            result.append({"path": str(manifest.parent), "invalid": True,
                           "error": str(error)})
    return result


def capability_report() -> dict[str, Any]:
    """Read-only inventory: repeated experiences, skills, and drafts."""
    entries: list[experience.Experience] = []
    if paths.EXPERIENCES_DIR.is_dir():
        known = set(experience.Experience.__dataclass_fields__)
        for source in sorted(paths.EXPERIENCES_DIR.glob("*.json")):
            try:
                payload = json.loads(source.read_text(encoding="utf-8"))
                entries.append(experience.Experience(
                    **{key: value for key, value in payload.items() if key in known}
                ))
            except (OSError, json.JSONDecodeError, TypeError):
                continue
    by_key: dict[str, dict[str, Any]] = {}
    for entry in entries:
        group = by_key.setdefault(entry.key, {
            "key": entry.key, "attempts": 0, "successes": 0,
            "failures": 0, "verified_methods": 0,
        })
        group["attempts"] += entry.attempts
        group["successes"] += entry.success_count
        group["failures"] += entry.failure_count
        group["verified_methods"] += int(entry.status == experience.VERIFIED)
    opportunities = [
        value for value in by_key.values()
        if value["attempts"] >= 3 and value["verified_methods"] == 0
    ]
    opportunities.sort(key=lambda item: (-item["failures"], -item["attempts"], item["key"]))
    installed = sorted(
        skill.parent.name for skill in paths.SKILLS_DIR.glob("*/SKILL.md")
    ) if paths.SKILLS_DIR.is_dir() else []
    observed_text = " ".join(
        f"{entry.key} {entry.method} {entry.tool or ''}" for entry in entries
    ).casefold()
    return {
        "schema_version": 1,
        "experience_keys": len(by_key),
        "installed_skills": installed,
        "unobserved_installed_skills": [
            name for name in installed if name.casefold() not in observed_text
        ],
        "skill_candidates": list_candidates(),
        "candidate_opportunities": opportunities,
        "mutations_performed": 0,
    }
