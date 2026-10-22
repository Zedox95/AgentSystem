"""Full test run of the agent system.

A single entry point so regression runs after any change to skills, agents,
adapters, routing, or hooks are reproducible (AGENTS.md section 21).

    python C:\\AgentSystem\\tests\\run-all.py
"""

from __future__ import annotations

import json
import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent

# Order is deliberate: library before hooks, config before adapters.
SUITES = (
    "test_core.py",
    "test_completion_gate.py",
    "test_contracts.py",
    "test_second_brain.py",
    "test_context.py",
    "test_evals.py",
    "test_skills_pipeline.py",
    "test_supervisor.py",
    "test_second_brain_cli.py",
    "test_hooks.py",
    "test_config.py",
    "test_routing.py",
    "test_adapters.py",
    "test_mcp.py",
    "test_memory_mcp.py",
    "test_cloud_memory.py",
    "test_codex_plugin.py",
    "test_codex_global_hooks.py",
    "test_global_provider_integration.py",
    "test_portable.py",
)


def _last_json_object(text: str) -> dict | None:
    """Finds the last multi-line JSON object in an output.

    The suites write their result as indented JSON; a line-by-line
    evaluation would only see the closing brace.
    """
    starts = [i for i, line in enumerate(text.splitlines()) if line.startswith("{")]
    lines = text.splitlines()
    for start in reversed(starts):
        try:
            return json.loads("\n".join(lines[start:]))
        except json.JSONDecodeError:
            continue
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--integration", action="store_true", help="Exercise optional installed desktop/browser adapters")
    args = parser.parse_args()
    results = []
    child_env = dict(os.environ)
    # Windows consoles otherwise use cp1252 depending on the host. All
    # tests and the JSON aggregator use UTF-8 as a firm rule, so that
    # handoff texts and German error messages remain lossless.
    child_env["PYTHONIOENCODING"] = "utf-8"
    child_env["PYTHONUTF8"] = "1"
    temporary_root = TESTS_DIR.parent / "state" / "test-tmp"
    temporary_root.mkdir(parents=True, exist_ok=True)
    child_env["TMP"] = str(temporary_root)
    child_env["TEMP"] = str(temporary_root)
    for suite in SUITES:
        if suite in ("test_adapters.py", "test_mcp.py") and not args.integration:
            results.append({"suite": suite, "status": "SKIPPED",
                            "reason": "optional live adapter test; use --integration; core memory MCP covered by test_portable.py"})
            continue
        path = TESTS_DIR / suite
        if not path.exists():
            results.append({"suite": suite, "status": "SKIPPED",
                            "reason": "not present yet"})
            continue
        started = time.monotonic()
        try:
            completed = subprocess.run(
                [sys.executable, str(path)], capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=180, env=child_env,
            )
        except subprocess.TimeoutExpired:
            results.append({"suite": suite, "status": "FAIL", "failures": ["suite timed out after 180 seconds"]})
            continue
        duration_ms = int((time.monotonic() - started) * 1000)
        payload = _last_json_object(completed.stdout)
        if payload is None:
            failures = [completed.stderr.strip()[-800:] or "keine auswertbare Ausgabe"]
        else:
            failures = payload.get("failures", [])
        results.append({
            "suite": suite,
            "status": "PASS" if completed.returncode == 0 and payload and payload.get("status") == "PASS" and not failures else (
                "SKIPPED" if completed.returncode == 0 and payload and payload.get("status") == "SKIPPED" else "FAIL"),
            "duration_ms": duration_ms,
            "failures": failures,
        })

    failed = [r for r in results if r["status"] == "FAIL"]
    print(json.dumps({
        "status": "FAIL" if failed else "PASS",
        "suites": results,
    }, ensure_ascii=False, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
