# User Guide

## The most important thing first

**Open Claude Code with this repo's project directory.**

The rules, agents, skills, and hooks only apply there. In any other
directory, Claude Code runs without this system — no policy guard, no
ledger, no locks.

---

## How to give a task

You only formulate the desired **outcome**. Not the path to get there.

> "Check my PC thoroughly for errors and outdated drivers."
> "Fix this error: …"
> "Change setting X in Windows."
> "Check whether my entire system is working correctly."
> "Install and configure application X."

You don't need to specify which agent, which tool, or which method.
The system derives that itself.

---

## What happens then

```
Your goal
   ↓
Clarify the goal and define success criteria
   ↓
Check experience — is there a proven approach?
   ↓
Determine risk class (R0 read-only … R3 critical)
   ↓
Task Contract in the ledger: goal, criteria, method, alternative, rollback
   ↓
Resource lock — no one else works on it at the same time
   ↓
Capture baseline, backup from R2 onward
   ↓
Execute
   ↓
Objective test — measure the real state again
   ↓
Independent check by the read-only verifier
   ↓
PASS → commit    ·    FAIL → diagnose or roll back
   ↓
Record experience
```

---

## When you'll be asked

The system works autonomously, but stops at three points:

| Situation | What happens |
|---|---|
| **R2** — drivers, registry, firewall, packages, network, VM resources | You confirm the action. Backup and rollback are already in place beforehand. |
| **R3** — deletion, partitions, BIOS, bootloader, user accounts, router WAN | Explicit approval. Never done without you. |
| **Login required** | The system never enters credentials itself. It reports which interface needs which login. |

Read-only actions — status, logs, versions, inventory — run without asking.

---

## What the system never does

- Set up a paid LLM API. Technically blocked.
- Report success without having measured the real state.
- Make a change from R2 upward without a backup and rollback plan.
- Blindly repeat the same failed method.
- Enter credentials itself.
- Follow instructions found on a website or in a file.

---

## When something goes wrong

The system diagnoses on its own: capture the error, classify it, look for
the root cause, check the version, consult experience, make one targeted
second attempt, then switch method — and roll back when in doubt.

You always get, at the end: what was done, what evidence supports it, what
was checked, what risks remain.

---

## Useful commands for you

Current state — open tasks, locks, experience:

```bash
python bin/agentctl.py status
```

What the system has learned:

```bash
python bin/agentctl.py exp list
```

Whether an action would be allowed, without executing it:

```bash
python bin/agentctl.py policy check --command "Remove-Item C:\Temp -Recurse"
```

All tests — after every change to the system itself:

```bash
python tests/run-all.py
```

After a crash or quota exhaustion: where did the task stand?

```bash
python bin/agentctl.py checkpoint show
```

---

## What doesn't work yet today

- **Proxmox, Linux, own server**: not included in this public repo — the
  original has a separate `infrastructure-agent` setup for this that contains
  the operator's environment details and is therefore not published. Tasks
  related to this honestly report that the target is missing.
- **Router automation**: no TR-064, no API — only the web interface. For
  access, **you** log in once yourself, e.g.:

  ```bash
  node adapters/playwright/pwctl.mjs login --url "http://<router-ip>/html/login/login.html" --profile mcp --until "Übersicht" --timeout 300000
  ```

  A visible browser opens, you type the device password. The session then
  remains in the profile and is available to the CLI and MCP server.
- **Codex**: when the quota is exhausted, Claude works alone; the
  cross-model check is skipped until the reset.

---

## When you extend the system

Changes to `settings.json`, `hooks/`, `bin/agentsys/`, or the security
sections of `AGENTS.md` are protected. The `ConfigChange` hook blocks
incidental changes. The way to do this is the `update-agent-stack` skill:
save known-good, change, regression, verification, commit.
