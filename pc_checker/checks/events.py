from __future__ import annotations

from pc_checker.finding import Finding
from pc_checker.powershell import run_json


def check_critical_events() -> list[Finding]:
    """Recent critical/error system events (freeze-related clues)."""
    findings: list[Finding] = []
    script = r"""
$start = (Get-Date).AddHours(-48)
Get-WinEvent -FilterHashtable @{
  LogName = 'System'; Level = 1,2; StartTime = $start
} -MaxEvents 30 -ErrorAction SilentlyContinue |
  ForEach-Object {
    $m = ($_.Message -replace '\s+', ' ')
    if ($m.Length -gt 180) { $m = $m.Substring(0, 180) }
    [PSCustomObject]@{
      TimeCreated = $_.TimeCreated.ToString('s')
      Id = $_.Id
      Provider = $_.ProviderName
      Message = $m
    }
  }
"""
    data = run_json(script)
    if data is None:
        findings.append(
            Finding(
                "warn",
                "System event log",
                "Could not read recent critical/error events (permissions or log access).",
            )
        )
        return findings

    items = data if isinstance(data, list) else [data] if data else []
    if not items:
        findings.append(
            Finding(
                "ok",
                "Recent critical system events",
                "No Level 1/2 System events in the last 48 hours.",
            )
        )
        return findings

    sample = []
    for row in items[:8]:
        if isinstance(row, dict):
            sample.append(
                f"[{row.get('TimeCreated', '')}] {row.get('Provider', '')} Id={row.get('Id')}: {row.get('Message', '')[:120]}"
            )
    detail = " | ".join(sample)
    findings.append(
        Finding(
            "warn",
            f"Recent system errors ({len(items)} in 48h)",
            detail + ". Review Event Viewer for patterns (disk, WHEA, kernel-power).",
            next_steps=(
                "Open Event Viewer → Windows Logs → System; filter Current log on Level Critical/Error.",
                "Reliability Monitor: press Win+R, type perfmon /rel, Enter.",
                "Check Insights tab for 14-day Application/System error trend.",
            ),
        )
    )
    return findings
