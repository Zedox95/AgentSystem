---
name: update-agent-stack
description: Performs an update of a system component in a controlled way - check the changelog, assess relevance, record a known-good state, back up, test in isolation, run smoke tests, run regression, verify, then adopt it or stay on the known-good version. Use for updates to Claude Code, Codex, UFO², Playwright, Node, Python, MCP servers, or the agent system itself.
allowed-tools: Bash(python C:\AgentSystem\bin\agentctl.py *), Bash(python C:\AgentSystem\tests\*), Read, Grep, Glob
---

# Controlled update

No blind `latest`. A new version only becomes production once it's
demonstrably **not worse**.

## 1. Record known-good — before anything else

```bash
python C:\AgentSystem\bin\agentctl.py env known-good --name pre-<component>-<date>
```

This defines the way back before anything is changed. Without this step,
there's no later comparison point.

## 2. Check the changelog and assess relevance

Read the actual changelog of the target version, not the marketing claim.
Ask specifically:

- Does the update fix a problem we actually have?
- Are there breaking changes to interfaces we use?
- Do configuration schemas, hook names, CLI flags, or API contracts change?
- Are stored `VERIFIED` experiences affected?

An update with no discernible benefit to us is not a reason to update.

```bash
python C:\AgentSystem\bin\agentctl.py exp stale
```

shows which experiences become questionable due to an environment change.

## 3. Backup

From R2 up: a complete restore point of the affected configuration with a
SHA256 manifest. For `C:\AgentSystem`, a clean git state is sufficient —
check that `git status` is empty before you begin.

## 4. Test in isolation where possible

Preferably in a copy, a separate venv, a worktree, or a VM. Not every
component allows this — if not, say so clearly and treat the update
correspondingly more cautiously.

## 5. Smoke tests

The component starts, reports the expected version, and its core function
runs through once. For this system:

```bash
python C:\AgentSystem\bin\agentctl.py env show
python C:\AgentSystem\bin\agentctl.py status
```

## 6. Regression run — mandatory

```bash
python C:\AgentSystem\tests\run-all.py
```

Regression is required after any change to: skill, agent prompt, adapter,
routing, hook, tool update, UFO update, Playwright update.

What's evaluated isn't just "green", but the comparison: success rate,
runtime, retries, verification success, side effects. A version that's green
but measurably slower or more retry-prone is not progress.

## 7. Decide

| Result | Decision |
|---|---|
| Regression green, no regression in quality | adopt, write new known-good |
| Regression green, but measurably worse | stay on known-good, document the finding |
| Regression red | roll back, investigate root cause via `diagnose-failure` |
| Breaking change to a used interface | fix first, then rerun regression |

On adoption:

```bash
python C:\AgentSystem\bin\agentctl.py env known-good --name <component>-<version>
```

## 8. Follow up on affected experiences

Experiences whose `revalidate_when` was triggered by the update are **no
longer `VERIFIED`**. Either reconfirm them or set them to `DEPRECATED` —
silently continuing to use them is not permitted.

```bash
python C:\AgentSystem\bin\agentctl.py exp deprecate --key <k> --method <m> --reason "Environment changed by update to <version>"
```

## Special case: change to the control plane

`settings.json`, `hooks/`, `bin/agentsys/`, and the security sections of
`AGENTS.md` are especially protected. The `ConfigChange` hook blocks
incidental changes. A deliberate update there follows exactly this process
and ends with its own git commit containing the reasoning.

After any hook change, `tests/test_hooks.py` is mandatory — the hooks are
invoked there as real processes, not just imported.

## Result

Report: old and new version, changelog findings checked, test results
compared, decision with reasoning, new known-good state, and which
experiences were followed up on.
