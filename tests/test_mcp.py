"""MCP server tests.

Starts every server declared in `.mcp.json` as a real stdio process and
performs a full MCP handshake: `initialize`, `notifications/initialized`,
`tools/list`. This checks what actually happens at runtime — not just
whether the file exists.

**No** tools are invoked: no window is touched, no browser navigates
anywhere.

    python C:\\AgentSystem\\tests\\test_mcp.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MCP_CONFIG = ROOT / ".mcp.json"

PROTOCOL_VERSION = "2025-06-18"

FAILURES: list[str] = []
SKIPPED: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        FAILURES.append(message)


def _frame(payload: dict) -> bytes:
    return (json.dumps(payload) + "\n").encode("utf-8")


def handshake(name: str, spec: dict, timeout: float = 120.0) -> dict:
    """Performs an MCP handshake over stdio and returns the tool list."""
    environment = {**os.environ, **(spec.get("env") or {})}
    process = subprocess.Popen(
        [spec["command"], *spec.get("args", [])],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env=environment, cwd=str(ROOT),
    )

    try:
        process.stdin.write(_frame({
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "agentsystem-test", "version": "1.0"},
            },
        }))
        process.stdin.flush()

        initialize = _read_response(process, expect_id=1, timeout=timeout)
        if initialize is None:
            return {"error": "keine Antwort auf initialize",
                    "stderr": _drain_stderr(process)}

        process.stdin.write(_frame({
            "jsonrpc": "2.0", "method": "notifications/initialized"}))
        process.stdin.write(_frame({
            "jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}))
        process.stdin.flush()

        listing = _read_response(process, expect_id=2, timeout=timeout)
        if listing is None:
            return {"error": "keine Antwort auf tools/list",
                    "stderr": _drain_stderr(process)}

        return {
            "server_info": initialize.get("result", {}).get("serverInfo", {}),
            "tools": [t["name"] for t in listing.get("result", {}).get("tools", [])],
        }
    finally:
        try:
            process.stdin.close()
        except OSError:
            pass
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()


def _read_response(process: subprocess.Popen, *, expect_id: int,
                   timeout: float) -> dict | None:
    """Reads lines until the response with the expected id arrives.

    Servers occasionally send notifications without an id in between;
    those are skipped.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        line = process.stdout.readline()
        if not line:
            return None
        try:
            message = json.loads(line.decode("utf-8", "replace"))
        except json.JSONDecodeError:
            continue  # Foreign output on stdout: ignore, but don't abort.
        if message.get("id") == expect_id:
            return message
    return None


def _drain_stderr(process: subprocess.Popen) -> str:
    try:
        process.kill()
        return (process.stderr.read() or b"").decode("utf-8", "replace")[-600:]
    except Exception:  # noqa: BLE001
        return ""


def main() -> int:
    if not MCP_CONFIG.is_file():
        SKIPPED.append(f".mcp.json fehlt: {MCP_CONFIG}")
        return _report()

    config = json.loads(MCP_CONFIG.read_text(encoding="utf-8"))
    servers = config.get("mcpServers", {})
    check(set(servers) >= {"ufo", "playwright", "shared-memory"},
          f"Expected ufo, playwright, and shared-memory, found: {sorted(servers)}")

    results = {}
    for name, spec in servers.items():
        result = handshake(name, spec)
        results[name] = result
        if "error" in result:
            FAILURES.append(f"{name}: {result['error']} — {result.get('stderr', '')}")
            continue
        check(bool(result["tools"]), f"{name} reports no tools")

    # UFO: the shell executor must not be reachable via MCP either.
    ufo_tools = results.get("ufo", {}).get("tools", [])
    if ufo_tools:
        shell = [t for t in ufo_tools if "command" in t.lower() or "shell" in t.lower()]
        check(not shell, f"UFO MCP must not carry a shell executor: {shell}")
        for required in ("ui_get_desktop_app_info", "host_select_application_window",
                         "ui_get_app_window_controls_info", "app_click_input"):
            check(required in ufo_tools, f"UFO MCP: tool missing: {required}")

    # Playwright: the expected core tools are there.
    pw_tools = results.get("playwright", {}).get("tools", [])
    if pw_tools:
        expected = [t for t in pw_tools if "navigate" in t or "snapshot" in t]
        check(bool(expected),
              f"Playwright MCP: neither navigate nor snapshot found: {pw_tools[:10]}")

    memory_tools = results.get("shared-memory", {}).get("tools", [])
    if memory_tools:
        for required in (
            "memory_search", "memory_read_managed_note", "memory_submit_candidate",
            "memory_capture_verified", "memory_task_review_status",
        ):
            check(required in memory_tools, f"Shared-memory MCP: tool missing: {required}")
        forbidden = [name for name in memory_tools if "file" in name or "shell" in name]
        check(not forbidden, f"Shared-memory MCP must not offer generic file/shell access: {forbidden}")

    # The browser profile must not end up in version control. A blanket
    # "state/" ignore rule covers it too, not just the literal subpath.
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    gitignore_lines = [line.strip() for line in gitignore.splitlines()]
    check("state/browser-profiles/" in gitignore_lines or "state/" in gitignore_lines,
          "state/browser-profiles/ must be covered by .gitignore — it contains cookies")

    return _report(results)


def _report(results: dict | None = None) -> int:
    print(json.dumps({
        "status": "FAIL" if FAILURES else ("SKIPPED" if SKIPPED else "PASS"),
        "servers": {
            name: {"tools": len(data.get("tools", [])),
                   "server_info": data.get("server_info", {})}
            for name, data in (results or {}).items()
        },
        "failures": FAILURES,
        "skipped": SKIPPED,
    }, ensure_ascii=False, indent=2))
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
