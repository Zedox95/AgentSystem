"""Smoke tests for the new agentctl operating paths."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="agentsys-cli-"))
VAULT = TMP / "vault"
VAULT.mkdir(parents=True)
note = VAULT / "router.md"
note.write_text(
    "---\ntype: system_entity\nentity: router-main\nstatus: current\n"
    "confidence: high\nsource_type: local_config\nvalid_from: 2026-08-23\n"
    "last_verified: 2026-08-23\n---\nRouter Endpoint\n\n"
    "<!-- agentsystem:facts:start -->\n```json\n"
    '{"schema_version": 1, "entity": "router-main", "facts": {}}'
    "\n```\n<!-- agentsystem:facts:end -->\n",
    encoding="utf-8",
)
ENV = dict(os.environ)
ENV["AGENTSYSTEM_ROOT"] = str(TMP / "system")
ENV["AGENTSYSTEM_VAULT"] = str(VAULT)
ENV["PYTHONIOENCODING"] = "utf-8"
FAILURES: list[str] = []


def run(*arguments: str) -> tuple[int, object]:
    completed = subprocess.run(
        [sys.executable, str(ROOT / "bin" / "agentctl.py"), *arguments],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=ENV, timeout=30,
    )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        payload = {"stdout": completed.stdout, "stderr": completed.stderr}
    return completed.returncode, payload


code, package = run("context", "build", "--vault", str(VAULT),
                    "--query", "Router", "--budget", "256")
if code or not str(package.get("package_id", "")).startswith("ctx-") \
        or len(package.get("items", [])) != 1:
    FAILURES.append(f"context build CLI fehlgeschlagen: {package}")
code, report = run("metrics", "report", "--events", str(TMP / "empty.jsonl"))
if code or report.get("overall", {}).get("tasks") != 0:
    FAILURES.append(f"metrics report CLI fehlgeschlagen: {report}")
code, candidates = run("skill-candidate", "list")
if code or candidates != []:
    FAILURES.append(f"skill-candidate list CLI fehlgeschlagen: {candidates}")
if (TMP / "system").exists():
    FAILURES.append("Read-only CLI-Berichte duerfen keinen frischen State-Root anlegen")

print(json.dumps({
    "status": "FAIL" if FAILURES else "PASS",
    "package_id": package.get("package_id") if isinstance(package, dict) else None,
    "failures": FAILURES,
    "temp_root": str(TMP),
}, ensure_ascii=False, indent=2))
sys.exit(1 if FAILURES else 0)
