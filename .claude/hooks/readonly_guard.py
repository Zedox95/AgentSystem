"""PreToolUse for the verification-agent — enforces read-only.

The verifier must never repair anything. Tool restrictions in the frontmatter
cover Write and Edit, but a shell can also write. This hook is the technical
boundary for that.

Only what is on the allowlist of `agentsys.policy`, or what clearly triggers
no mutation, is allowed. Everything else is denied — with a note that the
correct result is then INCONCLUSIVE.
"""

from __future__ import annotations

import re

import hooklib

# Additional clearly read-only patterns that go beyond the general
# allowlist and are needed for verification.
EXTRA_READONLY = re.compile(
    r"^\s*(?:"
    r"curl\s+(?:-[sSILkm]\S*\s+)*(?:-X\s+(?:GET|HEAD)\s+)?https?://"
    r"|invoke-restmethod\b(?![^\n]*-method\s+(?:post|put|patch|delete))"
    r"|invoke-webrequest\b(?![^\n]*-method\s+(?:post|put|patch|delete))"
    r"|python\s+-c\s+"
    r"|type\s+"
    r"|more\s+"
    r"|sort\s+"
    r"|diff\s+"
    r"|md5sum|sha256sum|certutil\s+-hashfile"
    r"|select-string\b"
    r"|measure-object\b"
    r"|compare-object\b"
    r"|nmap\s+-sn"
    r")",
    re.IGNORECASE,
)

# Clearly mutating verbs that are never let through.
MUTATING = re.compile(
    r"\b(?:set-|new-|remove-|clear-|stop-|start-|restart-|install-|uninstall-"
    r"|register-|unregister-|enable-|disable-|rename-|move-|copy-|out-file"
    r"|add-content|set-content|mkdir|rm\b|del\b|erase\b|mv\b|cp\b|touch\b"
    r"|chmod\b|chown\b|systemctl\s+(?:start|stop|restart|enable|disable)"
    r"|docker\s+(?:run|rm|stop|start|exec)|apt|winget|npm\s+i|pip\s+install"
    r"|git\s+(?:add|commit|push|merge|rebase|checkout|reset|clean|stash))\b",
    re.IGNORECASE,
)

REDIRECT = re.compile(r"(?<![0-9])>{1,2}(?!&)|\btee\b")


def main() -> None:
    data = hooklib.read_input()
    command = str((data.get("tool_input") or {}).get("command", "")).strip()

    if not command:
        hooklib.emit_nothing()

    from agentsys import policy

    # The general policy guard takes precedence: what is forbidden there stays forbidden.
    decision = policy.evaluate(data.get("tool_name", ""), data.get("tool_input") or {})
    if decision.verdict == policy.DENY:
        hooklib.pre_tool_decision(
            "deny", f"Policy Guard: {decision.reason} (rule: {decision.rule})"
        )

    if REDIRECT.search(command) or MUTATING.search(command):
        _deny(command, "contains a mutating command or output redirection")

    if policy.is_readonly_command(command) or EXTRA_READONLY.match(command):
        hooklib.pre_tool_decision("allow", "Read-only check (verification-agent)")

    _deny(command, "is not on the verifier's read-only allowlist")


def _deny(command: str, why: str) -> None:
    hooklib.pre_tool_decision(
        "deny",
        f"The verification-agent is strictly read-only. The command {why}. "
        "If a check is not possible without a change, the correct "
        "result is INCONCLUSIVE naming the missing check — not PASS.",
    )


hooklib.safe(main)
