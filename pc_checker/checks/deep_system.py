"""Extended read-only diagnostics: memory commit, disk reliability counters, startup entries, services, tasks, error-day trend."""

from __future__ import annotations

import sys
from typing import Any

from pc_checker.checks.hardware_identity import collect_hardware_identity
from pc_checker.powershell import run_json


def _mem_pressure() -> dict[str, Any]:
    script = r"""
$out = @{ error = $null; counters = $null }
try {
  $c = Get-Counter '\Memory\Committed Bytes','\Memory\Commit Limit','\Memory\Pool Nonpaged Bytes' -ErrorAction Stop
  $s = $c.CounterSamples
  $m = @{}
  foreach ($x in $s) { $m[$x.Path.Split('\')[-1]] = [Math]::Round($x.CookedValue, 0) }
  $committed = [double]$m['Committed Bytes']
  $limit = [double]$m['Commit Limit']
  $pct = if ($limit -gt 0) { [Math]::Round(100.0 * $committed / $limit, 1) } else { $null }
  $out.counters = [PSCustomObject]@{
    CommittedBytes = $committed
    CommitLimitBytes = $limit
    CommitPercent = $pct
    PoolNonpagedBytes = $m['Pool Nonpaged Bytes']
  }
} catch { $out.error = $_.Exception.Message }
$out
"""
    data = run_json(script, timeout=25)
    return data if isinstance(data, dict) else {"error": "no data"}


def _disk_reliability() -> dict[str, Any]:
    script = r"""
$rows = @()
Get-PhysicalDisk -ErrorAction SilentlyContinue | ForEach-Object {
  $pd = $_
  $c = Get-StorageReliabilityCounter -PhysicalDisk $pd -ErrorAction SilentlyContinue
  $rows += [PSCustomObject]@{
    FriendlyName = $pd.FriendlyName
    MediaType = [string]$pd.MediaType
    HealthStatus = [string]$pd.HealthStatus
    OperationalStatus = [string]$pd.OperationalStatus
    Temperature = if ($c) { $c.Temperature } else { $null }
    Wear = if ($c) { $c.Wear } else { $null }
    ReadErrorsTotal = if ($c) { $c.ReadErrorsTotal } else { $null }
    ReadErrorsUncorrected = if ($c) { $c.ReadErrorsUncorrected } else { $null }
    WriteErrorsTotal = if ($c) { $c.WriteErrorsTotal } else { $null }
    PowerOnHours = if ($c) { $c.PowerOnHours } else { $null }
  }
}
$rows
"""
    data = run_json(script, timeout=45)
    if data is None:
        return {"disks": [], "error": "query failed"}
    rows = data if isinstance(data, list) else [data] if data else []
    return {"disks": rows}


def _startup_items() -> dict[str, Any]:
    script = r"""
function Get-RunValues($path) {
  $p = Get-ItemProperty -LiteralPath $path -ErrorAction SilentlyContinue
  if (-not $p) { return @() }
  $skip = 'PSPath','PSParentPath','PSChildName','PSDrive','PSProvider'
  $p.PSObject.Properties | Where-Object { $_.Name -notin $skip -and $_.Value -and $_.Value.ToString().Trim() } |
    ForEach-Object { [PSCustomObject]@{ HivePath = $path; Name = $_.Name; Command = [string]$_.Value } }
}
$rows = @()
foreach ($path in @(
  'HKLM:\Software\Microsoft\Windows\CurrentVersion\Run',
  'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run',
  'HKLM:\Software\Microsoft\Windows\CurrentVersion\RunOnce',
  'HKCU:\Software\Microsoft\Windows\CurrentVersion\RunOnce'
)) { $rows += Get-RunValues $path }
$rows | Sort-Object HivePath, Name
"""
    data = run_json(script, timeout=35)
    if data is None:
        return {"items": [], "error": "query failed"}
    items = data if isinstance(data, list) else [data] if data else []
    return {"items": items, "note": "Registry Run / RunOnce only; StartupApproved and shell:startup not included."}


def _services_auto_running_nonwindows() -> dict[str, Any]:
    script = r"""
Get-CimInstance Win32_Service -ErrorAction SilentlyContinue |
  Where-Object {
    $_.State -eq 'Running' -and $_.StartMode -eq 'Auto' -and $_.PathName -and
    ($_.PathName -notmatch '(?i)\\Windows\\')
  } |
  Select-Object Name, DisplayName, StartMode, State, PathName |
  Sort-Object DisplayName |
  Select-Object -First 100
"""
    data = run_json(script, timeout=50)
    if data is None:
        return {"services": [], "error": "query failed"}
    rows = data if isinstance(data, list) else [data] if data else []
    return {"services": rows}


