"""Deterministische Integrationschecks für das offizielle Codex-Plugin.

Der Test verbraucht kein Modellkontingent. Der reale Rescue- und Transfer-Test
wird beim Installations-/Update-Task separat ausgeführt und im Run Ledger
dokumentiert.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(r"C:\AgentSystem")
USER_SETTINGS = Path.home() / ".claude" / "settings.json"
PROJECT_SETTINGS = ROOT / ".claude" / "settings.json"
BACKUP = ROOT / "backups" / "20260824-2138-codex-plugin-cc-replacement"
CLAUDE = shutil.which("claude.cmd") or shutil.which("claude") or "claude"
CODEX = shutil.which("codex.exe") or shutil.which("codex") or "codex"
FAILURES: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        FAILURES.append(message)


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args), cwd=ROOT, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=60,
    )


settings = json.loads(USER_SETTINGS.read_text(encoding="utf-8"))
project_settings = json.loads(PROJECT_SETTINGS.read_text(encoding="utf-8"))
check(settings.get("env", {}).get("OPENAI_API_KEY") == "" and
      settings.get("env", {}).get("CODEX_API_KEY") == "",
      "OpenAI/Codex-API-Schlüssel sind global nicht neutralisiert")
check("StopFailure" not in settings.get("hooks", {}),
      "Legacy-StopFailure-Hook ist global noch aktiv")
check("StopFailure" not in project_settings.get("hooks", {}),
      "Legacy-StopFailure-Hook ist im AgentSystem-Projekt noch aktiv")
check(settings.get("enabledPlugins", {}).get("codex@openai-codex") is True,
      "codex@openai-codex ist in den Benutzereinstellungen nicht aktiviert")
market = settings.get("extraKnownMarketplaces", {}).get("openai-codex", {})
check(market.get("source", {}).get("repo") == "openai/codex-plugin-cc",
      "offizieller OpenAI-Marketplace fehlt oder zeigt auf eine andere Quelle")

legacy_paths = (
    ROOT / ".claude" / "hooks" / "stop_failure.py",
    ROOT / ".claude" / "skills" / "codex-manual-handoff",
    ROOT / "adapters" / "codex" / "codex_takeover.py",
    ROOT / "adapters" / "codex" / "manual_handoff.py",
    ROOT / "adapters" / "codex" / "takeover-schema.json",
    ROOT / "bin" / "agentsys" / "guarded_exec.py",
    ROOT / "bin" / "agentsys" / "livelog.py",
    ROOT / "tests" / "test_takeover.py",
)
for path in legacy_paths:
    check(not path.exists(), f"Legacy-Komponente noch aktiv: {path}")

listing = run(CLAUDE, "plugin", "list", "--json")
check(listing.returncode == 0, f"claude plugin list fehlgeschlagen: {listing.stderr[-300:]}")
plugins: list[dict] = []
if listing.returncode == 0:
    try:
        plugins = json.loads(listing.stdout)
    except json.JSONDecodeError as exc:
        FAILURES.append(f"Plugin-Liste ist kein JSON: {exc}")

plugin = next((item for item in plugins if item.get("id") == "codex@openai-codex"), None)
check(plugin is not None, "codex@openai-codex ist nicht installiert")
if plugin:
    check(plugin.get("scope") == "user", "Codex-Plugin ist nicht im User-Scope")
    check(plugin.get("projectPath") in (None, ""),
          "User-Scope-Plugin trägt unerwartet einen Projektpfad")
    check(plugin.get("enabled") is True, "Codex-Plugin ist deaktiviert")
    check(plugin.get("version") == "1.0.6", "Plugin-Version weicht vom verifizierten Stand 1.0.6 ab")
    install_path = Path(plugin.get("installPath", ""))
    check((install_path / "commands" / "rescue.md").is_file(), "/codex:rescue fehlt")
    check((install_path / "commands" / "transfer.md").is_file(), "/codex:transfer fehlt")
    companion = install_path / "scripts" / "codex-companion.mjs"
    setup = run("node", str(companion), "setup", "--json", "--disable-review-gate")
    check(setup.returncode == 0, f"Plugin-Setup fehlgeschlagen: {setup.stderr[-300:]}")
    if setup.returncode == 0:
        try:
            setup_data = json.loads(setup.stdout)
            check(setup_data.get("ready") is True, "Plugin-Setup meldet nicht ready")
            check(setup_data.get("reviewGateEnabled") is False, "Review-Gate ist unerwartet aktiv")
            check(setup_data.get("auth", {}).get("authMethod") == "chatgpt",
                  "Codex verwendet nicht die ChatGPT-Anmeldung")
        except json.JSONDecodeError as exc:
            FAILURES.append(f"Setup-Ausgabe ist kein JSON: {exc}")

    runtime = install_path / "scripts" / "lib" / "codex.mjs"
    runtime_text = runtime.read_text(encoding="utf-8") if runtime.is_file() else ""
    check("function normalizeImportPath" in runtime_text,
          "Windows-Transfer-Kompatibilitätsfix fehlt")
    check("candidates.at(-1)" in runtime_text,
          "Live-Transcript-Fallback des Transfer-Fixes fehlt")

login = run(CODEX, "login", "status")
check(login.returncode == 0 and "ChatGPT" in (login.stdout + login.stderr),
      "Codex ist nicht über ChatGPT angemeldet")

check((BACKUP / "sha256-manifest.json").is_file(), "Rollback-Hashmanifest fehlt")
check((BACKUP / "project" / ".claude" / "hooks" / "stop_failure.py").is_file(),
      "Legacy-StopFailure-Hook fehlt im Rollback-Backup")

print(json.dumps({
    "status": "FAIL" if FAILURES else "PASS",
    "checks": 21,
    "failures": FAILURES,
}, ensure_ascii=False, indent=2))
sys.exit(1 if FAILURES else 0)
