# Portable sessions and installation

## Install for a new user

Use a fresh clone and the new user's own subscriptions, logins and Obsidian vault. Python 3.11+ is required; Node.js is only needed for optional browser tooling.

On Windows run .\\setup.ps1. It configures this checkout, asks for a vault, and installs no LLM API keys or global permission bypass. For a scripted setup:

`python bin/setup_agent.py install --vault "C:/Users/YourName/Documents/Obsidian Vault"`

Choose one or more --provider claude, --provider codex, --provider chatgpt as needed. Without a vault, setup leaves memory disconnected; --skip-vault explicitly disconnects a prior configuration. Existing unrelated Codex TOML, hooks and Claude settings are preserved. Conflicting manually edited generated skills/agents are rejected. Rerunning an unchanged installation makes no changes.

Setup writes only local configuration under the checkout and creates missing standard directories in an explicitly selected vault. It does not install Python, Claude Code, Codex, Obsidian, or log in for the user. Optional Playwright downloads happen only with -InstallPlaywright:$true. Existing optional adapters stay optional.

Open this repository as a trusted project. Codex discovers generated .agents/skills, .codex/agents and .codex/hooks.json. Review exact hook definitions with /hooks; changed hooks need renewed trust. No global rules or hooks are secretly installed. For ChatGPT follow chatgpt-setup.md.

`python bin/setup_agent.py doctor` checks generated file hashes, available commands and vault existence. It distinguishes configuration from activation: verify actual hook runs in the target client before relying on them.

## Rollback

Every effective setup creates a private backup manifest under ignored state/setup-backups. Use its reported path:

`python bin/setup_agent.py rollback --backup "<reported manifest path>"`

Rollback refuses to overwrite files changed since setup. Restore the most recent installation first. Existing notes, unrelated settings and newly created vault directories are not deleted.

## Sessions

Keep follow-ups and implementation steps for one coherent task together. Start a separate session for an unrelated task. Shared memory supplies relevant persistent context; there is no all-seeing controller session.

`python bin/assistantctl.py plan --prompt "Compare two backup approaches"` returns an advisory plan without a model call. balanced and reasoning are capability tiers, not provider model IDs. Domain classification alone does not spawn agents.

Save a handoff with:
`python bin/assistantctl.py checkpoint save --session-id "<real host ID>" --file handoff.json`

Use show or clear with the same ID. Hashed filenames prevent path injection and collisions between opaque IDs. Sessions never silently load another session's checkpoint. A pre-upgrade state/checkpoint.json remains a legacy CLI checkpoint; it is not assigned to a new session automatically.

The Claude and Codex lifecycle adapters preserve an existing structured handoff before compaction/stop. The assistant must first save meaningful goals and next steps; the hooks do not scrape transcripts or invent project state.

## Verification and subagents

Default: main agent alone. At most two additional agents unless independent work justifies more. Give each a bounded assignment and compact evidence package. One writer per resource; research and verification do not implement fixes.

R1+ changes retain objective testing and independent verification. Reuse unchanged evidence, independently reproduce critical acceptance checks, and test likely side effects. R0 factual answers use sources appropriate to uncertainty and consequences; they do not require a reviewer chain.

Current Codex custom-agent sandbox_mode does not override the parent's permissions. The generated verifier is instructed to remain read-only; for an independently enforced read-only boundary use a separate root verification session with a read-only sandbox. No claim is made that a prompt alone enforces tool permissions.

## Regression

`python tests/run-all.py` runs portable tests without contacting installed desktop apps. Use --integration to additionally exercise optional live adapters. Integration availability is reported separately and is not proof of a successful task. The core memory MCP is tested in an isolated temporary vault even without those optional tools.

Primary references: https://developers.openai.com/codex/build-skills , https://developers.openai.com/codex/hooks , https://developers.openai.com/codex/agent-configuration/subagents .