def _scheduled_tasks_sample() -> dict[str, Any]:
    script = r"""
Get-ScheduledTask -ErrorAction SilentlyContinue |
  Where-Object { $_.TaskPath -and ($_.TaskPath -notmatch '(?i)^\\Microsoft') } |
  Select-Object -First 55 TaskName, TaskPath, State, @{n='Actions';e={ ($_.Actions | ForEach-Object { $_.Execute + ' ' + $_.Arguments }) -join '; ' }}
"""
    data = run_json(script, timeout=45)
    if data is None:
        return {"tasks": [], "error": "query failed"}
    rows = data if isinstance(data, list) else [data] if data else []
    return {"tasks": rows}


def _reliability_stability() -> dict[str, Any]:
    """Win32_ReliabilityStabilityMetrics + Stability Index counter when available (approx. Reliability Monitor)."""
    script = r"""
$out = @{ cim = @(); counter = $null; error = $null }
try {
  $cim = Get-CimInstance -Namespace root\cimv2 -ClassName Win32_ReliabilityStabilityMetrics -ErrorAction SilentlyContinue |
    Select-Object -First 40 TimeGenerated, SystemStabilityIndex, CustomerId
  if ($cim) { $out.cim = @($cim) }
} catch { $out.error = $_.Exception.Message }
try {
  $c = Get-Counter '\Reliability Metrics\Stability Index' -ErrorAction SilentlyContinue
  if ($c) {
    $s = $c.CounterSamples | Select-Object -First 1
    $out.counter = [PSCustomObject]@{ Value = $s.CookedValue; Path = $s.Path }
  }
} catch { }
$out
"""
    data = run_json(script, timeout=40)
    return data if isinstance(data, dict) else {"error": "no data"}


def _memory_pool_counters() -> dict[str, Any]:
    """Extra Memory performance counters (not per-pool-tag; use Windows Driver Kit poolmon for tags)."""
    script = r"""
$names = @(
  '\Memory\Committed Bytes','\Memory\Commit Limit','\Memory\Pool Nonpaged Bytes','\Memory\Pool Paged Bytes',
  '\Memory\Pool Nonpaged Allocs','\Memory\Pool Paged Allocs','\Memory\Pool Nonpaged Resident Bytes',
  '\Memory\Standby Cache Reserve Bytes','\Memory\Modified Page List Bytes'
)
$rows = @()
try {
  $c = Get-Counter $names -ErrorAction Stop
  foreach ($s in $c.CounterSamples) {
    $short = ($s.Path -split '\\')[-1]
    $rows += [PSCustomObject]@{ Counter = $short; Value = [Math]::Round($s.CookedValue, 0) }
  }
} catch { $rows = @([PSCustomObject]@{ Counter = 'Error'; Value = $_.Exception.Message }) }
$rows
"""
    data = run_json(script, timeout=35)
    if data is None:
        return {"counters": [], "note": "Per-pool tags require poolmon.exe (WDK), not exposed here."}
    rows = data if isinstance(data, list) else [data] if data else []
    return {
        "counters": rows,
        "note": "Aggregate counters only. For driver pool leaks use poolmon / Windows Performance Toolkit ETW.",
    }


def _error_trend_days() -> dict[str, Any]:
    script = r"""
$start = (Get-Date).AddDays(-14)
$app = Get-WinEvent -FilterHashtable @{ LogName='Application'; Level=2,3; StartTime=$start } -MaxEvents 5000 -ErrorAction SilentlyContinue |
  Group-Object { $_.TimeCreated.ToString('yyyy-MM-dd') } | ForEach-Object { [PSCustomObject]@{ Day=$_.Name; ApplicationErrors=$_.Count } }
$sys = Get-WinEvent -FilterHashtable @{ LogName='System'; Level=1,2; StartTime=$start } -MaxEvents 5000 -ErrorAction SilentlyContinue |
  Group-Object { $_.TimeCreated.ToString('yyyy-MM-dd') } | ForEach-Object { [PSCustomObject]@{ Day=$_.Name; SystemCriticalErrors=$_.Count } }
[PSCustomObject]@{ ApplicationByDay = @($app); SystemByDay = @($sys); note = 'Max 5000 events per log; recent days dominate.' }
"""
    data = run_json(script, timeout=90)
    return data if isinstance(data, dict) else {"error": "no data"}


def collect_extended_diagnostics() -> dict[str, Any]:
    if sys.platform != "win32":
        return {"platform": "non-windows", "sections_skipped": True}

    out: dict[str, Any] = {"collected_at": None, "sections": {}}
    import time as _t

    out["collected_at"] = _t.time()

    for key, fn in (
        ("hardware_identity", collect_hardware_identity),
        ("memory_pressure", _mem_pressure),
        ("memory_pool_counters", _memory_pool_counters),
        ("disk_reliability", _disk_reliability),
        ("reliability_stability", _reliability_stability),
        ("startup_items", _startup_items),
        ("services_auto_nonwindows", _services_auto_running_nonwindows),
        ("scheduled_tasks_non_microsoft", _scheduled_tasks_sample),
        ("error_trend_14d", _error_trend_days),
    ):
        try:
            out["sections"][key] = fn()
        except Exception as e:  # noqa: BLE001
            out["sections"][key] = {"error": str(e)}

    return out
