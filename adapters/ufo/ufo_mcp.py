"""UFO²-MCP-Server für exploratives Arbeiten.

**Ergänzung zu `ufoctl.py`, kein Ersatz.** Beide Wege existieren nebeneinander,
weil sie unterschiedliche Aufgaben lösen:

* `ufoctl.py` — für bekannte, wiederholbare Abläufe. Jeder Aufruf ist in sich
  geschlossen, deterministisch skriptbar, mit kleiner Kontextausgabe und ohne
  laufenden Prozess. Der Normalfall.
* Dieser MCP-Server — für exploratives Arbeiten in einer unbekannten
  Oberfläche. Der Fensterzustand bleibt über viele Schritte hinweg erhalten,
  statt bei jedem Aufruf neu aufgebaut zu werden. Das spart Zeit, wenn man sich
  erst durch eine Anwendung tasten muss.

Der UFO-Core bleibt unverändert. Diese Datei liegt ausserhalb von `C:\\UFO`
und benutzt nur dessen registrierte MCP-Server.

## Bewusst nicht eingebunden: CommandLineExecutor

UFO registriert auch einen Shell-Executor. Der bleibt aussen vor. Claude hat
über Bash und PowerShell bereits Shell-Zugriff, und der läuft durch den Policy
Guard. Ein zweiter Shell-Weg über MCP würde diese Sicherheitsgrenze umgehen.

## Verifikation

Auch im MCP-Modus gilt: Eine Aktion wird **nicht** mit UFOs eigener
Steuerelementliste verifiziert — die meldet den Accessible Name statt des
lebenden Werts. Dafür gibt es `ufoctl.py inspect`, das über pywinauto an UFO
vorbei misst. Siehe `docs/known-issues.md`.

## Aufruf

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

# UICollector liest, HostUIExecutor wählt ein Fenster aus (aktiviert es nur).
READ_SERVERS = ("UICollector", "HostUIExecutor")
# Nur hier stecken echte Mutationen.
ACTION_SERVERS = ("AppUIExecutor",)
EXCLUDED = ("CommandLineExecutor",)

PREFIX = {"UICollector": "ui", "HostUIExecutor": "host", "AppUIExecutor": "app"}

INSTRUCTIONS = """\
Windows-UI-Automation über UFO². Für exploratives Arbeiten in einer unbekannten
Oberfläche; der Fensterzustand bleibt zwischen den Aufrufen erhalten.

Arbeitsweise:
1. ui_get_desktop_app_info -> offene Fenster mit id und name
2. host_select_application_window -> Fenster aktivieren
3. ui_get_app_window_controls_info -> Steuerelemente mit label, control_text,
   control_type. Dieser Schritt ist Pflicht vor jeder Aktion; ohne ihn kennt
   UFO die Elemente nicht.
4. app_click_input / app_set_edit_text / app_keyboard_input -> über das label
   handeln, nicht über Koordinaten.

Koordinatenbasierte Aktionen sind nicht reproduzierbar und brechen bei jeder
Layoutänderung - nur benutzen, wenn kein benanntes Steuerelement existiert.

Wichtig zur Verifikation: Die Steuerelementliste meldet bei Eingabefeldern den
Accessible Name, nicht den eingegebenen Inhalt, und kann veraltet sein. Eine
ausgeführte Aktion wird deshalb nicht mit dieser Liste bestätigt, sondern mit
'ufoctl.py inspect', das über pywinauto direkt misst.

Für bekannte, wiederholbare Abläufe ist ufoctl.py der bessere Weg: kleinere
Ausgabe, deterministisch skriptbar, einzeln verifizierbar.
"""


def _prepare() -> None:
    if not UFO_ROOT.is_dir():
        sys.exit(f"UFO wurde nicht gefunden: {UFO_ROOT}")
    if str(UFO_ROOT) not in sys.path:
        sys.path.insert(0, str(UFO_ROOT))
    # UFOs Config-Loader sucht `config/ufo/` relativ zum Arbeitsverzeichnis.
    os.chdir(UFO_ROOT)
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    # stdout gehört dem MCP-Protokoll. UFO protokolliert sehr gesprächig und
    # würde den Transport zerstören.
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
                        help="Nur lesende Werkzeuge einbinden, keine GUI-Aktionen")
    parser.add_argument("--list", action="store_true",
                        help="Werkzeuge auflisten und beenden (für Tests)")
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

    # show_banner=False: auf stdout darf nichts ausser dem MCP-Protokoll stehen.
    server.run(transport="stdio", show_banner=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
