"""Guarded local MCP access to AgentSystem-managed Obsidian memory."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Callable

ROOT = Path(os.environ.get("AGENTSYSTEM_ROOT", r"C:\AgentSystem"))
sys.path.insert(0, str(ROOT / "bin"))

from agentsys import knowledge, ledger  # noqa: E402
from agentsys.contracts import ContractError, KnowledgeCandidate, file_hash  # noqa: E402

SERVER_NAME = "agentsystem-shared-memory"
SERVER_VERSION = "1.0.0"
PROTOCOL_VERSION = "2025-06-18"
AUTO_SOURCE_TYPES = {"measurement", "user_confirmed", "local_config"}
AUTO_STATUSES = {"current", "planned", "tested", "historical", "superseded"}
NEW_NOTE_ROOTS = {"01 Inbox", "03 Bereiche", "04 Ressourcen"}


def _result(payload: Any) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False, indent=2, default=str)}],
        "structuredContent": payload, "isError": False,
    }


def _error(message: str) -> dict[str, Any]:
    safe = ledger.redact(str(message)) or "Unknown error"
    return {"content": [{"type": "text", "text": safe}], "isError": True}


def _require(arguments: dict[str, Any], *names: str) -> None:
    missing = [name for name in names if arguments.get(name) in (None, "")]
    if missing:
        raise ContractError("Required fields missing: " + ", ".join(missing))


def _candidate(arguments: dict[str, Any], *, created_by: str) -> KnowledgeCandidate:
    _require(arguments, "entity", "fact_key", "value", "status", "confidence",
             "source_type", "source_ref", "valid_from", "last_verified")
    return KnowledgeCandidate(
        entity=arguments["entity"], fact_key=arguments["fact_key"], value=arguments["value"],
        status=arguments["status"], confidence=arguments["confidence"],
        source_type=arguments["source_type"], source_ref=arguments["source_ref"],
        valid_from=arguments["valid_from"], last_verified=arguments["last_verified"],
        project=arguments.get("project"), target_note=arguments.get("target_note"),
        created_by=created_by,
    ).validate()


def memory_search(arguments: dict[str, Any]) -> dict[str, Any]:
    statuses = arguments.get("statuses")
    matches = knowledge.search(
        knowledge.DEFAULT_VAULT, str(arguments.get("query") or ""),
        entity=arguments.get("entity"), project=arguments.get("project"),
        statuses=set(statuses) if statuses is not None else None,
        limit=max(1, min(int(arguments.get("limit", 10)), 25)),
    )
    return _result({"matches": matches, "scope": "managed_notes_only"})


def memory_read_managed_note(arguments: dict[str, Any]) -> dict[str, Any]:
    _require(arguments, "source_path")
    requested = str(arguments["source_path"]).replace("\\", "/")
    root = knowledge.DEFAULT_VAULT.resolve()
    found = None
    for path, meta, text in knowledge._managed_notes(root):
        if path.resolve().relative_to(root).as_posix() == requested:
            found = (path, meta, text)
            break
    if found is None:
        raise ContractError("Note does not exist or is not AgentSystem-managed")
    path, meta, note_text = found
    payload = knowledge._managed_payload(note_text, meta["entity"])
    safe_payload = json.loads(ledger.redact(json.dumps(payload, ensure_ascii=False)) or "{}")
    return _result({
        "source_path": requested, "source_sha256": file_hash(path), "metadata": meta,
        "managed_facts": safe_payload.get("facts", {}),
        "scope": "frontmatter_and_managed_facts_only",
    })


def memory_submit_candidate(arguments: dict[str, Any]) -> dict[str, Any]:
    submitted = knowledge.submit(_candidate(arguments, created_by="shared-memory-mcp"))
    return _result({**submitted, "write_policy": "pending_only"})


def _existing_target(candidate: KnowledgeCandidate) -> tuple[Path, str]:
    root = knowledge.DEFAULT_VAULT.resolve()
    existing = knowledge._entity_notes(root, candidate.entity)
    if len(existing) > 1:
        raise ContractError("Multiple managed notes for this entity; manual review needed")
    if existing:
        return existing[0], file_hash(existing[0])
    if not candidate.target_note:
        raise ContractError("New facts need target_note in 01 Inbox, 03 Bereiche, or 04 Ressourcen")
    relative = Path(candidate.target_note)
    if not relative.parts or relative.parts[0] not in NEW_NOTE_ROOTS:
        raise ContractError("New notes are only allowed in 01 Inbox, 03 Bereiche, or 04 Ressourcen")
    target = (root / relative).resolve()
    target.relative_to(root)
    if target.suffix.lower() != ".md":
        raise ContractError("target_note must be a Markdown file")
    return target, "NEW"


def _start_capture_task(candidate: KnowledgeCandidate) -> tuple[str, str]:
    task_id = ledger.create_task(
        "Verified productive fact in shared Obsidian memory capture", "R1",
        target_resource=f"obsidian:entity:{candidate.entity}",
        desired_state=f"Managed fact {candidate.fact_key} is safely recorded for {candidate.entity}",
        planned_method="KnowledgeCandidate validation and Archivist atomic write",
        alternative_method="Leave candidate pending for manual review",
        acceptance_criteria="Managed-note readback, SHA256 and exact candidate presence pass",
        rollback_plan="Use Archivist baseline copy; never overwrite private note text",
    )
    ledger.set_state(task_id, "PLANNED", "Verified-fact capture plan")
    ledger.set_state(task_id, "PREFLIGHT", "Candidate contract and target scope validated")
    ledger.set_state(task_id, "LOCKED", f"Archivist owns obsidian:entity:{candidate.entity}")
    ledger.set_state(task_id, "BASELINED", "Existing managed entity note and SHA inspected")
    ledger.set_state(task_id, "BACKED_UP", "Archivist creates a hash-checked backup before replacement")
    ledger.set_state(task_id, "EXECUTING", "Candidate submitted to guarded Archivist path")
    run_id = ledger.start_run(task_id, "shared-memory-mcp", "memory_capture_verified",
                              "Validated candidate plus Archivist atomic write", "R1",
                              f"obsidian:entity:{candidate.entity}")
    return task_id, run_id


def memory_capture_verified(arguments: dict[str, Any]) -> dict[str, Any]:
    candidate = _candidate(arguments, created_by="shared-memory-mcp")
    if candidate.source_type not in AUTO_SOURCE_TYPES:
        raise ContractError("Auto-write allows only measurement, user_confirmed or local_config; submit other sources as candidates")
    if candidate.status not in AUTO_STATUSES or candidate.confidence != "high":
        raise ContractError("Auto-write requires confidence=high and a verified fact status")
    target, expected_sha256 = _existing_target(candidate)
    task_id, run_id = _start_capture_task(candidate)
    submitted = knowledge.submit(candidate)
    captured_ids: list[str] = []
    if submitted["status"] == "ACCEPTED":
        decision = {"status": "ALREADY_ACCEPTED",
                    "target_note": target.relative_to(knowledge.DEFAULT_VAULT.resolve()).as_posix(),
                    "target_sha256": file_hash(target)}
    else:
        decision = knowledge.approve(candidate.candidate_id, vault_root=knowledge.DEFAULT_VAULT,
                                     task_id=task_id, expected_sha256=expected_sha256)
        captured_ids.append(candidate.candidate_id)
    ledger.set_state(task_id, "OBJECTIVE_TEST", "Read back the managed note")
    final_target = knowledge.DEFAULT_VAULT / decision["target_note"]
    if not final_target.is_file() or file_hash(final_target) != decision["target_sha256"]:
        raise RuntimeError("Post-write SHA256 verification failed")
    managed = [(path, meta, text) for path, meta, text in knowledge._managed_notes(knowledge.DEFAULT_VAULT)
               if meta.get("entity") == candidate.entity]
    if len(managed) != 1:
        raise RuntimeError("Post-write entity uniqueness verification failed")
    facts = knowledge._managed_payload(managed[0][2], candidate.entity).get("facts", {})
    if not any(item.get("candidate_id") == candidate.candidate_id
               for item in facts.get(candidate.fact_key, [])):
        raise RuntimeError("Post-write exact candidate readback failed")
    ledger.set_state(task_id, "INDEPENDENT_VERIFY", "Deterministic fresh-file readback passed")
    ledger.finish_run(run_id, "PASS",
                      change_summary=("Managed Obsidian fact captured" if captured_ids else "No change; exact fact already present"),
                      objective_tests="Target exists; SHA256 matches; one managed entity note; exact candidate ID present",
                      verification="PASS: deterministic fresh-file readback of managed facts")
    if captured_ids:
        review = knowledge.review_task(task_id, decision="captured",
                                       reason="Verified productive fact accepted and read back.",
                                       candidate_ids=captured_ids)
    else:
        review = knowledge.review_task(task_id, decision="none",
                                       reason="Exact canonical fact was already accepted; no duplicate write needed.")
    readiness = ledger.completion_readiness(task_id)
    if not readiness["ready"]:
        raise RuntimeError("Completion gate blocked: " + "; ".join(readiness["reasons"]))
    ledger.set_state(task_id, "COMMITTED", "Verified fact capture complete")
    return _result({"task_id": task_id, "candidate_id": candidate.candidate_id,
                    "decision": decision, "knowledge_review": review, "completion": "COMMITTED"})


def memory_task_review_status(arguments: dict[str, Any]) -> dict[str, Any]:
    _require(arguments, "task_id")
    task_id = str(arguments["task_id"])
    return _result({"task": ledger.get_task(task_id),
                    "completion_readiness": ledger.completion_readiness(task_id),
                    "latest_knowledge_review": ledger.latest_knowledge_review(task_id)})


_CANDIDATE_SCHEMA = {"type": "object", "properties": {
    "entity": {"type": "string", "pattern": "^[a-z0-9][a-z0-9._:-]{1,127}$"},
    "fact_key": {"type": "string", "pattern": "^[a-z0-9][a-z0-9._:-]{1,127}$"},
    "value": {}, "status": {"type": "string"}, "confidence": {"type": "string"},
    "source_type": {"type": "string"}, "source_ref": {"type": "string"},
    "valid_from": {"type": "string", "format": "date"},
    "last_verified": {"type": "string", "format": "date"},
    "project": {"type": "string"}, "target_note": {"type": "string"},
}, "required": ["entity", "fact_key", "value", "status", "confidence", "source_type",
                  "source_ref", "valid_from", "last_verified"], "additionalProperties": False}

TOOLS: dict[str, tuple[Callable[[dict[str, Any]], dict[str, Any]], dict[str, Any]]] = {
    "memory_search": (memory_search, {"description": "Search only AgentSystem-managed Obsidian notes; no private or Daily Notes access.",
        "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}, "entity": {"type": "string"}, "project": {"type": "string"}, "statuses": {"type": "array", "items": {"type": "string"}}, "limit": {"type": "integer", "minimum": 1, "maximum": 25}}},
        "annotations": {"readOnlyHint": True, "destructiveHint": False}}),
    "memory_read_managed_note": (memory_read_managed_note, {"description": "Read frontmatter and managed facts from one search result, never free-form private text.",
        "inputSchema": {"type": "object", "properties": {"source_path": {"type": "string"}}, "required": ["source_path"], "additionalProperties": False},
        "annotations": {"readOnlyHint": True, "destructiveHint": False}}),
    "memory_submit_candidate": (memory_submit_candidate, {"description": "Submit uncertain information as pending; does not write an Obsidian note.", "inputSchema": _CANDIDATE_SCHEMA,
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True}}),
    "memory_capture_verified": (memory_capture_verified, {"description": "Write one high-confidence measured, user-confirmed or local-config fact via Archivist.", "inputSchema": _CANDIDATE_SCHEMA,
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True}}),
    "memory_task_review_status": (memory_task_review_status, {"description": "Inspect a formal AgentSystem task's hard completion gate and Knowledge Review.",
        "inputSchema": {"type": "object", "properties": {"task_id": {"type": "string"}}, "required": ["task_id"], "additionalProperties": False},
        "annotations": {"readOnlyHint": True, "destructiveHint": False}}),
}


def handle(message: dict[str, Any]) -> dict[str, Any] | None:
    method, request_id = message.get("method"), message.get("id")
    if method == "notifications/initialized":
        return None
    if method == "initialize":
        result = {"protocolVersion": PROTOCOL_VERSION, "capabilities": {"tools": {"listChanged": False}},
                  "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION}}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": [{"name": name, **spec} for name, (_, spec) in TOOLS.items()]}
    elif method == "tools/call":
        params, name = message.get("params") or {}, (message.get("params") or {}).get("name")
        if name not in TOOLS:
            result = _error(f"Unknown tool: {name}")
        else:
            try:
                result = TOOLS[name][0](params.get("arguments") or {})
            except Exception as error:  # noqa: BLE001
                result = _error(str(error))
    else:
        return {"jsonrpc": "2.0", "id": request_id,
                "error": {"code": -32601, "message": "Method not found"}}
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def main() -> int:
    for raw in sys.stdin.buffer:
        try:
            message = json.loads(raw.decode("utf-8"))
            response = handle(message)
            if response is not None and message.get("id") is not None:
                sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
                sys.stdout.flush()
        except Exception as error:  # noqa: BLE001
            sys.stderr.write((ledger.redact(str(error)) or "MCP error") + "\n")
            sys.stderr.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
