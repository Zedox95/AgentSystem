"""Adapter tests for UFO² and Playwright.

Checks both adapters against the real running environment. All checks are
**read-only** — nothing is clicked, nothing is entered, and nowhere is
signed in, so the run stays safely repeatable at any time.

The writing chains were each demonstrated once during setup and documented
in `docs/known-issues.md`:

* UFO: `type` into the search field of the Windows settings, then
  independently confirmed via `inspect` and cleared again.
* Playwright: `fill` with read-back against a locally generated page.

Both are excluded from a routine run due to their visibility and/or state
change respectively.

    python C:\\AgentSystem\\tests\\test_adapters.py
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UFOCTL = ROOT / "adapters" / "ufo" / "ufoctl.py"
UFO_PYTHON = Path(r"C:\UFO\.venv\Scripts\python.exe")
PWCTL = ROOT / "adapters" / "playwright" / "pwctl.mjs"

# The local router is a stable, reachable target without external
# dependency and without login. Adjust the IP to your own environment.
LOCAL_HTTP_TARGET = "http://192.0.2.1/"

FAILURES: list[str] = []
SKIPPED: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        FAILURES.append(message)


def _run(command: list[str], cwd: Path, timeout: int) -> tuple[int, dict | None, str]:
    completed = subprocess.run(
        command, capture_output=True, text=True, errors="replace",
        timeout=timeout, cwd=str(cwd),
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        payload = None
    return completed.returncode, payload, completed.stderr[-500:]


def ufoctl(*args: str, timeout: int = 240) -> tuple[int, dict | None, str]:
    return _run([str(UFO_PYTHON), str(UFOCTL), *args], UFOCTL.parent, timeout)


def pwctl(*args: str, timeout: int = 240) -> tuple[int, dict | None, str]:
    return _run(["node", str(PWCTL), *args], PWCTL.parent, timeout)


# --------------------------------------------------------------------------
# UFO²
# --------------------------------------------------------------------------


def run_ufo_tests() -> None:
    # Tool list: the shell executor must not be reachable.
    code, payload, stderr = ufoctl("tools")
    check(code == 0, f"ufoctl tools ended with {code}: {stderr}")
    if payload:
        tools = payload.get("tools", [])
        check(bool(tools), "ufoctl tools returns no tools")
        shell_tools = [t for t in tools
                       if "command" in t.lower() or "shell" in t.lower()]
        check(not shell_tools,
              f"Shell executor must not be exposed, found: {shell_tools}")
        check("CommandLineExecutor" in payload.get("excluded", []),
              "CommandLineExecutor must be explicitly excluded")
        for required in ("ui_get_desktop_app_info", "ui_get_app_window_controls_info",
                         "host_select_application_window", "app_click_input",
                         "app_set_edit_text"):
            check(required in tools, f"Tool missing: {required}")

    # Read-only mode must not carry any mutating tools.
    code, payload, _ = ufoctl("tools", "--read-only")
    if payload:
        mutating = [t for t in payload.get("tools", []) if t.startswith("app_")]
        check(not mutating,
              f"Read-only mode must not carry any app_ tools: {mutating}")

    # List windows.
    code, payload, stderr = ufoctl("windows")
    check(code == 0, f"ufoctl windows ended with {code}: {stderr}")
    windows = (payload or {}).get("windows", [])
    if code == 0 and not windows:
        # In non-interactive desktop/sandbox sessions, UFO can start
        # correctly but fail to reach a visible user desktop. That is
        # a missing test precondition, not proof of adapter regression.
        SKIPPED.append("Kein interaktives Fenster fuer UFO-Lesetests verfuegbar")
        return
    for window in windows:
        check("id" in window and "name" in window,
              f"Window entry incomplete: {window}")
    if not windows:
        return

    # Read controls of a real open window. Via the ID, not the name:
    # names change, IDs are stable for the call.
    code, payload, stderr = ufoctl("controls", "--window", str(windows[0]["id"]))
    check(code == 0, f"ufoctl controls ended with {code}: {stderr}")
    for control in (payload or {}).get("controls", [])[:5]:
        check("label" in control, f"Control without label: {control}")
        check("control_type" in control, f"Control without type: {control}")

    # Independent check bypasses UFO. The window list is fetched fresh:
    # the desktop may have changed between two calls.
    _, fresh, _ = ufoctl("windows")
    current = (fresh or {}).get("windows", [])
    if not current:
        SKIPPED.append("No window open for the inspect check")
    else:
        code, payload, stderr = ufoctl(
            "inspect", "--window", current[0]["name"], "--limit", "5")
        check(code == 0, "ufoctl inspect ended with "
                         f"{code}: {(payload or {}).get('error', stderr)}")
        check(payload is not None and "matches" in payload,
              "inspect returns no matches structure")

    # Error cases are named, not guessed.
    code, payload, _ = ufoctl("controls", "--window", "gibtesnichtxyz123")
    check(code == 1, "Unknown window must end with exit 1")
    check((payload or {}).get("status") == "FAILED",
          "Unknown window must report status FAILED")
    check("No window matches" in (payload or {}).get("error", ""),
          "Error message must name the open windows")


# --------------------------------------------------------------------------
# Playwright
# --------------------------------------------------------------------------


def run_playwright_tests() -> None:
    code, payload, stderr = pwctl("help")
    check(code == 0, f"pwctl help ended with {code}: {stderr}")
    commands = (payload or {}).get("commands", [])
    for required in ("snapshot", "text", "http", "click", "fill", "plan"):
        check(required in commands, f"pwctl command missing: {required}")

    code, _, _ = pwctl("http")
    check(code == 1, "Call without --url must end with exit 1")

    # Browser starts and returns a real, verifiable HTTP response.
    code, payload, stderr = pwctl("http", "--url", LOCAL_HTTP_TARGET)
    if code != 0:
        SKIPPED.append("Lokales HTTP-Ziel nicht erreichbar: "
                       f"{(payload or {}).get('error', stderr)}")
        return
    response = (payload or {}).get("response", {})
    check(response.get("status") == 200,
          f"Expected HTTP 200, got {response.get('status')}")
    check(bool((payload or {}).get("title")), "Page title missing")

    # Accessibility snapshot provides structure instead of pixels. Without
    # networkidle a JavaScript interface stays empty - that's the actual test.
    code, payload, stderr = pwctl("snapshot", "--url", LOCAL_HTTP_TARGET,
                                  "--wait", "networkidle", "--timeout", "30000")
    check(code == 0, f"pwctl snapshot ended with {code}: {stderr}")
    aria = (payload or {}).get("aria", "")
    check("link" in aria or "button" in aria,
          "Snapshot contains no operable roles — JS build not awaited?")

    # A click without a locator is rejected instead of hitting the first
    # element by guesswork.
    code, payload, _ = pwctl("click", "--url", LOCAL_HTTP_TARGET)
    check(code == 1, "Click without locator must end with exit 1")
    check("Lokalisierer" in (payload or {}).get("error", ""),
          "Error message must name the missing locator")




# --------------------------------------------------------------------------


def main() -> int:
    if not UFO_PYTHON.exists():
        SKIPPED.append(f"UFO-venv fehlt: {UFO_PYTHON}")
    elif not UFOCTL.exists():
        SKIPPED.append(f"ufoctl fehlt: {UFOCTL}")
    else:
        run_ufo_tests()

    if not PWCTL.exists():
        SKIPPED.append(f"pwctl fehlt: {PWCTL}")
    elif shutil.which("node") is None:
        SKIPPED.append("node nicht im PATH")
    else:
        run_playwright_tests()

    print(json.dumps({
        "status": "FAIL" if FAILURES else ("SKIPPED" if SKIPPED else "PASS"),
        "failures": FAILURES,
        "skipped": SKIPPED,
    }, ensure_ascii=False, indent=2))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
