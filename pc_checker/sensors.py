from __future__ import annotations

import threading
import time
from typing import Any

import psutil

from pc_checker.powershell import run_json

# WMI thermal probe can take many seconds; the GUI calls this every ~1s when psutil
# has no temps — without caching the main thread blocks and the window freezes.
_WMI_TEMPS_LOCK = threading.Lock()
_WMI_TEMPS_CACHE: dict[str, float] | None = None
_WMI_TEMPS_MONO: float = 0.0


def _wmi_ttl_s() -> float:
    try:
        from pc_checker.settings_store import load_settings

        return max(15.0, float(load_settings().wmi_temp_ttl_s))
    except Exception:
        return 45.0


def read_temperatures_c() -> dict[str, float]:
    """Best-effort Celsius readings (often empty on Windows without vendor/OHM drivers)."""
    global _WMI_TEMPS_CACHE, _WMI_TEMPS_MONO
    out: dict[str, float] = {}
    raw: dict[str, Any] = {}
    fn = getattr(psutil, "sensors_temperatures", None)
    if callable(fn):
        try:
            raw = fn() or {}
        except (NotImplementedError, OSError):
            raw = {}
    if raw:
        for name, entries in raw.items():
            if not entries:
                continue
            try:
                cur = float(entries[0].current)
                if cur > -40:
                    out[str(name)] = cur
            except (TypeError, ValueError, IndexError):
                continue

    if out:
        return out

    now = time.monotonic()
    ttl = _wmi_ttl_s()
    with _WMI_TEMPS_LOCK:
        if _WMI_TEMPS_CACHE is not None and (now - _WMI_TEMPS_MONO) < ttl:
            return dict(_WMI_TEMPS_CACHE)

    data = run_json(
        r"""
Get-CimInstance -Namespace root/wmi -Class MSAcpi_ThermalZoneTemperature -ErrorAction SilentlyContinue |
  ForEach-Object {
    $c = ($_.CurrentTemperature / 10) - 273.15
    [PSCustomObject]@{ Celsius = [Math]::Round($c, 1) }
  }
""",
        timeout=15,
    )
    items: list[Any] = data if isinstance(data, list) else [data] if data else []
    for i, row in enumerate(items):
        if isinstance(row, dict) and "Celsius" in row:
            try:
                v = float(row["Celsius"])
                if v > -40:
                    out[f"ThermalZone {i}"] = v
            except (TypeError, ValueError):
                continue

    with _WMI_TEMPS_LOCK:
        _WMI_TEMPS_CACHE = dict(out)
        _WMI_TEMPS_MONO = time.monotonic()
    return out
