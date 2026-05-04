"""Run PowerShell snippets and parse JSON output."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Any


def _powershell_exe() -> str | None:
    for name in ("powershell.exe", "pwsh.exe"):
        path = shutil.which(name)
        if path:
            return path
    sys32 = os.environ.get("SystemRoot", r"C:\Windows")
    legacy = os.path.join(sys32, "System32", "WindowsPowerShell", "v1.0", "powershell.exe")
    if os.path.isfile(legacy):
        return legacy
    return None


def run_json(script: str, timeout: int = 45) -> Any:
    """Execute a PowerShell script that ends with ConvertTo-Json. Returns parsed JSON or None on failure."""
    exe = _powershell_exe()
    if not exe:
        return None
    full = f"& {{ {script} }} | ConvertTo-Json -Depth 6 -Compress"
    proc = subprocess.run(
        [exe, "-NoProfile", "-NonInteractive", "-Command", full],
        capture_output=True,
        text=True,
        timeout=timeout,
        creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None
