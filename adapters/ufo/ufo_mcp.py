"""UFO² MCP server for exploratory work.

**A complement to `ufoctl.py`, not a replacement.** Both paths exist side by
side because they solve different tasks:

* `ufoctl.py` — for known, repeatable workflows. Every call is self-contained,
  deterministically scriptable, with small context output and no running
  process. The default case.
* This MCP server — for exploratory work in an unfamiliar interface. Window
  state persists across many steps instead of being rebuilt on every call.
  That saves time when you first have to feel your way through an
  application.

The UFO core stays unchanged. This file lives outside `C:\\UFO` and only uses
its registered MCP servers.

## Deliberately not wired in: CommandLineExecutor

UFO also registers a shell executor. That one stays out. Claude already has
shell access via Bash and PowerShell, which runs through the policy guard. A
second shell path via MCP would bypass that security boundary.

## Verification

Even in MCP mode: an action is **never** verified with UFO's own control list
— that reports the accessible name instead of the live value. `ufoctl.py
inspect` exists for that, measuring past UFO via pywinauto. See
`docs/known-issues.md`.

## Invocation

    C:\\UFO\\.venv\\Scripts\\python.exe ufo_mcp.py [--read-only] [--list]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

UFO_ROOT = Path(os.environ.get("UFO_ROOT", r"C:\UFO"))

# UICollector reads, HostUIExecutor selects a window (only activates it).
READ_SERVERS = ("UICollector", "HostUIExecutor")
# Only here do real mutations happen.
ACTION_SERVERS = ("AppUIExecutor",)
EXCLUDED = ("CommandLineExecutor",)

PREFIX = {"UICollector": "ui", "HostUIExecutor": "host", "AppUIExecutor": "app"}

INSTRUCTIONS = """\
Windows UI automation via UFO². For exploratory work in an unfamiliar
interface; window state persists across calls.

Workflow:
1. ui_get_desktop_app_info -> open windows with id and name
2. host_select_application_window -> activate a window
3. ui_get_app_window_controls_info -> controls with label, control_text,
   control_type. This step is mandatory before every action; without it UFO
   does not know the elements.
4. app_click_input / app_set_edit_text / app_keyboard_input -> act via the
   label, not via coordinates.

Coordinate-based actions are not reproducible and break with every layout
change - only use them when no named control exists.

Important for verification: for input fields, the control list reports the
accessible name, not the entered content, and can be stale. An executed
action is therefore not confirmed with this list, but with 'ufoctl.py
inspect', which measures directly via pywinauto.

For known, repeatable workflows, ufoctl.py is the better path: smaller
output, deterministically scriptable, individually verifiable.
"""


def _prepare() -> None:
    if not UFO_ROOT.is_dir():
        sys.exit(f"UFO was not found: {UFO_ROOT}")
    if str(UFO_ROOT) not in sys.path:
        sys.path.insert(0, str(UFO_ROOT))
    # UFO's config loader looks for `config/ufo/` relative to the working directory.
    os.chdir(UFO_ROOT)
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    # stdout belongs to the MCP protocol. UFO logs very verbosely and would
    # destroy the transport.
    logging.disable(logging.CRITICAL)


def build_server(read_only: bool):
    _prepare()
    from fastmcp import FastMCP
    import ufo.client.mcp.local_servers.ui_mcp_server  # noqa: F401
    from ufo.client.mcp.mcp_registry import MCPRegistry

    server = FastMCP(name="ufo-windows", instructions=INSTRUCTIONS)
    mounted = []
    for name in (READ_SERVERS if read_only else READ_SERVERS + ACTION_SERVERS):
        if name in EXCLUDED:
            continue
        server.mount(MCPRegistry.get(name), prefix=PREFIX[name])
        mounted.append(name)
    return server, mounted


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--read-only", action="store_true",
                        help="Only mount read-only tools, no GUI actions")
    parser.add_argument("--list", action="store_true",
                        help="List tools and exit (for tests)")
    args = parser.parse_args()

    server, mounted = build_server(args.read_only)

    if args.list:
        tools = asyncio.run(server.get_tools())
        print(json.dumps({
            "mounted_servers": mounted,
            "excluded": list(EXCLUDED),
            "read_only": args.read_only,
            "tools": sorted(tools),
        }, ensure_ascii=False, indent=2))
        return 0

    # show_banner=False: stdout must contain nothing but the MCP protocol.
    server.run(transport="stdio", show_banner=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
