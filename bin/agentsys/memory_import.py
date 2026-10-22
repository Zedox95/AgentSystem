"""Import user-provided memory lists or conversation exports as pending evidence.

No account scraping; no assistant messages promoted into facts; no vault writes.
Category selection is a transparent suggestion rather than semantic certainty.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from . import knowledge, paths
from .contracts import ContractError, KnowledgeCandidate, content_hash, file_hash

CATEGORIES = (
    ("Systems", r"server|proxmox|computer|windows|linux|hardware|router|codex|claude"),
    ("Learning", r"learn|exam|course|umschulung|pruefung|prüfung|ausbildung|lernen"),
    ("Projects", r"project|projekt|minecraft|schematic|website|dashboard"),
    ("Preferences", r"prefer|bevorzug|wichtig|moechte|möchte|ich will|i want"),
)


def category(text: str) -> str:
    return next((name for name, pattern in CATEGORIES if re.search(pattern, text, re.I)), "Unsorted")


def _texts(payload: object) -> list[str]:
    if isinstance(payload, str):
        return [line.lstrip("-* ").strip() for line in payload.splitlines() if line.strip()]
    if isinstance(payload, dict):
        if "memories" in payload:
            return _texts(payload["memories"])
        if "mapping" in payload:
            result = []
            for node in payload["mapping"].values():
                message = (node or {}).get("message") or {}
                if message.get("author", {}).get("role") != "user":
                    continue
                parts = message.get("content", {}).get("parts", [])
                result.extend(part for part in parts if isinstance(part, str) and part.strip())
            return result
        text = payload.get("text") or payload.get("memory")
        if isinstance(text, str):
            return [text]
        raise ContractError("Expected memories, text, memory, or a conversation mapping")
    if isinstance(payload, list):
        result = []
        for item in payload:
            result.extend(_texts(item))
        return result
    raise ContractError("Unsupported import format")


def import_file(source: Path, *, stage: bool = False) -> dict:
    if source.stat().st_size > 50 * 1024 * 1024:
        raise ContractError("Split imports larger than 50 MiB before processing")
    raw = source.read_text(encoding="utf-8-sig")
    payload = json.loads(raw) if source.suffix.lower() == ".json" else raw
    texts = _texts(payload)
    if len(texts) > 5000:
        raise ContractError("Split imports exceeding 5000 records")
    # Stable across retries and dates; never claim that an import was re-verified today.
    observed = datetime.fromtimestamp(source.stat().st_mtime, timezone.utc).date().isoformat()
    sha = file_hash(source)
    existing = set()
    for directory in (paths.KNOWLEDGE_PENDING_DIR, paths.KNOWLEDGE_ACCEPTED_DIR, paths.KNOWLEDGE_REJECTED_DIR):
        if directory.is_dir():
            for path in directory.glob("*.json"):
                entry = json.loads(path.read_text(encoding="utf-8"))
                if entry.get("created_by") == "memory-import":
                    existing.add(entry.get("entity"))
    prepared = []
    duplicates = 0
    rejected = 0
    for text in texts:
        text = text.strip()
        if not text:
            continue
        entity = "import-" + content_hash(" ".join(text.casefold().split()))[:24]
        if entity in existing:
            duplicates += 1
            continue
        name = category(text)
        try:
            candidate = KnowledgeCandidate(
                entity=entity, fact_key="imported.statement",
                value={"text": text, "suggested_category": name, "requires_review": True},
                status="needs_review", confidence="low", source_type="agent_inference",
                source_ref=f"user-provided import sha256:{sha}; record:{entity}; not current-state verification",
                valid_from=observed, last_verified=observed,
                target_note=f"01 Inbox/Imported Memory/{name}/{entity}.md",
                created_by="memory-import",
            ).validate()
        except ContractError:
            rejected += 1  # Do not echo potentially secret content into logs/output.
            continue
        if stage:
            knowledge.submit(candidate)
        prepared.append({"candidate_id": candidate.candidate_id, "entity": entity,
                         "category": name, "target_note": candidate.target_note})
        existing.add(entity)
    return {"status": "PENDING" if stage else "PREVIEW", "records": prepared,
            "duplicates": duplicates, "rejected": rejected, "vault_writes": 0,
            "complete_chatgpt_memory_export": False}
