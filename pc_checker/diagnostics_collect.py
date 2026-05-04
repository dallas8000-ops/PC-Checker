from __future__ import annotations

from typing import Any

from pc_checker.checks import (
    check_boot_uptime,
    check_critical_events,
    check_disks,
    check_memory,
    check_physical_disks,
    check_pnp_devices,
)
from pc_checker.checks.deep_system import collect_extended_diagnostics
from pc_checker.checks.disk_space_hints import collect_disk_hints
from pc_checker.checks.software import check_application_faults
from pc_checker.finding import Finding
from pc_checker.scan_history import finalize_scan_after_update


def collect_hardware_findings() -> list[Finding]:
    out: list[Finding] = []
    for fn in (
        check_memory,
        check_disks,
        check_boot_uptime,
        check_physical_disks,
        check_pnp_devices,
        check_critical_events,
    ):
        out.extend(fn())
    return out


def apply_full_diagnostics_to_state(state: Any) -> None:
    """Populate hardware + software + disk + extended findings on SharedState (used by web server)."""
    try:
        h = collect_hardware_findings()
        s = check_application_faults()
        try:
            disk = collect_disk_hints()
        except Exception:
            disk = {
                "relocatable_apps": [],
                "deletable_folders": [],
                "program_files_top_level": [],
                "program_files_disclaimer": "",
                "notes": "Disk hints could not be collected on this run.",
            }
        state.set_findings(h)
        state.set_software_findings(s)
        state.set_disk_hints(disk)
    except Exception:
        state.set_findings(
            [
                Finding(
                    "warn",
                    "Scan failed",
                    "An error occurred while running core diagnostics.",
                )
            ]
        )
        state.set_software_findings([])
        state.set_disk_hints(
            {
                "relocatable_apps": [],
                "deletable_folders": [],
                "program_files_top_level": [],
                "program_files_disclaimer": "",
                "notes": "Core diagnostics failed; disk hints not refreshed.",
            }
        )

    try:
        ext = collect_extended_diagnostics()
    except Exception:
        ext = {"sections": {}, "error": "extended_diagnostics_failed"}
    state.set_extended_diagnostics(ext)

    try:
        finalize_scan_after_update(state)
    except Exception:
        state.set_scan_compare_summary("Could not read or write scan history (LocalAppData\\PCChecker).")
