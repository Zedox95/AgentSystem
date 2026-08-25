"""Environment Fingerprint.

Eine Erfahrung ist nur so viel wert wie die Umgebung, in der sie gemessen
wurde. Dieses Modul erfasst die relevanten Versionen, damit später entschieden
werden kann, ob eine gespeicherte Erkenntnis noch anwendbar ist.

Die Erfassung ist bewusst tolerant: fehlt ein Werkzeug, wird `None` vermerkt,
statt zu scheitern.
"""

from __future__ import annotations

import hashlib
import json
import platform
import re
import shutil
import subprocess
from typing import Any

from . import paths

# Werkzeug -> Kommando zum Auslesen der Version.
_PROBES: dict[str, list[str]] = {
    "python": ["python", "--version"],
    "node": ["node", "--version"],
    "npm": ["npm", "--version"],
    "git": ["git", "--version"],
    "docker": ["docker", "--version"],
    "codex": ["codex", "--version"],
}

# Playwright ist bewusst lokal im Adapterverzeichnis installiert, damit die
# Version festgehalten werden kann. Ein globales `npx playwright` gibt es
# deshalb nicht und würde nur eine irreführende Antwort liefern.
_PLAYWRIGHT_BIN = (
    paths.ADAPTERS_DIR / "playwright" / "node_modules" / ".bin" / "playwright.cmd"
)

_VERSION_RE = re.compile(r"\d+(?:\.\d+)+(?:[-.\w]+)?")


def _probe(command: list[str]) -> str | None:
    # Der aufgelöste Pfad ist nötig: CreateProcess startet unter Windows keine
    # .cmd-Wrapper (npm, npx) über den bloßen Namen.
    resolved = shutil.which(command[0])
    if resolved is None:
        return None
    try:
        completed = subprocess.run(
            [resolved, *command[1:]], capture_output=True, text=True,
            errors="replace", timeout=20, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    # Nur ein erfolgreicher Aufruf zählt. Fehlermeldungen enthalten oft eine
    # Versionsnummer - etwa npm's "npx canceled due to missing packages:
    # ['playwright@1.62.1']" - und würden ein nicht installiertes Werkzeug
    # fälschlich als vorhanden melden.
    if completed.returncode != 0:
        return None
    output = (completed.stdout or completed.stderr or "").strip()
    match = _VERSION_RE.search(output)
    return match.group(0) if match else (output.splitlines()[0] if output else None)


def _windows_build() -> str | None:
    if platform.system() != "Windows":
        return None
    try:
        completed = subprocess.run(
            ["reg", "query",
             r"HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion",
             "/v", "CurrentBuild"],
            capture_output=True, text=True, errors="replace",
            timeout=20, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    match = re.search(r"CurrentBuild\s+REG_SZ\s+(\S+)", completed.stdout)
    return match.group(1) if match else None


def _ufo_commit() -> str | None:
    ufo_root = r"C:\UFO"
    try:
        completed = subprocess.run(
            ["git", "-C", ufo_root, "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, errors="replace",
            timeout=20, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = completed.stdout.strip()
    return value or None


def _playwright_version() -> str | None:
    if not _PLAYWRIGHT_BIN.is_file():
        return None
    try:
        completed = subprocess.run(
            [str(_PLAYWRIGHT_BIN), "--version"], capture_output=True, text=True,
            errors="replace", timeout=60, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    match = _VERSION_RE.search(completed.stdout or "")
    return match.group(0) if match else None


def _claude_code_version() -> str | None:
    """Liest die Version aus dem Verzeichnisnamen der installierten CLI."""
    from pathlib import Path
    import os
    base = Path(os.environ.get("APPDATA", "")) / "Claude" / "claude-code"
    if not base.is_dir():
        return None
    versions = sorted(
        (child.name for child in base.iterdir() if child.is_dir()),
        key=lambda name: [int(part) if part.isdigit() else part
                          for part in re.split(r"[.\-]", name)],
    )
    return versions[-1] if versions else None


def collect() -> dict[str, Any]:
    """Erfasst den aktuellen Environment Fingerprint."""
    data: dict[str, Any] = {
        "os": platform.system(),
        "os_release": platform.release(),
        "windows_build": _windows_build(),
        "arch": platform.machine(),
        "claude_code": _claude_code_version(),
        "ufo_commit": _ufo_commit(),
        "playwright": _playwright_version(),
    }
    for name, command in _PROBES.items():
        data[name] = _probe(command)
    return data


def digest(data: dict[str, Any] | None = None) -> str:
    """Kurzer, stabiler Hash über den Fingerprint - für Environment-Match-Prüfungen."""
    payload = data if data is not None else collect()
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def matches(stored: dict[str, Any], current: dict[str, Any] | None = None,
            *, keys: tuple[str, ...] | None = None) -> tuple[bool, list[str]]:
    """Vergleicht zwei Fingerprints.

    Gibt zurück, ob sie für die angegebenen Schlüssel übereinstimmen, und
    welche Schlüssel abweichen. Fehlt ein Wert auf einer Seite, zählt das als
    Abweichung — eine unbekannte Umgebung ist keine passende Umgebung.
    """
    now = current if current is not None else collect()
    relevant = keys or tuple(stored.keys())
    mismatches = [key for key in relevant if stored.get(key) != now.get(key)]
    return (not mismatches, mismatches)


def save_known_good(name: str, data: dict[str, Any] | None = None) -> str:
    """Friert den aktuellen Stand als Known-Good-Version ein."""
    paths.ensure_dirs()
    payload = data if data is not None else collect()
    record = {"name": name, "digest": digest(payload), "versions": payload}
    target = paths.KNOWN_GOOD_DIR / f"{name}.json"
    target.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(target)


if __name__ == "__main__":
    print(json.dumps(collect(), ensure_ascii=False, indent=2))
