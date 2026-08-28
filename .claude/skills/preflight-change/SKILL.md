---
name: preflight-change
description: Prepares a system change in a controlled way - clarify the goal and target resource, capture the current state, determine risk class R0-R3, choose method and alternative, set a resource lock, create baseline and backup, and record acceptance criteria and rollback plan. Use before any change from R1 up, before anything is altered.
allowed-tools: Bash(python C:\AgentSystem\bin\agentctl.py *), Read, Grep, Glob
---

# Preflight before a change

Nothing is changed until this process is complete. The result is a task
contract in the ledger, a set lock, and a verified way back.

## 1. Goal and target resource

Formulate the **observable** outcome, not the activity.
Bad: "Update the driver." Good: "`Get-PnpDevice` reports Status OK for the
GPU and driver version ≥ X, event log has no new errors of class Y."

Name the target resource the way it will later be locked:
`windows:driver:nvidia` · `proxmox:vm:103` · `pterodactyl:server:<id>` ·
`router:firewall` · `windows:network`

## 2. Capture the current state

Read the real state before describing it. For Windows: service, registry, or
driver state; for Linux: `systemctl`, ports, package version; for Proxmox
and Pterodactyl: API state. The raw output is the baseline.

## 3. Determine risk class

Per AGENTS.md section 5. When in doubt, use the higher class. **R3 requires
the user's explicit approval before you proceed** — ask, don't assume.

## 4. Choose method and alternative

Check experience first:

```bash
python C:\AgentSystem\bin\agentctl.py exp best --key <task-type>
```

If there's a `VERIFIED` method with a matching environment, use it.
Otherwise choose per the preference in AGENTS.md section 10 and justify the
choice. **Always** name an alternative — it's needed when the first method
fails, and it prevents blind retries.

## 5. Create the task contract

```bash
python C:\AgentSystem\bin\agentctl.py task new --goal "<goal>" --risk R2 --resource "<lock-id>" --desired-state "<desired state>" --method "<method>" --alternative "<alternative>" --acceptance "<measurable criteria>" --rollback "<rollback path>"
```

The command exits 1 if acceptance criteria or a rollback plan are missing
for R2 or R3. That's not a formality — it's a stop signal.

## 6. Set the lock

```bash
python C:\AgentSystem\bin\agentctl.py lock acquire --resource "<lock-id>" --agent <agent> --task-id <task-id>
```

If the lock fails, another process is working on the same resource. Do
**not** proceed in parallel — wait or clarify with the other process. If
`lock list` shows a holder with `holder_alive: false`, the lock is stale and
may be released.

## 7. Baseline and backup

At R1, the noted current output is enough. From **R2** up, a restorable
backup is mandatory:

- Files and configuration: copy with a SHA256 manifest under
  `C:\AgentSystem-Backups\<date>-<purpose>\`
- Registry: `reg export` of the affected key
- Proxmox: snapshot
- Pterodactyl: backup via the API
- Save games: full copy, check size and file count first

A backup whose restoration hasn't been verified isn't a backup. At minimum,
check that the files exist and the hashes match.

## 8. Advance the state

```bash
python C:\AgentSystem\bin\agentctl.py task state --task-id <id> --state PREFLIGHT
python C:\AgentSystem\bin\agentctl.py task state --task-id <id> --state LOCKED
python C:\AgentSystem\bin\agentctl.py task state --task-id <id> --state BASELINED
python C:\AgentSystem\bin\agentctl.py task state --task-id <id> --state BACKED_UP
```

## Abort conditions

Abort and ask the user if any of the following is missing: approval for R3,
a working backup, an exact deletion target, a required access credential, or
a decision only the user can make.

## Result

Report: task ID, risk class, lock, baseline location, backup location,
acceptance criteria, rollback plan, chosen method and alternative.
