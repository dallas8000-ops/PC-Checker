from __future__ import annotations

import psutil

from pc_checker.finding import Finding


def check_memory() -> list[Finding]:
    findings: list[Finding] = []
    vm = psutil.virtual_memory()
    swap = psutil.swap_memory()

    pct_used = vm.percent
    avail_gb = vm.available / (1024**3)
    total_gb = vm.total / (1024**3)

    if pct_used >= 95 or avail_gb < 0.5:
        findings.append(
            Finding(
                "critical",
                "Very low free RAM",
                f"{pct_used:.0f}% in use ({avail_gb:.2f} GB free of {total_gb:.1f} GB). Risk of freezes when memory pressure spikes.",
                next_steps=(
                    "Close the heaviest apps (Task Manager → Processes → sort by Memory).",
                    "Disable non-essential startup apps: Settings → Apps → Startup.",
                    "Check Insights tab → memory commit vs limit after a diagnostics scan.",
                ),
            )
        )
    elif pct_used >= 88 or avail_gb < 1.0:
        findings.append(
            Finding(
                "warn",
                "Low free RAM",
                f"{pct_used:.0f}% in use ({avail_gb:.2f} GB free of {total_gb:.1f} GB). Close heavy apps or add RAM if freezes are common.",
                next_steps=(
                    "Open Task Manager and sort by memory to find outliers.",
                    "Settings → System → Storage → Temporary files (optional cleanup).",
                ),
            )
        )
    else:
        findings.append(
            Finding(
                "ok",
                "RAM headroom",
                f"{pct_used:.0f}% in use, {avail_gb:.2f} GB free of {total_gb:.1f} GB.",
            )
        )

    if swap.percent >= 80 and swap.total > 0:
        findings.append(
            Finding(
                "warn",
                "High page file use",
                f"Page file {swap.percent:.0f}% used. Heavy paging can cause stutter and disk thrashing.",
                next_steps=(
                    "Reduce RAM pressure first (close apps).",
                    "If pagefile is tiny, Windows may expand it on a busy disk — check disk health in Insights.",
                ),
            )
        )
    elif swap.total > 0:
        findings.append(
            Finding(
                "ok",
                "Page file",
                f"Page file {swap.percent:.0f}% used.",
            )
        )

    return findings
