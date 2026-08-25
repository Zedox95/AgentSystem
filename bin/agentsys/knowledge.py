"""Kontrollierter Second-Brain-Zugriff.

Lesen ist breit, aber standardmaessig auf verwaltete Notizen mit vollstaendigem
Frontmatter begrenzt. Schreiben geschieht ausschliesslich ueber validierte
Knowledge Candidates und den Archivist-Pfad mit Lock, Optimistic Concurrency,
Backup und atomarem Replace.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import asdict
from pathlib import Path
from typing import Any

from . import ledger, locks, paths
from .contracts import (
    SOURCE_PRIORITY, ContractError, KnowledgeCandidate, atomic_write_json,
    file_hash, utcnow,
)

DEFAULT_VAULT = Path(os.environ.get(
    "AGENTSYSTEM_VAULT", str(Path.home() / "Documents" / "Obsidian Vault")
))

_MANAGED_START = "<!-- agentsystem:facts:start -->"
_MANAGED_END = "<!-- agentsystem:facts:end -->"
_REQUIRED_FRONTMATTER = {
    "type", "entity", "status", "confidence", "source_type",
    "valid_from", "last_verified",
}
_SKIP_PARTS = {".git", ".obsidian", ".trash", "05 Daily Notes"}
_WORD = re.compile(r"[a-zA-Z0-9_.:-]{2,}")


class KnowledgeConflict(ContractError):
    """Ein Kandidat darf den vorhandenen Wissensstand nicht ueberschreiben."""


def _frontmatter(text: str) -> tuple[dict[str, str], int]:
    if not text.startswith("---\n"):
        return {}, 0
    end = text.find("\n---\n", 4)
    if end < 0:
        return {}, 0
    result: dict[str, str] = {}
    for line in text[4:end].splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, sep, value = line.partition(":")
        if sep:
            result[key.strip()] = value.strip().strip('"\'')
    return result, end + len("\n---\n")


def _render_frontmatter(meta: dict[str, str]) -> str:
    lines = ["---"]
    for key, value in meta.items():
        safe = str(value).replace("\n", " ").replace('"', "\\\"")
        lines.append(f'{key}: "{safe}"')
    return "\n".join(lines) + "\n---\n"


def _managed_payload(text: str, entity: str) -> dict[str, Any]:
    start = text.find(_MANAGED_START)
    end = text.find(_MANAGED_END)
    if start < 0 or end < start:
        return {"schema_version": 1, "entity": entity, "facts": {}}
    block = text[start + len(_MANAGED_START):end].strip()
    if block.startswith("```json") and block.endswith("```"):
        block = block[len("```json"): -len("```")].strip()
    try:
        payload = json.loads(block)
    except json.JSONDecodeError as error:
        raise KnowledgeConflict("Vorhandener AgentSystem-Faktenblock ist beschaedigt") from error
    if payload.get("entity") != entity or not isinstance(payload.get("facts"), dict):
        raise KnowledgeConflict("Vorhandener Faktenblock passt nicht zur Entitaet")
    return payload


def _is_managed_note(text: str, entity: str) -> bool:
    """Nur explizit markierte, strukturell gueltige Notizen gelten als verwaltet."""
    meta, _ = _frontmatter(text)
    if not _REQUIRED_FRONTMATTER <= set(meta) or meta.get("entity") != entity:
        return False
    if _MANAGED_START not in text or _MANAGED_END not in text:
        return False
    try:
        _managed_payload(text, entity)
    except KnowledgeConflict:
        return False
    return True


def _candidate_identity(candidate: KnowledgeCandidate) -> dict[str, Any]:
    """Semantischer Inhalt ohne fluechtigen Erstellungszeitpunkt und berechnete ID."""
    return {
        key: value for key, value in candidate.to_dict().items()
        if key not in {"candidate_id", "created_utc"}
    }


def _strongest_visible_fact(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Waehlt die Metadatensicht ohne eine staerkere Quelle herabzustufen."""
    records = [
        record
        for history in payload.get("facts", {}).values()
        if isinstance(history, list)
        for record in history
        if isinstance(record, dict)
        and record.get("status") in ("current", "planned", "tested")
    ]
    if not records:
        records = [
            record
            for history in payload.get("facts", {}).values()
            if isinstance(history, list)
            for record in history
            if isinstance(record, dict)
            and record.get("status") not in ("superseded", "historical", "rejected")
        ]
    if not records:
        return None
    status_rank = {"current": 4, "tested": 3, "planned": 2,
                   "needs_review": 1, "hypothesis": 0}
    confidence_rank = {"high": 2, "medium": 1, "low": 0}
    return max(records, key=lambda record: (
        SOURCE_PRIORITY.get(record.get("source_type", "hypothesis"), 0),
        status_rank.get(record.get("status"), -1),
        record.get("last_verified", ""),
        confidence_rank.get(record.get("confidence"), -1),
        record.get("candidate_id", ""),
    ))


