# AgentSystem

A vendor-neutral control plane for AI coding agents (Claude Code,
Codex) on a personal Windows machine: a system policy, six
subagents, twelve custom skills, nine hooks, and a small Python control
plane (Ledger, Locks, Policy Guard, Experience Store).

The core principle: **A task is never successful just because an agent
says so.** Real system state and objective tests outrank any
agent statement — for that there are risk classes, a Task Contract, Resource
Locks, a transaction principle with backup/rollback, and an independent,
read-only verification role.

This is the published **core** of a larger, private setup: everything
here is reusable without being tied to a specific machine or
specific infrastructure. Operator-specific runtime state (Ledger
contents, locks, backups, concrete server/network configuration) is
deliberately not part of this repo.

## Getting started

| Document | Content |
|---|---|
| [User guide](docs/benutzeranleitung.md) | How to give a task and what happens next |
| [System documentation](docs/systemdokumentation.md) | Architecture and origins |
| [Second Brain](docs/second-brain-architecture.md) | Learning knowledge management with source attribution |
| [Global provider integration](docs/global-provider-integration.md) | Claude Code, Codex, ChatGPT |
| [Known issues](docs/known-issues.md) | Measured findings with workarounds |
| [AGENTS.md](AGENTS.md) | The binding, vendor-neutral system policy — 24 sections |

## Structure

```
AGENTS.md              vendor-neutral system policy (priorities, risk classes,
                        Task Contract, locks, verification, secrets, learning)
CLAUDE.md               Claude Code-specific addition, imports AGENTS.md
.claude/
  agents/                6 subagents (Windows, infrastructure, browser, gaming,
                          implementation, verification)
  skills/                 12 custom skills
  hooks/                  9 hook scripts (SessionStart, PreToolUse, ConfigChange, ...)
  settings.json            permissions and hook wiring
bin/
  agentsys/                Ledger, Locks, Policy, Fingerprint, Experience, Knowledge, ...
  agentctl.py              control plane command line
adapters/
  ufo/                     Windows UI automation (UFO²) — CLI + MCP
  playwright/              browser automation — CLI + MCP
  memory/                  MCP access to managed, source-attributed knowledge
schemas/                   JSON schemas for Knowledge/Context/Eval/Metric
evals/                     eval cases for regression testing
tests/                     test suites, run-all.py
docs/
```

## Second model as control and handoff

Codex is connected as a second frontier model, not as a replacement when
quota runs out. From Claude Code:

- `/codex:rescue` — limited delegation of an investigation or a fix,
  Claude remains lead
- `/codex:review` — independent Codex review of a change
- `/codex:transfer` — full session handoff: goal, prior
  history, and context transfer to a Codex thread in one command, which is
  then resumed with `codex resume <thread-id>`

None of these steps sets an API key — everything runs via the locally
logged-in Codex CLI. Details in AGENTS.md section 4 and in
[System documentation](docs/systemdokumentation.md).

## Second Brain: learning, source-attributed knowledge

The system doesn't simply remember chat history. New insights go
through a controlled single-writer path before they count as fact:

```
Observation -> Knowledge Candidate -> Archivist review -> managed note
                                              |
                  Read-only search -> Context Builder -> source package
```

- Every fact starts as a `pending` candidate with source, file hash, and
  confidence level — never directly as confirmed.
- Only a reviewed approval (`knowledge approve`) writes to the
  knowledge store; it requires an open task, an entity lock, and, for
  existing notes, the currently measured hash.
- Weaker sources never override stronger ones — older values remain
  as `superseded` rather than being deleted.
- A Knowledge Review is mandatory before every task completion: `none`,
  `captured`, or `deferred`, documented in the Ledger.

Details, CLI commands, and safety boundaries in
[Second Brain](docs/second-brain-architecture.md).

## Prerequisites

- Windows with [Claude Code](https://claude.com/product/claude-code) and/or
  [Codex CLI](https://github.com/openai/codex)
- Python 3.11+, Node.js 20+
- Optional: [UFO²](https://github.com/microsoft/UFO) for Windows GUI
  automation, [Playwright](https://playwright.dev/) for browser tasks

## Installation

```powershell
git clone https://github.com/Zedox95/AgentSystem.git
cd AgentSystem
.\setup.ps1
```

`setup.ps1` adjusts the hard-coded paths to the actual clone location
(regardless of where you clone) and asks, in order:

- **Second Brain / Obsidian** — provide an existing vault path, or leave
  it empty to have a new vault created with the expected folder structure.
  No → the `shared-memory` MCP server is removed from `.mcp.json`.
- **UFO² (Windows GUI automation)** — path to an existing
  UFO² installation. No → the `ufo` MCP server is removed, the skill
  `ufo-windows` remains unused.
- **Playwright (browser automation)** — if yes, the script runs
  `npm install` and downloads Chromium. No → the `playwright`
  entry is removed.
- **Codex connection** — if yes, you're given the three necessary steps in
  the terminal (`/plugin marketplace add`, `/plugin install`,
  `/codex:setup`); the script itself does not install Claude Code plugins.

Answering all four questions with No/Enter yields a working system
without any of the optional components. It also works non-interactively, e.g.
for scripts:

```powershell
.\setup.ps1 -VaultPath 'D:\Notizen\Vault' -InstallPlaywright:$true -SkipUfo -SkipCodexHint
```

**What the installer cannot handle for you** — policy or technical boundary,
not an oversight:

1. **Perform logins yourself:** Claude Code with the Anthropic account,
   Codex CLI with ChatGPT (`authMethod: chatgpt`), and if applicable `gh auth login` with
   GitHub. All browser/device-code logins — no tool in this system
   types credentials.
2. **Never set LLM API keys.** `.claude/settings.json` deliberately blocks
   `ANTHROPIC_API_KEY`/`OPENAI_API_KEY`/`CODEX_API_KEY` — only the
   subscriptions are needed (Claude Pro/Code, ChatGPT Plus), no pay-as-you-go API.
3. **Confirm project trust once**, when Claude Code or the
   Codex plugin asks about hooks/`settings.json` on first open.
4. Credentials for web interfaces addressed by the `browser-admin` skill —
   you always type these yourself.

Then:

```bash
python bin/agentctl.py status
python tests/run-all.py
```

Open Claude Code or Codex with this directory as the project directory —
rules, agents, skills, and hooks only apply there. Details in the
[User guide](docs/benutzeranleitung.md) and in
[Global provider integration](docs/global-provider-integration.md).

## License

MIT, see [LICENSE](LICENSE). All files in this repo are original work.
The private overall system additionally incorporates a few externally
sourced third-party skills (with their own license and provenance) — these are
deliberately not part of this publication.
