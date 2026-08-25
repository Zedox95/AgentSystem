"""ConfigChange — Control Plane schützen.

Änderungen an Hooks, Berechtigungen und Skill-Konfiguration werden nicht
beiläufig durchgelassen. Sie gehören in den regulären Wartungsablauf mit
Baseline, Backup, Regression und Verifikation (AGENTS.md Abschnitt 22).

Exit 2 blockiert die Änderung — außer bei `policy_settings`, die laut
Dokumentation nicht blockierbar sind; dort wird nur protokolliert.
"""

from __future__ import annotations

import hooklib

# Schlüssel, deren Änderung die Sicherheitsgrenze verschiebt.
PROTECTED_KEYS = (
    "hooks",
    "permissions",
    "permissions.allow",
    "permissions.deny",
    "permissions.ask",
    "permissions.defaultMode",
    "disableAllHooks",
    "enableAllProjectMcpServers",
    "apiKeyHelper",
    "awsAuthRefresh",
    "env",
)


def main() -> None:
    data = hooklib.read_input()
    source = str(data.get("config_source", ""))
    key = str(data.get("config_key", ""))

    from agentsys import ledger

    protected = any(key == k or key.startswith(f"{k}.") for k in PROTECTED_KEYS)

    ledger.log_event(
        "CONFIG_CHANGE",
        session_id=data.get("session_id"),
        detail={
            "source": source,
            "key": key,
            "protected": protected,
            "new_value": str(data.get("new_value"))[:300],
        },
    )

    if protected and source != "policy_settings":
        hooklib.block(
            f"ConfigChange blockiert: '{key}' gehört zur Control Plane. "
            "Änderungen an Hooks, Berechtigungen oder Umgebungsvariablen laufen "
            "über den Wartungsablauf — Baseline, Backup, Änderung, Regression, "
            "Verifikation, Commit. Wenn das beabsichtigt ist, den Vorgang "
            "ausdrücklich als solchen starten."
        )

    hooklib.emit_nothing()


hooklib.safe(main)
