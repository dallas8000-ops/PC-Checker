from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any

from pc_checker.finding import Finding


def finding_to_dict(f: Finding) -> dict[str, Any]:
    d: dict[str, Any] = {"severity": f.severity, "title": f.title, "detail": f.detail}
    if f.next_steps:
        d["next_steps"] = list(f.next_steps)
    return d


class SharedState:
    """Thread-safe snapshot for the GUI and local HTTP API."""

    def __init__(self, history_len: int = 180) -> None:
        self._lock = threading.Lock()
        self._history_ts: deque[float] = deque(maxlen=history_len)
        self._history_cpu: deque[float] = deque(maxlen=history_len)
        self._history_ram: deque[float] = deque(maxlen=history_len)
        self._live: dict[str, Any] = {}
        self._findings: list[dict[str, str]] = []
        self._software_findings: list[dict[str, str]] = []
        self._disk_hints: dict[str, Any] = {
            "relocatable_apps": [],
            "deletable_folders": [],
            "program_files_top_level": [],
            "program_files_disclaimer": "",
            "notes": "Run a diagnostics scan (Diagnostics tab) to load app paths and cleanup folder hints.",
        }
        self._top_processes: list[dict[str, Any]] = []
        self._defender: dict[str, Any] = {}
        self._windows_updates: dict[str, Any] = {"items": [], "error": None, "fetched_at": None}
        self._winget: dict[str, Any] = {"items": [], "error": None, "fetched_at": None}
        self._updates_refresh_busy = False
        self._extended_diagnostics: dict[str, Any] = {}
        self._scan_compare_summary: str = ""

    def record_live_sample(
        self,
        *,
        cpu: float,
        ram_percent: float,
        ram_available_gb: float,
        ram_total_gb: float,
        per_cpu: list[float],
        temps_c: dict[str, float],
        disk_read_mbps: float,
        disk_write_mbps: float,
        swap_percent: float | None = None,
        swap_used_gb: float | None = None,
        swap_total_gb: float | None = None,
        uptime_seconds: float | None = None,
    ) -> None:
        ts = time.time()
        with self._lock:
            self._history_ts.append(ts)
            self._history_cpu.append(cpu)
            self._history_ram.append(ram_percent)
            self._live = {
                "timestamp": ts,
                "cpu_percent": cpu,
                "ram_percent": ram_percent,
                "ram_available_gb": ram_available_gb,
                "ram_total_gb": ram_total_gb,
                "per_cpu_percent": per_cpu,
                "temperatures_c": temps_c,
                "disk_read_mbps": disk_read_mbps,
                "disk_write_mbps": disk_write_mbps,
                "swap_percent": swap_percent,
                "swap_used_gb": swap_used_gb,
                "swap_total_gb": swap_total_gb,
                "uptime_seconds": uptime_seconds,
            }

    def get_live_bundle(self) -> dict[str, Any]:
        with self._lock:
            return {
                "live": dict(self._live),
                "history": {
                    "timestamp": list(self._history_ts),
                    "cpu_percent": list(self._history_cpu),
                    "ram_percent": list(self._history_ram),
                },
                "top_processes": list(self._top_processes),
            }

    def set_top_processes(self, rows: list[dict[str, Any]]) -> None:
        with self._lock:
            self._top_processes = list(rows)

    def set_findings(self, findings: list[Finding]) -> None:
        with self._lock:
            self._findings = [finding_to_dict(f) for f in findings]

    def set_software_findings(self, findings: list[Finding]) -> None:
        with self._lock:
            self._software_findings = [finding_to_dict(f) for f in findings]

    def set_disk_hints(self, data: dict[str, Any]) -> None:
        with self._lock:
            self._disk_hints = {
                "relocatable_apps": list(data.get("relocatable_apps") or []),
                "deletable_folders": list(data.get("deletable_folders") or []),
                "program_files_top_level": list(data.get("program_files_top_level") or []),
                "program_files_disclaimer": str(data.get("program_files_disclaimer") or ""),
                "notes": str(data.get("notes") or ""),
            }

    def set_extended_diagnostics(self, data: dict[str, Any]) -> None:
        with self._lock:
            self._extended_diagnostics = dict(data)

    def set_scan_compare_summary(self, text: str) -> None:
        with self._lock:
            self._scan_compare_summary = str(text)

    def get_diagnostics_bundle(self) -> dict[str, Any]:
        with self._lock:
            return {
                "findings": list(self._findings),
                "software_findings": list(self._software_findings),
                "disk_hints": dict(self._disk_hints),
                "extended": dict(self._extended_diagnostics),
                "scan_compare_summary": self._scan_compare_summary,
            }

    def export_snapshot(self) -> dict[str, Any]:
        """Full read-only bundle for JSON/HTML export (caller supplies host meta)."""
        with self._lock:
            return {
                "export_format": 1,
                "live": dict(self._live),
                "findings": list(self._findings),
                "software_findings": list(self._software_findings),
                "disk_hints": dict(self._disk_hints),
                "extended": dict(self._extended_diagnostics),
                "updates": {
                    "defender": dict(self._defender),
                    "windows_update": dict(self._windows_updates),
                    "winget": dict(self._winget),
                },
                "top_processes": list(self._top_processes),
            }

    def set_defender(self, data: dict[str, Any]) -> None:
        with self._lock:
            self._defender = dict(data)

    def set_windows_updates(self, items: list[dict[str, Any]], error: str | None) -> None:
        with self._lock:
            self._windows_updates = {
                "items": list(items),
                "error": error,
                "fetched_at": time.time(),
            }

    def set_winget(self, items: list[dict[str, Any]], error: str | None) -> None:
        with self._lock:
            self._winget = {
                "items": list(items),
                "error": error,
                "fetched_at": time.time(),
            }

    def get_updates_bundle(self) -> dict[str, Any]:
        with self._lock:
            return {
                "defender": dict(self._defender),
                "windows_update": dict(self._windows_updates),
                "winget": dict(self._winget),
                "refresh_busy": self._updates_refresh_busy,
            }

    def get_history_lists(self) -> tuple[list[float], list[float], list[float]]:
        with self._lock:
            return (
                list(self._history_ts),
                list(self._history_cpu),
                list(self._history_ram),
            )

    def set_updates_refresh_busy(self, busy: bool) -> None:
        with self._lock:
            self._updates_refresh_busy = busy
