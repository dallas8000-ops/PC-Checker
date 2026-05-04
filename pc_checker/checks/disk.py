from __future__ import annotations

import psutil

from pc_checker.finding import Finding


def check_disks() -> list[Finding]:
    findings: list[Finding] = []
    for part in psutil.disk_partitions(all=False):
        try:
            usage = psutil.disk_usage(part.mountpoint)
        except (PermissionError, OSError):
            continue
        free_pct = 100.0 * usage.free / usage.total if usage.total else 100.0
        label = part.device or part.mountpoint
        if free_pct < 3:
            findings.append(
                Finding(
                    "critical",
                    f"Critically low space on {label}",
                    f"{free_pct:.1f}% free ({usage.free // (1024**3)} GB). Low disk space can crash apps and break updates.",
                )
            )
        elif free_pct < 10:
            findings.append(
                Finding(
                    "warn",
                    f"Low space on {label}",
                    f"{free_pct:.1f}% free. Windows and apps need spare space for temp files and paging.",
                )
            )
        else:
            findings.append(
                Finding(
                    "ok",
                    f"Disk space {label}",
                    f"{free_pct:.0f}% free.",
                )
            )
    if not findings:
        findings.append(Finding("warn", "Disk partitions", "Could not read disk usage (permissions or mount points)."))
    return findings
