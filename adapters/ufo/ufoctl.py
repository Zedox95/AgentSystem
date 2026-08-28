"""ufoctl — UFO² as a Windows action layer via the command line.

Claude Code remains the brain. UFO² only provides UI Automation: reading the
control tree and executing limited GUI actions. UFO's own HostAgent/AppAgent
loop is not used and therefore needs no language model.

The UFO core stays unchanged. This file lives outside `C:\\UFO` and only uses
its registered MCP servers within the same process.

## Why a CLI and not a persistent server process

Every call is self-contained: resolve the window, select it, act, read the
result back. That makes each step reproducible and independently verifiable,
keeps the context output small, and leaves no running service behind.

UFO's window selection lives in the process. A call that performs an action
therefore always selects the window itself — there is no carryover selection
from an earlier call.

## Deliberately not wired in: CommandLineExecutor

UFO also registers a shell executor. That one stays out. Claude already has
shell access via Bash and PowerShell, which runs through the policy guard. A
second shell path would bypass that security boundary.

## Invocation

    C:\\UFO\\.venv\\Scripts\\python.exe C:\\AgentSystem\\adapters\\ufo\\ufoctl.py <command>

All output is JSON on stdout. Diagnostics go to stderr.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

UFO_ROOT = Path(os.environ.get("UFO_ROOT", r"C:\UFO"))

# UICollector reads the control tree. HostUIExecutor selects a window - that
# only activates it and mutates nothing, but is also needed for reading,
# because UFO always reports the controls of the active window.
READ_SERVERS = ("UICollector", "HostUIExecutor")

# Only here do real mutations happen: click, type, drag, scroll.
ACTION_SERVERS = ("AppUIExecutor",)

EXCLUDED = ("CommandLineExecutor",)

PREFIX = {"UICollector": "ui", "HostUIExecutor": "host", "AppUIExecutor": "app"}

DEFAULT_FIELDS = ["control_text", "control_type"]


def _stderr(message: str) -> None:
    print(message, file=sys.stderr)


def _prepare() -> None:
    if not UFO_ROOT.is_dir():
        sys.exit(json.dumps({"error": f"UFO not found: {UFO_ROOT}"}))
    if str(UFO_ROOT) not in sys.path:
        sys.path.insert(0, str(UFO_ROOT))
    # UFO's config loader looks for `config/ufo/` relative to the working directory.
    os.chdir(UFO_ROOT)
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    # UFO logs very verbosely to stdout; that would destroy the JSON output.
    logging.disable(logging.CRITICAL)


def _build(read_only: bool):
    _prepare()
    from fastmcp import FastMCP
    import ufo.client.mcp.local_servers.ui_mcp_server  # noqa: F401
    from ufo.client.mcp.mcp_registry import MCPRegistry

    bridge = FastMCP(name="ufoctl")
    for name in (READ_SERVERS if read_only else READ_SERVERS + ACTION_SERVERS):
        if name in EXCLUDED:
            continue
        bridge.mount(MCPRegistry.get(name), prefix=PREFIX[name])
    return bridge


def _payload(result: Any) -> Any:
    """Reliably extracts the result of a tool call.

    `.content[0].text` is not reliable - with structured output the list can
    be empty. `.data` is the robust access path.
    """
    data = getattr(result, "data", None)
    if data is not None:
        return data
    structured = getattr(result, "structured_content", None)
    if isinstance(structured, dict) and "result" in structured:
        return structured["result"]
    if structured is not None:
        return structured
    content = getattr(result, "content", None) or []
    if content and hasattr(content[0], "text"):
        text = content[0].text
        try:
            return json.loads(text)
        except (json.JSONDecodeError, TypeError):
            return text
    return None


class Session:
    """A UFO work session within a single process."""

    def __init__(self, client):
        self._client = client

    async def call(self, tool: str, arguments: dict | None = None) -> Any:
        result = await self._client.call_tool(tool, arguments or {})
        if getattr(result, "is_error", False):
            raise RuntimeError(f"{tool} reported an error: {_payload(result)}")
        return _payload(result)

    async def windows(self) -> list[dict]:
        data = await self.call("ui_get_desktop_app_info")
        return data if isinstance(data, list) else []

    async def resolve_window(self, needle: str) -> dict:
        """Finds a window by its ID or a name fragment."""
        windows = await self.windows()
        for window in windows:
            if str(window.get("id")) == str(needle):
                return window
        lowered = needle.lower()
        exact = [w for w in windows if w.get("name", "").lower() == lowered]
        if exact:
            return exact[0]
        partial = [w for w in windows if lowered in w.get("name", "").lower()]
        if len(partial) == 1:
            return partial[0]
        if len(partial) > 1:
            raise RuntimeError(
                f"'{needle}' matches multiple windows: "
                + ", ".join(f"{w['id']}={w['name']}" for w in partial)
                + " — please specify the ID or the full name"
            )
        raise RuntimeError(
            f"No window matches '{needle}'. Open windows: "
            + ", ".join(f"{w['id']}={w['name']}" for w in windows)
        )

    async def select(self, needle: str, settle: float = 0.6) -> dict:
        window = await self.resolve_window(needle)
        info = await self.call("host_select_application_window",
                               {"id": str(window["id"]), "name": window["name"]})
        # Wait briefly: the controls are not always already enumerated right
        # after activation.
        time.sleep(settle)
        return {"window": window, "selection": info}

    async def controls(self, fields: list[str], retries: int = 3) -> list[dict]:
        """Reads the controls of the selected window.

        Right after a window switch, UFO occasionally returns an empty list.
        A bounded retry here is not a blind repeat, but waiting out a known
        race.
        """
        for attempt in range(retries):
            data = await self.call("ui_get_app_window_controls_info",
                                   {"field_list": fields})
            if isinstance(data, list) and data:
                return data
            if attempt < retries - 1:
                time.sleep(0.5)
        return []

    async def read_control(self, label: str, fields: list[str]) -> dict | None:
        """Re-reads a control via the control list.

        Deliberately not via `app_texts`: UFO v3.0.8 declares `-> str` there
        but returns a list, which breaks output validation. The control list
        carries the same information and has a correct schema. See
        docs/known-issues.md.
        """
        for item in await self.controls(fields):
            if str(item.get("label")) == str(label):
                return item
        return None

    async def resolve_control(self, needle: str, fields: list[str]) -> dict:
        """Finds a control by its label or a text fragment."""
        items = await self.controls(fields)
        if not items:
            raise RuntimeError("The window reports no controls")
        for item in items:
            if str(item.get("label")) == str(needle):
                return item
        lowered = needle.lower()
        exact = [i for i in items if i.get("control_text", "").lower() == lowered]
        if exact:
            return exact[0]
        partial = [i for i in items if lowered in i.get("control_text", "").lower()]
        if len(partial) == 1:
            return partial[0]
        if len(partial) > 1:
            raise RuntimeError(
                f"'{needle}' matches multiple controls: "
                + ", ".join(f"{i['label']}={i.get('control_text')}" for i in partial[:10])
                + " — please specify the label"
            )
        raise RuntimeError(
            f"No control matches '{needle}'. Available: "
            + ", ".join(f"{i['label']}={i.get('control_text')}" for i in items[:25])
        )


async def _with_session(read_only: bool, body) -> Any:
    from fastmcp import Client
    bridge = _build(read_only)
    async with Client(bridge) as client:
        return await body(Session(client))


# --------------------------------------------------------------------------
# Commands
# --------------------------------------------------------------------------


def cmd_windows(args) -> Any:
    async def body(session: Session):
        return {"windows": await session.windows()}
    return asyncio.run(_with_session(True, body))


def cmd_controls(args) -> Any:
    fields = args.fields or DEFAULT_FIELDS

    async def body(session: Session):
        selection = await session.select(args.window)
        items = await session.controls(fields)
        if args.type:
            items = [i for i in items
                     if i.get("control_type", "").lower() == args.type.lower()]
        if args.contains:
            needle = args.contains.lower()
            items = [i for i in items if needle in i.get("control_text", "").lower()]
        return {
            "window": selection["window"],
            "control_count": len(items),
            "controls": items[: args.limit],
            "truncated": len(items) > args.limit,
        }
    return asyncio.run(_with_session(True, body))


def cmd_tree(args) -> Any:
    async def body(session: Session):
        selection = await session.select(args.window)
        return {"window": selection["window"], "tree": await session.call("ui_get_ui_tree")}
    return asyncio.run(_with_session(True, body))


def cmd_texts(args) -> Any:
    async def body(session: Session):
        selection = await session.select(args.window)
        control = await session.resolve_control(args.control, DEFAULT_FIELDS)
        return {"window": selection["window"], "control": control,
                "text": control.get("control_text")}
    return asyncio.run(_with_session(True, body))


def cmd_click(args) -> Any:
    async def body(session: Session):
        selection = await session.select(args.window)
        control = await session.resolve_control(args.control, DEFAULT_FIELDS)
        result = await session.call("app_click_input", {
            "id": str(control["label"]), "name": control.get("control_text", ""),
            "button": args.button, "double": args.double,
        })
        after = await session.controls(DEFAULT_FIELDS) if args.read_back else None
        return {"window": selection["window"], "control": control,
                "result": result, "controls_after": after}
    return asyncio.run(_with_session(False, body))


def cmd_type(args) -> Any:
    async def body(session: Session):
        selection = await session.select(args.window)
        control = await session.resolve_control(args.control, DEFAULT_FIELDS)
        result = await session.call("app_set_edit_text", {
            "id": str(control["label"]), "name": control.get("control_text", ""),
            "text": args.text, "clear_current_text": args.clear,
        })
        # Read back: a written value only counts as set once it has been
        # re-read.
        verified = await session.read_control(control["label"], DEFAULT_FIELDS)
        written = args.text in (verified or {}).get("control_text", "")
        return {"window": selection["window"], "control": control,
                "result": result, "read_back": verified,
                "verified": written}
    return asyncio.run(_with_session(False, body))


def cmd_keys(args) -> Any:
    async def body(session: Session):
        selection = await session.select(args.window)
        control = await session.resolve_control(args.control, DEFAULT_FIELDS)
        return {"window": selection["window"], "control": control,
                "result": await session.call("app_keyboard_input", {
                    "id": str(control["label"]), "name": control.get("control_text", ""),
                    "keys": args.keys, "control_focus": not args.no_focus,
                })}
    return asyncio.run(_with_session(False, body))


def cmd_scroll(args) -> Any:
    async def body(session: Session):
        selection = await session.select(args.window)
        control = await session.resolve_control(args.control, DEFAULT_FIELDS)
        return {"window": selection["window"], "control": control,
                "result": await session.call("app_wheel_mouse_input", {
                    "id": str(control["label"]), "name": control.get("control_text", ""),
                    "wheel_dist": args.dist,
                })}
    return asyncio.run(_with_session(False, body))


def cmd_screenshot(args) -> Any:
    async def body(session: Session):
        if args.window:
            selection = await session.select(args.window)
            data = await session.call("ui_capture_window_screenshot")
            return {"window": selection["window"], "screenshot": data}
        return {"screenshot": await session.call("ui_capture_desktop_screenshot",
                                                 {"all_screens": args.all_screens})}
    return asyncio.run(_with_session(True, body))


def cmd_inspect(args) -> Any:
    """Reads the real state of a control - without UFO.

    UFO's control list can return stale values: it reports
    `element_info.name` instead of the live `window_text()`. An action
    performed with UFO must therefore never be verified with UFO's own list
    - that would be the executor confirming itself.

    This command goes directly through pywinauto to the UI Automation
    interface and is thus the independent measurement in the sense of
    AGENTS.md section 13.
    """
    _prepare()
    import warnings
    warnings.filterwarnings("ignore")
    from pywinauto import Desktop

    matches = []
    for window in Desktop(backend="uia").windows():
        try:
            title = window.window_text() or ""
        except Exception:  # noqa: BLE001
            continue
        if args.window.lower() not in title.lower():
            continue
        # pywinauto only accepts `depth` together with a search criterion;
        # passed alone it fails internally. Without --type, enumeration is
        # therefore unbounded and only the result is limited.
        try:
            children = (window.descendants(control_type=args.type, depth=args.depth)
                        if args.type else window.descendants())
        except (TypeError, AttributeError):
            children = window.descendants()
        for control in children:
            try:
                name = control.element_info.name or ""
                if args.control and args.control.lower() not in name.lower():
                    continue
                try:
                    value = control.get_value()
                except Exception:  # noqa: BLE001
                    value = None
                matches.append({
                    "name": name,
                    "control_type": control.element_info.control_type,
                    "window_text": control.window_text(),
                    "value": value,
                })
            except Exception:  # noqa: BLE001
                continue
        break

    result: dict[str, Any] = {"window": args.window, "matches": matches[: args.limit]}
    if args.expect is not None:
        found = any(args.expect in (m.get("value") or "")
                    or args.expect in (m.get("window_text") or "")
                    for m in matches)
        result["expect"] = args.expect
        result["verified"] = found
    return result


def cmd_tools(args) -> Any:
    async def body(session: Session):
        tools = await session._client.list_tools()
        return {"tools": sorted(t.name for t in tools), "excluded": list(EXCLUDED)}
    return asyncio.run(_with_session(args.read_only, body))


def cmd_plan(args) -> Any:
    """Runs a sequence of steps within a single window context.

    File format:

        {"window": "Editor",
         "steps": [{"action": "type", "control": "Text-Editor", "text": "hello"},
                   {"action": "keys", "control": "Text-Editor", "keys": "^s"}]}

    Aborts on the first failure and reports which steps already ran — a
    half-executed plan must never count as success.
    """
    plan = json.loads(Path(args.file).read_text(encoding="utf-8"))

    async def body(session: Session):
        selection = await session.select(plan["window"])
        done: list[dict] = []
        for index, step in enumerate(plan.get("steps", [])):
            action = step.get("action")
            try:
                if action == "wait":
                    result = await session.call("app_wait", {"seconds": step["seconds"]})
                    control = None
                else:
                    control = await session.resolve_control(step["control"], DEFAULT_FIELDS)
                    base = {"id": str(control["label"]),
                            "name": control.get("control_text", "")}
                    if action == "click":
                        result = await session.call("app_click_input", {
                            **base, "button": step.get("button", "left"),
                            "double": step.get("double", False)})
                    elif action == "type":
                        result = await session.call("app_set_edit_text", {
                            **base, "text": step["text"],
                            "clear_current_text": step.get("clear", True)})
                    elif action == "keys":
                        result = await session.call("app_keyboard_input", {
                            **base, "keys": step["keys"], "control_focus": True})
                    elif action == "scroll":
                        result = await session.call("app_wheel_mouse_input", {
                            **base, "wheel_dist": step.get("dist", -3)})
                    elif action == "read":
                        result = await session.read_control(control["label"],
                                                            DEFAULT_FIELDS)
                    else:
                        raise RuntimeError(f"Unknown action: {action}")
                done.append({"index": index, "action": action,
                             "control": control, "result": result, "status": "OK"})
            except Exception as error:  # noqa: BLE001
                done.append({"index": index, "action": action,
                             "status": "FAILED", "error": str(error)})
                return {"window": selection["window"], "status": "FAILED",
                        "completed_steps": done,
                        "remaining": len(plan.get("steps", [])) - index - 1}
        return {"window": selection["window"], "status": "OK", "completed_steps": done}

    return asyncio.run(_with_session(False, body))


# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ufoctl", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("windows", help="List open windows").set_defaults(func=cmd_windows)

    controls = sub.add_parser("controls", help="List the controls of a window")
    controls.add_argument("--window", required=True)
    controls.add_argument("--fields", nargs="+")
    controls.add_argument("--type", help="Only this control type")
    controls.add_argument("--contains", help="Only elements with this text")
    controls.add_argument("--limit", type=int, default=80)
    controls.set_defaults(func=cmd_controls)

    tree = sub.add_parser("tree", help="Print the full UI tree")
    tree.add_argument("--window", required=True)
    tree.set_defaults(func=cmd_tree)

    texts = sub.add_parser("texts", help="Read the text of a control")
    texts.add_argument("--window", required=True)
    texts.add_argument("--control", required=True)
    texts.set_defaults(func=cmd_texts)

    click = sub.add_parser("click", help="Click a control")
    click.add_argument("--window", required=True)
    click.add_argument("--control", required=True)
    click.add_argument("--button", default="left", choices=["left", "right", "middle"])
    click.add_argument("--double", action="store_true")
    click.add_argument("--read-back", action="store_true",
                       help="Re-read the controls after the click")
    click.set_defaults(func=cmd_click)

    typing = sub.add_parser("type", help="Write text into an input field")
    typing.add_argument("--window", required=True)
    typing.add_argument("--control", required=True)
    typing.add_argument("--text", required=True)
    typing.add_argument("--clear", action="store_true", default=True)
    typing.add_argument("--no-clear", dest="clear", action="store_false")
    typing.set_defaults(func=cmd_type)

    keys = sub.add_parser("keys", help="Send a key sequence, e.g. ^s for Ctrl+S")
    keys.add_argument("--window", required=True)
    keys.add_argument("--control", required=True)
    keys.add_argument("--keys", required=True)
    keys.add_argument("--no-focus", action="store_true")
    keys.set_defaults(func=cmd_keys)

    scroll = sub.add_parser("scroll", help="Turn the mouse wheel on a control")
    scroll.add_argument("--window", required=True)
    scroll.add_argument("--control", required=True)
    scroll.add_argument("--dist", type=int, default=-3)
    scroll.set_defaults(func=cmd_scroll)

    shot = sub.add_parser("screenshot", help="Take a screenshot")
    shot.add_argument("--window")
    shot.add_argument("--all-screens", action="store_true")
    shot.set_defaults(func=cmd_screenshot)

    inspect_cmd = sub.add_parser(
        "inspect",
        help="Read the real control state without UFO - independent verification")
    inspect_cmd.add_argument("--window", required=True)
    inspect_cmd.add_argument("--control", help="Name fragment of the control")
    inspect_cmd.add_argument("--type", help="UIA control type, e.g. Edit")
    inspect_cmd.add_argument("--expect", help="Expected content; sets 'verified'")
    inspect_cmd.add_argument("--limit", type=int, default=40)
    inspect_cmd.add_argument("--depth", type=int, default=12,
                             help="Maximum enumeration depth in the control tree")
    inspect_cmd.set_defaults(func=cmd_inspect)

    tools = sub.add_parser("tools", help="List available UFO tools")
    tools.add_argument("--read-only", action="store_true")
    tools.set_defaults(func=cmd_tools)

    plan = sub.add_parser("plan", help="Run a sequence of steps from a JSON file")
    plan.add_argument("--file", required=True)
    plan.set_defaults(func=cmd_plan)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        result = args.func(args)
    except Exception as error:  # noqa: BLE001
        print(json.dumps({"status": "FAILED", "error": str(error)},
                         ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
