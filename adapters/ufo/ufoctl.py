"""ufoctl — UFO² als Windows-Aktionsschicht über die Kommandozeile.

Claude Code bleibt das Gehirn. UFO² liefert nur UI Automation: den
Steuerelementbaum auslesen und begrenzte GUI-Aktionen ausführen. UFOs eigene
HostAgent/AppAgent-Schleife wird nicht benutzt und braucht deshalb kein
Sprachmodell.

Der UFO-Core bleibt unverändert. Diese Datei liegt außerhalb von `C:\\UFO` und
nutzt nur dessen registrierte MCP-Server im selben Prozess.

## Warum CLI und nicht ein dauerhafter Serverprozess

Jeder Aufruf ist in sich geschlossen: Fenster auflösen, auswählen, handeln,
Ergebnis zurücklesen. Das macht jeden Schritt reproduzierbar und einzeln
verifizierbar, hält die Kontextausgabe klein und hinterlässt keinen laufenden
Dienst.

UFOs Fensterauswahl lebt im Prozess. Ein Aufruf, der eine Aktion ausführt,
wählt das Fenster deshalb immer selbst aus — eine Auswahl aus einem früheren
Aufruf gibt es nicht.

## Bewusst nicht eingebunden: CommandLineExecutor

UFO registriert auch einen Shell-Executor. Der bleibt außen vor. Claude hat
über Bash und PowerShell bereits Shell-Zugriff, und der läuft durch den Policy
Guard. Ein zweiter Shell-Weg würde diese Sicherheitsgrenze umgehen.

## Aufruf

    C:\\UFO\\.venv\\Scripts\\python.exe C:\\AgentSystem\\adapters\\ufo\\ufoctl.py <befehl>

Alle Ausgaben sind JSON auf stdout. Diagnose geht nach stderr.
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

# UICollector liest den Steuerelementbaum. HostUIExecutor wählt ein Fenster
# aus - das aktiviert es nur und mutiert nichts, wird aber auch zum Lesen
# gebraucht, weil UFO die Steuerelemente immer für das aktive Fenster liefert.
READ_SERVERS = ("UICollector", "HostUIExecutor")

# Nur hier stecken echte Mutationen: klicken, tippen, ziehen, scrollen.
ACTION_SERVERS = ("AppUIExecutor",)

EXCLUDED = ("CommandLineExecutor",)

PREFIX = {"UICollector": "ui", "HostUIExecutor": "host", "AppUIExecutor": "app"}

DEFAULT_FIELDS = ["control_text", "control_type"]


def _stderr(message: str) -> None:
    print(message, file=sys.stderr)


def _prepare() -> None:
    if not UFO_ROOT.is_dir():
        sys.exit(json.dumps({"error": f"UFO nicht gefunden: {UFO_ROOT}"}))
    if str(UFO_ROOT) not in sys.path:
        sys.path.insert(0, str(UFO_ROOT))
    # UFOs Config-Loader sucht `config/ufo/` relativ zum Arbeitsverzeichnis.
    os.chdir(UFO_ROOT)
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    # UFO protokolliert sehr gesprächig nach stdout; das würde die JSON-Ausgabe
    # zerstören.
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
    """Holt das Ergebnis eines Tool-Aufrufs zuverlässig heraus.

    `.content[0].text` ist nicht verlässlich - bei strukturierter Ausgabe kann
    die Liste leer sein. `.data` ist der belastbare Zugriff.
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
    """Ein UFO-Arbeitsgang innerhalb eines einzigen Prozesses."""

    def __init__(self, client):
        self._client = client

    async def call(self, tool: str, arguments: dict | None = None) -> Any:
        result = await self._client.call_tool(tool, arguments or {})
        if getattr(result, "is_error", False):
            raise RuntimeError(f"{tool} meldete einen Fehler: {_payload(result)}")
        return _payload(result)

    async def windows(self) -> list[dict]:
        data = await self.call("ui_get_desktop_app_info")
        return data if isinstance(data, list) else []

    async def resolve_window(self, needle: str) -> dict:
        """Findet ein Fenster über seine ID oder einen Namensausschnitt."""
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
                f"'{needle}' passt auf mehrere Fenster: "
                + ", ".join(f"{w['id']}={w['name']}" for w in partial)
                + " — bitte die ID oder den vollen Namen angeben"
            )
        raise RuntimeError(
            f"Kein Fenster passt auf '{needle}'. Offen sind: "
            + ", ".join(f"{w['id']}={w['name']}" for w in windows)
        )

    async def select(self, needle: str, settle: float = 0.6) -> dict:
        window = await self.resolve_window(needle)
        info = await self.call("host_select_application_window",
                               {"id": str(window["id"]), "name": window["name"]})
        # Kurz warten: die Steuerelemente sind unmittelbar nach dem Aktivieren
        # nicht immer schon aufgezählt.
        time.sleep(settle)
        return {"window": window, "selection": info}

    async def controls(self, fields: list[str], retries: int = 3) -> list[dict]:
        """Liest die Steuerelemente des ausgewählten Fensters.

        Direkt nach dem Fensterwechsel liefert UFO gelegentlich eine leere
        Liste. Ein begrenzter Wiederholungsversuch ist hier keine blinde
        Wiederholung, sondern das Abwarten eines bekannten Rennens.
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
        """Liest ein Steuerelement über die Steuerelementliste erneut aus.

        Bewusst nicht über `app_texts`: UFO v3.0.8 deklariert dort `-> str`,
        liefert aber eine Liste, was die Ausgabevalidierung sprengt. Die
        Steuerelementliste enthält dieselbe Information und hat ein korrektes
        Schema. Siehe docs/known-issues.md.
        """
        for item in await self.controls(fields):
            if str(item.get("label")) == str(label):
                return item
        return None

    async def resolve_control(self, needle: str, fields: list[str]) -> dict:
        """Findet ein Steuerelement über sein Label oder einen Textausschnitt."""
        items = await self.controls(fields)
        if not items:
            raise RuntimeError("Das Fenster meldet keine Steuerelemente")
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
                f"'{needle}' passt auf mehrere Steuerelemente: "
                + ", ".join(f"{i['label']}={i.get('control_text')}" for i in partial[:10])
                + " — bitte das Label angeben"
            )
        raise RuntimeError(
            f"Kein Steuerelement passt auf '{needle}'. Vorhanden sind: "
            + ", ".join(f"{i['label']}={i.get('control_text')}" for i in items[:25])
        )


async def _with_session(read_only: bool, body) -> Any:
    from fastmcp import Client
    bridge = _build(read_only)
    async with Client(bridge) as client:
        return await body(Session(client))


# --------------------------------------------------------------------------
# Befehle
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
        # Zurücklesen: eine geschriebene Eingabe gilt erst als gesetzt, wenn
        # sie erneut ausgelesen wurde.
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
    """Liest den echten Zustand eines Steuerelements - ohne UFO.

    UFOs Steuerelementliste kann veraltete Werte liefern: sie meldet
    `element_info.name` statt des lebenden `window_text()`. Eine mit UFO
    ausgeführte Aktion darf deshalb niemals mit UFOs eigener Liste verifiziert
    werden - das wäre der Executor, der sich selbst bestätigt.

    Dieser Befehl geht direkt über pywinauto an die UI-Automation-Schnittstelle
    und ist damit die unabhängige Messung im Sinne von AGENTS.md Abschnitt 13.
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
        # pywinauto akzeptiert `depth` nur zusammen mit einem Suchkriterium;
        # allein uebergeben scheitert es intern. Ohne --type wird deshalb
        # unbegrenzt aufgezaehlt und erst das Ergebnis begrenzt.
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
    """Führt eine Schrittfolge in einem einzigen Fensterkontext aus.

    Format der Datei:

        {"window": "Editor",
         "steps": [{"action": "type", "control": "Text-Editor", "text": "hallo"},
                   {"action": "keys", "control": "Text-Editor", "keys": "^s"}]}

    Bricht beim ersten Fehlschlag ab und meldet, welche Schritte bereits
    ausgeführt wurden — ein halb ausgeführter Plan darf nie als Erfolg gelten.
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
                        raise RuntimeError(f"Unbekannte Aktion: {action}")
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

    sub.add_parser("windows", help="Offene Fenster auflisten").set_defaults(func=cmd_windows)

    controls = sub.add_parser("controls", help="Steuerelemente eines Fensters auflisten")
    controls.add_argument("--window", required=True)
    controls.add_argument("--fields", nargs="+")
    controls.add_argument("--type", help="Nur diesen Steuerelementtyp")
    controls.add_argument("--contains", help="Nur Elemente mit diesem Text")
    controls.add_argument("--limit", type=int, default=80)
    controls.set_defaults(func=cmd_controls)

    tree = sub.add_parser("tree", help="Vollständigen UI-Baum ausgeben")
    tree.add_argument("--window", required=True)
    tree.set_defaults(func=cmd_tree)

    texts = sub.add_parser("texts", help="Text eines Steuerelements lesen")
    texts.add_argument("--window", required=True)
    texts.add_argument("--control", required=True)
    texts.set_defaults(func=cmd_texts)

    click = sub.add_parser("click", help="Steuerelement anklicken")
    click.add_argument("--window", required=True)
    click.add_argument("--control", required=True)
    click.add_argument("--button", default="left", choices=["left", "right", "middle"])
    click.add_argument("--double", action="store_true")
    click.add_argument("--read-back", action="store_true",
                       help="Steuerelemente nach dem Klick erneut auslesen")
    click.set_defaults(func=cmd_click)

    typing = sub.add_parser("type", help="Text in ein Eingabefeld schreiben")
    typing.add_argument("--window", required=True)
    typing.add_argument("--control", required=True)
    typing.add_argument("--text", required=True)
    typing.add_argument("--clear", action="store_true", default=True)
    typing.add_argument("--no-clear", dest="clear", action="store_false")
    typing.set_defaults(func=cmd_type)

    keys = sub.add_parser("keys", help="Tastenfolge senden, z. B. ^s für Strg+S")
    keys.add_argument("--window", required=True)
    keys.add_argument("--control", required=True)
    keys.add_argument("--keys", required=True)
    keys.add_argument("--no-focus", action="store_true")
    keys.set_defaults(func=cmd_keys)

    scroll = sub.add_parser("scroll", help="Mausrad im Steuerelement drehen")
    scroll.add_argument("--window", required=True)
    scroll.add_argument("--control", required=True)
    scroll.add_argument("--dist", type=int, default=-3)
    scroll.set_defaults(func=cmd_scroll)

    shot = sub.add_parser("screenshot", help="Screenshot aufnehmen")
    shot.add_argument("--window")
    shot.add_argument("--all-screens", action="store_true")
    shot.set_defaults(func=cmd_screenshot)

    inspect_cmd = sub.add_parser(
        "inspect",
        help="Echten Steuerelementzustand ohne UFO lesen - unabhängige Verifikation")
    inspect_cmd.add_argument("--window", required=True)
    inspect_cmd.add_argument("--control", help="Namensausschnitt des Steuerelements")
    inspect_cmd.add_argument("--type", help="UIA-Steuerelementtyp, z. B. Edit")
    inspect_cmd.add_argument("--expect", help="Erwarteter Inhalt; setzt 'verified'")
    inspect_cmd.add_argument("--limit", type=int, default=40)
    inspect_cmd.add_argument("--depth", type=int, default=12,
                             help="Maximale Aufzaehlungstiefe im Steuerelementbaum")
    inspect_cmd.set_defaults(func=cmd_inspect)

    tools = sub.add_parser("tools", help="Verfügbare UFO-Werkzeuge auflisten")
    tools.add_argument("--read-only", action="store_true")
    tools.set_defaults(func=cmd_tools)

    plan = sub.add_parser("plan", help="Schrittfolge aus einer JSON-Datei ausführen")
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