def _replace_managed_payload(text: str, payload: dict[str, Any]) -> str:
    rendered = (
        _MANAGED_START + "\n```json\n"
        + json.dumps(payload, ensure_ascii=False, indent=2, default=str)
        + "\n```\n" + _MANAGED_END
    )
    start = text.find(_MANAGED_START)
    end = text.find(_MANAGED_END)
    if start >= 0 and end >= start:
        return text[:start] + rendered + text[end + len(_MANAGED_END):]
    separator = "" if text.endswith("\n\n") else ("\n" if text.endswith("\n") else "\n\n")
    return text + separator + "## Verwaltete Fakten\n\n" + rendered + "\n"


def _safe_relative(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _candidate_path(candidate_id: str, bucket: str = "pending") -> Path:
    paths.ensure_dirs()
    directory = {
        "pending": paths.KNOWLEDGE_PENDING_DIR,
        "accepted": paths.KNOWLEDGE_ACCEPTED_DIR,
        "rejected": paths.KNOWLEDGE_REJECTED_DIR,
    }[bucket]
    return directory / f"{candidate_id}.json"


def submit(candidate: KnowledgeCandidate | dict[str, Any]) -> dict[str, Any]:
    entry = (candidate if isinstance(candidate, KnowledgeCandidate)
             else KnowledgeCandidate.from_dict(candidate)).validate()
    payload = entry.to_dict()
    found_bucket: str | None = None
    target = _candidate_path(entry.candidate_id)
    for bucket in ("pending", "accepted", "rejected"):
        existing_path = _candidate_path(entry.candidate_id, bucket)
        if not existing_path.is_file():
            continue
        raw = json.loads(existing_path.read_text(encoding="utf-8"))
        known = {key: value for key, value in raw.items()
                 if key in KnowledgeCandidate.__dataclass_fields__}
        existing = KnowledgeCandidate.from_dict(known)
        if _candidate_identity(existing) != _candidate_identity(entry):
            raise KnowledgeConflict("Candidate-ID-Kollision mit abweichendem Inhalt")
        target = existing_path
        found_bucket = bucket
        break
    if found_bucket is None:
        try:
            atomic_write_json(target, payload, exclusive=True)
            duplicate = False
        except FileExistsError:
            # Parallel entstandener Eintrag wird im naechsten Aufruf vollstaendig
            # verglichen; niemals ungeprueft als Duplikat behandeln.
            raw = json.loads(target.read_text(encoding="utf-8"))
            existing = KnowledgeCandidate.from_dict(raw)
            if _candidate_identity(existing) != _candidate_identity(entry):
                raise KnowledgeConflict("Candidate-ID-Kollision mit abweichendem Inhalt")
            duplicate = True
            found_bucket = "pending"
    else:
        duplicate = True
    ledger.log_event("KNOWLEDGE_CANDIDATE_SUBMITTED", detail={
        "candidate_id": entry.candidate_id, "entity": entry.entity,
        "fact_key": entry.fact_key, "duplicate": duplicate,
    })
    return {"candidate_id": entry.candidate_id, "path": str(target),
            "duplicate": duplicate, "status": (found_bucket or "pending").upper()}


def load_candidate(candidate_id: str, bucket: str = "pending") -> KnowledgeCandidate:
    path = _candidate_path(candidate_id, bucket)
    if not path.is_file():
        raise KeyError(f"Unbekannter Knowledge Candidate: {candidate_id}")
    return KnowledgeCandidate.from_dict(json.loads(path.read_text(encoding="utf-8")))


def list_candidates(bucket: str = "pending") -> list[dict[str, Any]]:
    directory = {
        "pending": paths.KNOWLEDGE_PENDING_DIR,
        "accepted": paths.KNOWLEDGE_ACCEPTED_DIR,
        "rejected": paths.KNOWLEDGE_REJECTED_DIR,
    }[bucket]
    paths.ensure_dirs()
    result = []
    for path in sorted(directory.glob("kc-*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            entry = KnowledgeCandidate.from_dict({
                key: value for key, value in payload.items()
                if key in KnowledgeCandidate.__dataclass_fields__
            })
        except (OSError, json.JSONDecodeError, ContractError):
            result.append({"path": str(path), "invalid": True})
            continue
        result.append({"candidate_id": entry.candidate_id, "entity": entry.entity,
                       "fact_key": entry.fact_key, "status": bucket.upper(),
                       "source_type": entry.source_type})
    return result


def _managed_notes(vault_root: str | Path) -> list[tuple[Path, dict[str, str], str]]:
    root = Path(vault_root).resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"Vault nicht gefunden: {root}")
    result = []
    for note in sorted(root.rglob("*.md")):
        relative_parts = set(note.relative_to(root).parts)
        if relative_parts & _SKIP_PARTS:
            continue
        try:
            text = note.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        meta, _ = _frontmatter(text)
        if not _REQUIRED_FRONTMATTER <= set(meta):
            continue
        if not _is_managed_note(text, meta.get("entity", "")):
            continue
        result.append((note, meta, text))
    return result


