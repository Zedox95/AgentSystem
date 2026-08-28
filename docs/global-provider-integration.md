# Global Provider Integration

## Central source

Rules, roles, skills, hooks, and ledger stay under the root of this repo.
Provider adapters may pull in this source or provide a compatible, clearly
bounded format; they do not become a second substantive source.

## Claude Code

- global rules: `~/.claude/CLAUDE.md` imports `AGENTS.md` from this repo
- global skills: junction/symlink `~/.claude/skills` → `<repo>/.claude/skills`
- global agents: junction/symlink `~/.claude/agents` → `<repo>/.claude/agents`
- global hooks/permissions: `~/.claude/settings.json`
- Claude→Codex: official Codex plugin at user scope

New Claude Code sessions load this layer automatically. A reload command is
not available in every graphical Claude environment; the reliable
activation boundary is a new session.

## Codex

- global rules: hardlink `~/.codex/AGENTS.md` ↔ `AGENTS.md` from this repo
- global skills: junction/symlink `~/.agents/skills` → `<repo>/.claude/skills`
- portable core and hooks via a dedicated, personal plugin
- shared knowledge via a dedicated shared-memory plugin

Plugin hooks are not automatically trusted after installation. After every
substantive hook change, open `/hooks`, review the definitions, and approve
the new hash. Trust bypass is not a permanent operating mode.

## ChatGPT

Account-wide custom instructions can carry the portable core into new
chats. That is the maximum directly configurable global rule base in the
ChatGPT cloud.

Local Windows hooks, local files, and local personal-marketplace plugins are
not executed by a normal cloud chat. A plugin installed locally for Codex is
only present in ChatGPT as a plugin once it has been separately published/
installed there, or connected via a cloud-reachable MCP service. A still-open
cloud rollout must not be presented as already in production.

## Rollback

Before any change to this global layer, a restore point with a SHA-256
manifest is created. Before restoring, re-inventory plugin states; then
restore global files from the backup, deliberately dissolve junctions/
hardlink, remove the user-scope plugin, and restore the previous
project scope if needed.
