"""Prüft die Konfiguration der Control Plane auf Konsistenz.

Fängt ab, was sonst erst im Betrieb auffällt: kaputtes Frontmatter, ein
Hook-Skript, das nicht existiert oder nicht kompiliert, ein Hook-Ereignis, das
diese Claude-Code-Version nicht kennt, oder ein Agent, der ein festes Modell
verdrahtet.

    python C:\\AgentSystem\\tests\\test_config.py
"""

from __future__ import annotations

import json
import py_compile
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(r"C:\AgentSystem")
AGENTS_DIR = ROOT / ".claude" / "agents"
SKILLS_DIR = ROOT / ".claude" / "skills"
HOOKS_DIR = ROOT / ".claude" / "hooks"
SETTINGS = ROOT / ".claude" / "settings.json"

# Hook-Ereignisse, die in Claude Code 2.1.234 tatsächlich existieren.
# Belegt gegen die offizielle Hook-Referenz; nichts davon ist geraten.
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

# Extern übernommene Skills (disable-model-invocation: true, nur manuell per
# /skill-name aufrufbar - siehe .claude/skills/EXTERNAL-SKILLS.md). Bundle-
# Skills tragen einen Quellen-Präfix vor dem Verzeichnisnamen; das Frontmatter-
# `name`-Feld bleibt dabei unverändert der Original-Skillname aus dem
# Quell-Repo. Die Namensmenge wird aus dem Manifest gelesen, damit Manifest
# und Testerwartung nicht auseinanderlaufen können.
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

# Nur diese Felder erlaubt die Skill-Spezifikation bzw. die Claude-Code-
# Erweiterung. Ein unbekannter Schlüssel führt beim Laden zu einem Fehler.
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
    """Minimaler YAML-Frontmatter-Parser für flache Schlüssel-Wert-Paare."""
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
# Agenten
# --------------------------------------------------------------------------
agent_files = sorted(AGENTS_DIR.glob("*.md"))
found_agents = {path.stem for path in agent_files}
check(found_agents == EXPECTED_AGENTS,
      f"Agentenmenge weicht ab: fehlt {EXPECTED_AGENTS - found_agents}, "
      f"unerwartet {found_agents - EXPECTED_AGENTS}")

for path in agent_files:
    fields, body = parse_frontmatter(path)
    check(bool(fields), f"{path.name}: kein auswertbares Frontmatter")
    check(fields.get("name") == path.stem,
          f"{path.name}: name '{fields.get('name')}' passt nicht zum Dateinamen")
    check(len(fields.get("description", "")) > 60,
          f"{path.name}: description zu knapp für zuverlässige Auswahl")
    check(":" not in fields.get("name", ""), f"{path.name}: name darf kein ':' enthalten")
    unknown = set(fields) - ALLOWED_AGENT_KEYS
    check(not unknown, f"{path.name}: unbekannte Frontmatter-Schlüssel {unknown}")
    # Kein Agent pinnt ein Modell fest (Vorgabe des Benutzers).
    check("model" not in fields,
          f"{path.name}: verdrahtet ein festes Modell — nicht zulässig")
    check(len(body.strip()) > 400, f"{path.name}: Systemprompt ist zu dünn")

verifier = AGENTS_DIR / "verification-agent.md"
fields, _ = parse_frontmatter(verifier)
for forbidden in ("Write", "Edit", "NotebookEdit"):
    check(forbidden not in fields.get("tools", ""),
          f"verification-agent darf {forbidden} nicht in tools führen")
    check(forbidden in fields.get("disallowedTools", ""),
          f"verification-agent muss {forbidden} in disallowedTools führen")

# --------------------------------------------------------------------------
# Skills
# --------------------------------------------------------------------------
skill_files = sorted(SKILLS_DIR.glob("*/SKILL.md"))
found_skills = {path.parent.name for path in skill_files}
all_expected_skills = EXPECTED_SKILLS | EXTERNAL_SKILLS
check(found_skills == all_expected_skills,
      f"Skillmenge weicht ab: fehlt {all_expected_skills - found_skills}, "
      f"unerwartet {found_skills - all_expected_skills}")

