---
name: session-checkpoint
description: Save or resume a compact handoff for a long coherent task before compaction, interruption or transfer; keep unrelated tasks in separate sessions sharing managed knowledge.
---

Use the host's actual session ID. Save a JSON object containing the user goal, project, task_id if formal, constraints, decisions, changed files, evidence references, unresolved criteria and next_step. Include enough to resume; omit raw transcripts, secrets and irrelevant history.

From the repository root:
`python bin/assistantctl.py checkpoint save --session-id "<actual ID>" --file "<handoff.json>"`
and resume with checkpoint show and the same --session-id. Never invent or reuse another session's ID. This checkpoint is operational state under ignored state/, not a verified Obsidian fact.

Keep follow-ups in the same coherent task. Start a fresh task session for unrelated work and retrieve only relevant shared knowledge. A central overview may list project status; it does not silently monitor all conversations. Hooks preserve an existing handoff but cannot infer a complete goal from an incomplete event. Run knowledge-review when durable facts emerge.
