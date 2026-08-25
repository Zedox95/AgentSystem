"""Gesamter Testlauf des Agentensystems.

Ein einziger Einstiegspunkt, damit Regressionsläufe nach jeder Änderung an
Skills, Agenten, Adaptern, Routing oder Hooks reproduzierbar sind
(AGENTS.md Abschnitt 21).

    python C:\\AgentSystem\\tests\\run-all.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent

# Reihenfolge ist bewusst: Bibliothek vor Hooks, Konfiguration vor Adaptern.
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
)


def _last_json_object(text: str) -> dict | None:
    """Findet das letzte mehrzeilige JSON-Objekt in einer Ausgabe.

    Die Suiten schreiben ihr Ergebnis als eingerücktes JSON; eine zeilenweise
    Auswertung würde nur die schließende Klammer sehen.
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
    results = []
    child_env = dict(os.environ)
    # Windows-Konsolen verwenden sonst abhängig vom Host cp1252. Alle
    # Tests und der JSON-Aggregator sprechen verbindlich UTF-8, damit auch
    # Handoff-Texte und deutsche Fehlermeldungen verlustfrei bleiben.
    child_env["PYTHONIOENCODING"] = "utf-8"
    child_env["PYTHONUTF8"] = "1"
    for suite in SUITES:
        path = TESTS_DIR / suite
        if not path.exists():
            results.append({"suite": suite, "status": "SKIPPED",
                            "reason": "noch nicht vorhanden"})
            continue
        started = time.monotonic()
        completed = subprocess.run(
            [sys.executable, str(path)], capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=900, env=child_env,
        )
        duration_ms = int((time.monotonic() - started) * 1000)
        payload = _last_json_object(completed.stdout)
        if payload is None:
            failures = [completed.stderr.strip()[-800:] or "keine auswertbare Ausgabe"]
        else:
            failures = payload.get("failures", [])
        results.append({
            "suite": suite,
            "status": "PASS" if completed.returncode == 0 else "FAIL",
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
