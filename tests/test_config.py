"""Checks the control plane configuration for consistency.

Catches what would otherwise only surface at runtime: broken frontmatter, a
hook script that doesn't exist or doesn't compile, a hook event this
Claude Code version doesn't know, or an agent that hardwires a fixed model.

    python C:\\AgentSystem\\tests\\test_config.py
"""

from __future__ import annotations

import json
import py_compile
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGENTS_DIR = ROOT / ".claude" / "agents"
SKILLS_DIR = ROOT / ".claude" / "skills"
HOOKS_DIR = ROOT / ".claude" / "hooks"
SETTINGS = ROOT / ".claude" / "settings.json"

# Hook events that actually exist in Claude Code 2.1.234.
# Verified against the official hook reference; none of this is guessed.
KNOWN_HOOK_EVENTS = {
    "SessionStart", "Setup", "UserPromptSubmit", "UserPromptExpansion",
    "PreToolUse", "PermissionRequest", "PermissionDenied", "PostToolUse",
    "PostToolUseFailure", "PostToolBatch", "Stop", "StopFailure",
    "SubagentStart", "SubagentStop", "TaskCreated", "TaskCompleted",
    "TeammateIdle", "Notification", "MessageDisplay", "InstructionsLoaded",
    "ConfigChange", "CwdChanged", "DirectoryAdded", "FileChanged",
    "WorktreeCreate", "WorktreeRemove", "PreCompact", "PostCompact",
    "Elicitation", "ElicitationResult", "SessionEnd",
}

EXPECTED_AGENTS = {
    "windows-agent", "infrastructure-agent", "browser-agent",
    "gaming-agent", "implementation-agent", "verification-agent",
}

EXPECTED_SKILLS = {
    "preflight-change", "verify-change", "diagnose-failure", "rollback-change",
    "windows-admin", "browser-admin", "infrastructure-admin", "update-agent-stack",
    "ufo-windows", "playwright-web", "model-routing",
    "knowledge-review",
}

# Externally adopted skills (disable-model-invocation: true, only invocable
# manually via /skill-name - see .claude/skills/EXTERNAL-SKILLS.md). Bundle
# skills carry a source prefix before the directory name; the frontmatter
# `name` field stays the original skill name from the source repo
# unchanged. The name set is read from the manifest so the manifest and
# the test expectation can't drift apart.
EXTERNAL_SKILLS_MANIFEST = SKILLS_DIR / "EXTERNAL-SKILLS.md"
EXTERNAL_BUNDLE_PREFIXES = ("marketingskills-", "obsidian-", "superpowers-")


def load_external_skill_names() -> set[str]:
    if not EXTERNAL_SKILLS_MANIFEST.exists():
        return set()
    names: set[str] = set()
    for line in EXTERNAL_SKILLS_MANIFEST.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^\|\s*`([a-zA-Z0-9_-]+)`\s*\|", line)
        if match:
            names.add(match.group(1))
    return names


EXTERNAL_SKILLS = load_external_skill_names()

# Only these fields are allowed by the skill spec resp. the Claude Code
# extension. An unknown key causes an error on load.
ALLOWED_SKILL_KEYS = {
    "name", "description", "license", "compatibility", "metadata",
    "allowed-tools", "disallowed-tools", "argument-hint", "arguments",
    "disable-model-invocation", "context", "paths", "model", "user-invocable",
}

ALLOWED_AGENT_KEYS = {
    "name", "description", "tools", "disallowedTools", "model", "permissionMode",
    "maxTurns", "skills", "mcpServers", "hooks", "memory", "background",
    "effort", "isolation", "color", "initialPrompt",
}

FAILURES: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        FAILURES.append(message)


def parse_frontmatter(path: Path) -> tuple[dict, str]:
    """Minimal YAML frontmatter parser for flat key-value pairs."""
    text = path.read_text(encoding="utf-8")
    match = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n(.*)$", text, re.DOTALL)
    if not match:
        return {}, text
    fields: dict[str, str] = {}
    current: str | None = None
    for line in match.group(1).splitlines():
        if not line.strip():
            continue
        if line.startswith((" ", "\t", "-")) and current:
            fields[current] += " " + line.strip()
            continue
        key, _, value = line.partition(":")
        current = key.strip()
        fields[current] = value.strip()
    return fields, match.group(2)


# --------------------------------------------------------------------------
# Agents
# --------------------------------------------------------------------------
agent_files = sorted(AGENTS_DIR.glob("*.md"))
found_agents = {path.stem for path in agent_files}
check(found_agents == EXPECTED_AGENTS,
      f"Agent set deviates: missing {EXPECTED_AGENTS - found_agents}, "
      f"unexpected {found_agents - EXPECTED_AGENTS}")

for path in agent_files:
    fields, body = parse_frontmatter(path)
    check(bool(fields), f"{path.name}: no evaluable frontmatter")
    check(fields.get("name") == path.stem,
          f"{path.name}: name '{fields.get('name')}' doesn't match the file name")
    check(len(fields.get("description", "")) > 60,
          f"{path.name}: description too short for reliable selection")
    check(":" not in fields.get("name", ""), f"{path.name}: name must not contain ':'")
    unknown = set(fields) - ALLOWED_AGENT_KEYS
    check(not unknown, f"{path.name}: unknown frontmatter keys {unknown}")
    # No agent hardwires a fixed model (user's requirement).
    check("model" not in fields,
          f"{path.name}: hardwires a fixed model — not allowed")
    check(len(body.strip()) > 400, f"{path.name}: system prompt is too thin")

