"""Deterministic policy guard.

No AI model is the sole security boundary. This module decides, rule-based
and without a model call, whether a tool use is allowed, escalated to a
follow-up question, or denied.

Design principles:

* Conservative. When in doubt, ASK instead of ALLOW; DENY only for clearly
  destructive, hard-to-reverse patterns.
* Traceable. Every decision names the rule that triggered it.
* No network and no side effects, so it runs reliably in a hook with a
  tight time budget.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from . import paths

ALLOW = "allow"
ASK = "escalate"
DENY = "deny"


@dataclass(frozen=True)
class Decision:
    verdict: str
    rule: str
    reason: str


@dataclass(frozen=True)
class Rule:
    name: str
    pattern: re.Pattern[str]
    verdict: str
    reason: str


def _rule(name: str, pattern: str, verdict: str, reason: str) -> Rule:
    return Rule(name, re.compile(pattern, re.IGNORECASE), verdict, reason)


# --------------------------------------------------------------------------
# DENY: destructive and practically irreversible. These actions belong to
# the user, not to an agent.
# --------------------------------------------------------------------------
DENY_RULES: tuple[Rule, ...] = (
    _rule("disk-format",
          r"\b(format-volume|format\s+[a-z]:|mkfs(\.\w+)?|diskpart\b.*\bclean\b)",
          DENY, "Formatting or wiping a disk"),
    _rule("partition-write",
          r"\b(clear-disk|initialize-disk|set-partition|remove-partition|sgdisk|fdisk\s+/dev/|parted\s+/dev/)",
          DENY, "Write access to partition tables"),
    _rule("raw-device-write",
          r"\bdd\b[^\n]*\bof=/dev/(sd|nvme|hd|vd)",
          DENY, "Raw write access to a block device"),
    _rule("bootloader",
          r"\b(bcdedit\s+/(delete|deletevalue|set)|bootrec\s+/|grub-install|efibootmgr\s+-(B|b\b.*-B))",
          DENY, "Change to the bootloader or boot configuration"),
    _rule("firmware",
          r"\b(flashrom|afudos|fptw(64)?|nvflash|--flash-bios)\b",
          DENY, "Firmware or BIOS flash"),
    _rule("recursive-root-delete",
          r"\brm\b[^\n]*\s-[a-z]*[rR][a-z]*f?[^\n]*\s+(/|/\*|~|~/\*|\$HOME)\s*$",
          DENY, "Recursive deletion of a root or home directory"),
    _rule("windows-root-delete",
          r"remove-item[^\n]*-recurse[^\n]*\b([a-z]:\\?\s*$|[a-z]:\\(windows|users|program files)\b)",
          DENY, "Recursive deletion of a system directory"),
    _rule("recycle-empty",
          r"\b(clear-recyclebin|rd\s+/s\s+/q\s+[a-z]:\\\$recycle)",
          DENY, "Permanently emptying the recycle bin"),
    _rule("db-drop",
          r"\bdrop\s+(database|schema)\b",
          DENY, "Deleting a database"),
    # No trailing \b: arguments like "HEAD~5" don't end on a word boundary,
    # which would make the rule never match.
    _rule("git-destructive",
          r"\bgit\b[^\n]*?\s(?:push[^\n]*--force(?!-with-lease)|reset\s+--hard|"
          r"clean\s+-[a-z]*f[a-z]*d\b|branch\s+-D\b)",
          DENY, "Destructive Git operation with risk of data loss"),
    _rule("ssh-key-delete",
          r"\b(rm|remove-item|del)\b[^\n]*\.ssh[\\/](id_\w+|authorized_keys)",
          DENY, "Deleting SSH keys or authorized_keys"),
    _rule("account-delete",
          r"\b(remove-localuser|net\s+user\s+\S+\s+/delete|userdel\b|deluser\b)",
          DENY, "Deleting a user account"),
    _rule("proxmox-destroy",
          r"\b(qm|pct)\s+destroy\b",
          DENY, "Destroying a Proxmox VM or container"),
    _rule("permission-wipe",
          r"\b(icacls[^\n]*/reset[^\n]*/t|chmod\s+-R\s+777\s+/|takeown[^\n]*/f\s+[a-z]:\\\s*$)",
          DENY, "Blanket permission change across a broad scope"),
    _rule("llm-api-key",
          r"\b(setx|set-item\s+env:|export)\b[^\n]*\b(ANTHROPIC_API_KEY|OPENAI_API_KEY|CODEX_API_KEY)\b\s*=?\s*\S",
          DENY, "Setting a paid LLM API key is forbidden by the cost policy"),
    _rule("skip-permissions",
          r"--dangerously-skip-permissions|--yolo\b|danger-full-access",
          DENY, "Bypassing the permission check"),
)

# --------------------------------------------------------------------------
# ASK: legitimate, but R2 and above - the user decides.
# --------------------------------------------------------------------------
ASK_RULES: tuple[Rule, ...] = (
    _rule("service-write",
          r"\b(stop-service|set-service|restart-service|remove-service|sc\.exe\s+(config|delete|stop)|systemctl\s+(stop|disable|mask))\b",
          ASK, "Change to a system service"),
    _rule("registry-write",
          r"\b(set-itemproperty|new-itemproperty|remove-itemproperty|remove-item)\b[^\n]*\bhk(lm|cu|cr|u|cc):",
          ASK, "Write access to the registry"),
    _rule("reg-exe-write",
          r"\breg(\.exe)?\s+(add|delete|import)\b",
          ASK, "Write access to the registry via reg.exe"),
    _rule("driver-change",
          r"\b(pnputil[^\n]*/(add|delete)-driver|devcon\s+(remove|update)|install-windowsdriver)\b",
          ASK, "Driver installation or removal"),
    _rule("firewall-change",
          r"\b(new-netfirewallrule|set-netfirewallrule|remove-netfirewallrule|netsh\s+advfirewall|ufw\s+(allow|deny|delete)|iptables\s+-[AIDF])\b",
          ASK, "Firewall change"),
    _rule("network-change",
          r"\b(new-netipaddress|set-netipaddress|set-dnsclientserveraddress|netsh\s+interface|ip\s+(addr|route)\s+(add|del))\b",
          ASK, "Network configuration change"),
    _rule("package-install",
          r"\b(winget\s+(install|uninstall)|choco\s+(install|uninstall)|apt(-get)?\s+(install|remove|purge)|dnf\s+(install|remove)|pacman\s+-(S|R))\b",
          ASK, "Package installation or removal"),
    _rule("pip-npm-global",
          r"\b(pip\s+install[^\n]*(--user|\s-U|\s--upgrade)|npm\s+(install|i)\s+-g|npm\s+uninstall\s+-g)\b",
          ASK, "Global package change"),
    _rule("scheduled-task",
          r"\b(register-scheduledtask|schtasks\s+/(create|delete|change)|crontab\s+-)\b",
          ASK, "Change to scheduled tasks"),
    _rule("shutdown",
          r"\b(restart-computer|stop-computer|shutdown(\.exe)?\s+/|\breboot\b|systemctl\s+(reboot|poweroff))\b",
          ASK, "Restart or shutdown"),
    _rule("elevation",
          r"-verb\s+runas|start-process[^\n]*-verb\s+runas|\bsudo\b",
          ASK, "Execution with elevated privileges"),
    _rule("recursive-delete",
          r"\b(remove-item[^\n]*-recurse|rm\b[^\n]*\s-[a-z]*r|rd\s+/s|rmdir\s+/s)\b",
          ASK, "Recursive deletion"),
    _rule("docker-destructive",
          r"\bdocker\b[^\n]*\b(system\s+prune|volume\s+rm|rm\s+-f)\b",
          ASK, "Docker operation with risk of data loss"),
    _rule("proxmox-write",
          r"\b(qm|pct)\s+(set|stop|shutdown|rollback|delsnapshot|migrate)\b",
          ASK, "Write-capable Proxmox operation"),
    _rule("router-write",
          r"\b(tr-?064|/cgi-bin/|upnp)\b[^\n]*\b(set|configure|reboot)\b",
          ASK, "Write access to the router"),
    _rule("env-persist",
          r"\b(setx\b|\[environment\]::setenvironmentvariable)",
          ASK, "Permanent change to an environment variable"),
    _rule("bulk-download-exec",
          r"(curl|wget|invoke-webrequest|iwr)\b[^\n]*\|\s*(bash|sh|iex|invoke-expression)",
          ASK, "Downloading and directly executing code"),
)

# --------------------------------------------------------------------------
# ALLOW: known, clearly read-only commands. Only exact command prefixes, so
# no chained write command can slip through.
# --------------------------------------------------------------------------
READONLY_PREFIXES: tuple[str, ...] = (
    "git status", "git diff", "git log", "git show", "git branch", "git remote",
    "git rev-parse", "git describe", "git ls-files", "git config --get",
    "get-service", "get-process", "get-childitem", "get-content", "get-item",
    "get-itemproperty", "get-ciminstance", "get-wmiobject", "get-command",
    "get-module", "get-netadapter", "get-netipaddress", "get-nettcpconnection",
    "get-netroute", "get-netfirewallrule", "get-scheduledtask", "get-eventlog",
    "get-winevent", "get-psdrive", "get-volume", "get-disk", "get-pnpdevice",
    "get-hotfix", "get-localuser", "get-acl", "get-filehash", "get-date",
    "test-path", "test-connection", "test-netconnection", "resolve-dnsname",
    "systemctl status", "systemctl is-active", "systemctl is-enabled",
    "journalctl", "docker ps", "docker images", "docker inspect", "docker logs",
    "ls", "ll", "dir", "cat", "head", "tail", "wc", "find", "grep", "rg",
    "which", "where", "echo", "pwd", "df", "du", "free", "uname", "hostname",
    "whoami", "date", "ping", "tracert", "traceroute", "nslookup", "ipconfig",
    "ifconfig", "netstat", "ss ", "ps ", "top -b", "uptime", "lsblk", "mount",
    "python --version", "node --version", "npm --version", "pip list",
    "qm list", "qm config", "qm status", "pct list", "pct config", "pct status",
)

# Characters that chain several commands. As soon as one occurs, the
# allowlist no longer applies - otherwise "git status; rm -rf /" would be allowed.
CHAIN_PATTERN = re.compile(r"[;&|`]|\$\(|\n|&&|\|\|")


def _command_text(tool_name: str, tool_input: dict[str, Any]) -> str:
    """Extracts the text to be evaluated from the tool input."""
    if tool_name in ("Bash", "PowerShell"):
        return str(tool_input.get("command", ""))
    if tool_name in ("Write", "Edit", "NotebookEdit"):
        return str(tool_input.get("file_path", ""))
    return ""


def is_readonly_command(command: str) -> bool:
    """True only for clearly read-only, unchained single commands."""
    text = command.strip()
    if not text or CHAIN_PATTERN.search(text):
        return False
    if ">" in text or "<" in text:  # Input or output redirection writes.
        return False
    lowered = text.lower()
    return any(lowered.startswith(prefix) for prefix in READONLY_PREFIXES)


def evaluate(tool_name: str, tool_input: dict[str, Any]) -> Decision:
    """Evaluates a planned tool use."""
    # Write access to the control plane always requires a follow-up question.
    if tool_name in ("Write", "Edit", "NotebookEdit"):
        target = str(tool_input.get("file_path", ""))
        if target and paths.is_vault_path(target):
            return Decision(
                DENY, "vault-direct-write",
                "Direct write access to the Obsidian vault is blocked; "
                "productive facts go through the Knowledge Candidate and Archivist path",
            )
        if target and paths.is_control_plane(target):
            return Decision(
                ASK, "control-plane-write",
                "Write access to the protected control plane "
                "(settings.json, hooks, agentsys, AGENTS.md)",
            )
        return Decision(ALLOW, "default", "File change outside the control plane")

    command = _command_text(tool_name, tool_input)
    if not command:
        return Decision(ALLOW, "default", "No evaluable command")

    for rule in DENY_RULES:
        if rule.pattern.search(command):
            return Decision(DENY, rule.name, rule.reason)

    for rule in ASK_RULES:
        if rule.pattern.search(command):
            return Decision(ASK, rule.name, rule.reason)

    if is_readonly_command(command):
        return Decision(ALLOW, "readonly-allowlist", "Known read-only command")

    return Decision(ALLOW, "default", "No rule matched")
