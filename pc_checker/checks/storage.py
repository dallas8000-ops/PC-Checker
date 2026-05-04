from __future__ import annotations

from pc_checker.finding import Finding
from pc_checker.powershell import run_json


def check_physical_disks() -> list[Finding]:
    """Storage subsystem health via Get-PhysicalDisk (Windows 8+)."""
    findings: list[Finding] = []
    script = """
$d = Get-PhysicalDisk -ErrorAction SilentlyContinue
if (-not $d) { @() } else {
  $d | ForEach-Object {
    [PSCustomObject]@{
      FriendlyName = $_.FriendlyName
      MediaType = $_.MediaType.ToString()
      HealthStatus = $_.HealthStatus.ToString()
      OperationalStatus = $_.OperationalStatus.ToString()
    }
  }
}
"""
    data = run_json(script)
    if data is None:
        findings.append(
            Finding(
                "warn",
                "Physical disk health",
                "Could not query physical disks (Storage module unavailable or permission issue).",
            )
        )
        return findings

    items = data if isinstance(data, list) else [data]
    for row in items:
        if not isinstance(row, dict):
            continue
        name = str(row.get("FriendlyName") or "Disk")
        health = str(row.get("HealthStatus") or "")
        op = str(row.get("OperationalStatus") or "")
        media = str(row.get("MediaType") or "")

        if health.upper() == "HEALTHY" and "OK" in op.upper():
            findings.append(
                Finding("ok", f"Disk: {name}", f"{media} — {health}, {op}.")
            )
        elif "UNHEALTHY" in health.upper() or "FAIL" in op.upper():
            findings.append(
                Finding(
                    "critical",
                    f"Unhealthy disk: {name}",
                    f"HealthStatus={health}, OperationalStatus={op}. Back up data and check SMART/drive health.",
                )
            )
        else:
            findings.append(
                Finding(
                    "warn",
                    f"Disk attention: {name}",
                    f"HealthStatus={health}, OperationalStatus={op}, MediaType={media}.",
                )
            )

    if not findings:
        findings.append(Finding("warn", "Physical disks", "No physical disk records returned."))
    return findings
