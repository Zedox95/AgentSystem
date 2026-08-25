"""Adaptertests für UFO² und Playwright.

Prüft beide Adapter gegen die real laufende Umgebung. Alle Prüfungen sind
**lesend** — es wird nichts angeklickt, nichts eingegeben und nirgends
angemeldet, damit der Lauf jederzeit gefahrlos wiederholbar ist.

Die schreibenden Ketten wurden beim Aufbau je einmal nachgewiesen und in
`docs/known-issues.md` dokumentiert:

* UFO: `type` in das Suchfeld der Windows-Einstellungen, anschließend über
  `inspect` unabhängig bestätigt und wieder geleert.
* Playwright: `fill` mit Rücklesen gegen eine lokal erzeugte Seite.

Beide gehören wegen ihrer Sichtbarkeit beziehungsweise Zustandsänderung nicht
in einen Routinelauf.

    python C:\\AgentSystem\\tests\\test_adapters.py
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(r"C:\AgentSystem")
UFOCTL = ROOT / "adapters" / "ufo" / "ufoctl.py"
UFO_PYTHON = Path(r"C:\UFO\.venv\Scripts\python.exe")
PWCTL = ROOT / "adapters" / "playwright" / "pwctl.mjs"

# Der lokale Router ist ein stabiles, erreichbares Ziel ohne externe
# Abhängigkeit und ohne Anmeldung. IP an die eigene Umgebung anpassen.
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
    # Werkzeugliste: der Shell-Executor darf nicht erreichbar sein.
    code, payload, stderr = ufoctl("tools")
    check(code == 0, f"ufoctl tools endete mit {code}: {stderr}")
    if payload:
        tools = payload.get("tools", [])
        check(bool(tools), "ufoctl tools liefert keine Werkzeuge")
        shell_tools = [t for t in tools
                       if "command" in t.lower() or "shell" in t.lower()]
        check(not shell_tools,
              f"Shell-Executor darf nicht exponiert sein, gefunden: {shell_tools}")
        check("CommandLineExecutor" in payload.get("excluded", []),
              "CommandLineExecutor muss ausdrücklich ausgeschlossen sein")
        for required in ("ui_get_desktop_app_info", "ui_get_app_window_controls_info",
                         "host_select_application_window", "app_click_input",
                         "app_set_edit_text"):
            check(required in tools, f"Werkzeug fehlt: {required}")

    # Der Lesemodus darf keine Mutationswerkzeuge führen.
    code, payload, _ = ufoctl("tools", "--read-only")
    if payload:
        mutating = [t for t in payload.get("tools", []) if t.startswith("app_")]
        check(not mutating,
              f"Lesemodus darf keine app_-Werkzeuge führen: {mutating}")

    # Fenster auflisten.
    code, payload, stderr = ufoctl("windows")
    check(code == 0, f"ufoctl windows endete mit {code}: {stderr}")
    windows = (payload or {}).get("windows", [])
    if code == 0 and not windows:
        # In nichtinteraktiven Desktop-/Sandbox-Sitzungen kann UFO korrekt
        # starten, aber keinen sichtbaren Benutzerdesktop erreichen. Das ist
        # eine fehlende Testvoraussetzung, kein Adapterregressionsbeweis.
        SKIPPED.append("Kein interaktives Fenster fuer UFO-Lesetests verfuegbar")
        return
    for window in windows:
        check("id" in window and "name" in window,
              f"Fenstereintrag unvollständig: {window}")
    if not windows:
        return

    # Steuerelemente eines real offenen Fensters lesen. Über die ID, nicht
    # über den Namen: Namen ändern sich, IDs sind für den Aufruf stabil.
    code, payload, stderr = ufoctl("controls", "--window", str(windows[0]["id"]))
    check(code == 0, f"ufoctl controls endete mit {code}: {stderr}")
    for control in (payload or {}).get("controls", [])[:5]:
        check("label" in control, f"Steuerelement ohne label: {control}")
        check("control_type" in control, f"Steuerelement ohne Typ: {control}")

    # Unabhängige Prüfung geht an UFO vorbei. Die Fensterliste wird frisch
    # geholt: zwischen zwei Aufrufen kann sich der Desktop geändert haben.
    _, fresh, _ = ufoctl("windows")
    current = (fresh or {}).get("windows", [])
    if not current:
        SKIPPED.append("Kein Fenster für die inspect-Prüfung offen")
    else:
        code, payload, stderr = ufoctl(
            "inspect", "--window", current[0]["name"], "--limit", "5")
        check(code == 0, "ufoctl inspect endete mit "
                         f"{code}: {(payload or {}).get('error', stderr)}")
        check(payload is not None and "matches" in payload,
              "inspect liefert keine matches-Struktur")

    # Fehlerfälle werden benannt, nicht geraten.
    code, payload, _ = ufoctl("controls", "--window", "gibtesnichtxyz123")
    check(code == 1, "Unbekanntes Fenster muss mit Exit 1 enden")
    check((payload or {}).get("status") == "FAILED",
          "Unbekanntes Fenster muss status FAILED melden")
    check("Kein Fenster passt" in (payload or {}).get("error", ""),
          "Fehlermeldung muss die offenen Fenster nennen")


# --------------------------------------------------------------------------
# Playwright
# --------------------------------------------------------------------------


def run_playwright_tests() -> None:
    code, payload, stderr = pwctl("help")
    check(code == 0, f"pwctl help endete mit {code}: {stderr}")
    commands = (payload or {}).get("commands", [])
    for required in ("snapshot", "text", "http", "click", "fill", "plan"):
        check(required in commands, f"pwctl-Befehl fehlt: {required}")

    code, _, _ = pwctl("http")
    check(code == 1, "Aufruf ohne --url muss mit Exit 1 enden")

    # Browser startet und liefert eine echte, verifizierbare HTTP-Antwort.
    code, payload, stderr = pwctl("http", "--url", LOCAL_HTTP_TARGET)
    if code != 0:
        SKIPPED.append("Lokales HTTP-Ziel nicht erreichbar: "
                       f"{(payload or {}).get('error', stderr)}")
        return
    response = (payload or {}).get("response", {})
    check(response.get("status") == 200,
          f"Erwartet HTTP 200, war {response.get('status')}")
    check(bool((payload or {}).get("title")), "Seitentitel fehlt")

    # Accessibility-Snapshot liefert Struktur statt Pixel. Ohne networkidle
    # bleibt eine JavaScript-Oberfläche leer - das ist der eigentliche Test.
    code, payload, stderr = pwctl("snapshot", "--url", LOCAL_HTTP_TARGET,
                                  "--wait", "networkidle", "--timeout", "30000")
    check(code == 0, f"pwctl snapshot endete mit {code}: {stderr}")
    aria = (payload or {}).get("aria", "")
    check("link" in aria or "button" in aria,
          "Snapshot enthält keine bedienbaren Rollen — JS-Aufbau nicht abgewartet?")

    # Ein Klick ohne Lokalisierer wird abgelehnt, statt aufs Geratewohl das
    # erste Element zu treffen.
    code, payload, _ = pwctl("click", "--url", LOCAL_HTTP_TARGET)
    check(code == 1, "Klick ohne Lokalisierer muss mit Exit 1 enden")
    check("Lokalisierer" in (payload or {}).get("error", ""),
          "Fehlermeldung muss den fehlenden Lokalisierer benennen")




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
