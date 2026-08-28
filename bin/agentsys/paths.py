"""Central paths of the agent system.

Everything else derives its paths from here, so that relocating the control
plane only needs to be updated in exactly one place.
"""

from __future__ import annotations

import os
from pathlib import Path

# The fixed installation location. It is always co-checked for control-plane
# protection, so that redirecting AGENTSYSTEM_ROOT cannot bypass the protection.
DEFAULT_ROOT = Path(r"C:\AgentSystem")
DEFAULT_VAULT_ROOT = Path(os.environ.get(
    "AGENTSYSTEM_VAULT", str(Path.home() / "Documents" / "Obsidian Vault")
))

# Allows the system to be placed elsewhere for tests.
ROOT = Path(os.environ.get("AGENTSYSTEM_ROOT", str(DEFAULT_ROOT))).resolve()

CLAUDE_DIR = ROOT / ".claude"
AGENTS_DIR = CLAUDE_DIR / "agents"
SKILLS_DIR = CLAUDE_DIR / "skills"
HOOKS_DIR = CLAUDE_DIR / "hooks"

BIN_DIR = ROOT / "bin"
ADAPTERS_DIR = ROOT / "adapters"
DESIRED_STATE_DIR = ROOT / "desired-state"
EVALS_DIR = ROOT / "evals"
CONTRACTS_DIR = ROOT / "schemas"
TESTS_DIR = ROOT / "tests"
DOCS_DIR = ROOT / "docs"
LOGS_DIR = ROOT / "logs"

STATE_DIR = ROOT / "state"
RUNS_DIR = STATE_DIR / "runs"
EXPERIENCES_DIR = STATE_DIR / "experiences"
BASELINES_DIR = STATE_DIR / "baselines"
LOCKS_DIR = STATE_DIR / "locks"
KNOWN_GOOD_DIR = STATE_DIR / "known-good"
SCHEMAS_DIR = STATE_DIR / "schemas"
KNOWLEDGE_QUEUE_DIR = STATE_DIR / "knowledge-candidates"
KNOWLEDGE_PENDING_DIR = KNOWLEDGE_QUEUE_DIR / "pending"
KNOWLEDGE_ACCEPTED_DIR = KNOWLEDGE_QUEUE_DIR / "accepted"
KNOWLEDGE_REJECTED_DIR = KNOWLEDGE_QUEUE_DIR / "rejected"
METRICS_DIR = STATE_DIR / "metrics"
METRIC_EVENTS_FILE = METRICS_DIR / "events.jsonl"
SKILL_CANDIDATES_DIR = STATE_DIR / "skill-candidates"

LEDGER_DB = STATE_DIR / "ledger.sqlite"
CHECKPOINT_FILE = STATE_DIR / "checkpoint.json"

# Relative paths that form the system's security boundary. Changes to these
# only happen through the regular maintenance workflow, never incidentally.
_CONTROL_PLANE_RELATIVE = (
    ".claude/settings.json",
    ".claude/settings.local.json",
    "AGENTS.md",
    ".claude/hooks",
    "bin/agentsys",
)


def _control_plane_paths() -> tuple[Path, ...]:
    """Protected paths under the active *and* the fixed root."""
    roots = {ROOT, DEFAULT_ROOT}
    return tuple(root / relative for root in roots for relative in _CONTROL_PLANE_RELATIVE)


CONTROL_PLANE = _control_plane_paths()


def ensure_dirs() -> None:
    """Creates the state directories if they are missing."""
    for directory in (
        STATE_DIR, RUNS_DIR, EXPERIENCES_DIR, BASELINES_DIR,
        LOCKS_DIR, KNOWN_GOOD_DIR, SCHEMAS_DIR, LOGS_DIR,
        KNOWLEDGE_PENDING_DIR, KNOWLEDGE_ACCEPTED_DIR,
        KNOWLEDGE_REJECTED_DIR, METRICS_DIR, SKILL_CANDIDATES_DIR,
    ):
        directory.mkdir(parents=True, exist_ok=True)


def is_control_plane(path: str | Path) -> bool:
    """True if the path belongs to the protected control plane."""
    try:
        candidate = Path(path).resolve()
    except (OSError, ValueError):
        return False
    for protected in CONTROL_PLANE:
        if candidate == protected:
            return True
        try:
            candidate.relative_to(protected)
            return True
        except ValueError:
            continue
    return False


def is_vault_path(path: str | Path) -> bool:
    """True for direct model-file writes into the managed Obsidian vault."""
    try:
        candidate = Path(path).resolve()
        candidate.relative_to(DEFAULT_VAULT_ROOT.resolve())
        return True
    except (OSError, ValueError):
        return False
