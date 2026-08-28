---
name: verify-change
description: Objectively checks whether a change that was made actually took effect - chooses the appropriate measurable verification method for Windows, Linux, browser, Proxmox, or Pterodactyl, runs it, and then hands off to the read-only verification-agent. Use after every change from R1 up, before reporting success.
allowed-tools: Bash(python C:\AgentSystem\bin\agentctl.py *), Read, Grep, Glob
---

# Verifying a change

A successful exit code is not proof. Verification means: reading the real
state again and holding it against the acceptance criteria recorded
beforehand.

## Order

1. **Objective test** — measurable, without model involvement
2. **Negative check** — what could have broken?
3. **Independent verification** — `verification-agent`, read-only
4. **Knowledge review** — run `$knowledge-review` and document it
5. Only then `COMMITTED`

The acceptance criteria must **not** be adjusted in the process. If the
result doesn't match the criterion, the result is wrong, not the criterion.

## Objective tests by domain

**Windows**
Re-read service status (`Get-Service`), re-read registry value, driver
version and device code (`Get-PnpDevice`, `Get-CimInstance
Win32_PnPSignedDriver`), event log for **new** entries since the time of the
change, file diff or hash comparison.

**Linux**
`systemctl is-active` and `is-enabled`, running processes, open ports,
configuration syntax (`nginx -t`, `sshd -t`), package version, `journalctl`
since the time of the change.

**Browser**
DOM or accessibility state, HTTP status code and response body. Where
possible, check against the API rather than the UI — a green message in a
web UI is the weakest conceivable proof.

**Proxmox**
API status of the VM, assigned resources, boot behavior, network, snapshot
list.

**Pterodactyl**
Server object present, node and allocation correct, Wings reachable,
container running, ports open, limits set, startup log free of critical
errors — and the game server actually responds.

## Negative check

Actively ask: what could this change have broken that nobody tested?
Dependent services, autostart behavior, behavior after a restart,
permissions, network reachability from outside, configuration precedence
across multiple files.

At least one negative check belongs to every R2 verification.

## Independent verification

Task the `verification-agent` with: original goal, task contract, acceptance
criteria, before state, after state, raw evidence.

Do **not** give it your own assessment, and don't phrase the task in a way
that suggests the desired answer.

Its result is `PASS`, `FAIL`, or `INCONCLUSIVE`. On `FAIL` or
`INCONCLUSIVE`, **no** success is reported; the task goes back to an
executor.

## Closing out

```bash
python C:\AgentSystem\bin\agentctl.py task state --task-id <id> --state OBJECTIVE_TEST
python C:\AgentSystem\bin\agentctl.py task state --task-id <id> --state INDEPENDENT_VERIFY
python C:\AgentSystem\bin\agentctl.py run finish --run-id <run> --outcome PASS --change "<actual change>" --tests "<what was measured>" --verification "PASS: <verifier and evidence>"
python C:\AgentSystem\bin\agentctl.py knowledge review --task-id <id> --decision <none|captured|deferred> --reason "<result of the knowledge check>"
python C:\AgentSystem\bin\agentctl.py task readiness --task-id <id>
python C:\AgentSystem\bin\agentctl.py task state --task-id <id> --state COMMITTED
python C:\AgentSystem\bin\agentctl.py lock release --resource "<lock-id>" --token <token>
```

On confirmed success, the method used may be recorded as experience and —
after `PASS` — promoted to `VERIFIED`:

```bash
python C:\AgentSystem\bin\agentctl.py exp record --key <task-type> --method <method> --success --duration <ms> --agent <agent>
python C:\AgentSystem\bin\agentctl.py exp promote --key <task-type> --method <method> --revalidate-when "<when to recheck>"
```

## Result

Report: which objective tests ran with what raw output, which negative
check was performed, the verifier's verdict, and the ledger state.
