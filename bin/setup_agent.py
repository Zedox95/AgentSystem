"""Configure this checkout for its owner. Standard library only, no account login.

All writes are repository-local except explicitly selected new vault directories.
Backups and an optimistic rollback manifest stay in ignored state/.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ".agentsystem.local.json"
BEGIN = "# BEGIN AGENTSYSTEM MANAGED MEMORY"
END = "# END AGENTSYSTEM MANAGED MEMORY"


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def encoded(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        Path(name).replace(path)
    finally:
        Path(name).unlink(missing_ok=True)


def private_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        account = os.environ.get("USERNAME")
        if not account:
            raise ValueError("Cannot determine the Windows account for private setup backups")
        domain = os.environ.get("USERDOMAIN")
        account = f"{domain}\\{account}" if domain else account
        result = subprocess.run(["icacls", str(path), "/inheritance:r", "/grant:r",
                                 f"{account}:(OI)(CI)F"], capture_output=True, timeout=15)
        if result.returncode:
            raise ValueError("Could not restrict setup backup access; no configuration changed")
    else:
        path.chmod(0o700)


def scoped(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    path.relative_to(root.resolve())
    return path


def replace_paths(value: object, old_root: str, root: Path, vault: Path | None) -> object:
    if isinstance(value, str):
        result = value
        for old in {old_root, "C:\\AgentSystem", "C:/AgentSystem"}:
            result = result.replace(old.replace("\\", "/"), root.as_posix()).replace(old, str(root))
        result = result.replace("YOURUSERNAME", Path.home().name)
        if vault:
            result = result.replace(str(Path.home() / "Documents" / "Obsidian Vault"), str(vault))
        return result
    if isinstance(value, list):
        return [replace_paths(item, old_root, root, vault) for item in value]
    if isinstance(value, dict):
        return {key: replace_paths(item, old_root, root, vault) for key, item in value.items()}
    return value


def plans(root: Path, providers: list[str], vault: Path | None, ufo_root: Path | None = None) -> dict[str, bytes]:
    current = json.loads((root / ".claude/settings.json").read_text(encoding="utf-8-sig"))
    prior_profile = root / LOCAL
    prior = json.loads(prior_profile.read_text(encoding="utf-8")) if prior_profile.exists() else {}
    providers = sorted(set(providers) | set(prior.get("providers", [])))
    old_root = current.get("env", {}).get("AGENTSYSTEM_ROOT", "C:\\AgentSystem")
    old_vault = current.get("env", {}).get("AGENTSYSTEM_VAULT") or prior.get("vault")
    result: dict[str, bytes] = {}
    profile = {"schema_version": 1, "root": str(root), "vault": str(vault) if vault else None,
               "providers": sorted(set(providers)), "max_extra_agents": 2}
    result[LOCAL] = encoded(profile)
    if "claude" in providers:
        settings = replace_paths(current, old_root, root, vault)
        if settings.get("permissions", {}).get("defaultMode") != "default":
            raise ValueError("Review the existing Claude permission mode before setup; expected default")
        settings.setdefault("env", {})["AGENTSYSTEM_ROOT"] = str(root)
        if vault:
            settings["env"]["AGENTSYSTEM_VAULT"] = str(vault)
        else:
            settings["env"].pop("AGENTSYSTEM_VAULT", None)
        old_rules = {f"Read({path}/**)".replace("\\", "/") for path in (
            old_vault, str(Path.home() / "Documents" / "Obsidian Vault")) if path}
        allow = settings.setdefault("permissions", {}).setdefault("allow", [])
        own_rule = f"Read({vault}/**)" if vault else None
        own_normalized = own_rule.replace("\\", "/") if own_rule else None
        preserved_allow = []
        own_seen = False
        for rule in allow:
            normalized = rule.replace("\\", "/")
            if normalized in old_rules or normalized == own_normalized:
                if own_rule and not own_seen:
                    preserved_allow.append(own_rule)
                    own_seen = True
            else:
                preserved_allow.append(rule)
        if own_rule and not own_seen:
            preserved_allow.append(own_rule)
        allow[:] = preserved_allow
        result[".claude/settings.json"] = encoded(settings)
        mcp = json.loads((root / ".mcp.json").read_text(encoding="utf-8-sig"))
        mcp = replace_paths(mcp, old_root, root, vault)
        playwright = root / "adapters/playwright/node_modules/@playwright/mcp/cli.js"
        if playwright.is_file() and "playwright" not in mcp.setdefault("mcpServers", {}):
            mcp["mcpServers"]["playwright"] = {"command": "node", "args": [str(playwright),
                "--user-data-dir", str(root / "state/browser-profiles/mcp"),
                "--output-dir", str(root / "logs/playwright-mcp"), "--browser", "chromium",
                "--block-service-workers", "--console-level", "warning"]}
        if ufo_root:
            interpreter = ufo_root / ".venv/Scripts/python.exe"
            if not interpreter.is_file():
                raise ValueError("UFO installation has no .venv/Scripts/python.exe")
            mcp.setdefault("mcpServers", {})["ufo"] = {
                "command": str(interpreter), "args": [str(root / "adapters/ufo/ufo_mcp.py")],
                "env": {"UFO_ROOT": str(ufo_root), "PYTHONUTF8": "1"},
            }
        # Optional tools are retained only when their local installation exists.
        for name in ("ufo", "playwright"):
            spec = mcp.get("mcpServers", {}).get(name)
            if spec:
                arguments = spec.get("args", [])
                script = str(arguments[0]) if arguments else ""
                own_adapter = str(root / f"adapters/{name}").replace("\\", "/")
                owned_optional = script.replace("\\", "/").startswith(own_adapter + "/")
                target = Path(spec["command"]) if name == "ufo" else Path(script)
                if owned_optional and not target.is_file():
                    mcp["mcpServers"].pop(name)
        existing_memory = mcp.get("mcpServers", {}).get("shared-memory")
        if existing_memory and existing_memory.get("args") != [str(root / "adapters/memory/memory_mcp.py")]:
            expected = (root / "adapters/memory/memory_mcp.py").as_posix()
            if [str(item).replace("\\", "/") for item in existing_memory.get("args", [])] != [expected]:
                raise ValueError("Existing shared-memory MCP is not owned by this checkout; preserve it and resolve the name collision")
        if vault:
            mcp.setdefault("mcpServers", {})["shared-memory"] = {
                "command": sys.executable, "args": [str(root / "adapters/memory/memory_mcp.py")],
                "env": {"AGENTSYSTEM_ROOT": str(root), "AGENTSYSTEM_VAULT": str(vault),
                        "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
            }
        else:
            mcp.setdefault("mcpServers", {}).pop("shared-memory", None)
        result[".mcp.json"] = encoded(mcp)
    if "codex" in providers:
        config_path = root / ".codex/config.toml"
        text = config_path.read_text(encoding="utf-8-sig") if config_path.exists() else ""
        if text.count(BEGIN) != text.count(END) or text.count(BEGIN) > 1:
            raise ValueError("Malformed managed Codex configuration markers")
        text = re.sub(re.escape(BEGIN) + r".*?" + re.escape(END) + r"\n?", "", text, flags=re.S)
        parsed = tomllib.loads(text)
        if "agentsystem_memory" in parsed.get("mcp_servers", {}):
            raise ValueError("Existing unowned mcp_servers.agentsystem_memory; rename or configure it manually")
        block = ""
        if vault:
            block = (f"{BEGIN}\n[mcp_servers.agentsystem_memory]\n"
                     f"command = {json.dumps(sys.executable)}\n"
                     f"args = [{json.dumps(str(root / 'adapters/memory/memory_mcp.py'))}]\n"
                     "[mcp_servers.agentsystem_memory.env]\n"
                     f"AGENTSYSTEM_ROOT = {json.dumps(str(root))}\n"
                     f"AGENTSYSTEM_VAULT = {json.dumps(str(vault))}\n"
                     'PYTHONUTF8 = "1"\nPYTHONIOENCODING = "utf-8"\n' + END + "\n")
        config = text.rstrip() + ("\n\n" if text.strip() and block else "") + block
        tomllib.loads(config)
        result[".codex/config.toml"] = config.encode("utf-8")
        hook_path = root / ".codex/hooks.json"
        hooks = json.loads(hook_path.read_text(encoding="utf-8-sig")) if hook_path.exists() else {"hooks": {}}
        adapter = str(root / "adapters/codex/hook.py")
        for event in ("SessionStart", "UserPromptSubmit", "PreToolUse", "PreCompact", "Stop"):
            groups = hooks.setdefault("hooks", {}).setdefault(event, [])
            preserved = []
            for group in groups:
                handlers = [handler for handler in group.get("hooks", []) if
                            "adapters/codex/hook.py" not in str(handler.get("command", "")).replace("\\", "/")]
                if handlers:
                    preserved.append({**group, "hooks": handlers})
            groups[:] = preserved
            handler = {"type": "command", "command": f'"{sys.executable}" "{adapter}"', "timeout": 10}
            group = {"hooks": [handler]}
            if event == "PreToolUse":
                group["matcher"] = "Bash|PowerShell|apply_patch|Write|Edit|NotebookEdit"
            groups.append(group)
        result[".codex/hooks.json"] = encoded(hooks)
        for agent in (root / ".claude/agents").glob("*.md"):
            adapted = replace_paths(agent.read_text(encoding="utf-8"), old_root, root, vault)
            result[agent.relative_to(root).as_posix()] = adapted.encode("utf-8")
            _, header, body = adapted.split("---", 2)
            fields = dict(line.split(":", 1) for line in header.splitlines() if ":" in line and not line.startswith(" "))
            description = fields["description"].strip()
            config = (f"name = {json.dumps(agent.stem)}\ndescription = {json.dumps(description)}\n"
                      f"developer_instructions = {json.dumps(body.strip())}\n")
            # Codex custom-agent sandbox_mode does not override the parent.
            # Read-only is behavioral here; a separate read-only root session is
            # required when an independently enforced boundary is necessary.
            if agent.stem in ("verification-agent", "research-agent"):
                config += '[features]\nrequest_permissions_tool = false\n'
            tomllib.loads(config)
            result[f".codex/agents/{agent.stem}.toml"] = config.encode("utf-8")
        for source in (root / ".claude/skills").rglob("*"):
            if source.is_file():
                relative = source.relative_to(root / ".claude/skills").as_posix()
                result[f".agents/skills/{relative}"] = source.read_bytes()
    # Paths in legacy skill tool allowlists must also match the selected checkout.
    for source in (root / ".claude/skills").glob("*/SKILL.md"):
        text = source.read_text(encoding="utf-8")
        updated = replace_paths(text, old_root, root, vault)
        result[source.relative_to(root).as_posix()] = updated.encode("utf-8")
        if "codex" in providers:
            result[".agents/skills/" + source.relative_to(root / ".claude/skills").as_posix()] = updated.encode("utf-8")
    if "claude" in providers and "codex" not in providers:
        for agent in (root / ".claude/agents").glob("*.md"):
            result[agent.relative_to(root).as_posix()] = replace_paths(
                agent.read_text(encoding="utf-8"), old_root, root, vault).encode("utf-8")
    return result


def install(root: Path, providers: list[str], vault: Path | None, ufo_root: Path | None = None) -> dict:
    root = root.resolve()
    if not set(providers) <= {"claude", "codex", "chatgpt"} or not providers:
        raise ValueError("Choose claude, codex and/or chatgpt")
    if vault:
        vault = vault.resolve()
        if vault.exists() and not vault.is_dir():
            raise ValueError("The vault must be a directory")
    state = scoped(root, "state")
    state.mkdir(exist_ok=True)
    lock_path = state / "setup.lock"
    lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    try:
        os.close(lock_fd)
        desired = plans(root, providers, vault, ufo_root)
        old_manifest = state / "setup-installed.json"
        owned = json.loads(old_manifest.read_text(encoding="utf-8")) if old_manifest.exists() else {}
        changes = {}
        for relative, data in desired.items():
            path = scoped(root, relative)
            previous = path.read_bytes() if path.exists() else None
            if relative.startswith((".agents/", ".codex/agents/")) and previous is not None:
                if previous != data and digest(previous) != owned.get(relative):
                    raise ValueError(f"Preserve manually changed generated file: {relative}")
            if previous != data:
                changes[relative] = {"before": base64.b64encode(previous).decode() if previous is not None else None,
                                     "after_sha256": digest(data)}
        if not changes:
            return {"status": "UNCHANGED", "changed_files": 0, "hooks_active": "not_verified"}
        backup_dir = state / "setup-backups" / uuid.uuid4().hex
        private_directory(backup_dir)
        manifest = backup_dir / "manifest.json"
        installed_bytes = encoded({**owned, **{key: digest(data) for key, data in desired.items()}})
        atomic(manifest, encoded({"schema_version": 1, "root": str(root), "files": changes,
                                 "installed_before": base64.b64encode(old_manifest.read_bytes()).decode() if old_manifest.exists() else None,
                                 "installed_after_sha256": digest(installed_bytes)}))
        written = []
        try:
            for relative in changes:
                target = scoped(root, relative)
                # Optimistic check: no concurrent editor may be overwritten after baseline.
                before = changes[relative]["before"]
                expected = base64.b64decode(before) if before is not None else None
                actual = target.read_bytes() if target.exists() else None
                if actual != expected:
                    raise ValueError(f"Configuration changed concurrently: {relative}")
                atomic(target, desired[relative])
                written.append(relative)
                if target.read_bytes() != desired[relative]:
                    raise ValueError(f"Setup readback failed: {relative}")
            if vault:
                for directory in ("01 Inbox", "03 Bereiche", "04 Ressourcen"):
                    (vault / directory).mkdir(parents=True, exist_ok=True)
            atomic(old_manifest, installed_bytes)
        except Exception:
            for relative in reversed(written):
                target = scoped(root, relative)
                if digest(target.read_bytes()) != changes[relative]["after_sha256"]:
                    continue  # Never overwrite a concurrent user's edit during rollback.
                before = changes[relative]["before"]
                if before is None:
                    target.unlink()
                else:
                    atomic(target, base64.b64decode(before))
            raise
        return {"status": "CONFIGURED", "changed_files": len(changes), "backup": str(manifest),
                "hooks_active": "not_verified", "next": "Review /hooks in Codex; open a trusted new project session; run doctor"}
    finally:
        lock_path.unlink(missing_ok=True)


def _rollback(root: Path, manifest: Path) -> dict:
    manifest = manifest.resolve()
    manifest.relative_to((root / "state/setup-backups").resolve())
    saved = json.loads(manifest.read_text(encoding="utf-8"))
    if saved["root"] != str(root.resolve()):
        raise ValueError("Backup belongs to a different checkout")
    installed = scoped(root, "state/setup-installed.json")
    if not installed.is_file() or digest(installed.read_bytes()) != saved["installed_after_sha256"]:
        raise ValueError("Installation changed since this backup; rollback the most recent setup first")
    for relative, entry in saved["files"].items():
        target = scoped(root, relative)
        if not target.exists() or digest(target.read_bytes()) != entry["after_sha256"]:
            raise ValueError(f"Rollback refused: file changed since setup: {relative}")
    for relative, entry in saved["files"].items():
        target = scoped(root, relative)
        if not target.is_file() or digest(target.read_bytes()) != entry["after_sha256"]:
            raise ValueError(f"Rollback stopped: file changed concurrently: {relative}")
        if entry["before"] is None:
            target.unlink()
        else:
            atomic(target, base64.b64decode(entry["before"]))
    if saved["installed_before"] is None:
        installed.unlink()
    else:
        atomic(installed, base64.b64decode(saved["installed_before"]))
    return {"status": "RESTORED", "files": len(saved["files"])}


def rollback(root: Path, manifest: Path) -> dict:
    lock = scoped(root, "state/setup.lock")
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.close(fd)
    try:
        return _rollback(root, manifest)
    finally:
        lock.unlink(missing_ok=True)


def doctor(root: Path) -> dict:
    profile_path = root / LOCAL
    profile = json.loads(profile_path.read_text(encoding="utf-8")) if profile_path.exists() else {}
    files = root / "state/setup-installed.json"
    manifest = json.loads(files.read_text(encoding="utf-8")) if files.exists() else {}
    changed = [name for name, sha in manifest.items() if not scoped(root, name).is_file()
               or digest(scoped(root, name).read_bytes()) != sha]
    return {"status": "PASS" if profile and not changed else "INCONCLUSIVE",
            "configured": bool(profile), "changed_generated_files": changed,
            "providers": profile.get("providers", []),
            "vault_exists": bool(profile.get("vault") and Path(profile["vault"]).is_dir()),
            "commands": {name: bool(shutil.which(name)) for name in ("python", "codex", "claude")},
            "hooks_active": "not_verified", "chatgpt_connection": "requires_separate_connection_test"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["install", "doctor", "rollback"])
    parser.add_argument("--provider", action="append", choices=["claude", "codex", "chatgpt"])
    parser.add_argument("--vault", type=Path)
    parser.add_argument("--backup", type=Path)
    parser.add_argument("--ufo-root", type=Path)
    parser.add_argument("--skip-vault", action="store_true")
    args = parser.parse_args()
    try:
        if args.action == "doctor":
            result = doctor(ROOT)
        elif args.action == "rollback":
            if not args.backup:
                raise ValueError("rollback requires --backup")
            result = rollback(ROOT, args.backup)
        else:
            profile_path = ROOT / LOCAL
            profile = json.loads(profile_path.read_text(encoding="utf-8")) if profile_path.exists() else {}
            vault = None if args.skip_vault else args.vault or (Path(profile["vault"]) if profile.get("vault") else None)
            result = install(ROOT, args.provider or profile.get("providers") or ["claude", "codex", "chatgpt"], vault, args.ufo_root)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["status"] != "INCONCLUSIVE" else 1
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        print(json.dumps({"status": "FAIL", "error": str(error)}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
