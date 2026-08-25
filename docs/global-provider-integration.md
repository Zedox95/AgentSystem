# Globale Provider-Integration

## Zentrale Quelle

Regeln, Rollen, Skills, Hooks und Ledger bleiben unter der Wurzel dieses
Repos. Provideradapter dürfen diese Quelle einbinden oder ein kompatibles,
klar begrenztes Format bereitstellen; sie werden nicht zur zweiten
fachlichen Quelle.

## Claude Code

- globale Regeln: `~/.claude/CLAUDE.md` importiert `AGENTS.md` dieses Repos
- globale Skills: Junction/Symlink `~/.claude/skills` → `<repo>/.claude/skills`
- globale Agenten: Junction/Symlink `~/.claude/agents` → `<repo>/.claude/agents`
- globale Hooks/Berechtigungen: `~/.claude/settings.json`
- Claude→Codex: offizielles Codex-Plugin im User-Scope

Neue Claude-Code-Sitzungen laden diese Schicht automatisch. Ein Reload-Befehl
ist nicht in jeder grafischen Claude-Umgebung vorhanden; der zuverlässige
Aktivierungsrand ist eine neue Sitzung.

## Codex

- globale Regeln: Hardlink `~/.codex/AGENTS.md` ↔ `AGENTS.md` dieses Repos
- globale Skills: Junction/Symlink `~/.agents/skills` → `<repo>/.claude/skills`
- portabler Kern und Hooks über ein eigenes, persönliches Plugin
- gemeinsames Wissen über ein eigenes Shared-Memory-Plugin

Plugin-Hooks werden nach Installation nicht automatisch vertraut. Nach jeder
inhaltlichen Hook-Änderung `/hooks` öffnen, Definitionen prüfen und den neuen
Hash freigeben. Trust-Bypass ist kein dauerhafter Betriebsmodus.

## ChatGPT

Kontoweite benutzerdefinierte Anweisungen können den portablen Kern für neue
Chats tragen. Das ist die maximal direkt einstellbare globale Regelbasis in
der ChatGPT-Cloud.

Lokale Windows-Hooks, lokale Dateien und lokale Personal-Marketplace-Plugins
werden von einem normalen Cloud-Chat nicht ausgeführt. Ein für Codex lokal
installiertes Plugin ist in ChatGPT erst dann als Plugin vorhanden, wenn es
dort separat veröffentlicht/installiert oder über einen cloud-erreichbaren
MCP-Dienst verbunden wurde. Ein noch offener Cloud-Ausbau darf nicht als
bereits produktiv dargestellt werden.

## Rollback

Vor jeder Änderung an dieser globalen Schicht entsteht ein Restore-Point mit
SHA-256-Manifest. Vor dem Restore Plugin-Zustände erneut inventarisieren; dann
globale Dateien aus dem Backup zurückspielen, Junctions/Hardlink gezielt
auflösen, das User-Scope-Plugin entfernen und bei Bedarf den vorherigen
Project-Scope wiederherstellen.
