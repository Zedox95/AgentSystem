---
name: task-orchestration
description: Divide substantial independent work into bounded subagent tasks while preserving the user's goal, one writer per resource, a small context and required verification.
---

The main session owns the user goal, decisions and final synthesis. Default to one agent. Delegate only when a task can run independently, requires specialized investigation, or benefits from an independent verifier. Use at most two extra agents concurrently unless the task explicitly warrants more; avoid nested delegation by default.

Give each agent the original goal relevant to its task, permitted resources, evidence references, output contract and stop condition. Do not copy the entire conversation when a short handoff suffices. Domain specialists are candidates, not mandatory invocations for every matching keyword.

Only one agent may write a resource. Research and verification remain read-only. Objective tests precede independent review. A verifier receives raw evidence, not the executor's verdict; use PASS, FAIL or INCONCLUSIVE with concrete references. Reuse unaffected evidence, independently reproduce critical checks, and do not build a chain of reviewers checking each other's prose.