def search(vault_root: str | Path, query: str, *, entity: str | None = None,
           project: str | None = None, statuses: set[str] | None = None,
           limit: int = 10) -> list[dict[str, Any]]:
    """Deterministische, rein lesende Metadata-/Volltextsuche."""
    if not query.strip() and not entity and not project:
        raise ContractError("Suche braucht query, entity oder project")
    root = Path(vault_root).resolve()
    terms = {token.lower() for token in _WORD.findall(query)}
    matches = []
    for note, meta, text in _managed_notes(root):
        if entity and meta.get("entity") != entity:
            continue
        if project and meta.get("project") != project:
            continue
        if statuses and meta.get("status") not in statuses:
            continue
        lower = text.lower()
        score = 0
        if entity and meta.get("entity") == entity:
            score += 1000
        if project and meta.get("project") == project:
            score += 500
        score += sum(40 for term in terms if term in meta.get("entity", "").lower())
        score += sum(min(lower.count(term), 5) * 10 for term in terms)
        score += SOURCE_PRIORITY.get(meta.get("source_type", "hypothesis"), 0)
        if score <= 0:
            continue
        plain = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
        plain = re.sub(r"<!--.*?-->", " ", plain, flags=re.DOTALL)
        plain = " ".join(plain.split())
        # Keine Credential-artigen Werte in Suchausgaben tragen.
        from .ledger import redact
        excerpt = redact(plain[:1200]) or ""
        matches.append({
            "source_path": _safe_relative(note, root),
            "source_sha256": file_hash(note),
            "entity": meta.get("entity"), "project": meta.get("project"),
            "status": meta.get("status"),
            "last_verified": meta.get("last_verified"),
            "source_type": meta.get("source_type"),
            "score": score, "excerpt": excerpt,
        })
    return sorted(matches, key=lambda item: (-item["score"], item["source_path"]))[:limit]


def _entity_notes(vault_root: Path, entity: str) -> list[Path]:
    return [note for note, meta, _ in _managed_notes(vault_root)
            if meta.get("entity") == entity]


def _target_for(candidate: KnowledgeCandidate, vault_root: Path) -> Path:
    if candidate.target_note:
        target = (vault_root / candidate.target_note).resolve()
        target.relative_to(vault_root.resolve())
        return target
    existing = _entity_notes(vault_root, candidate.entity)
    if len(existing) > 1:
        raise KnowledgeConflict(
            f"Mehrere verwaltete Notizen fuer entity={candidate.entity}; manuelle Klaerung noetig"
        )
    if existing:
        return existing[0]
    return vault_root / "01 Inbox" / f"{candidate.entity}.md"


