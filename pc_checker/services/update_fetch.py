from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
from typing import Any

from pc_checker.powershell import _powershell_exe, run_json
from pc_checker.state import SharedState


def get_defender_status() -> dict[str, Any]:
    script = r"""
try {
  $s = Get-MpComputerStatus
  [PSCustomObject]@{
    AntivirusEnabled = [bool]$s.AntivirusEnabled
    RealTimeProtectionEnabled = [bool]$s.RealTimeProtectionEnabled
    AntivirusSignatureLastUpdated = if ($s.AntivirusSignatureLastUpdated) { $s.AntivirusSignatureLastUpdated.ToString('s') } else { $null }
    AntispywareSignatureLastUpdated = if ($s.AntispywareSignatureLastUpdated) { $s.AntispywareSignatureLastUpdated.ToString('s') } else { $null }
    NISSignatureLastUpdated = if ($s.NISSignatureLastUpdated) { $s.NISSignatureLastUpdated.ToString('s') } else { $null }
    QuickScanStartTime = if ($s.QuickScanStartTime) { $s.QuickScanStartTime.ToString('s') } else { $null }
    FullScanStartTime = if ($s.FullScanStartTime) { $s.FullScanStartTime.ToString('s') } else { $null }
    QuickScanAge = $s.QuickScanAge.ToString()
    FullScanAge = $s.FullScanAge.ToString()
    EngineVersion = $s.AMEngineVersion
    AntivirusSignatureVersion = $s.AntivirusSignatureVersion
  }
} catch {
  [PSCustomObject]@{ error = $_.Exception.Message }
}
"""
    data = run_json(script, timeout=30)
    if data is None:
        return {"error": "Get-MpComputerStatus failed (Microsoft Defender WMI/Cmdlet unavailable or access denied)."}
    if isinstance(data, list) and len(data) == 1 and isinstance(data[0], dict):
        data = data[0]
    if isinstance(data, dict) and data.get("error"):
        return {"error": str(data["error"])}
    return data if isinstance(data, dict) else {"raw": data}


def get_pending_windows_updates() -> tuple[list[dict[str, Any]], str | None]:
    script = r"""
$ErrorActionPreference = 'Stop'
try {
  $session = New-Object -ComObject Microsoft.Update.Session
  $searcher = $session.CreateUpdateSearcher()
  $result = $searcher.Search("IsInstalled=0 and IsHidden=0 and Type='Software'")
  $list = New-Object System.Collections.Generic.List[object]
  for ($i = 0; $i -lt $result.Updates.Count; $i++) {
    $u = $result.Updates.Item($i)
    $list.Add([PSCustomObject]@{
      Title = $u.Title
      IsMandatory = [bool]$u.IsMandatory
      RebootRequired = [bool]$u.RebootRequired
    })
  }
  $list
} catch {
  @([PSCustomObject]@{ error = $_.Exception.Message })
}
"""
    data = run_json(script, timeout=180)
    if data is None:
        return [], "Windows Update search failed (COM timeout, policy, or no connectivity)."
    items = data if isinstance(data, list) else [data]
    if items and isinstance(items[0], dict) and items[0].get("error"):
        return [], str(items[0]["error"])
    clean: list[dict[str, Any]] = []
    for row in items:
        if isinstance(row, dict) and "Title" in row:
            clean.append(
                {
                    "title": row.get("Title"),
                    "mandatory": bool(row.get("IsMandatory")),
                    "reboot_required": bool(row.get("RebootRequired")),
                }
            )
    return clean, None


def get_winget_upgrades() -> tuple[list[dict[str, Any]], str | None]:
    exe = shutil.which("winget.exe")
    if not exe:
        wing = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WindowsApps", "winget.exe")
        if os.path.isfile(wing):
            exe = wing
    if not exe:
        return [], "winget.exe not found. Install App Installer from the Microsoft Store."

    proc = subprocess.run(
        [
            exe,
            "upgrade",
            "--source",
            "winget",
            "--output",
            "json",
            "--accept-source-agreements",
            "--disable-interactivity",
        ],
        capture_output=True,
        text=True,
        timeout=180,
        creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
    )
    if proc.returncode != 0 and not proc.stdout.strip():
        err = (proc.stderr or proc.stdout or "").strip() or f"exit {proc.returncode}"
        return [], err
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return [], "Could not parse winget JSON output."

    items: list[dict[str, Any]] = []
    if isinstance(data, list):
        rows = data
    elif isinstance(data, dict):
        rows = (
            data.get("UpgradeResult", {}).get("Results")
            or data.get("Packages")
            or data.get("Data")
            or []
        )
        if not isinstance(rows, list):
            rows = []
    else:
        rows = []

    for row in rows:
        if not isinstance(row, dict):
            continue
        name = row.get("Name") or row.get("name")
        pid = row.get("Id") or row.get("id")
        ver = row.get("InstalledVersion") or row.get("InstalledVer")
        avail = row.get("AvailableVersion") or row.get("AvailableVer")
        if name or pid:
            items.append(
                {
                    "name": name,
                    "id": pid,
                    "installed_version": ver,
                    "available_version": avail,
                    "source": row.get("Source") or row.get("source"),
                }
            )
    return items, None


def trigger_defender_signature_update() -> tuple[bool, str]:
    ps = _powershell_exe()
    if not ps:
        return False, "PowerShell not found."
    proc = subprocess.run(
        [ps, "-NoProfile", "-NonInteractive", "-Command", "Update-MpSignature"],
        capture_output=True,
        text=True,
        timeout=300,
        creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
    )
    msg = (proc.stderr or proc.stdout or "").strip()
    if proc.returncode == 0:
        return True, msg or "Update-MpSignature completed."
    return False, msg or f"Update-MpSignature failed (exit {proc.returncode}). Try running PC Checker as Administrator."


def trigger_windows_update_scan() -> tuple[bool, str]:
    uso = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "UsoClient.exe")
    if not os.path.isfile(uso):
        return False, "UsoClient.exe not found."
    proc = subprocess.run(
        [uso, "StartScan"],
        capture_output=True,
        text=True,
        timeout=30,
        creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
    )
    if proc.returncode == 0:
        return True, "Windows Update scan requested (UsoClient StartScan)."
    return False, (proc.stderr or proc.stdout or "").strip() or f"UsoClient exit {proc.returncode}"


def fetch_all_updates(state: SharedState) -> None:
    state.set_updates_refresh_busy(True)
    try:
        state.set_defender(get_defender_status())
        wu, wu_err = get_pending_windows_updates()
        state.set_windows_updates(wu, wu_err)
        wg, wg_err = get_winget_upgrades()
        state.set_winget(wg, wg_err)
    finally:
        state.set_updates_refresh_busy(False)


def schedule_updates_refresh(state: SharedState) -> None:
    def worker() -> None:
        fetch_all_updates(state)

    threading.Thread(target=worker, daemon=True).start()
