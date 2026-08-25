"""Export only AgentSystem-managed Obsidian facts for the cloud mirror."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(os.environ.get("AGENTSYSTEM_ROOT", r"C:\AgentSystem"))
sys.path.insert(0, str(ROOT / "bin"))

from agentsys import knowledge, ledger  # noqa: E402
from agentsys.contracts import file_hash  # noqa: E402

DEFAULT_OUTPUT = ROOT / "state" / "cloud-memory" / "snapshot.json"
SENSITIVE_MARKER = re.compile(
    r"(?i)(password|passwort|api[_ -]?key|access[_ -]?token|refresh[_ -]?token|private[_ -]?key|secret)"
)


def _scrub_sensitive(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _scrub_sensitive(item) for key, item in value.items()
                if not SENSITIVE_MARKER.search(str(key))}
    if isinstance(value, list):
        return [_scrub_sensitive(item) for item in value]
    if isinstance(value, str) and SENSITIVE_MARKER.search(value):
        return "[REDACTED]"
    return value


def build_snapshot(vault_root: Path = knowledge.DEFAULT_VAULT) -> dict[str, Any]:
    root = vault_root.resolve()
    notes: list[dict[str, Any]] = []
    for path, metadata, text in knowledge._managed_notes(root):
        relative = path.resolve().relative_to(root).as_posix()
        payload = {
            "source_path": relative,
            "source_sha256": file_hash(path),
            "metadata": metadata,
            "managed_facts": knowledge._managed_payload(text, metadata["entity"]).get("facts", {}),
        }
        redacted = ledger.redact(json.dumps(payload, ensure_ascii=False, default=str)) or "{}"
        notes.append(_scrub_sensitive(json.loads(redacted)))
    notes.sort(key=lambda item: (str(item["metadata"].get("entity", "")), item["source_path"]))
    return {
        "schema_version": 1,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "managed_frontmatter_and_facts_only",
        "note_count": len(notes),
        "notes": notes,
    }


def write_snapshot(output: Path, vault_root: Path = knowledge.DEFAULT_VAULT) -> dict[str, Any]:
    snapshot = build_snapshot(vault_root)
    output.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(prefix=output.name + ".", suffix=".tmp", dir=output.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(snapshot, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    return snapshot


def render_markdown(snapshot: dict[str, Any]) -> str:
    lines = ["# Verwaltete Shared Memory", "",
             f"Stand (UTC): {snapshot['generated_utc']}", "",
             "Enthalten sind ausschließlich verwaltete Metadaten und Fakten. Private freie Notiztexte sind ausgeschlossen.", ""]
    for note in snapshot["notes"]:
        metadata = note.get("metadata", {})
        lines.extend([
            f"## {metadata.get('entity', note['source_path'])}", "",
            f"- Quelle: `{note['source_path']}`",
            f"- Status: `{metadata.get('status', 'needs_review')}`",
            f"- Vertrauen: `{metadata.get('confidence', 'unknown')}`",
            f"- Zuletzt geprüft: `{metadata.get('last_verified', 'unknown')}`",
            "", "```json",
            json.dumps(note.get("managed_facts", {}), ensure_ascii=False, indent=2, default=str),
            "```", "",
        ])
    return "\n".join(lines)


def write_markdown(output: Path, snapshot: dict[str, Any]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(prefix=output.name + ".", suffix=".tmp", dir=output.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(render_markdown(snapshot))
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--markdown-output", type=Path,
                        default=DEFAULT_OUTPUT.with_name("managed-memory.md"))
    parser.add_argument("--vault", type=Path, default=knowledge.DEFAULT_VAULT)
    args = parser.parse_args()
    snapshot = write_snapshot(args.output, args.vault)
    write_markdown(args.markdown_output, snapshot)
    print(json.dumps({"status": "PASS", "output": str(args.output),
                      "markdown_output": str(args.markdown_output),
                      "note_count": snapshot["note_count"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
