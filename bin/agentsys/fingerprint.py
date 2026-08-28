"""Environment fingerprint.

An experience is only as valuable as the environment in which it was
measured. This module captures the relevant versions so that later it can
be decided whether a stored finding is still applicable.

The capture is deliberately tolerant: if a tool is missing, `None` is
recorded instead of failing.
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

# Tool -> command to read out the version.
_PROBES: dict[str, list[str]] = {
    "python": ["python", "--version"],
    "node": ["node", "--version"],
    "npm": ["npm", "--version"],
    "git": ["git", "--version"],
    "docker": ["docker", "--version"],
    "codex": ["codex", "--version"],
}

# Playwright is deliberately installed locally in the adapter directory so
# the version can be pinned down. There is therefore no global
# `npx playwright`, and it would only give a misleading answer.
_PLAYWRIGHT_BIN = (
    paths.ADAPTERS_DIR / "playwright" / "node_modules" / ".bin" / "playwright.cmd"
)

_VERSION_RE = re.compile(r"\d+(?:\.\d+)+(?:[-.\w]+)?")


def _probe(command: list[str]) -> str | None:
    # The resolved path is necessary: on Windows, CreateProcess does not
    # start .cmd wrappers (npm, npx) via the bare name.
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
    # Only a successful call counts. Error messages often contain a version
    # number - e.g. npm's "npx canceled due to missing packages:
    # ['playwright@1.62.1']" - and would falsely report an uninstalled tool
    # as present.
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
    """Reads the version from the directory name of the installed CLI."""
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
    """Captures the current environment fingerprint."""
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
    """Short, stable hash over the fingerprint - for environment-match checks."""
    payload = data if data is not None else collect()
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def matches(stored: dict[str, Any], current: dict[str, Any] | None = None,
            *, keys: tuple[str, ...] | None = None) -> tuple[bool, list[str]]:
    """Compares two fingerprints.

    Returns whether they match for the given keys, and which keys differ.
    If a value is missing on one side, that counts as a mismatch — an
    unknown environment is not a matching environment.
    """
    now = current if current is not None else collect()
    relevant = keys or tuple(stored.keys())
    mismatches = [key for key in relevant if stored.get(key) != now.get(key)]
    return (not mismatches, mismatches)


def save_known_good(name: str, data: dict[str, Any] | None = None) -> str:
    """Freezes the current state as a known-good version."""
    paths.ensure_dirs()
    payload = data if data is not None else collect()
    record = {"name": name, "digest": digest(payload), "versions": payload}
    target = paths.KNOWN_GOOD_DIR / f"{name}.json"
    target.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(target)


if __name__ == "__main__":
    print(json.dumps(collect(), ensure_ascii=False, indent=2))
