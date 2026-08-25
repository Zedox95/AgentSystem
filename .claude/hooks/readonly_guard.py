"""PreToolUse für den verification-agent — erzwingt Read-only.

Der Verifier darf niemals reparieren. Werkzeugbeschränkungen im Frontmatter
decken Write und Edit ab, aber eine Shell kann ebenfalls schreiben. Dieser
Hook ist die technische Grenze dafür.

Zugelassen wird nur, was in der Allowlist von `agentsys.policy` steht oder
eindeutig keine Mutation auslöst. Alles andere wird verweigert — mit einem
Hinweis, dass das korrekte Ergebnis dann INCONCLUSIVE lautet.
"""

from __future__ import annotations

import re

import hooklib

# Zusätzliche eindeutig lesende Muster, die über die allgemeine Allowlist
# hinausgehen und für Verifikation gebraucht werden.
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

# Eindeutig mutierende Verben, die nie durchgelassen werden.
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

    # Der allgemeine Policy Guard hat Vorrang: was dort verboten ist, bleibt es.
    decision = policy.evaluate(data.get("tool_name", ""), data.get("tool_input") or {})
    if decision.verdict == policy.DENY:
        hooklib.pre_tool_decision(
            "deny", f"Policy Guard: {decision.reason} (Regel: {decision.rule})"
        )

    if REDIRECT.search(command) or MUTATING.search(command):
        _deny(command, "enthält ein mutierendes Kommando oder eine Ausgabeumleitung")

    if policy.is_readonly_command(command) or EXTRA_READONLY.match(command):
        hooklib.pre_tool_decision("allow", "Lesende Prüfung (verification-agent)")

    _deny(command, "steht nicht auf der Read-only-Allowlist des Verifiers")


def _deny(command: str, why: str) -> None:
    hooklib.pre_tool_decision(
        "deny",
        f"Der verification-agent ist strikt read-only. Das Kommando {why}. "
        "Wenn eine Prüfung ohne Änderung nicht möglich ist, lautet das korrekte "
        "Ergebnis INCONCLUSIVE mit Angabe der fehlenden Prüfung — nicht PASS.",
    )


hooklib.safe(main)
