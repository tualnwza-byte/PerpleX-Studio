"""Windows desktop-shortcut support for the optional Studio launcher."""

from __future__ import annotations

import base64
import os
from pathlib import Path
from subprocess import run


def _powershell_script(python: Path, working_directory: Path, shortcut: Path) -> str:
    """Return a PowerShell script that writes one Windows shortcut safely."""
    target = str(python).replace("'", "''")
    directory = str(working_directory).replace("'", "''")
    destination = str(shortcut).replace("'", "''")
    return f"""
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut('{destination}')
$shortcut.TargetPath = '{target}'
$shortcut.Arguments = '-m perplex_studio.app'
$shortcut.WorkingDirectory = '{directory}'
$shortcut.IconLocation = '{target},0'
$shortcut.Save()
"""


def create_desktop_shortcut(python: str | Path, working_directory: str | Path) -> Path:
    """Create or replace the user's optional *PerpleX Studio* desktop shortcut."""
    if os.name != "nt":
        raise OSError("Desktop shortcuts are currently supported only on Windows.")
    target = Path(python).resolve()
    directory = Path(working_directory).resolve()
    if not target.is_file():
        raise ValueError(f"Python executable was not found: {target}")
    if not directory.is_dir():
        raise ValueError(f"Studio working directory was not found: {directory}")
    desktop = Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Desktop"
    shortcut = desktop / "PerpleX Studio.lnk"
    script = _powershell_script(target, directory, shortcut)
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    result = run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "unknown PowerShell error"
        raise OSError(f"Could not create desktop shortcut: {message}")
    if not shortcut.is_file():
        raise OSError(f"Desktop shortcut was not created: {shortcut}")
    return shortcut
