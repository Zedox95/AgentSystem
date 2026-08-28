---
name: windows-admin
description: Chooses the most reliable route for a Windows task - native API and CIM, PowerShell, COM, UFO² UI Automation, or visual computer use as a last resort - and knows this machine's specifics such as PowerShell 5.1 without pwsh and the lack of elevation. Use for system diagnostics, drivers, services, registry, Windows settings, and GUI automation on this PC.
allowed-tools: Bash(python C:\AgentSystem\bin\agentctl.py *), Read, Grep, Glob
---

# Routing Windows tasks correctly

## This machine's environment

These points are measured, not assumed:

- Windows 11 Pro 25H2, build **26200**. The registry reports `ProductName =
  "Windows 10 Pro"` — a known stale-key artifact. The build is what counts.
- `powershell.exe` is **Windows PowerShell 5.1**. **No `pwsh` in PATH.**
  Missing there: `Test-Json`, `&&`, `||`, `??`, `?.`, `?:`, `-AsHashtable`.
- The session runs **without** administrator rights.
- Git Bash is available via the Bash tool, PowerShell via the PowerShell
  tool. Both have their own syntax — don't mix them.

## Choosing a method

Check experience first:

```bash
python C:\AgentSystem\bin\agentctl.py exp best --key windows.<task-type>
```

Without a matching entry, this order applies — as a preference, not a
mandate:

**1. CIM/WMI and native API.** Structured, machine-readable, verifiable.
`Get-CimInstance Win32_PnPSignedDriver`, `Win32_Service`,
`Win32_LogicalDisk`.

**2. PowerShell cmdlets.** `Get-Service`, `Get-PnpDevice`, `Get-WinEvent`,
`Get-NetAdapter`. Literal paths, no guessing.

**3. COM.** When an application has an automation model (Office, Explorer),
it's more reliable than any GUI operation.

**4. UFO² UI Automation** via `adapters/ufo/`. Only when the task genuinely
requires a GUI and none of the above layers cover it.

**5. Visual recognition.** Only when UI Automation can't find the controls.

**6. Raw coordinates.** Last resort. Not reproducible, breaks with every
resolution or layout change.

**UFO² is not a shortcut.** It's not there to bypass the filesystem,
permissions, or a missing API. If you're considering doing via GUI what a
cmdlet can do, that's the wrong choice.

## Elevation

Admin-required actions include: service changes, HKLM write access, driver
installation, firewall rules, scheduled tasks in the system context.

The way to do this is a **visible UAC prompt per action**:
`Start-Process powershell -Verb RunAs -ArgumentList ...`

No permanently elevated agent process, no pre-elevated scheduled task for
general purposes. The user confirms every single action. The policy guard
escalates `-Verb RunAs` to a confirmation prompt anyway.

## Risk

| Task | Class |
|---|---|
| Inventory, versions, reading logs, diagnostics | R0 |
| Restart a service, reversible setting | R1 |
| Driver, registry write access, firewall, package removal, network | R2 |
| Bootloader, BIOS/firmware, partitions, user accounts, disks | R3 |

From R2 up, run `preflight-change` first, then `verify-change`.

## Verification

Always re-read the real state — don't reuse the output of the command that
made the change. This includes the event log: check for **new** entries
since the time of the change, not merely the absence of errors overall.

```powershell
Get-WinEvent -FilterHashtable @{ LogName='System'; Level=1,2; StartTime=$timestamp }
```

## Common pitfalls on this machine

- `Test-Json` doesn't exist under 5.1 — solve schema validation differently
- `2>&1` on native programs produces ErrorRecords under 5.1 and sets `$?` to
  `$false` even though the program exited with 0
- `Set-Content` without `-Encoding utf8` writes in the ANSI codepage
- `New-Item -Force` on an existing file **clears** it
- `-ErrorAction SilentlyContinue` suppresses the output, not the exit code
- German-locale output (`tasklist`, `netstat`) isn't always decodable as
  cp1252 — set `errors="replace"` when processing it further in Python
