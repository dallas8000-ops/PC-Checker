"""Disk volume summary for API and cloud webhook payloads (Windows psutil)."""

from __future__ import annotations

from typing import Any

import psutil


def volumes_snapshot() -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for part in psutil.disk_partitions(all=False):
        try:
            u = psutil.disk_usage(part.mountpoint)
        except OSError:
            continue
        total = u.total or 1
        rows.append(
            {
                "device": part.device or part.mountpoint,
                "mountpoint": part.mountpoint,
                "free_percent": round(100.0 * u.free / total, 2),
                "used_percent": round(100.0 * u.used / total, 2),
            }
        )
    return {"volumes": rows}