def approve(candidate_id: str, *, vault_root: str | Path = DEFAULT_VAULT,
            task_id: str, expected_sha256: str) -> dict[str, Any]:
    task = ledger.get_task(task_id)
    if task is None or task.get("state") in ("COMMITTED", "FAILED", "ROLLED_BACK"):
        raise ContractError("Archivist-Schreiben braucht einen offenen Task Contract")
    if task.get("risk_class") not in ("R1", "R2", "R3"):
        raise ContractError("Produktives Wissen ist mindestens R1")
    candidate = load_candidate(candidate_id)
    root = Path(vault_root).resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"Vault nicht gefunden: {root}")
    resource = f"obsidian:entity:{candidate.entity}"
    with locks.held(resource, agent="archivist", task_id=task_id, owner="process"):
        target = _target_for(candidate, root).resolve()
        target.relative_to(root)
        existed = target.is_file()
        if existed:
            actual_hash = file_hash(target)
            if expected_sha256 != actual_hash:
                raise KnowledgeConflict(
                    f"Optimistic-Concurrency-Konflikt: erwartet {expected_sha256}, ist {actual_hash}"
                )
            text = target.read_text(encoding="utf-8")
            meta, body_start = _frontmatter(text)
            if not _is_managed_note(text, candidate.entity):
                raise KnowledgeConflict(
                    "Bestehende target_note ist keine verwaltete AgentSystem-Notiz"
                )
        else:
            if expected_sha256 != "NEW":
                raise KnowledgeConflict("Neue Notiz muss expected_sha256=NEW verwenden")
            meta = {
                "type": "system_entity", "entity": candidate.entity,
                "status": candidate.status, "confidence": candidate.confidence,
                "source_type": candidate.source_type,
                "valid_from": candidate.valid_from,
                "last_verified": candidate.last_verified,
            }
            if candidate.project:
                meta["project"] = candidate.project
            text = _render_frontmatter(meta) + f"\n# {candidate.entity}\n"
            _, body_start = _frontmatter(text)

        payload = _managed_payload(text, candidate.entity)
        history = payload["facts"].setdefault(candidate.fact_key, [])
        active = [fact for fact in history
                  if fact.get("status") in ("current", "planned", "tested")]
        for fact in active:
            if fact.get("value") != candidate.value:
                old_priority = SOURCE_PRIORITY.get(fact.get("source_type", "hypothesis"), 0)
                new_priority = SOURCE_PRIORITY[candidate.source_type]
                if new_priority < old_priority:
                    raise KnowledgeConflict(
                        "Schwaechere Quelle darf vorhandenes Wissen nicht ueberschreiben"
                    )
                fact["status"] = "superseded"
                fact["superseded_utc"] = utcnow()
        fact_record = {
            "value": candidate.value, "status": candidate.status,
            "confidence": candidate.confidence,
            "source_type": candidate.source_type, "source_ref": candidate.source_ref,
            "valid_from": candidate.valid_from,
            "last_verified": candidate.last_verified,
            "candidate_id": candidate.candidate_id,
            "project": candidate.project,
        }
        if not any(item.get("candidate_id") == candidate.candidate_id for item in history):
            history.append(fact_record)
        payload["updated_utc"] = utcnow()
        visible = _strongest_visible_fact(payload)
        if visible:
            meta.update({
                "status": visible.get("status", meta.get("status", "needs_review")),
                "confidence": visible.get("confidence", meta.get("confidence", "low")),
                "source_type": visible.get("source_type", meta.get("source_type", "hypothesis")),
                "valid_from": visible.get("valid_from", meta.get("valid_from", candidate.valid_from)),
                "last_verified": visible.get(
                    "last_verified", meta.get("last_verified", candidate.last_verified)
                ),
            })
            if visible.get("project"):
                meta["project"] = visible["project"]
        text = _render_frontmatter(meta) + text[body_start:]
        updated = _replace_managed_payload(text, payload)

        if existed:
            backup = paths.BASELINES_DIR / "knowledge" / candidate.candidate_id / _safe_relative(target, root)
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, backup)
            if file_hash(backup) != actual_hash:
                raise OSError("Knowledge-Backup-Hash stimmt nicht")
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + f".{os.getpid()}.tmp")
        temporary.write_text(updated, encoding="utf-8", newline="\n")
        temporary.replace(target)

        accepted = json.loads(_candidate_path(candidate_id).read_text(encoding="utf-8"))
        accepted["decision"] = {"status": "ACCEPTED", "task_id": task_id,
                                "decided_utc": utcnow(),
                                "target_note": _safe_relative(target, root),
                                "target_sha256": file_hash(target)}
        accepted_path = _candidate_path(candidate_id, "accepted")
        atomic_write_json(accepted_path, accepted)
        _candidate_path(candidate_id).unlink()
        ledger.log_event("KNOWLEDGE_CANDIDATE_ACCEPTED", task_id=task_id,
                         agent="archivist", detail=accepted["decision"])
        return accepted["decision"]


