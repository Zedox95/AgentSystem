"""Isolated tests for reproducible, budgeted context packages."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="agentsys-context-"))
VAULT = TMP / "vault"
VAULT.mkdir(parents=True)
os.environ["AGENTSYSTEM_ROOT"] = str(TMP / "system")
sys.path.insert(0, str(ROOT / "bin"))

from agentsys import context  # noqa: E402

FAILURES: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        FAILURES.append(message)


def write_note(name: str, entity: str, body: str, *, status: str = "current") -> None:
    (VAULT / name).write_text(
        "---\n"
        f"type: system_entity\nentity: {entity}\nstatus: {status}\n"
        "confidence: high\nsource_type: local_config\n"
        "valid_from: 2026-08-23\nlast_verified: 2026-08-23\n"
        "---\n\n"
        f"# {entity}\n\n{body}\n\n"
        "<!-- agentsystem:facts:start -->\n```json\n"
        + json.dumps({
            "schema_version": 1,
            "entity": entity,
            "facts": {
                "endpoint": [{
                    "value": body,
                    "status": "current",
                    "source_type": "local_config",
                }]
            },
        }, ensure_ascii=False, indent=2)
        + "\n```\n<!-- agentsystem:facts:end -->\n",
        encoding="utf-8",
    )


write_note("router.md", "router-main", "Router Endpoint 192.0.2.1 " + "stabil " * 120)
write_note("server.md", "server-main", "Server Endpoint 192.0.2.2", status="needs_review")
(VAULT / "private.md").write_text("Router Endpoint privates Passwort", encoding="utf-8")

first = context.build(VAULT, "Endpoint", entity="router-main", token_budget=256)
second = context.build(VAULT, "Endpoint", entity="router-main", token_budget=256)
check(first.package_id == second.package_id,
      "Same vault and query must yield the same package_id")
check(first.estimated_tokens <= first.token_budget,
      "Context builder must respect the token budget")
check(first.truncated, "Long content must be marked as truncated")
check(len(first.items) == 1 and first.items[0].source_path == "router.md",
      f"Entity filter or ranking wrong: {[i.source_path for i in first.items]}")
check(len(first.items[0].source_sha256) == 64,
      "Source manifest needs a SHA-256")
check("private.md" not in {item.source_path for item in first.items},
      "Unmanaged private note must not enter the context")

review = context.build(VAULT, "Server", token_budget=1000)
check(review.conflicts == ["server-main: Notizstatus needs_review"],
      f"needs_review conflict missing: {review.conflicts}")

print(json.dumps({
    "status": "FAIL" if FAILURES else "PASS",
    "package_id": first.package_id,
    "estimated_tokens": first.estimated_tokens,
    "truncated": first.truncated,
    "conflicts": review.conflicts,
    "failures": FAILURES,
    "temp_root": str(TMP),
}, ensure_ascii=False, indent=2))
sys.exit(1 if FAILURES else 0)
