# Known Issues and Workarounds

Measured findings, not guesses. Each entry states how it was determined and
what follows from it for the way of working.

---

## UFO² v3.0.8 — `app_texts` declares a wrong output schema

**Finding.** The tool `texts` in
`ufo/client/mcp/local_servers/ui_mcp_server.py:570` is declared as
`-> Annotated[str, …]`, but returns a list. Every call through an MCP client
fails on output validation:

```
Output validation error: ['Suchfeld, Einstellung suchen'] is not of type 'string'
```

**Determined on** 2026-08-21, UFO commit `96983c73`, fastmcp 2.11.3.

**Workaround.** `adapters/ufo/ufoctl.py` does not use `app_texts`. Reading is
done via `ui_get_app_window_controls_info`, or for verification via the
`inspect` command.

**Not** fixed in the UFO core: the core is deliberately left unchanged so
that `git pull` and updates keep working.

---

## UFO² v3.0.8 — control list does not report the live value

**Finding.** `get_control_info` in
`ufo/automator/ui_control/inspector.py:636` sets both `control_text` and
`control_title` to `element_info.name`. For an input field, that is the
accessible name, **not** the entered content. In addition, the list can
originate from an earlier enumeration and thus be stale.

**Verified as follows:** Via `ufoctl.py type`, a test value was written into
the search field of Windows Settings. UFO's control list continued to report
the old placeholder text. An independent measurement via pywinauto showed
that the written value was actually present — UFO's own feedback was wrong.

**Consequence for the way of working.** An action performed with UFO is
**never** verified with UFO's own control list. That would be the executor
confirming itself, which contradicts AGENTS.md section 13.

Verification is done with:

```bash
python adapters/ufo/ufoctl.py inspect --window "<window>" --type Edit --expect "<expected content>"
```

This command goes directly through pywinauto to the UI Automation interface,
bypassing UFO.

---

## UFO² — controls must be listed before every action

**Finding.** An action tool without a prior
`ui_get_app_window_controls_info` fails with:

```
No application windows available. Please call get_desktop_app_info first.
```

The cause is UFO's internal `control_dict`, which is only populated by the
enumeration.

**Workaround.** `ufoctl.py` automatically lists the controls first in every
action command. For callers, the finding is therefore resolved; it is
documented here because it resurfaces when using UFO's tools directly.

---

## UFO² — control list is empty right after the window switch

**Finding.** Immediately after `host_select_application_window`,
`ui_get_app_window_controls_info` occasionally returns an empty list.
A repeated call after a brief wait returns the elements.

**Workaround.** `ufoctl.py` waits briefly after the window selection and
retries the enumeration a limited number of times. This is waiting out a
known race, not a blind retry in the sense of AGENTS.md section 15.

---

## UFO's config loader depends on the working directory

**Finding.** `config/config_loader.py:393` looks for `config/ufo/` relative
to the current working directory. An import from outside the UFO
installation directory fails with `FileNotFoundError: No configuration found
for 'ufo'`.

**Workaround.** `ufoctl.py` changes into this directory before the import.

---

## Windows PowerShell 5.1 — no `pwsh` in the PATH

**Finding.** `powershell.exe` is Windows PowerShell 5.1. There is no `pwsh`
in the PATH.

Missing there: `Test-Json`, `&&`, `||`, `??`, `?.`, `?:`,
`ConvertFrom-Json -AsHashtable`.

An embedded PowerShell 7 can be bound to a different local installation and
is therefore **not** a reliable path for custom scripts.

**Consequence.** Custom scripts are to be written 5.1-compatible.

---

## German locale output cannot be decoded as cp1252

**Finding.** `tasklist` and comparable Windows commands return bytes under a
German locale that break Python's default decoding:

```
UnicodeDecodeError: 'charmap' codec can't decode byte 0x81
```

**Workaround.** For every `subprocess.run(..., text=True)`, additionally set
`errors="replace"`. Implemented in `bin/agentsys/locks.py` and
`bin/agentsys/fingerprint.py`.

---

## `subprocess` does not start `.cmd` wrappers by bare name

**Finding.** `subprocess.run(["npm", "--version"])` fails on Windows even
though `shutil.which("npm")` finds the path. `npm` and `npx` are `.cmd`
wrappers, and `CreateProcess` looks for `npm.exe`.

**Workaround.** Pass the full path resolved by `shutil.which()`. Implemented
in `bin/agentsys/fingerprint.py`.

---

## Playwright 1.62 — `page.accessibility` no longer exists

**Finding.** The former API `page.accessibility.snapshot()` has been
removed:

