---
name: knowledge-review
description: Automatically checks before COMMITTED whether a completed AgentSystem task produced durably relevant knowledge for the managed Obsidian vault, deduplicates it via the existing entity search, and records a decision of either captured, deferred, or none. Run for every formal task contract after objective tests and a verifier PASS; the commit gate blocks without this check.
allowed-tools: Bash(python C:\AgentSystem\bin\agentctl.py *), Read, Grep, Glob, Write
---

# Knowledge review before commit

This check is semantic: the hook enforces **that** it happens; you decide
from the evidence **what** is durably relevant. Never write directly to the
vault. Use only knowledge candidates and the archivist path.

## Timing

After a completed run with objective tests and an independent `PASS`, but
before `COMMITTED`.
The task must still be open at this point, so the archivist can work under
the same task with entity lock, backup, and optimistic concurrency.

## Relevance check

Capture:

- new or changed systems, devices, and projects,
- completed project steps and evidenced runtime states,
- decisions with durably useful reasoning,
- open items that a later session must continue,
- confirmed user preferences for recurring work.

Do not capture:

- transient output, one-off commands, or plain conversation recap,
- unsubstantiated guesses presented as fact,
- secrets, credentials, private notes, or daily notes,
- information already present with an equally strong or stronger source.

## Procedure

1. Read the task contract, run evidence, and verifier verdict.
2. Search every affected entity with `agentctl knowledge search`.
3. If nothing is durably relevant, document that with a reason:

```powershell
python C:\AgentSystem\bin\agentctl.py knowledge review `
  --task-id <task-id> --decision none `
  --reason "Only transient execution; no new durable fact"
```

4. For relevant facts, read
   `C:\AgentSystem\schemas\knowledge-candidate.schema.json`, create small
   atomic candidates, submit them with `knowledge submit`, and have them
   adopted via `knowledge approve`.
5. Document all successfully adopted candidate IDs:

```powershell
python C:\AgentSystem\bin\agentctl.py knowledge review `
  --task-id <task-id> --decision captured `
  --review-candidate-id kc-... `
  --reason "Confirmed new system state was merged into the existing entity"
```

6. If a relevant candidate cannot be adopted due to a conflict or missing
   confirmation, leave it pending or reject it with clear reasoning and
   document `deferred` with the candidate ID. Don't invent a
   conflict-free substitute.

## Completion order

1. Finish the run with `outcome=PASS`, non-empty objective test evidence,
   a change summary, and `verification="PASS: ..."`.
2. Then run the knowledge review; a review performed before the last
   completed run is considered stale.
3. Run `agentctl task readiness --task-id <task-id>`.
4. Only set the task to `COMMITTED` when `ready: true`.

`FAIL` or `INCONCLUSIVE` is never commit-ready.