def review_task(task_id: str, *, decision: str, reason: str,
                candidate_ids: list[str] | None = None) -> dict[str, Any]:
    """Dokumentiert die verpflichtende Wissensprüfung vor COMMITTED.

    `captured` ist nur für Candidates zulässig, die mit demselben Task bereits
    über den Archivist akzeptiert wurden. `deferred` hält bewusst offene oder
    abgelehnte Candidates sichtbar, ohne den Arbeitserfolg umzudeuten.
    """
    normalized = decision.strip().lower()
    ids = list(dict.fromkeys(candidate_ids or []))
    if normalized == "none":
        if ids:
            raise ContractError("decision=none darf keine Candidate-IDs enthalten")
    elif normalized == "captured":
        if not ids:
            raise ContractError("decision=captured braucht mindestens eine Candidate-ID")
        for candidate_id in ids:
            path = _candidate_path(candidate_id, "accepted")
            if not path.is_file():
                raise ContractError(
                    f"Captured Candidate ist nicht akzeptiert: {candidate_id}"
                )
            payload = json.loads(path.read_text(encoding="utf-8"))
            if (payload.get("decision") or {}).get("task_id") != task_id:
                raise ContractError(
                    f"Captured Candidate gehört nicht zu Task {task_id}: {candidate_id}"
                )
    elif normalized == "deferred":
        if not ids:
            raise ContractError("decision=deferred braucht mindestens eine Candidate-ID")
        for candidate_id in ids:
            pending = _candidate_path(candidate_id, "pending").is_file()
            rejected = _candidate_path(candidate_id, "rejected").is_file()
            if not (pending or rejected):
                raise ContractError(
                    f"Deferred Candidate ist weder pending noch rejected: {candidate_id}"
                )
    else:
        raise ContractError(f"Unbekannte Knowledge-Review-Entscheidung: {decision}")
    return ledger.record_knowledge_review(
        task_id, decision=normalized, reason=reason, candidate_ids=ids,
    )


def reject(candidate_id: str, *, task_id: str, reason: str) -> dict[str, Any]:
    if not reason.strip():
        raise ContractError("Ablehnung braucht eine Begruendung")
    task = ledger.get_task(task_id)
    if task is None or task.get("state") in ("COMMITTED", "FAILED", "ROLLED_BACK"):
        raise ContractError("Candidate-Ablehnung braucht einen offenen Task Contract")
    candidate = load_candidate(candidate_id)
    payload = candidate.to_dict()
    payload["decision"] = {"status": "REJECTED", "task_id": task_id,
                           "reason": reason, "decided_utc": utcnow()}
    destination = _candidate_path(candidate_id, "rejected")
    atomic_write_json(destination, payload)
    _candidate_path(candidate_id).unlink()
    ledger.log_event("KNOWLEDGE_CANDIDATE_REJECTED", task_id=task_id,
                     agent="archivist", detail={"candidate_id": candidate_id,
                                                "reason": reason})
    return payload["decision"]
