"""notify — local Windows notification with no external dependency.

Used for the Codex failover: the user should notice when Codex takes over
as the substitute main, even when no Claude Code session is running that
could tell them. Purely local on the machine - there is no cloud or phone
push in this system (see the Codex takeover architecture plan).

Uses `System.Windows.Forms.NotifyIcon` via PowerShell instead of an
additional module like BurntToast, whose installation on this machine is
unverified - .NET is present on every Windows 11 system.

Best-effort: a failed notification must never block or delay the actual
operation (checkpoint, takeover, rollback).
"""

from __future__ import annotations

import subprocess

_SCRIPT = r"""
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$icon = New-Object System.Windows.Forms.NotifyIcon
$icon.Icon = [System.Drawing.SystemIcons]::Information
$icon.Visible = $true
$icon.BalloonTipTitle = @'
{title}
'@
$icon.BalloonTipText = @'
{message}
'@
$icon.ShowBalloonTip(15000)
Start-Sleep -Seconds 2
$icon.Dispose()
"""


def toast(title: str, message: str, *, timeout: int = 30) -> bool:
    """Shows a Windows notification. Returns True if the call went through
    without error - that is no proof it was actually visible."""
    script = _SCRIPT.format(title=title, message=message)
    try:
        subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=timeout, check=False,
        )
        return True
    except (OSError, subprocess.SubprocessError):
        return False
