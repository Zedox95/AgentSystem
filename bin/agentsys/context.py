"""Reproduzierbare Kontextpakete aus dem verwalteten Second Brain.

Der Builder schreibt nichts in den Vault. Er verwendet ausschliesslich die
verwaltete Nur-Lese-Suche, bindet jede Aussage an Pfad und Datei-Hash und
schneidet Auszuege deterministisch auf das vorgegebene Budget zu.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from . import knowledge
from .contracts import ContextItem, ContextPackage, ContractError, canonical_json


def estimate_tokens(value: Any) -> int:
    """Konservative, modellunabhaengige Schaetzung: vier UTF-8-Zeichen/Token."""
    return max(1, math.ceil(len(canonical_json(value)) / 4))


def _conflicts(vault_root: Path, selected_paths: set[str]) -> list[str]:
    findings: set[str] = set()
    for note, meta, text in knowledge._managed_notes(vault_root):
        relative = note.resolve().relative_to(vault_root.resolve()).as_posix()
        if relative not in selected_paths:
            continue
        entity = meta.get("entity", relative)
        if meta.get("status") == "needs_review":
            findings.add(f"{entity}: Notizstatus needs_review")
        try:
            payload = knowledge._managed_payload(text, entity)
        except knowledge.KnowledgeConflict as error:
            findings.add(f"{entity}: {error}")
            continue
        for fact_key, history in sorted(payload.get("facts", {}).items()):
            if not isinstance(history, list):
                findings.add(f"{entity}.{fact_key}: ungueltige Faktenhistorie")
                continue
            active_values = {
                canonical_json(record.get("value"))
                for record in history
                if isinstance(record, dict)
                and record.get("status") in ("current", "planned", "tested")
            }
            if len(active_values) > 1:
                findings.add(f"{entity}.{fact_key}: widerspruechliche aktive Werte")
    return sorted(findings)


def _fit_item(match: dict[str, Any], remaining: int) -> tuple[ContextItem | None, bool]:
    excerpt = match["excerpt"].strip()
    base = {
        "source_path": match["source_path"],
        "source_sha256": match["source_sha256"],
        "score": match["score"],
        "entity": match.get("entity"),
        "status": match.get("status"),
        "last_verified": match.get("last_verified"),
        "excerpt": "",
    }
    fixed = estimate_tokens(base)
    if remaining <= fixed + 1:
        return None, True
    max_chars = min(len(excerpt), max(1, (remaining - fixed) * 4))
    fitted = excerpt[:max_chars].rstrip()
    truncated = max_chars < len(excerpt)
    item = ContextItem(
        source_path=match["source_path"],
        source_sha256=match["source_sha256"],
        excerpt=fitted,
        score=match["score"],
        entity=match.get("entity"),
        status=match.get("status"),
        last_verified=match.get("last_verified"),
    ).validate()
    while estimate_tokens(item.__dict__) > remaining and item.excerpt:
        item.excerpt = item.excerpt[:-4].rstrip()
        truncated = True
    if not item.excerpt:
        return None, True
    return item, truncated


def build(vault_root: str | Path, query: str, *, entity: str | None = None,
          project: str | None = None, statuses: set[str] | None = None,
          token_budget: int = 2_000, limit: int = 20) -> ContextPackage:
    """Baut ein stabiles, quellenbelegtes Kontextpaket ohne Seiteneffekte."""
    if not 128 <= token_budget <= 100_000:
        raise ContractError("token_budget ausserhalb 128..100000")
    root = Path(vault_root).resolve()
    matches = knowledge.search(
        root, query, entity=entity, project=project, statuses=statuses, limit=limit,
    )
    selected_paths = {match["source_path"] for match in matches}
    conflicts = _conflicts(root, selected_paths)
    overhead = estimate_tokens({
        "query": query,
        "entity": entity,
        "project": project,
        "statuses": sorted(statuses or []),
        "conflicts": conflicts,
    })
    if overhead >= token_budget:
        raise ContractError("Query und Konfliktmanifest ueberschreiten das Kontextbudget")

    items: list[ContextItem] = []
    used = overhead
    truncated = False
    for match in matches:
        item, was_truncated = _fit_item(match, token_budget - used)
        if item is None:
            truncated = True
            break
        item_tokens = estimate_tokens(item.__dict__)
        items.append(item)
        used += item_tokens
        truncated = truncated or was_truncated
        if was_truncated:
            break
    if len(items) < len(matches):
        truncated = True

    return ContextPackage(
        query=query,
        token_budget=token_budget,
        items=items,
        estimated_tokens=used,
        conflicts=conflicts,
        truncated=truncated,
    ).validate()
