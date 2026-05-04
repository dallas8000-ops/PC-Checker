from __future__ import annotations

from pc_checker.finding import Finding
from pc_checker.powershell import run_json


def check_pnp_devices() -> list[Finding]:
    """Devices not in OK state (common freeze source: bad drivers / hardware)."""
    findings: list[Finding] = []
    script = """
Get-PnpDevice -ErrorAction SilentlyContinue |
  Where-Object { $_.Status -ne 'OK' -and $_.Present -eq $true } |
  Select-Object -First 25 FriendlyName, Status, Class, InstanceId |
  ForEach-Object {
    [PSCustomObject]@{
      FriendlyName = $_.FriendlyName
      Status = $_.Status.ToString()
      Class = $_.Class
    }
  }
"""
    data = run_json(script)
    if data is None:
        findings.append(
            Finding(
                "warn",
                "Device Manager scan",
                "Could not list PnP devices. Run as Administrator for a fuller scan.",
            )
        )
        return findings

    items = data if isinstance(data, list) else [data] if data else []
    if not items:
        findings.append(Finding("ok", "Problem devices", "No present devices reported outside OK status."))
        return findings

    lines = []
    for row in items:
        if isinstance(row, dict):
            lines.append(
                f"{row.get('FriendlyName', '?')}: {row.get('Status')} ({row.get('Class', '')})"
            )
    detail = "; ".join(lines[:12])
    if len(lines) > 12:
        detail += f" … (+{len(lines) - 12} more)"

    findings.append(
        Finding(
            "warn",
            f"Devices needing attention ({len(items)})",
            detail + ". Problem devices often correlate with freezes or crashes until drivers are fixed.",
        )
    )
    return findings
