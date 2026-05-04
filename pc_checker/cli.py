from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from pc_checker import APP_ATTRIBUTION, __version__
from pc_checker.checks import (
    check_boot_uptime,
    check_critical_events,
    check_disks,
    check_memory,
    check_physical_disks,
    check_pnp_devices,
)
from pc_checker.checks.disk_space_hints import collect_disk_hints
from pc_checker.checks.software import check_application_faults
from pc_checker.finding import Finding


def _collect() -> list[Finding]:
    out: list[Finding] = []
    for fn in (
        check_memory,
        check_disks,
        check_boot_uptime,
        check_physical_disks,
        check_pnp_devices,
        check_critical_events,
        check_application_faults,
    ):
        out.extend(fn())
    return out


def run_cli() -> int:
    console = Console()

    console.print(
        Panel.fit(
            f"[bold]PC Checker[/bold] v{__version__}\n"
            "Read-only checks for common freeze/malfunction causes on Windows.\n"
            "[dim]Not a substitute for hardware diagnostics or malware scans.[/dim]\n"
            f"[dim]{APP_ATTRIBUTION}[/dim]",
            border_style="cyan",
        )
    )

    findings = _collect()
    sev_order = {"critical": 0, "warn": 1, "ok": 2}
    findings.sort(key=lambda f: (sev_order.get(f.severity, 9), f.title))

    table = Table(show_header=True, header_style="bold", expand=True)
    table.add_column("Severity", width=10)
    table.add_column("Check")
    table.add_column("Detail")

    style_map = {"critical": "red", "warn": "yellow", "ok": "green"}

    for f in findings:
        table.add_row(
            Text(f.severity.upper(), style=style_map.get(f.severity, "white")),
            f.title,
            f.detail,
        )

    console.print(table)

    crit = sum(1 for f in findings if f.severity == "critical")
    warn = sum(1 for f in findings if f.severity == "warn")
    if crit:
        console.print(f"\n[red bold]{crit} critical[/red bold] — address these first.")
    if warn:
        console.print(f"[yellow]{warn} warning(s)[/yellow] — review when you can.")
    if not crit and not warn:
        console.print("\n[green]No warnings or critical items from these checks.[/green]")

    hints = collect_disk_hints()
    console.print("\n[bold cyan]Disk & cleanup hints[/bold cyan] (read-only; see GUI tab for full text)")
    console.print("[dim]" + (hints.get("notes") or "") + "[/dim]")
    if hints.get("program_files_disclaimer"):
        console.print("\n[bold]Program Files note[/bold]\n[dim]" + hints["program_files_disclaimer"] + "[/dim]")
    t_pf = Table(title="Program Files — top-level folder vs. Uninstall registry", expand=True)
    t_pf.add_column("Status", max_width=28)
    t_pf.add_column("Path", max_width=56)
    t_pf.add_column("Sample products", max_width=40)
    for row in (hints.get("program_files_top_level") or [])[:60]:
        prods = row.get("matched_products") or []
        sample = "; ".join(str(p) for p in prods[:3])
        if row.get("matched_products_note"):
            sample = (sample + " " + row["matched_products_note"]).strip()
        t_pf.add_row(str(row.get("status", "")), str(row.get("path", ""))[:120], sample[:120])
    console.print(t_pf)
    t_apps = Table(title="Apps — install folder heuristics", expand=True)
    t_apps.add_column("Name", max_width=36)
    t_apps.add_column("Category", max_width=22)
    t_apps.add_column("Path", max_width=52)
    for r in (hints.get("relocatable_apps") or [])[:45]:
        t_apps.add_row(
            str(r.get("name", ""))[:80],
            str(r.get("category", "")),
            str(r.get("install_location", ""))[:120],
        )
    console.print(t_apps)
    t_fold = Table(title="Folders — trim candidates (if folder exists)", expand=True)
    t_fold.add_column("Risk", width=8)
    t_fold.add_column("Label", max_width=28)
    t_fold.add_column("Path", max_width=52)
    for r in hints.get("deletable_folders") or []:
        sz = r.get("size_note") or ("~%s MB" % r["size_mb"] if r.get("size_mb") is not None else "—")
        t_fold.add_row(
            str(r.get("risk", "")).upper(),
            str(r.get("label", "")),
            f"{r.get('path', '')}  ({sz})",
        )
    console.print(t_fold)

    console.print(
        "\n[dim]Tip: run from an elevated terminal for fuller event/device data. "
        "For random hard freezes, also check Reliability Monitor and run memory/disk tests outside this tool.[/dim]"
    )
    return 1 if crit else 0
