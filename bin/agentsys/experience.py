"""Experience Store.

Speichert objektiv messbare Workflow-Erfahrung: welche Methode für welche
Aufgabenart in welcher Umgebung wie zuverlässig war.

Statusmodell nach AGENTS.md Abschnitt 17:

* `CANDIDATE`  — neu beobachtet, noch nicht bestätigt
* `VERIFIED`   — durch unabhängige Verifikation bestätigt
* `DEPRECATED` — überholt, wird nicht mehr bevorzugt

Eine Erfahrung ohne Environment Fingerprint ist wertlos und wird abgelehnt.
Secrets werden nicht gespeichert.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from . import fingerprint, paths
from .ledger import redact

CANDIDATE = "CANDIDATE"
VERIFIED = "VERIFIED"
DEPRECATED = "DEPRECATED"

_SAFE = re.compile(r"[^a-z0-9._-]+")


@dataclass
class Experience:
    """Eine Methode für eine Aufgabenart, mit gemessener Erfolgsbilanz."""

    key: str                      # z. B. "windows.driver.inventory"
    method: str                   # z. B. "powershell:Get-PnpDevice"
    status: str = CANDIDATE
    agent: str | None = None
    tool: str | None = None
    success_count: int = 0
    failure_count: int = 0
    total_duration_ms: int = 0
    retries: int = 0
    rollbacks: int = 0
    last_success_utc: str | None = None
    last_failure_utc: str | None = None
    last_error: str | None = None
    root_cause: str | None = None
    limitations: list[str] = field(default_factory=list)
    revalidate_when: list[str] = field(default_factory=list)
    environment: dict[str, Any] = field(default_factory=dict)
    environment_digest: str = ""
    created_utc: str = ""
    updated_utc: str = ""

    @property
    def attempts(self) -> int:
        return self.success_count + self.failure_count

    @property
    def success_rate(self) -> float | None:
        return (self.success_count / self.attempts) if self.attempts else None

    @property
    def median_duration_ms(self) -> int | None:
        """Mittlere Dauer über alle Erfolge - grobe, aber ausreichende Kennzahl."""
        return (self.total_duration_ms // self.success_count) if self.success_count else None


def _path(key: str, method: str):
    paths.ensure_dirs()
    name = _SAFE.sub("_", f"{key}__{method}".lower())
    return paths.EXPERIENCES_DIR / f"{name}.json"


def load(key: str, method: str) -> Experience | None:
    path = _path(key, method)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    known = {f for f in Experience.__dataclass_fields__}
    return Experience(**{k: v for k, v in data.items() if k in known})


def save(entry: Experience) -> str:
    now = datetime.now(timezone.utc).isoformat()
    entry.created_utc = entry.created_utc or now
    entry.updated_utc = now
    if not entry.environment:
        raise ValueError("Experience ohne Environment Fingerprint wird nicht gespeichert")
    entry.environment_digest = entry.environment_digest or fingerprint.digest(entry.environment)
    entry.last_error = redact(entry.last_error)
    path = _path(entry.key, entry.method)
    path.write_text(json.dumps(asdict(entry), ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def record(key: str, method: str, *, success: bool, duration_ms: int = 0,
           agent: str | None = None, tool: str | None = None,
           error: str | None = None, root_cause: str | None = None,
           retries: int = 0, rolled_back: bool = False) -> Experience:
    """Verbucht das Ergebnis einer Ausführung."""
    entry = load(key, method) or Experience(
        key=key, method=method, agent=agent, tool=tool,
        environment=fingerprint.collect(),
    )
    now = datetime.now(timezone.utc).isoformat()
    if success:
        entry.success_count += 1
        entry.total_duration_ms += max(duration_ms, 0)
        entry.last_success_utc = now
    else:
        entry.failure_count += 1
        entry.last_failure_utc = now
        entry.last_error = error
        entry.root_cause = root_cause or entry.root_cause
    entry.retries += max(retries, 0)
    if rolled_back:
        entry.rollbacks += 1
    entry.agent = agent or entry.agent
    entry.tool = tool or entry.tool
    save(entry)
    return entry


def promote(key: str, method: str, *, revalidate_when: list[str] | None = None) -> Experience:
    """Hebt eine bestätigte Erfahrung von CANDIDATE auf VERIFIED.

    Nur zulässig nach einem PASS des Verifiers und mindestens einem Erfolg.
    """
    entry = load(key, method)
    if entry is None:
        raise KeyError(f"Unbekannte Erfahrung: {key} / {method}")
    if entry.success_count < 1:
        raise ValueError("VERIFIED erfordert mindestens einen belegten Erfolg")
    entry.status = VERIFIED
    if revalidate_when:
        entry.revalidate_when = revalidate_when
    save(entry)
    return entry


def deprecate(key: str, method: str, reason: str) -> Experience:
    entry = load(key, method)
    if entry is None:
        raise KeyError(f"Unbekannte Erfahrung: {key} / {method}")
    entry.status = DEPRECATED
    entry.limitations = [*entry.limitations, f"DEPRECATED: {reason}"]
    save(entry)
    return entry


def all_entries() -> list[Experience]:
    paths.ensure_dirs()
    result = []
    for path in sorted(paths.EXPERIENCES_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        known = {f for f in Experience.__dataclass_fields__}
        result.append(Experience(**{k: v for k, v in data.items() if k in known}))
    return result


def best_method(key: str, *, require_environment_match: bool = True) -> Experience | None:
    """Wählt die beste bekannte Methode für eine Aufgabenart.

    Zuverlässigkeit schlägt Geschwindigkeit: sortiert wird zuerst nach Status,
    dann nach Erfolgsrate, erst danach nach Dauer. Veraltete Einträge und
    solche mit unpassender Umgebung werden ausgeschlossen.
    """
    current = fingerprint.collect()
    candidates = []
    for entry in all_entries():
        if entry.key != key or entry.status == DEPRECATED or entry.attempts == 0:
            continue
        if require_environment_match:
            ok, _ = fingerprint.matches(entry.environment, current)
            if not ok:
                continue
        candidates.append(entry)
    if not candidates:
        return None
    return sorted(
        candidates,
        key=lambda e: (
            0 if e.status == VERIFIED else 1,
            -(e.success_rate or 0.0),
            e.median_duration_ms or 10**9,
            e.rollbacks,
        ),
    )[0]


def stale_entries() -> list[tuple[Experience, list[str]]]:
    """Erfahrungen, deren Umgebung sich seit der Messung geändert hat."""
    current = fingerprint.collect()
    result = []
    for entry in all_entries():
        if entry.status == DEPRECATED:
            continue
        ok, mismatches = fingerprint.matches(entry.environment, current)
        if not ok:
            result.append((entry, mismatches))
    return result
