"""Deterministischer Policy Guard.

Kein KI-Modell ist die einzige Sicherheitsgrenze. Dieses Modul entscheidet
regelbasiert und ohne Modellaufruf, ob eine Werkzeugnutzung erlaubt, zur
Rückfrage eskaliert oder verweigert wird.

Entwurfsprinzipien:

* Konservativ. Im Zweifel ASK statt ALLOW, DENY nur bei eindeutig
  destruktiven, schwer umkehrbaren Mustern.
* Nachvollziehbar. Jede Entscheidung nennt die Regel, die sie ausgelöst hat.
* Ohne Netzwerk und ohne Seiteneffekte, damit sie in einem Hook mit engem
  Zeitbudget zuverlässig läuft.
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
# DENY: destruktiv und praktisch nicht umkehrbar. Diese Aktionen gehören dem
# Benutzer, nicht einem Agenten.
# --------------------------------------------------------------------------
DENY_RULES: tuple[Rule, ...] = (
    _rule("disk-format",
          r"\b(format-volume|format\s+[a-z]:|mkfs(\.\w+)?|diskpart\b.*\bclean\b)",
          DENY, "Formatieren oder Bereinigen eines Datenträgers"),
    _rule("partition-write",
          r"\b(clear-disk|initialize-disk|set-partition|remove-partition|sgdisk|fdisk\s+/dev/|parted\s+/dev/)",
          DENY, "Schreibender Zugriff auf Partitionstabellen"),
    _rule("raw-device-write",
          r"\bdd\b[^\n]*\bof=/dev/(sd|nvme|hd|vd)",
          DENY, "Rohschreibzugriff auf ein Blockgerät"),
    _rule("bootloader",
          r"\b(bcdedit\s+/(delete|deletevalue|set)|bootrec\s+/|grub-install|efibootmgr\s+-(B|b\b.*-B))",
          DENY, "Änderung an Bootloader oder Bootkonfiguration"),
    _rule("firmware",
          r"\b(flashrom|afudos|fptw(64)?|nvflash|--flash-bios)\b",
          DENY, "Firmware- oder BIOS-Flash"),
    _rule("recursive-root-delete",
          r"\brm\b[^\n]*\s-[a-z]*[rR][a-z]*f?[^\n]*\s+(/|/\*|~|~/\*|\$HOME)\s*$",
          DENY, "Rekursives Löschen eines Wurzel- oder Home-Verzeichnisses"),
    _rule("windows-root-delete",
          r"remove-item[^\n]*-recurse[^\n]*\b([a-z]:\\?\s*$|[a-z]:\\(windows|users|program files)\b)",
          DENY, "Rekursives Löschen eines Systemverzeichnisses"),
    _rule("recycle-empty",
          r"\b(clear-recyclebin|rd\s+/s\s+/q\s+[a-z]:\\\$recycle)",
          DENY, "Endgültiges Leeren des Papierkorbs"),
    _rule("db-drop",
          r"\bdrop\s+(database|schema)\b",
          DENY, "Löschen einer Datenbank"),
    # Kein abschließendes \b: Argumente wie "HEAD~5" enden nicht auf einer
    # Wortgrenze, das ließe die Regel ins Leere laufen.
    _rule("git-destructive",
          r"\bgit\b[^\n]*?\s(?:push[^\n]*--force(?!-with-lease)|reset\s+--hard|"
          r"clean\s+-[a-z]*f[a-z]*d\b|branch\s+-D\b)",
          DENY, "Destruktive Git-Operation mit Verlustrisiko"),
    _rule("ssh-key-delete",
          r"\b(rm|remove-item|del)\b[^\n]*\.ssh[\\/](id_\w+|authorized_keys)",
          DENY, "Löschen von SSH-Schlüsseln oder authorized_keys"),
    _rule("account-delete",
          r"\b(remove-localuser|net\s+user\s+\S+\s+/delete|userdel\b|deluser\b)",
          DENY, "Löschen eines Benutzerkontos"),
    _rule("proxmox-destroy",
          r"\b(qm|pct)\s+destroy\b",
          DENY, "Zerstören einer Proxmox-VM oder eines Containers"),
    _rule("permission-wipe",
          r"\b(icacls[^\n]*/reset[^\n]*/t|chmod\s+-R\s+777\s+/|takeown[^\n]*/f\s+[a-z]:\\\s*$)",
          DENY, "Pauschale Rechteänderung auf breiter Ebene"),
    _rule("llm-api-key",
          r"\b(setx|set-item\s+env:|export)\b[^\n]*\b(ANTHROPIC_API_KEY|OPENAI_API_KEY|CODEX_API_KEY)\b\s*=?\s*\S",
          DENY, "Setzen eines kostenpflichtigen LLM-API-Keys ist durch die Kostenpolitik untersagt"),
    _rule("skip-permissions",
          r"--dangerously-skip-permissions|--yolo\b|danger-full-access",
          DENY, "Umgehung der Berechtigungsprüfung"),
)

# --------------------------------------------------------------------------
# ASK: legitim, aber ab R2 - der Benutzer entscheidet.
# --------------------------------------------------------------------------
ASK_RULES: tuple[Rule, ...] = (
    _rule("service-write",
          r"\b(stop-service|set-service|restart-service|remove-service|sc\.exe\s+(config|delete|stop)|systemctl\s+(stop|disable|mask))\b",
          ASK, "Änderung an einem Systemdienst"),
    _rule("registry-write",
          r"\b(set-itemproperty|new-itemproperty|remove-itemproperty|remove-item)\b[^\n]*\bhk(lm|cu|cr|u|cc):",
          ASK, "Schreibender Registry-Zugriff"),
    _rule("reg-exe-write",
          r"\breg(\.exe)?\s+(add|delete|import)\b",
          ASK, "Schreibender Registry-Zugriff über reg.exe"),
    _rule("driver-change",
          r"\b(pnputil[^\n]*/(add|delete)-driver|devcon\s+(remove|update)|install-windowsdriver)\b",
          ASK, "Treiberinstallation oder -entfernung"),
    _rule("firewall-change",
          r"\b(new-netfirewallrule|set-netfirewallrule|remove-netfirewallrule|netsh\s+advfirewall|ufw\s+(allow|deny|delete)|iptables\s+-[AIDF])\b",
          ASK, "Firewall-Änderung"),
    _rule("network-change",
          r"\b(new-netipaddress|set-netipaddress|set-dnsclientserveraddress|netsh\s+interface|ip\s+(addr|route)\s+(add|del))\b",
          ASK, "Änderung der Netzwerkkonfiguration"),
    _rule("package-install",
          r"\b(winget\s+(install|uninstall)|choco\s+(install|uninstall)|apt(-get)?\s+(install|remove|purge)|dnf\s+(install|remove)|pacman\s+-(S|R))\b",
          ASK, "Paketinstallation oder -entfernung"),
    _rule("pip-npm-global",
          r"\b(pip\s+install[^\n]*(--user|\s-U|\s--upgrade)|npm\s+(install|i)\s+-g|npm\s+uninstall\s+-g)\b",
          ASK, "Globale Paketänderung"),
    _rule("scheduled-task",
          r"\b(register-scheduledtask|schtasks\s+/(create|delete|change)|crontab\s+-)\b",
          ASK, "Änderung an geplanten Aufgaben"),
    _rule("shutdown",
          r"\b(restart-computer|stop-computer|shutdown(\.exe)?\s+/|\breboot\b|systemctl\s+(reboot|poweroff))\b",
          ASK, "Neustart oder Herunterfahren"),
    _rule("elevation",
          r"-verb\s+runas|start-process[^\n]*-verb\s+runas|\bsudo\b",
          ASK, "Ausführung mit erhöhten Rechten"),
    _rule("recursive-delete",
          r"\b(remove-item[^\n]*-recurse|rm\b[^\n]*\s-[a-z]*r|rd\s+/s|rmdir\s+/s)\b",
          ASK, "Rekursives Löschen"),
    _rule("docker-destructive",
          r"\bdocker\b[^\n]*\b(system\s+prune|volume\s+rm|rm\s+-f)\b",
          ASK, "Docker-Operation mit Datenverlustrisiko"),
    _rule("proxmox-write",
          r"\b(qm|pct)\s+(set|stop|shutdown|rollback|delsnapshot|migrate)\b",
          ASK, "Schreibende Proxmox-Operation"),
    _rule("router-write",
          r"\b(tr-?064|/cgi-bin/|upnp)\b[^\n]*\b(set|configure|reboot)\b",
          ASK, "Schreibender Zugriff auf den Router"),
    _rule("env-persist",
          r"\b(setx\b|\[environment\]::setenvironmentvariable)",
          ASK, "Dauerhafte Änderung einer Umgebungsvariable"),
    _rule("bulk-download-exec",
          r"(curl|wget|invoke-webrequest|iwr)\b[^\n]*\|\s*(bash|sh|iex|invoke-expression)",
          ASK, "Herunterladen und direktes Ausführen von Code"),
)

# --------------------------------------------------------------------------
# ALLOW: bekannte, eindeutig lesende Kommandos. Nur exakte Kommandoanfänge,
# damit kein verketteter Schreibbefehl mitrutscht.
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

# Zeichen, die mehrere Kommandos verketten. Sobald eines vorkommt, greift die
# Allowlist nicht mehr - sonst wäre "git status; rm -rf /" erlaubt.
CHAIN_PATTERN = re.compile(r"[;&|`]|\$\(|\n|&&|\|\|")


def _command_text(tool_name: str, tool_input: dict[str, Any]) -> str:
    """Extrahiert den auszuwertenden Text aus der Werkzeugeingabe."""
    if tool_name in ("Bash", "PowerShell"):
        return str(tool_input.get("command", ""))
    if tool_name in ("Write", "Edit", "NotebookEdit"):
        return str(tool_input.get("file_path", ""))
    return ""


def is_readonly_command(command: str) -> bool:
    """True nur für eindeutig lesende, unverkettete Einzelkommandos."""
    text = command.strip()
    if not text or CHAIN_PATTERN.search(text):
        return False
    if ">" in text or "<" in text:  # Ein- oder Ausgabeumleitung schreibt.
        return False
    lowered = text.lower()
    return any(lowered.startswith(prefix) for prefix in READONLY_PREFIXES)


def evaluate(tool_name: str, tool_input: dict[str, Any]) -> Decision:
    """Bewertet eine geplante Werkzeugnutzung."""
    # Schreibzugriff auf die Control Plane erfordert immer eine Rückfrage.
    if tool_name in ("Write", "Edit", "NotebookEdit"):
        target = str(tool_input.get("file_path", ""))
        if target and paths.is_vault_path(target):
            return Decision(
                DENY, "vault-direct-write",
                "Direkter Schreibzugriff auf den Obsidian-Vault ist gesperrt; "
                "produktive Fakten laufen über Knowledge Candidate und Archivist",
            )
        if target and paths.is_control_plane(target):
            return Decision(
                ASK, "control-plane-write",
                "Schreibzugriff auf die geschützte Control Plane "
                "(settings.json, hooks, agentsys, AGENTS.md)",
            )
        return Decision(ALLOW, "default", "Dateiänderung außerhalb der Control Plane")

    command = _command_text(tool_name, tool_input)
    if not command:
        return Decision(ALLOW, "default", "Kein auswertbares Kommando")

    for rule in DENY_RULES:
        if rule.pattern.search(command):
            return Decision(DENY, rule.name, rule.reason)

    for rule in ASK_RULES:
        if rule.pattern.search(command):
            return Decision(ASK, rule.name, rule.reason)

    if is_readonly_command(command):
        return Decision(ALLOW, "readonly-allowlist", "Bekanntes lesendes Kommando")

    return Decision(ALLOW, "default", "Keine Regel getroffen")
