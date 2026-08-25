"""Machine-level checks for Kevin's global Claude/Codex provider adapters."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(r"C:\AgentSystem")
HOME = Path.home()
FAILURES: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        FAILURES.append(message)


def link_target(path: Path) -> str:
    try:
        return str(path.resolve()).lower()
    except OSError:
        return ""


claude_md = HOME / ".claude" / "CLAUDE.md"
claude_settings = HOME / ".claude" / "settings.json"
codex_agents = HOME / ".codex" / "AGENTS.md"
claude_skills = HOME / ".claude" / "skills"
claude_agents = HOME / ".claude" / "agents"
codex_skills = HOME / ".agents" / "skills"
plugin = HOME / "plugins" / "kevin-agent-system"
marketplace = HOME / ".agents" / "plugins" / "marketplace.json"

check(claude_md.exists(), "globale Claude CLAUDE.md fehlt")
if claude_md.exists():
    check("@C:/AgentSystem/AGENTS.md" in claude_md.read_text(encoding="utf-8"),
          "globale Claude CLAUDE.md importiert die zentrale Policy nicht")

for path, target, label in (
    (claude_skills, ROOT / ".claude" / "skills", "Claude skills"),
    (claude_agents, ROOT / ".claude" / "agents", "Claude agents"),
    (codex_skills, ROOT / ".claude" / "skills", "Codex skills"),
):
    check(path.exists(), f"{label}: globaler Pfad fehlt")
    check(link_target(path) == str(target.resolve()).lower(),
          f"{label}: Ziel ist nicht die zentrale Quelle")

check(codex_agents.exists(), "globale Codex AGENTS.md fehlt")
if codex_agents.exists():
    check(codex_agents.read_bytes() == (ROOT / "AGENTS.md").read_bytes(),
          "globale Codex Policy weicht von der zentralen Policy ab")

try:
    settings = json.loads(claude_settings.read_text(encoding="utf-8"))
except (OSError, json.JSONDecodeError) as error:
    settings = {}
    FAILURES.append(f"globale Claude settings.json ungültig: {error}")
check(bool(settings.get("hooks")), "globale Claude Hooks fehlen")
check(settings.get("enabledPlugins", {}).get("codex@openai-codex") is True,
      "globales Claude Codex-Plugin ist nicht aktiviert")
check("Write(C:\\Users\\Kevin\\Documents\\Obsidian Vault\\**)" not in
      settings.get("permissions", {}).get("allow", []),
      "direkter Vault-Write ist global fälschlich erlaubt")

check((plugin / ".codex-plugin" / "plugin.json").exists(),
      "persönliches AgentSystem-Plugin fehlt")
check((plugin / "hooks" / "hooks.json").exists(), "Codex Plugin-Hooks fehlen")
if marketplace.exists():
    market = json.loads(marketplace.read_text(encoding="utf-8"))
    check(any(entry.get("name") == "kevin-agent-system"
              for entry in market.get("plugins", [])),
          "AgentSystem-Plugin fehlt im Personal Marketplace")
else:
    FAILURES.append("Personal Marketplace fehlt")

skill_count = sum(1 for item in claude_skills.iterdir() if item.is_dir()) if claude_skills.exists() else 0
agent_count = sum(1 for item in claude_agents.glob("*.md")) if claude_agents.exists() else 0
check(skill_count == 85, f"globale Skills: erwartet 85, gefunden {skill_count}")
check(agent_count == 6, f"globale Agenten: erwartet 6, gefunden {agent_count}")

print(json.dumps({
    "status": "FAIL" if FAILURES else "PASS",
    "skills": skill_count,
    "agents": agent_count,
    "failures": FAILURES,
}, ensure_ascii=False, indent=2))
sys.exit(1 if FAILURES else 0)

