# ChatGPT and shared Obsidian memory

1. Copy templates/chatgpt-core.md into the custom instructions available in the account.
2. Keep one coherent task per chat. A ChatGPT project can hold related files and project-specific instructions.
3. Connect this user's own Obsidian service using an available plugin/MCP integration. A local stdio server is adapters/memory/memory_mcp.py; configure its Python command, absolute script path, AGENTSYSTEM_ROOT and AGENTSYSTEM_VAULT. Local-tool availability depends on the host and account. A web client needs a supported reachable service or tunnel and separate authentication; this repository does not expose a vault to the internet.
4. Test search against a known managed fact. Then perform a guarded test capture and read it back. A successful local setup or a discovered tool list alone does not prove a ChatGPT connection.
5. When skills can be installed in the selected client, use the same skill instructions. These are workflows, not guaranteed platform-wide hooks.

Normal cloud chats cannot execute the repository's Windows scripts merely because they have seen a GitHub URL. Codex hook installation does not install hooks in arbitrary ChatGPT chats. Automatic memory review in ChatGPT is model-driven and requires tools to be available.

## Import existing memories

Save the available memory summary/list as UTF-8 text or JSON with a memories array. Conversation JSON exports are also accepted; only user-authored text is staged. A conversation export and the memory summary are not a guaranteed complete export of internal ChatGPT memory.

Preview:
`python bin/assistantctl.py import-memory --file memories.json`

Stage:
`python bin/assistantctl.py import-memory --file memories.json --stage`

The importer suggests categories, rejects recognized secrets, deduplicates repeated statements and creates pending candidates. It never writes imported statements as current facts. Review usefulness, ownership, dates and conflicts before using the existing Archivist path. Do not commit the source export or state/ to Git.

## Availability and learning

The vault and its service must be reachable when a chat needs them. For access while the desktop is off, deploy a separately authenticated service on an always-on host with this user's selected managed data. This repository does not claim that such hosting is already running.

Learning improves stored knowledge and workflows; it does not modify model weights. Workflow proposals use the existing experience and skill-candidate pipeline and require validation before adoption.
