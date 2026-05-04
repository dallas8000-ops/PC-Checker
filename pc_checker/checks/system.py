from __future__ import annotations

import time

import psutil

from pc_checker.finding import Finding


def check_boot_uptime() -> list[Finding]:
    findings: list[Finding] = []
    boot = psutil.boot_time()
    uptime_s = time.time() - boot
    days = int(uptime_s // 86400)
    hours = int((uptime_s % 86400) // 3600)

    if days >= 14:
        findings.append(
            Finding(
                "warn",
                "Long uptime without reboot",
                f"~{days}d {hours}h since boot. Occasional reboots clear driver leaks and stuck state after updates.",
            )
        )
    else:
        findings.append(
            Finding(
                "ok",
                "Uptime",
                f"~{days}d {hours}h since last boot.",
            )
        )

    cpu = psutil.cpu_percent(interval=0.5)
    if cpu >= 95:
        findings.append(
            Finding(
                "warn",
                "Sustained high CPU",
                f"Snapshot CPU ~{cpu:.0f}%. If this is typical at idle, find the process in Task Manager.",
            )
        )
    elif cpu >= 80:
        findings.append(
            Finding(
                "warn",
                "Elevated CPU",
                f"Snapshot CPU ~{cpu:.0f}%.",
            )
        )
    else:
        findings.append(Finding("ok", "CPU snapshot", f"~{cpu:.0f}% CPU at sample time (not sustained load test)."))

    return findings
