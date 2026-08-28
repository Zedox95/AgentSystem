"""Versioned data contracts for knowledge, context, evals, and metrics.

The runtime deliberately stays standard-library-only. JSON schema files
under ``schemas/`` document the same contracts for external clients;
here the security-relevant rules are enforced deterministically.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from .ledger import redact

SCHEMA_VERSION = 1

KNOWLEDGE_STATUSES = {
    "current", "planned", "tested", "historical", "superseded",
    "rejected", "needs_review", "hypothesis",
}
CONFIDENCE_LEVELS = {"high", "medium", "low"}
SOURCE_TYPES = {
    "measurement", "user_confirmed", "local_config", "official_docs",
    "expert_source", "vendor", "community", "agent_inference", "hypothesis",
}
SOURCE_PRIORITY = {
    "measurement": 100,
    "user_confirmed": 100,
    "local_config": 90,
    "official_docs": 80,
    "expert_source": 70,
    "vendor": 60,
    "community": 50,
    "agent_inference": 40,
    "hypothesis": 10,
}
RISK_CLASSES = {"R0", "R1", "R2", "R3"}
METRIC_OUTCOMES = {"PASS", "FAIL", "INCONCLUSIVE", "ROLLED_BACK"}

_SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9._:-]{1,127}$")


class ContractError(ValueError):
    """A data object violates its versioned contract."""


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), default=str)


def content_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def file_hash(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ensure_no_secret(value: Any) -> None:
    serialized = canonical_json(value)
    if redact(serialized) != serialized:
        raise ContractError("Das Objekt enthaelt ein moegliches Secret und wird abgelehnt")


def require_id(value: str, label: str) -> None:
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        raise ContractError(f"{label} muss eine stabile, sichere ID sein")


def require_iso_date(value: str, label: str) -> None:
    try:
        date.fromisoformat(value)
    except (TypeError, ValueError) as error:
        raise ContractError(f"{label} muss YYYY-MM-DD sein") from error


def require_relative_path(value: str | None, label: str) -> None:
    if value is None:
        return
    candidate = Path(value)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ContractError(f"{label} muss relativ und traversal-frei sein")


def atomic_write_json(path: str | Path, payload: Any, *, exclusive: bool = False) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n").encode("utf-8")
    if exclusive:
        handle = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        with os.fdopen(handle, "wb") as stream:
            stream.write(encoded)
        return
    temporary = destination.with_name(destination.name + f".{os.getpid()}.tmp")
    temporary.write_bytes(encoded)
    temporary.replace(destination)


@dataclass
class KnowledgeCandidate:
    entity: str
    fact_key: str
    value: Any
    status: str
    confidence: str
    source_type: str
    source_ref: str
    valid_from: str
    last_verified: str
    project: str | None = None
    target_note: str | None = None
    created_by: str = "agent"
    created_utc: str = field(default_factory=utcnow)
    schema_version: int = SCHEMA_VERSION
    candidate_id: str = ""

    def validate(self) -> "KnowledgeCandidate":
        if self.schema_version != SCHEMA_VERSION:
            raise ContractError(f"Unbekannte schema_version: {self.schema_version}")
        require_id(self.entity, "entity")
        require_id(self.fact_key, "fact_key")
        if self.status not in KNOWLEDGE_STATUSES:
            raise ContractError(f"Unbekannter Wissensstatus: {self.status}")
        if self.confidence not in CONFIDENCE_LEVELS:
            raise ContractError(f"Unbekannte Confidence: {self.confidence}")
        if self.source_type not in SOURCE_TYPES:
            raise ContractError(f"Unbekannter source_type: {self.source_type}")
        if self.source_type == "hypothesis" and self.status != "hypothesis":
            raise ContractError("Hypothesenquelle darf nicht als Faktstatus gespeichert werden")
        if self.status == "hypothesis" and self.source_type != "hypothesis":
            raise ContractError("Status hypothesis erfordert source_type hypothesis")
        if not isinstance(self.source_ref, str) or not self.source_ref.strip():
            raise ContractError("source_ref fehlt")
        require_iso_date(self.valid_from, "valid_from")
        require_iso_date(self.last_verified, "last_verified")
        require_relative_path(self.target_note, "target_note")
        identity = {
            "entity": self.entity, "fact_key": self.fact_key, "value": self.value,
            "status": self.status, "confidence": self.confidence,
            "source_type": self.source_type, "source_ref": self.source_ref,
            "valid_from": self.valid_from, "last_verified": self.last_verified,
            "project": self.project, "target_note": self.target_note,
            "created_by": self.created_by, "schema_version": self.schema_version,
        }
        expected = "kc-" + content_hash(identity)[:16]
        if self.candidate_id and self.candidate_id != expected:
            raise ContractError("candidate_id passt nicht zum kanonischen Inhalt")
        self.candidate_id = expected
        ensure_no_secret(asdict(self))
        return self

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "KnowledgeCandidate":
        allowed = set(cls.__dataclass_fields__)
        unknown = set(data) - allowed
        if unknown:
            raise ContractError(f"Unbekannte Candidate-Felder: {sorted(unknown)}")
        return cls(**data).validate()


@dataclass
class ContextItem:
    source_path: str
    source_sha256: str
    excerpt: str
    score: int
    entity: str | None = None
    status: str | None = None
    last_verified: str | None = None

    def validate(self) -> "ContextItem":
        require_relative_path(self.source_path, "source_path")
        if not re.fullmatch(r"[0-9a-f]{64}", self.source_sha256):
            raise ContractError("source_sha256 ist ungueltig")
        if not isinstance(self.excerpt, str) or not self.excerpt.strip():
            raise ContractError("ContextItem braucht einen Textauszug")
        if self.status is not None and self.status not in KNOWLEDGE_STATUSES:
            raise ContractError(f"Unbekannter Context-Status: {self.status}")
        if self.last_verified:
            require_iso_date(self.last_verified, "last_verified")
        return self


@dataclass
class ContextPackage:
    query: str
    token_budget: int
    items: list[ContextItem]
    estimated_tokens: int
    conflicts: list[str] = field(default_factory=list)
    truncated: bool = False
    generated_utc: str = field(default_factory=utcnow)
    schema_version: int = SCHEMA_VERSION
    package_id: str = ""

    def validate(self) -> "ContextPackage":
        if self.schema_version != SCHEMA_VERSION:
            raise ContractError(f"Unbekannte schema_version: {self.schema_version}")
        if not self.query.strip():
            raise ContractError("ContextPackage braucht eine query")
        if not 128 <= self.token_budget <= 100_000:
            raise ContractError("token_budget ausserhalb 128..100000")
        for item in self.items:
            item.validate()
        if self.estimated_tokens < 0 or self.estimated_tokens > self.token_budget:
            raise ContractError("estimated_tokens verletzt das Budget")
        identity = {
            "query": self.query,
            "token_budget": self.token_budget,
            "items": [asdict(item) for item in self.items],
            "conflicts": self.conflicts,
            "truncated": self.truncated,
        }
        expected = "ctx-" + content_hash(identity)[:16]
        if self.package_id and self.package_id != expected:
            raise ContractError("package_id passt nicht zum Inhalt")
        self.package_id = expected
        ensure_no_secret(identity)
        return self

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        data = asdict(self)
        return data


@dataclass
class EvalCase:
    eval_id: str
    task_class: str
    prompt: str
    risk_class: str
    must_include: list[str] = field(default_factory=list)
    must_not_include: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    schema_version: int = SCHEMA_VERSION

    def validate(self) -> "EvalCase":
        if self.schema_version != SCHEMA_VERSION:
            raise ContractError(f"Unbekannte schema_version: {self.schema_version}")
        require_id(self.eval_id, "eval_id")
        require_id(self.task_class, "task_class")
        if self.risk_class not in RISK_CLASSES:
            raise ContractError(f"Unbekannte Risikoklasse: {self.risk_class}")
        if not self.prompt.strip():
            raise ContractError("EvalCase braucht einen Prompt")
        ensure_no_secret(asdict(self))
        return self


@dataclass
class MetricEvent:
    task_class: str
    outcome: str
    first_pass: bool
    user_corrected: bool
    critical_error: bool
    knowledge_reused: bool
    regression_recurrence: bool
    tool_calls: int
    duration_ms: int
    task_id: str | None = None
    run_id: str | None = None
    recorded_utc: str = field(default_factory=utcnow)
    schema_version: int = SCHEMA_VERSION

    def validate(self) -> "MetricEvent":
        if self.schema_version != SCHEMA_VERSION:
            raise ContractError(f"Unbekannte schema_version: {self.schema_version}")
        require_id(self.task_class, "task_class")
        if self.outcome not in METRIC_OUTCOMES:
            raise ContractError(f"Unbekanntes Outcome: {self.outcome}")
        if self.tool_calls < 0 or self.duration_ms < 0:
            raise ContractError("Metrikwerte duerfen nicht negativ sein")
        ensure_no_secret(asdict(self))
        return self


@dataclass
class SkillCandidate:
    candidate_id: str
    name: str
    rationale: str
    source_experience_keys: list[str]
    target_scope: str = "skill"
    status: str = "CANDIDATE"
    created_utc: str = field(default_factory=utcnow)
    schema_version: int = SCHEMA_VERSION

    def validate(self) -> "SkillCandidate":
        if self.schema_version != SCHEMA_VERSION:
            raise ContractError(f"Unbekannte schema_version: {self.schema_version}")
        require_id(self.candidate_id, "candidate_id")
        require_id(self.name, "name")
        if self.status != "CANDIDATE":
            raise ContractError("Neue Skill-Versionen starten immer als CANDIDATE")
        if self.target_scope != "skill":
            raise ContractError("Automatische Candidates duerfen nur Skills betreffen")
        if not self.rationale.strip() or not self.source_experience_keys:
            raise ContractError("SkillCandidate braucht Begruendung und Erfahrungen")
        ensure_no_secret(asdict(self))
        return self
