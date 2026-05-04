from __future__ import annotations

from pc_checker.finding import Finding
from pc_checker.powershell import run_json


def check_application_faults() -> list[Finding]:
    """Application / Admin log errors that often point to misbehaving software or drivers."""
    findings: list[Finding] = []
    script = r"""
$start = (Get-Date).AddHours(-72)
$ev = Get-WinEvent -FilterHashtable @{
  LogName = 'Application'
  Level = 2,3
  StartTime = $start
} -MaxEvents 120 -ErrorAction SilentlyContinue
if (-not $ev) { @() } else {
  $ev | Group-Object ProviderName, Id |
    Sort-Object Count -Descending |
    Select-Object -First 18 |
    ForEach-Object {
      $g = $_.Group[0]
      $msg = ($g.Message -replace '\s+', ' ')
      if ($msg.Length -gt 220) { $msg = $msg.Substring(0, 220) }
      [PSCustomObject]@{
        Count = $_.Count
        ProviderName = $g.ProviderName
        Id = $g.Id
        SampleMessage = $msg
      }
    }
}
"""
    data = run_json(script, timeout=60)
    if data is None:
        findings.append(
            Finding(
                "warn",
                "Application error log",
                "Could not read Application log (permissions or policy). Run as Administrator for a fuller view.",
            )
        )
        return findings

    items = data if isinstance(data, list) else [data] if data else []
    if not items:
        findings.append(
            Finding(
                "ok",
                "Application errors (72h)",
                "No Level 2/3 Application events in the last 72 hours.",
            )
        )
        return findings

    hot = [x for x in items if isinstance(x, dict) and int(x.get("Count") or 0) >= 8]
    for row in hot[:5]:
        c = int(row.get("Count") or 0)
        prov = row.get("ProviderName") or "?"
        eid = row.get("Id")
        msg = (row.get("SampleMessage") or "")[:400]
        sev = "critical" if c >= 25 else "warn"
        findings.append(
            Finding(
                sev,
                f"Repeated app errors: {prov} (Id {eid})",
                f"{c} similar events in 72h. Sample: {msg}",
            )
        )

    if not hot:
        row = items[0] if items else {}
        c = int(row.get("Count") or 0) if isinstance(row, dict) else 0
        prov = row.get("ProviderName") if isinstance(row, dict) else ""
        findings.append(
            Finding(
                "warn",
                "Application errors (72h)",
                f"Found {len(items)} error groups; largest is {c}x from {prov}. Open Event Viewer → Application for details.",
            )
        )
    elif len(hot) > 5:
        findings.append(
            Finding(
                "warn",
                "Many noisy application errors",
                f"{len(hot)} providers show high volume. Review the hottest entries above and uninstall or update those apps.",
            )
        )

    return findings