verifier = AGENTS_DIR / "verification-agent.md"
fields, _ = parse_frontmatter(verifier)
for forbidden in ("Write", "Edit", "NotebookEdit"):
    check(forbidden not in fields.get("tools", ""),
          f"verification-agent must not carry {forbidden} in tools")
    check(forbidden in fields.get("disallowedTools", ""),
          f"verification-agent must carry {forbidden} in disallowedTools")

# --------------------------------------------------------------------------
# Skills
# --------------------------------------------------------------------------
skill_files = sorted(SKILLS_DIR.glob("*/SKILL.md"))
found_skills = {path.parent.name for path in skill_files}
all_expected_skills = EXPECTED_SKILLS | EXTERNAL_SKILLS
check(found_skills == all_expected_skills,
      f"Skill set deviates: missing {all_expected_skills - found_skills}, "
      f"unexpected {found_skills - all_expected_skills}")

for path in skill_files:
    fields, body = parse_frontmatter(path)
    dirname = path.parent.name
    check(bool(fields), f"{dirname}: no evaluable frontmatter")
    name_matches = fields.get("name") == dirname
    if not name_matches and dirname in EXTERNAL_SKILLS:
        # Externally adopted bundle skills keep the original `name` from
        # the source repo; only the directory prefix marks the source
        # (see EXTERNAL-SKILLS.md).
        name_matches = any(dirname == prefix + fields.get("name", "")
                            for prefix in EXTERNAL_BUNDLE_PREFIXES)
    check(name_matches, f"{dirname}: name doesn't match the directory")
    description = fields.get("description", "")
    # disable-model-invocation means the description is never loaded into
    # context per the skills docs, so the minimum length for reliable
    # automatic activation doesn't apply there.
    auto_invocable = fields.get("disable-model-invocation", "").lower() not in (
        "true", "yes", "on", "1")
    if auto_invocable:
        check(len(description) > 80,
              f"{dirname}: description too short for reliable activation")
    check(len(description) <= 1536,
          f"{path.parent.name}: description exceeds 1536 characters")
    unknown = set(fields) - ALLOWED_SKILL_KEYS
    check(not unknown, f"{path.parent.name}: unknown frontmatter keys {unknown}")
    check(len(body.strip()) > 400, f"{path.parent.name}: content is too thin")

# --------------------------------------------------------------------------
# settings.json
# --------------------------------------------------------------------------
try:
    settings = json.loads(SETTINGS.read_text(encoding="utf-8"))
except json.JSONDecodeError as error:
    settings = {}
    FAILURES.append(f"settings.json is not valid JSON: {error}")

hooks = settings.get("hooks", {})
check(bool(hooks), "settings.json contains no hooks")

referenced_scripts: set[Path] = set()
for event, entries in hooks.items():
    check(event in KNOWN_HOOK_EVENTS,
          f"Hook event '{event}' is not documented for this Claude Code version")
    for entry in entries:
        for hook in entry.get("hooks", []):
            check(hook.get("type") == "command",
                  f"{event}: unexpected hook type {hook.get('type')}")
            command = hook.get("command", "")
            match = re.search(r'"([^"]+\.py)"', command)
            check(match is not None, f"{event}: hook command without script path: {command}")
            if match:
                script = Path(match.group(1))
                referenced_scripts.add(script)
                check(script.exists(), f"{event}: hook script missing: {script}")

# Every hook script must compile - a syntax error would otherwise only
# become visible at runtime, and as a silent non-block at that.
with tempfile.TemporaryDirectory() as cache:
    for script in sorted(HOOKS_DIR.glob("*.py")):
        try:
            py_compile.compile(str(script), cfile=str(Path(cache) / f"{script.stem}.pyc"),
                               doraise=True)
        except py_compile.PyCompileError as error:
            FAILURES.append(f"Hook {script.name} does not compile: {error}")

# Find orphaned hook scripts (except the shared library).
orphans = {
    script.name for script in HOOKS_DIR.glob("*.py")
    if script.name != "hooklib.py"
    and not any(script.name == ref.name for ref in referenced_scripts)
    and script.name != "readonly_guard.py"  # referenced in agent frontmatter
}
check(not orphans, f"Hook scripts without wiring: {orphans}")

# Permissions: the cost policy must be enforced.
deny = " ".join(settings.get("permissions", {}).get("deny", []))
for key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "CODEX_API_KEY"):
    check(key in deny, f"permissions.deny does not cover {key}")

check(settings.get("permissions", {}).get("defaultMode") == "default",
      "permissions.defaultMode must be 'default'")

# --------------------------------------------------------------------------
# AGENTS.md is included by CLAUDE.md
# --------------------------------------------------------------------------
claude_md = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
check("@AGENTS.md" in claude_md, "CLAUDE.md does not include AGENTS.md via @AGENTS.md")
check(len(claude_md) < 6000, "CLAUDE.md should stay short (AGENTS.md section 17)")

agents_md = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
for section in ("Risk Classes", "Task Contract", "Resource Locks",
                "Secrets", "Objective Tests", "Independent Verification"):
    check(section in agents_md, f"AGENTS.md is missing the section '{section}'")

# --------------------------------------------------------------------------
print(json.dumps({
    "status": "FAIL" if FAILURES else "PASS",
    "agents": len(agent_files),
    "skills": len(skill_files),
    "hook_events": len(hooks),
    "failures": FAILURES,
}, ensure_ascii=False, indent=2))
sys.exit(1 if FAILURES else 0)
