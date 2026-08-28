---
name: rollback-change
description: Restores a known-good state in a controlled way - verify backup integrity, plan the restore, execute it, objectively verify it, release the lock, and set the ledger to ROLLED_BACK. Use when a change has failed, the verifier reports FAIL, the state is unclear, or a change needs to be reverted.
allowed-tools: Bash(python C:\AgentSystem\bin\agentctl.py *), Read, Grep, Glob
---

# Controlled rollback

A rollback is itself a change. It follows the same rules as any other — with
checks before and verification after.

## 1. Establish the state before touching anything

```bash
python C:\AgentSystem\bin\agentctl.py status
python C:\AgentSystem\bin\agentctl.py task show --task-id <id>
```

Clarify: which changes actually took effect already? Rolling back something
that never happened does more damage than it fixes.

Set the state:

```bash
python C:\AgentSystem\bin\agentctl.py task state --task-id <id> --state ROLLING_BACK
```

## 2. Verify backup integrity — before restoring

A backup counts as usable only once it's been checked:

- All files listed in the manifest exist
- All SHA256 sums match
- The scope is plausible (file count, total size)

If something doesn't check out, **do not restore**. Laying a broken backup
over a damaged state makes things worse. Report to the user instead.

## 3. Choose a rollback path

| What | Path |
|---|---|
| Control repo `C:\AgentSystem` | `git revert <commit>` — not `reset --hard` |
| Files/configuration | Restore the copy from the restore point, then compare hashes |
| Registry | `reg import` of the exported `.reg` file |
| Windows driver | previous version via Device Manager rollback or `pnputil` with the saved INF |
| Service | restore previous start type and state from the baseline |
| Proxmox | snapshot rollback |
| Pterodactyl | restore backup via the API |
| UFO patches | revert the patch — **not** `git checkout` across the whole tree |
| Package | install the previous version specifically, not a blanket uninstall |

The principle: as targeted as possible. A broad revert sweeps up unrelated
changes nobody wanted reverted.

## 4. Execute

One step at a time, with a check in between. Don't run multiple rollbacks
simultaneously — otherwise, if a problem occurs, it's impossible to tell
which one caused it.

## 5. Verify objectively

The restored state must match the **baseline**, not the desired target
state. Compare against the raw output captured before the change: service
status, registry value, version, hash, API state.

Also check that no remnants of the failed change are left behind — half
installations, orphaned services, open ports, temporary rules.

## 6. Close out

```bash
python C:\AgentSystem\bin\agentctl.py run finish --run-id <run> --outcome ROLLED_BACK --rollback "<what was reverted>" --tests "<comparison against baseline>"
python C:\AgentSystem\bin\agentctl.py lock release --resource "<lock-id>" --token <token>
python C:\AgentSystem\bin\agentctl.py task state --task-id <id> --state ROLLED_BACK
python C:\AgentSystem\bin\agentctl.py exp record --key <task-type> --method <method> --rolled-back --error "<reason>" --root-cause "<cause>"
```

The lock is released only **after** the verified restoration.

## If the rollback itself fails

Don't improvise. Stop, secure the current state, and report to the user:
what was attempted, what failed, what state the system is in now, and what
options exist. A known inconsistent state is better than one obscured by
further attempts.

## Result

Report: what was reverted, against which baseline it was verified, with
which raw output, whether remnants were found, and the ledger state.
