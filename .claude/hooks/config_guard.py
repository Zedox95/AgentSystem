"""ConfigChange — protect the control plane.

Changes to hooks, permissions, and skill configuration are not passed
through casually. They belong in the regular maintenance workflow with
baseline, backup, regression, and verification (AGENTS.md section 22).

Exit 2 blocks the change — except for `policy_settings`, which per the
documentation cannot be blocked; those are only logged.
"""

from __future__ import annotations

import hooklib

# Keys whose change would shift the security boundary.
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
            f"ConfigChange blocked: '{key}' belongs to the control plane. "
            "Changes to hooks, permissions, or environment variables go "
            "through the maintenance workflow — baseline, backup, change, "
            "regression, verification, commit. If this is intentional, "
            "start the process explicitly as such."
        )

    hooklib.emit_nothing()


hooklib.safe(main)
