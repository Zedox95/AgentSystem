---
name: obsidian-context
description: Retrieve relevant managed Obsidian facts when prior preferences, project decisions or system history can materially change the current answer or action.
---

Use the configured memory tools if connected. Otherwise use the repository's context CLI from its root:
`python bin/assistantctl.py context --query "<narrow question>" --project "<optional project>" --budget 2000`.
Omit --project when the project is unknown.

Read only the relevant managed facts; do not dump a whole vault or private notes. Preserve source_path, source_sha256, status and last_verified. A stored fact is historical evidence, not proof that software, configuration or hardware still matches it. Resolve important stale information against current evidence.

When memory is unavailable, state that limitation and continue with the available facts if safe. Never invent remembered details or claim continuous access. Imported memory starts pending review. Shared knowledge belongs to this user's configured vault; sessions share useful facts but keep their checkpoints separate.
