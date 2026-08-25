"""notify — lokale Windows-Benachrichtigung ohne externe Abhängigkeit.

Genutzt für den Codex-Failover: der Benutzer soll mitbekommen, wenn Codex als
Ersatz-Main übernimmt, auch wenn dabei keine Claude-Code-Session läuft, die
es ihm sagen könnte. Rein lokal am Rechner - kein Cloud- oder Handy-Push,
den gibt es in diesem System nicht (siehe Architekturplan zum Codex-Takeover).

Nutzt `System.Windows.Forms.NotifyIcon` über PowerShell statt eines
zusätzlichen Moduls wie BurntToast, dessen Installation auf diesem Rechner
nicht geprüft ist - .NET ist auf jedem Windows-11-System vorhanden.

Best-effort: ein Fehlschlag der Benachrichtigung darf den eigentlichen
Vorgang (Checkpoint, Takeover, Rollback) nie verhindern oder verzögern.
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
    """Zeigt eine Windows-Benachrichtigung. Gibt True zurück, wenn der Aufruf
    ohne Fehler durchlief - das ist kein Beweis, dass sie sichtbar war."""
    script = _SCRIPT.format(title=title, message=message)
    try:
        subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, text=True, timeout=timeout, check=False,
        )
        return True
    except (OSError, subprocess.SubprocessError):
        return False
