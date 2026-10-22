# Provider integration

The configured checkout is the source of rules, skills and local runtime code. Each user gets their own local configuration and Obsidian vault; copying a maintainer's global settings, logins or runtime state is not an installation.

## Claude Code

Setup adapts project .claude/settings.json, agent hook paths and .mcp.json to this checkout. Open a trusted new project session and verify the callbacks you intend to rely on. Shared rules enter through CLAUDE.md importing AGENTS.md.

## Codex

Setup generates project .codex/config.toml, .codex/hooks.json, .codex/agents/*.toml and .agents/skills. Existing unrelated TOML and hook handlers are preserved. Hook trust is tied to the exact definition: review changes in /hooks. Never bypass trust globally.

The Codex adapter uses documented lifecycle payloads. It normalizes apply_patch targets for policy checks and uses deny rather than unsupported ask hook decisions. A hook refusal does not authorize a workaround. Hook failures and coverage limits must be visible.

Custom-agent permissions inherit from the parent. A custom-agent sandbox_mode field does not enforce a separate read-only sandbox. When the verification boundary must be technical, start a separate root session in read-only mode and give it the original task and raw evidence.

## ChatGPT

Use templates/chatgpt-core.md as account guidance and connect this user's managed memory through supported tools. See chatgpt-setup.md. Client, account and workspace support varies. Local script presence or a GitHub link does not establish cloud execution or memory connectivity.

## Scope and rollback

The default installer changes project-local configuration only. It does not install a global hook layer across unrelated projects. Reuse the repository as the task workspace, or deliberately configure broader provider scope after reviewing the target account's existing configuration.

Private backup manifests and optimistic readback protect setup changes. Rollback refuses to overwrite post-setup edits. See portable-sessions.md.
