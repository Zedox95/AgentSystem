"""PreCompact/Stop: preserve an existing structured handoff per session.

No transcript scrape, raw chat storage, automatic fact inference or LLM call.
"""

from __future__ import annotations

import hooklib


def main() -> None:
    data = hooklib.read_input()
    session_id = data.get("session_id")
    if not isinstance(session_id, str) or not session_id.strip():
        hooklib.emit_nothing()
    from agentsys import ledger
    previous = ledger.read_checkpoint(session_id) or {}
    if not previous:
        # The assistant writes meaningful handoffs via assistantctl checkpoint save.
        # The hook does not invent goals from incomplete event payloads.
        hooklib.emit_nothing()
    ledger.write_checkpoint(previous, session_id)
    hooklib.emit_nothing()


hooklib.safe(main)
