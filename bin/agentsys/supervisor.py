"""Read-only health check of the AgentSystem control plane."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from . import evals, knowledge, locks, paths, skills_pipeline
from .contracts import ContractError, KnowledgeCandidate, file_hash

_TERMINAL = {"COMMITTED", "FAILED", "ROLLED_BACK"}
_MOJIBAKE = ("\ufffd", "Ã", "Â", "â€", "ðŸ")


def _result(name: str, status: str, evidence: Any) -> dict[str, Any]:
    return {"check": name, "status": status, "evidence": evidence}


def _ledger_health() -> tuple[dict[str, Any], dict[str, str]]:
    if not paths.LEDGER_DB.is_file():
        return _result("ledger", "FAIL", "ledger.sqlite fehlt"), {}
    try:
        uri = paths.LEDGER_DB.resolve().as_uri() + "?mode=ro"
        connection = sqlite3.connect(uri, uri=True, timeout=5)
        quick = connection.execute("PRAGMA quick_check").fetchone()[0]
        rows = connection.execute("SELECT task_id, state FROM tasks").fetchall()
        connection.close()
    except (sqlite3.Error, OSError) as error:
        return _result("ledger", "FAIL", str(error)), {}
    status = "PASS" if quick == "ok" else "FAIL"
    return _result("ledger", status, {"quick_check": quick, "tasks": len(rows)}), dict(rows)


def _checkpoint_health(tasks: dict[str, str]) -> dict[str, Any]:
    if not paths.CHECKPOINT_FILE.is_file():
        return _result("checkpoint", "PASS", "kein Checkpoint")
    try:
        raw = paths.CHECKPOINT_FILE.read_text(encoding="utf-8")
        payload = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        return _result("checkpoint", "FAIL", str(error))
    issues: list[str] = []
    task_id = payload.get("task_id")
    if task_id:
        actual = tasks.get(task_id)
        if actual is None:
            issues.append("Checkpoint verweist auf unbekannten Task")
        elif actual in _TERMINAL:
            issues.append(f"Checkpoint verweist auf terminalen Task ({actual})")
        elif payload.get("state") and payload.get("state") != actual:
            issues.append(f"Checkpoint-State {payload.get('state')} != Ledger-State {actual}")
    if any(marker in raw for marker in _MOJIBAKE):
        issues.append("Checkpoint enthaelt moegliche Zeichenkodierungsfehler")
    return _result("checkpoint", "WARN" if issues else "PASS", issues or "konsistent")


def _lock_health(tasks: dict[str, str]) -> dict[str, Any]:
    if not paths.LOCKS_DIR.is_dir():
        return _result("locks", "PASS", {"locks": 0, "stale": []})
    stale: list[str] = []
    corrupt: list[str] = []
    count = 0
    for source in sorted(paths.LOCKS_DIR.glob("*.lock")):
        count += 1
        try:
            payload = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            corrupt.append(source.name)
            continue
        if payload.get("owner") == "task" and tasks.get(payload.get("task_id")) in _TERMINAL:
            stale.append(payload.get("resource", source.stem))
        elif payload.get("owner") != "task" and locks.is_stale(payload):
            stale.append(payload.get("resource", source.stem))
    if corrupt:
        return _result("locks", "FAIL", {"locks": count, "corrupt": corrupt, "stale": stale})
    return _result("locks", "WARN" if stale else "PASS", {"locks": count, "stale": stale})


def _candidate_health() -> dict[str, Any]:
    invalid: list[str] = []
    total = 0
    buckets = (
        paths.KNOWLEDGE_PENDING_DIR,
        paths.KNOWLEDGE_ACCEPTED_DIR,
        paths.KNOWLEDGE_REJECTED_DIR,
    )
    for directory in buckets:
        if not directory.is_dir():
            continue
        for source in sorted(directory.glob("*.json")):
            total += 1
            try:
                payload = json.loads(source.read_text(encoding="utf-8"))
                known = {key: value for key, value in payload.items()
                         if key in KnowledgeCandidate.__dataclass_fields__}
                KnowledgeCandidate.from_dict(known)
            except (OSError, json.JSONDecodeError, TypeError, ContractError):
                invalid.append(str(source.relative_to(paths.ROOT)))
    for candidate in skills_pipeline.list_candidates() if paths.SKILL_CANDIDATES_DIR.is_dir() else []:
        total += 1
        if candidate.get("invalid") or not candidate.get("draft_exists"):
            invalid.append(str(candidate.get("path")))
    return _result("candidates", "FAIL" if invalid else "PASS",
                   {"total": total, "invalid": invalid})


def _metric_eval_health() -> list[dict[str, Any]]:
    try:
        metric_count = len(evals.load_metrics())
        metrics = _result("metrics", "PASS", {"events": metric_count})
    except ContractError as error:
        metrics = _result("metrics", "FAIL", str(error))
    try:
        cases = evals.load_cases()
        eval_check = _result("evals", "PASS" if cases else "WARN", {"cases": len(cases)})
    except (OSError, json.JSONDecodeError, TypeError, ContractError) as error:
        eval_check = _result("evals", "FAIL", str(error))
    return [metrics, eval_check]


def _vault_health(vault_root: Path) -> dict[str, Any]:
    if not vault_root.is_dir():
        return _result("vault", "WARN", f"Vault nicht erreichbar: {vault_root}")
    try:
        notes = knowledge._managed_notes(vault_root)
    except (OSError, FileNotFoundError) as error:
        return _result("vault", "WARN", str(error))
    return _result("vault", "PASS", {"managed_notes": len(notes)})


def _index_health(vault_root: Path) -> dict[str, Any]:
    manifest = paths.STATE_DIR / "knowledge-index.json"
    if not manifest.is_file():
        return _result("knowledge_index", "PASS", {
            "mode": "live-scan", "drift": False,
            "note": "Kein persistenter Index; Hashes werden live gelesen",
        })
    try:
        expected = json.loads(manifest.read_text(encoding="utf-8"))
        if not isinstance(expected, dict):
            raise ValueError("Indexmanifest muss ein Objekt sein")
        actual = {
            note.resolve().relative_to(vault_root.resolve()).as_posix(): file_hash(note)
            for note, _, _ in knowledge._managed_notes(vault_root)
        }
    except (OSError, json.JSONDecodeError, ValueError, FileNotFoundError) as error:
        return _result("knowledge_index", "FAIL", str(error))
    changed = sorted(path for path in set(expected) | set(actual)
                     if expected.get(path) != actual.get(path))
    return _result("knowledge_index", "WARN" if changed else "PASS",
                   {"mode": "manifest", "drift": bool(changed), "changed": changed})


def check(vault_root: str | Path = knowledge.DEFAULT_VAULT) -> dict[str, Any]:
    """Runs all checks without repair or state changes."""
    vault = Path(vault_root).resolve()
    ledger_check, tasks = _ledger_health()
    checks = [
        ledger_check,
        _checkpoint_health(tasks),
        _lock_health(tasks),
        _candidate_health(),
        *_metric_eval_health(),
        _vault_health(vault),
        _index_health(vault),
    ]
    status = "FAIL" if any(item["status"] == "FAIL" for item in checks) \
        else ("WARN" if any(item["status"] == "WARN" for item in checks) else "PASS")
    return {"status": status, "read_only": True, "checks": checks}
