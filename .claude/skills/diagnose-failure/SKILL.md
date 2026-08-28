---
name: diagnose-failure
description: Systematic root-cause analysis after a failure - capture error data, determine the error class, form hypotheses and refute them individually, check version and configuration, query the experience store, then deliberately decide on a second attempt or a method change. Use when a command, service, server, or change has failed, instead of blindly retrying it.
allowed-tools: Bash(python C:\AgentSystem\bin\agentctl.py *), Read, Grep, Glob
context: fork
---

# Root cause analysis

No blind retries. The same method is attempted at most twice, and the second
attempt only with a **corrected cause**.

## 1. Capture error data completely

The exact error message verbatim, exit code, the command actually executed,
timestamp, affected resource, permission context. Plus the log excerpts
**around that point in time** — not the whole log.

A paraphrased error message is worthless. Use the original text.

## 2. Determine the error class

| Class | Distinguishing feature | Typical cause |
|---|---|---|
| Syntax/invocation | "unknown option", "unrecognized", parser error | wrong version, invented flag |
| Permissions | "access denied", "permission denied", 401/403 | missing elevation, wrong user, ACL |
| Not found | "not found", "no such file", 404 | wrong path, service doesn't exist, wrong version |
| State | "already exists", "in use", "locked" | resource occupied, precondition missing |
| Network | timeout, "connection refused", DNS | service down, firewall, wrong port |
| Schema/format | validation error, parse error | data format doesn't match version |
| Resources | OOM, "no space", VRAM | capacity |

The class determines where you look. A permissions error is not fixed by
different syntax.

## 3. Check version assumptions

The most common mistake is an assumption made from memory. Check in this
order (AGENTS.md section 3): installed version → local `--help` output →
actual configuration file → local README → installed source code → current
official primary documentation.

Especially common on this machine: `powershell.exe` is **5.1**, not `pwsh`.
`Test-Json`, `&&`, `||`, `??`, and `?:` don't exist there.

## 4. Form and refute hypotheses

Formulate two to three concrete hypotheses and try to **refute** each one —
not confirm it. Change only one variable at a time. The hypothesis that
explains all observations and that you could not refute is the working
hypothesis.

Watch for observations that your preferred hypothesis does **not** explain.
That's usually where the real cause is hiding.

## 5. Query experience

```bash
python C:\AgentSystem\bin\agentctl.py exp list
python C:\AgentSystem\bin\agentctl.py exp best --key <task-type>
```

Is the error known? Is there a method that has demonstrably worked here —
and does its environment still match?

## 6. Decide

- **Cause found and correctable** → second attempt with corrected cause, same
  method
- **Same error again** → change method per AGENTS.md section 10
- **The alternative also fails** → another agent or cross-model check via
  Codex
- **State unclear or partially changed** → rollback via `rollback-change`
- **Cause is outside your access** → report to the user, stating precisely
  what's missing

The `PostToolUseFailure` hook fires when the same error fingerprint occurs a
second time. That's the signal to change method, not to retry a third time.

## 7. Record it

```bash
python C:\AgentSystem\bin\agentctl.py exp record --key <task-type> --method <method> --error "<original error>" --root-cause "<cause found>" --agent <agent>
```

A method that reproducibly fails on the same cause belongs on `DEPRECATED` —
it will then no longer be suggested going forward.

## Result

Report: original error, error class, hypotheses examined with each attempted
refutation, root cause identified, next action chosen and why. If the cause
was **not** found, say so clearly — a plausible guess is not a diagnosis.
