---
name: ufo-windows
description: Operates the Windows UI via UFO² through the command line - list windows, read controls, click, type text, send keys, scroll, run step sequences - and independently verifies every action via the UI Automation interface. Use when a Windows task genuinely requires a graphical interface and no API, cmdlet, or CLI can solve it more reliably.
allowed-tools: Bash(C:\UFO\.venv\Scripts\python.exe C:\AgentSystem\adapters\ufo\ufoctl.py *), Read, Grep, Glob
---

# Windows GUI via UFO²

Claude is the brain, UFO² is only the hand. UFO's own agent loop is not
used — it needs a language model that this system deliberately doesn't
provide for it.

## CLI or MCP?

Both paths exist side by side and solve different tasks.

**`ufoctl` (this skill) — the default.** For known, repeatable workflows.
Every call is self-contained, deterministically scriptable, individually
verifiable, with small context output and no running process.

**MCP server `ufo` — for exploratory work.** When you need to feel your way
through an unknown application, the server holds window state across many
steps instead of rebuilding it on every call. Tools: `mcp__ufo__ui_*` for
reading, `mcp__ufo__host_select_application_window` for activating,
`mcp__ufo__app_*` for acting.

Rule of thumb: **explore via MCP, repeat via the CLI.** Whatever you
discovered in MCP mode should then go into a `plan` file or script for the
CLI — that's when it becomes reproducible.

Even in MCP mode: **verification is done with `ufoctl inspect`**, never with
UFO's own control list.

## First: is a GUI actually necessary?

Check in this order before touching UFO: CIM/WMI → PowerShell cmdlet → COM →
registry or configuration file. A GUI action is slower, more fragile, and
worse to verify than any of these layers.

UFO is **not** a shortcut around permissions, the filesystem, or a missing
API.

## Invocation

```bash
C:\UFO\.venv\Scripts\python.exe C:\AgentSystem\adapters\ufo\ufoctl.py windows
```

Every call is self-contained: resolve window, select, act, read back. UFO's
window selection lives only within the process — a selection from an
earlier call doesn't exist.

## Workflow

**1. Find the window.**

```bash
… ufoctl.py windows
```

**2. Read the controls — always before any action.**

```bash
… ufoctl.py controls --window "Settings" --type Edit
… ufoctl.py controls --window "Editor" --contains "Save"
```

This returns `label`, `control_text`, and `control_type` for each element.
The `label` is the identifier you act on. Without this step, UFO doesn't
know the elements and every action fails.

**3. Act — via the label, not coordinates.**

```bash
… ufoctl.py click  --window "Editor" --control 12
… ufoctl.py type   --window "Editor" --control 6 --text "content"
… ufoctl.py keys   --window "Editor" --control 6 --keys "^s"
… ufoctl.py scroll --window "Editor" --control 8 --dist -5
```

`--control` accepts the label or a unique text fragment. If the fragment is
ambiguous, the CLI reports all matches instead of guessing.

**4. Verify independently — the most important step.**

```bash
… ufoctl.py inspect --window "Settings" --type Edit --expect "expected text"
```

`inspect` goes **around UFO** directly through pywinauto to the UI
Automation interface and returns the `value` and `window_text` of the live
control.

**This is mandatory.** UFO's own control list reports the accessible name
instead of the actual content for input fields and can return stale values.
Confirming an action with UFO's own list would be the executor judging
itself. See `docs/known-issues.md`.

## Step sequences

For recurring workflows, use a plan file instead of many individual calls —
one window context, one execution:

```json
{
  "window": "Editor",
  "steps": [
    {"action": "type",  "control": "Text editor", "text": "content"},
    {"action": "keys",  "control": "Text editor", "keys": "^s"},
    {"action": "wait",  "seconds": 1},
    {"action": "read",  "control": "Text editor"}
  ]
}
```

```bash
… ufoctl.py plan --file plan.json
```

The plan aborts on the first failure and reports which steps already ran. A
partially executed plan is **never** counted as success — check the actual
state afterward and decide on continuing or rolling back.

## Risk

GUI actions are at least **R1**. Once they change configuration, files, or
system settings, they're **R2** — then run `preflight-change` first with a
baseline and backup.

Coordinate-based actions (`app_click_on_coordinates`,
`app_drag_on_coordinates`) are deliberately not exposed as a CLI command.
They aren't reproducible and break with every layout change.

## Pitfalls

- **Always run `controls` before acting.** Otherwise: "No application windows
  available."
- **Window ambiguous?** The CLI lists all matches — use the ID.
- **Empty control list?** The CLI waits and retries a limited number of
  times; that's a known race after a window switch, not a blind retry.
- **Never verify with `controls`, always with `inspect`.**
- Selecting a window brings it to the foreground. On a machine that's in
  use, that's visible — plan GUI work accordingly.

## Recording experience

```bash
python C:\AgentSystem\bin\agentctl.py exp record --key windows.gui.<task> --method "ufoctl:<command>" --success --duration <ms> --agent windows-agent
```