```
Cannot read properties of undefined (reading 'snapshot')
```

**Workaround.** `adapters/playwright/pwctl.mjs` uses `locator.ariaSnapshot()`.
This returns a compact YAML tree of roles, names, and links and is better
suited to an agent context than the earlier JSON tree anyway.

---

## Router web interfaces: content is only built after loading

**Finding.** With the default `domcontentloaded`, the start page of a
JavaScript-heavy router web interface returns a practically empty
accessibility tree (`- text: No entries available`). Only with
`--wait networkidle` does the actual structure appear.

**Workaround.** For JavaScript interfaces, set `--wait networkidle` and an
increased timeout.

---

## Own bug: version check evaluated error messages

**Finding.** `fingerprint._probe` also read the version from failed calls.
`npx --no-install playwright --version` reports, when the package is
missing, `npx canceled due to missing packages: ["playwright@1.62.1"]` — the
version number in the error text was treated as the installed version.

Result: the fingerprint reported `playwright: 1.62.1`, even though
Playwright was not installed at all.

**Fixed.** `_probe` now only evaluates calls with a return code of 0.

**Lesson.** An environment probe that reports uninstalled tools as present
is worse than none at all — it leads to experience entries with a wrong
environment match.

---

## Own bug: CLI locks were orphaned immediately

**Finding.** Originally, a lock was considered orphaned as soon as the
process with the stored PID was no longer running. On the command line,
however, that process ends immediately after `lock acquire`. Result: **every
lock set via the CLI was takeable from the very next second on** — the
protection against concurrent write access was ineffective.

**How it was found.** In the completion smoke test per AGENTS.md: two agents
requested the same resource one after the other. The second one got it, even
though the first one still held it.

**Fixed.** A lock now has an ownership kind:

* `process` — orphaned when the holding process is no longer running
* `task` — orphaned **only** when the associated task is verifiably completed
  (`COMMITTED`, `FAILED`, `ROLLED_BACK`)

Locks set via the command line are task locks and require a `task_id`;
without one it would not be decidable when they may be released. Time alone
never releases them.

**Lesson.** A safety mechanism that only works in theory is more dangerous
than none at all — you rely on it. Only the smoke test against the real
system uncovered this, not the unit tests: there, everything ran in a single
process.

---

## A permanently set LLM API key in the user environment is a risk

**Finding.** An `OPENAI_API_KEY` set as a **user** environment variable
remains readable by every tool that expects it — and can then incur paid
usage without anyone noticing. This contradicts the cost policy in AGENTS.md
section 4, which allows only subscription access.

**Countermeasure.** The project configuration (`.claude/settings.json`)
explicitly sets `OPENAI_API_KEY` and `CODEX_API_KEY` to empty for Claude Code
and the official Codex plugin, so that an existing user key is not
automatically picked up. The policy guard also refuses every attempt to set
one of these keys anew via `setx` or `export`. Removing the key itself from
the user environment is a decision only the user makes — no tool does this
automatically.

---

## Codex quota can be exhausted

**Finding.** A test call can end with a quota error message that names a
reset time.

**Handling.** Such a case is correctly classified as `QUOTA`, **not**
retried automatically, and **no** API is configured as a replacement. Claude
continues working alone until the reset; task states remain preserved in
the ledger.

---

## Two Codex versions can share a `CODEX_HOME`

**Finding.** If the CLI and desktop versions of Codex are at different
levels, the older binary can fail on startup with an error such as

```
ERROR codex_models_manager::cache: failed to load models cache:
missing field `base_instructions` at line 97 column 5
```

because the newer version writes the shared `~/.codex/models_cache.json` in
a format the older one doesn't understand.

**Impact.** No consequence for the run — Codex continues working normally
afterward. But it is visible evidence that both versions share the same
`CODEX_HOME`; which binary is used must be set explicitly at invocation.

---

## Lesson from a router investigation: a negative port scan is not proof of absence

**Finding.** An initial assessment of a home router concluded that a certain
remote management protocol was "not available and not enable-able", and was
filed as `VERIFIED`. **That was wrong.**

Two mistakes led to this:

1. The port scan only checked the standard port common with a different
   vendor. The actual vendor uses different ports.
2. As a substitute for the missing measurement, forum documentation about a
   related but different protocol was consulted and conflated with it.

The device's own page listing active services was the correct source and
only became reachable after logging in.

**Lesson.** The device's own service inventory beats both an incomplete port
scan and vendor forums. Where a device lists its own services, everything
else is circumstantial evidence. The wrong experience entry was set to
`DEPRECATED` and the corrected experience entry carries the method "device's
own services page".