for path in skill_files:
    fields, body = parse_frontmatter(path)
    dirname = path.parent.name
    check(bool(fields), f"{dirname}: kein auswertbares Frontmatter")
    name_matches = fields.get("name") == dirname
    if not name_matches and dirname in EXTERNAL_SKILLS:
        # Extern übernommene Bundle-Skills behalten den Original-`name` aus
        # dem Quell-Repo; nur der Verzeichnis-Präfix kennzeichnet die Quelle
        # (siehe EXTERNAL-SKILLS.md).
        name_matches = any(dirname == prefix + fields.get("name", "")
                            for prefix in EXTERNAL_BUNDLE_PREFIXES)
    check(name_matches, f"{dirname}: name passt nicht zum Verzeichnis")
    description = fields.get("description", "")
    # disable-model-invocation lädt die description laut Skills-Doku gar
    # nicht erst in den Kontext, damit entfällt dort die Mindestlänge für
    # zuverlässige automatische Aktivierung.
    auto_invocable = fields.get("disable-model-invocation", "").lower() not in (
        "true", "yes", "on", "1")
    if auto_invocable:
        check(len(description) > 80,
              f"{dirname}: description zu knapp für zuverlässige Aktivierung")
    check(len(description) <= 1536,
          f"{path.parent.name}: description überschreitet 1536 Zeichen")
    unknown = set(fields) - ALLOWED_SKILL_KEYS
    check(not unknown, f"{path.parent.name}: unbekannte Frontmatter-Schlüssel {unknown}")
    check(len(body.strip()) > 400, f"{path.parent.name}: Inhalt ist zu dünn")

# --------------------------------------------------------------------------
# settings.json
# --------------------------------------------------------------------------
try:
    settings = json.loads(SETTINGS.read_text(encoding="utf-8"))
except json.JSONDecodeError as error:
    settings = {}
    FAILURES.append(f"settings.json ist kein gültiges JSON: {error}")

hooks = settings.get("hooks", {})
check(bool(hooks), "settings.json enthält keine Hooks")

referenced_scripts: set[Path] = set()
for event, entries in hooks.items():
    check(event in KNOWN_HOOK_EVENTS,
          f"Hook-Ereignis '{event}' ist in dieser Claude-Code-Version nicht belegt")
    for entry in entries:
        for hook in entry.get("hooks", []):
            check(hook.get("type") == "command",
                  f"{event}: unerwarteter Hook-Typ {hook.get('type')}")
            command = hook.get("command", "")
            match = re.search(r'"([^"]+\.py)"', command)
            check(match is not None, f"{event}: Hook-Kommando ohne Skriptpfad: {command}")
            if match:
                script = Path(match.group(1))
                referenced_scripts.add(script)
                check(script.exists(), f"{event}: Hook-Skript fehlt: {script}")

# Jedes Hook-Skript muss kompilieren - ein Syntaxfehler wäre sonst erst im
# Betrieb sichtbar, und zwar als stiller Nicht-Block.
with tempfile.TemporaryDirectory() as cache:
    for script in sorted(HOOKS_DIR.glob("*.py")):
        try:
            py_compile.compile(str(script), cfile=str(Path(cache) / f"{script.stem}.pyc"),
                               doraise=True)
        except py_compile.PyCompileError as error:
            FAILURES.append(f"Hook {script.name} kompiliert nicht: {error}")

# Verwaiste Hook-Skripte finden (außer der gemeinsamen Bibliothek).
orphans = {
    script.name for script in HOOKS_DIR.glob("*.py")
    if script.name != "hooklib.py"
    and not any(script.name == ref.name for ref in referenced_scripts)
    and script.name != "readonly_guard.py"  # wird im Agent-Frontmatter referenziert
}
check(not orphans, f"Hook-Skripte ohne Verdrahtung: {orphans}")

# Berechtigungen: die Kostenpolitik muss durchgesetzt sein.
deny = " ".join(settings.get("permissions", {}).get("deny", []))
for key in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "CODEX_API_KEY"):
    check(key in deny, f"permissions.deny deckt {key} nicht ab")

check(settings.get("permissions", {}).get("defaultMode") == "default",
      "permissions.defaultMode muss 'default' sein")

# --------------------------------------------------------------------------
# AGENTS.md wird von CLAUDE.md eingebunden
# --------------------------------------------------------------------------
claude_md = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
check("@AGENTS.md" in claude_md, "CLAUDE.md bindet AGENTS.md nicht über @AGENTS.md ein")
check(len(claude_md) < 6000, "CLAUDE.md soll kurz bleiben (AGENTS.md Abschnitt 17)")

agents_md = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
for section in ("Risikoklassen", "Task Contract", "Resource Locks",
                "Secrets", "Objective Tests", "Unabhängige Verifikation"):
    check(section in agents_md, f"AGENTS.md fehlt der Abschnitt '{section}'")

# --------------------------------------------------------------------------
print(json.dumps({
    "status": "FAIL" if FAILURES else "PASS",
    "agents": len(agent_files),
    "skills": len(skill_files),
    "hook_events": len(hooks),
    "failures": FAILURES,
}, ensure_ascii=False, indent=2))
sys.exit(1 if FAILURES else 0)
