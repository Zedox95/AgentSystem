# System Documentation

All statements are measured on the machine, not assumed.

---

## 1. Origin

This system originated as the successor to a previous, local multi-agent
setup made up of several local LLM tools, UFO², and a custom orchestration
overlay. Carried over from it:

- The operating contract — revised in content, phrased provider-neutrally,
  and extended with rollback, locks, and task contract
- The agent descriptions, condensed to six Claude subagents
- Routing and learning concept: classification, escalation only as a
  new spawn with evidence, verifier-gated learning
- Knowledge and metric schemas
- The restore-point pattern with SHA256 manifest and dry-run restore
- Codex as the second frontier model via a read-only sandbox with actively
  removed API keys
- UFO² as the Windows action layer

Local LLM tools that were no longer needed were fully uninstalled; only
upstream components of UFO² were kept unchanged.

## 2. Structure

```
Repo root
├── AGENTS.md                     provider-neutral system policy, 24 sections
├── CLAUDE.md                     short; pulls in AGENTS.md via @AGENTS.md
├── .claude/
│   ├── settings.json             permissions and hooks
│   ├── agents/                   6 subagents
│   ├── skills/                   12 skills
│   └── hooks/                    hook scripts + hooklib
├── bin/
│   ├── agentsys/                 paths, policy, ledger, locks, fingerprint, experience, ...
│   └── agentctl.py               command line of the control plane
├── adapters/
│   ├── ufo/                      ufoctl.py (CLI) + ufo_mcp.py (MCP)
│   ├── playwright/                pwctl.mjs (CLI) + @playwright/mcp
│   └── memory/                   MCP access to the managed Second Brain store
├── .mcp.json                     MCP server for exploratory work
├── schemas/                      JSON schemas for knowledge/context/eval/metric
├── evals/                        eval cases for regression checking
├── tests/                        test suites, run-all.py
└── docs/
```

`state/` (ledger, locks, experience, known-good, backups) is the runtime
state of a specific operator and is therefore not part of this repo — see
`.gitignore`.

### Subagents

`windows-agent` · `infrastructure-agent` · `browser-agent` · `gaming-agent` ·
`implementation-agent` · `verification-agent`

None of them hard-wires a model — `tests/test_config.py` enforces this. The
`verification-agent` lists `Write`, `Edit`, and `NotebookEdit` in
`disallowedTools` and additionally has its own `PreToolUse` hook that denies
write-capable shell commands. Tool restrictions alone would not have covered
the shell.

### Skills

**Workflow:** `preflight-change`, `verify-change`, `diagnose-failure`,
`rollback-change`
**Routing:** `windows-admin`, `browser-admin`, `infrastructure-admin`
**Execution:** `ufo-windows`, `playwright-web`
**Learning:** `knowledge-review`, `model-routing`
**Maintenance:** `update-agent-stack`

### Hooks

| Event | Purpose |
|---|---|
| `SessionStart` | open tasks, locks, checkpoint, stale experience entries |
| `PreToolUse` | policy guard, deterministic |
| `PermissionRequest` | allow read-only commands, ask for the rest |
| `PostToolUseFailure` | error fingerprint, warns on repetition |
| `TaskCreated` | reminds about the task contract for risky tasks |
| `TaskCompleted` | blocks completion when an open, changed R3 operation exists |
| `SubagentStop` | enforces a structured result |
| `ConfigChange` | protects hooks, permissions, environment variables |
| `UserPromptSubmit` | routing hints for the current request |

`tests/test_config.py` holds the list of actually existing hook events and
flags any invented name.

### Policy Guard

Rule-based, without a model call, without network access. DENY rules (disks,
partitions, bootloader, firmware, database and account deletion, destructive
Git, SSH keys, API keys, permission bypass), ASK rules (services, registry,
drivers, firewall, network, packages, elevation, restart), and an allowlist
of known read-only commands.

A command chain lifts the allowlist: `git status; rm -rf /` is denied, not
allowed.

The control-plane protection also applies when the configured installation
root is redirected — the fixed root is always checked as well.

### Run Ledger and state

SQLite with WAL: `tasks`, `runs`, `events`. Events are append-only, never
altered. Command text passes through redaction for API keys, tokens, and
passwords before being written.

States: `RECEIVED → PLANNED → PREFLIGHT → LOCKED → BASELINED → BACKED_UP →
EXECUTING → OBJECTIVE_TEST → INDEPENDENT_VERIFY → COMMITTED`, error path
`FAILED_STEP → DIAGNOSING → RETRY_ALTERNATIVE → ROLLING_BACK → ROLLED_BACK →
FAILED`.

### Resource Locks

Atomic via `O_EXCL`. Two ownership kinds:

- `process` — orphaned when the holding process is no longer running
- `task` — orphaned **only** when the task is completed

This distinction arose from a bug that only the smoke test uncovered: CLI
locks were orphaned immediately, because the setting process ends. The
protection was ineffective. See `known-issues.md`.

### Experience Store

`CANDIDATE → VERIFIED → DEPRECATED`. Every entry carries an environment
fingerprint (Windows build, Claude Code, UFO commit, Playwright, Python,
Node, npm, Git, Docker, Codex). `best_method` sorts by status, then success
rate, only then duration — reliability before speed. Experience entries with
a diverging environment are excluded and reported at session start.

## 3. Adapters

**UFO²** (`ufoctl.py`) — `windows`, `controls`, `tree`, `texts`, `click`,
`type`, `keys`, `scroll`, `screenshot`, `plan`, `tools`, `inspect`.
UFO's shell executor is deliberately **not** exposed: shell runs through
Bash and PowerShell through the policy guard; a second path would bypass it.
`inspect` measures via pywinauto, bypassing UFO — necessary because UFO's
own control list reports the accessible name instead of the live value.

**Playwright** (`pwctl.mjs`) — `snapshot`, `text`, `http`, `click`, `fill`,
`login`, `screenshot`, `plan`. Installed locally instead of global `latest`.
Localization via accessibility roles; selectors are the last resort,
screenshots the fallback. Ambiguous locators abort instead of guessing.

**Codex** — connected via an official, project-wide plugin. Delegation and
session handoff run through dedicated slash commands. The project
environment neutralizes `OPENAI_API_KEY` and `CODEX_API_KEY`, so that no
paid API access is picked up automatically.

## 4. Second Brain

See `second-brain-architecture.md` for the full knowledge candidate
workflow: observation → candidate → archivist review → managed note, with
single-writer path, source priority, and optimistic concurrency.

## 5. Backup and Rollback

An operator repo is a Git repo: rollback via `git revert`, not via
`reset --hard` — the policy guard denies the latter. Before risky changes,
additional filesystem-level restore points with a SHA-256 manifest are also
created, outside version control.
