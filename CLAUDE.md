# Claude Code adapter

@AGENTS.md

The repository is the source of shared policy. Its .claude/agents and .claude/skills supply role definitions and workflows. Run setup.ps1 or bin/setup_agent.py for this user's actual checkout and vault, then open a trusted new project session.

Use bounded delegation under the shared policy. A domain name does not require a subagent. Skills are loaded only when applicable. Prefer deterministic interfaces and targeted tests. Do not set up paid API keys or assume another provider is logged in.

Hook event contracts are provider-specific. Keep Claude hooks in .claude/settings.json; the Codex adapter is generated separately. Never copy a maintainer's global settings, credentials, notes or runtime state to another user. Do not claim global activation from a project-local setup.

For independent verification follow verify-change; a verifier does not implement fixes. For shared knowledge use obsidian-context and knowledge-review. Checkpoint each coherent session separately.
