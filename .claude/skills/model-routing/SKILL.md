---
name: model-routing
description: Decides, rule-based, which model and effort level are appropriate for a task, and how to escalate after a failure. Use before delegating to a subagent, when a task is hard to classify, and when an attempt has failed and the question is whether a stronger model would even help.
allowed-tools: Bash(python C:\AgentSystem\bin\agentctl.py *), Read, Grep, Glob
---

# Model selection

## What can actually be switched here

**Not switchable:** the model of the running session. If you're reading
this, it has already read the prompt. A switch mid-response isn't possible,
and suggesting one unprompted is usually just noise.

**Switchable:** the model **per delegation**. When tasking a subagent, the
model can be set for exactly that call. That's where routing actually
matters — and only there.

This implies the real working method: if the session is running on the
weaker model and real thinking work is at hand, **delegate the thinking
part** instead of demanding a session switch.

## Query the classification

```bash
python C:\AgentSystem\bin\agentctl.py route --prompt "<task>"
```

Rule-based, without a model call. A classifier that itself queries a model
consumes exactly the budget it's supposed to save.

The `UserPromptSubmit` hook does this automatically for every task and only
speaks up when there's something to say.

## The rule

| Situation | Model | Effort |
|---|---|---|
| Query, status, inventory, clearly scoped execution | `sonnet` | low–medium |
| Known workflow with an existing skill | `sonnet` | medium |
| R2 — real change, but clear | `sonnet` | **high** |
| Open question: why, root cause, compare, design | `opus` | high |
| R3 — hard to reverse | `opus` | high |
| Contradictory evidence, two approaches failed | `opus` | xhigh |

**Effort before model.** `sonnet` with `high` is often better than `opus`
with the default on tricky but clearly scoped tasks — and noticeably more
economical. When a result feels too shallow, more effort is the better first
move.

## Why not always the strongest model

Because this system's intelligence deliberately does not live in the model
alone, but in skills, rules, objective tests, the experience store, and the
ledger. A strong model re-deriving a workflow that's already documented
delivers the same result and burns scarce budget.

The budget is the actual resource. Whoever spends it on routine work doesn't
have it when a diagnosis really gets stuck.

## Escalation after a failure

A stronger model doesn't fix a typo, a missing permission, or an
unreachable host. Escalation only applies when failure stems from
**reasoning** limitations.

| Trigger | Reaction |
|---|---|
| Verifier reports `INCONCLUSIVE` | increase effort, **keep** the model — evidence is missing, not reasoning ability |
| Verifier reports `FAIL` | escalate from `sonnet` to `opus`, with evidence handoff |
| Two substantively different approaches failed | `opus` with `xhigh` |
| Already on `opus` and still failing | don't escalate further — ask the main session for `/codex:rescue` or `/codex:review`, or report to the user |

An escalation is always a **new task**, not a context pass-through. The
handoff contains: original goal, observed versions, raw evidence, changed
state, hypotheses tried, error output, verifier finding, open acceptance
criteria.

```bash
python C:\AgentSystem\bin\agentctl.py route --escalate --model sonnet --verdict FAIL
```

## What the classification is not

A hint, not an instruction. It knows only the wording of the task, not the
system. If it contradicts what you actually measure, **the measurement
wins**. A task classified as routine that turns out to be convoluted becomes
a reasoning task — not the other way around.

The classifier itself reports when it's unsure: for very short tasks and for
tasks spanning several equally strong domains. Decide for yourself then.

## Learning from usage

Classifications land as `PROMPT_ROUTED` in the ledger. This later allows
checking whether the rule holds up — for example, whether tasks classified
as routine get escalated disproportionately often. That would be a reason to
refine the patterns, not to crank up the model.
