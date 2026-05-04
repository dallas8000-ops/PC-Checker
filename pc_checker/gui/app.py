from __future__ import annotations

import json
import logging
import os
import platform
import queue
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, cast

import customtkinter as ctk
import psutil

from pc_checker import APP_ATTRIBUTION, __version__
from pc_checker.api.server import start_api_background
from pc_checker.elevation import hide_attached_console_window, is_admin
from pc_checker.checks.deep_system import collect_extended_diagnostics
from pc_checker.checks.disk_space_hints import collect_disk_hints
from pc_checker.checks.software import check_application_faults
from pc_checker.diagnostics_collect import collect_hardware_findings
from pc_checker.export_report import write_html_report, write_json_report, write_pdf_report
from pc_checker.background_services import start_background_services, stop_tray_if_present
from pc_checker.settings_store import AppSettings, load_settings, save_settings
from pc_checker.scan_history import finalize_scan_after_update, snapshot_path
from pc_checker.finding import Finding
from pc_checker.gui.chart_panel import LiveTrendChart
from pc_checker.sensors import read_temperatures_c
from pc_checker.services.update_fetch import schedule_updates_refresh
from pc_checker.state import SharedState


class PCCheckerApp(ctk.CTk):
    def __init__(self, *, enable_api: bool = True) -> None:
        super().__init__()
        self.title(f"PC Checker v{__version__} — personal · not for distribution")
        self.geometry("1000x780")
        self.minsize(860, 620)

        self._st = load_settings()
        self._live_interval_ms = int(self._st.live_poll_ms)
        self._view_interval_ms = int(self._st.view_poll_ms)
        self._diag_interval_ms = int(self._st.diag_interval_ms)
        self._queue_poll_ms = int(self._st.queue_poll_ms)
        self._after_ids: dict[str, str | None] = {"live": None, "view": None, "queue": None, "diag": None}

        # Not named "state" — that shadows Tk/CTk's window state() method and crashes the UI.
        self.shared = SharedState()
        self._api_url: str | None = None
        if enable_api:
            try:
                self._api_url = start_api_background(self.shared)
            except Exception:
                self._api_url = None

        self._result_queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        self._diag_busy = False
        self._io_prev: Any = None
        self._io_tprev: float | None = None
        self._disk_rows: list[tuple[str, ctk.CTkProgressBar, ctk.CTkLabel]] = []
        self._core_rows: list[ctk.CTkProgressBar] = []
        self._sampler_stop = threading.Event()
        self._insights_txt: ctk.CTkTextbox | None = None
        self._footer_lbl: ctk.CTkLabel | None = None
        self._settings_entries: dict[str, Any] = {}

        self._build_ui()
        psutil.cpu_percent(interval=None)
        self._start_process_sampler()
        self._schedule_live()
        self._schedule_queue_poll()
        self._schedule_view_poll()
        self.after(400, self._request_diagnostics)
        self._after_ids["diag"] = self.after(self._diag_interval_ms, self._diag_timer)
        self.after(1500, lambda: schedule_updates_refresh(self.shared))

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_close(self) -> None:
        self._sampler_stop.set()
        try:
            stop_tray_if_present(self)
        except Exception:
            logging.getLogger(__name__).debug("tray stop", exc_info=True)
        self.destroy()

    def _start_process_sampler(self) -> None:
        stop = self._sampler_stop

        def loop() -> None:
            while not stop.is_set():
                try:
                    for p in psutil.process_iter(["pid", "name"]):
                        try:
                            p.cpu_percent(interval=None)
                        except (psutil.Error, OSError):
                            pass
                    time.sleep(0.28)
                    rows: list[dict[str, Any]] = []
                    for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]):
                        try:
                            rows.append(
                                {
                                    "pid": p.info["pid"],
                                    "name": (p.info["name"] or "?"),
                                    "cpu_percent": float(p.cpu_percent() or 0.0),
                                    "memory_percent": float(p.memory_percent() or 0.0),
                                }
                            )
                        except (psutil.Error, OSError, TypeError, ValueError):
                            continue
                    rows.sort(key=lambda r: r["cpu_percent"], reverse=True)
                    self.shared.set_top_processes(rows[:32])
                except Exception:
                    pass
                stop.wait(3.2)

        threading.Thread(target=loop, daemon=True).start()

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)

        tabs_row = 0
        if not is_admin():
            banner = ctk.CTkFrame(self, fg_color=("#3d2a1a", "#3d2a1a"))
            banner.grid(row=0, column=0, sticky="ew", padx=12, pady=(10, 0))
            ctk.CTkLabel(
                banner,
                text=(
                    "Not running as administrator — some Event Log reads, Windows Update catalog search, "
                    "and Defender maintenance actions may be limited. Close this window and run again to accept the "
                    "UAC prompt, use Run as administrator, or start with --no-elevate to skip elevation."
                ),
                wraplength=920,
                anchor="w",
                justify="left",
                text_color="#f5cba7",
            ).pack(fill="x", padx=10, pady=8)
            tabs_row = 1
            self.grid_rowconfigure(0, weight=0)

        self.grid_rowconfigure(tabs_row, weight=1)
        self._ui_tabs_row = tabs_row

        tabs = ctk.CTkTabview(self)
        tabs.grid(row=tabs_row, column=0, sticky="nsew", padx=12, pady=12)

        tabs.add("Live")
        tabs.add("Software")
        tabs.add("Updates & API")
        tabs.add("Diagnostics")
        tabs.add("Disk & cleanup")
        tabs.add("Settings")
        tabs.add("Insights & export")

        self._build_live_tab(tabs.tab("Live"))
        self._build_software_tab(tabs.tab("Software"))
        self._build_updates_tab(tabs.tab("Updates & API"))
        self._build_diagnostics_tab(tabs.tab("Diagnostics"))
        self._build_disk_cleanup_tab(tabs.tab("Disk & cleanup"))
        self._build_settings_tab(tabs.tab("Settings"))
        self._build_insights_tab(tabs.tab("Insights & export"))

        self._footer_lbl = ctk.CTkLabel(
            self,
            text=APP_ATTRIBUTION,
            anchor="center",
            justify="center",
            wraplength=960,
            font=ctk.CTkFont(size=11),
            text_color="gray",
        )
        self._footer_lbl.grid(row=self._ui_tabs_row + 1, column=0, sticky="ew", padx=16, pady=(0, 10))
        if self._st.hide_attribution_banner:
            self._footer_lbl.grid_remove()
        self.grid_rowconfigure(tabs_row + 1, weight=0)

    def _build_live_tab(self, live: ctk.CTkFrame) -> None:
        live.grid_columnconfigure(0, weight=1)
        scroll = ctk.CTkScrollableFrame(live, fg_color="transparent")
        scroll.grid(row=0, column=0, sticky="nsew")
        live.grid_rowconfigure(0, weight=1)

        hdr = ctk.CTkLabel(
            scroll,
            text="Live metrics (CPU/RAM/disk/temp). Spikes are normal; sustained maxed values + errors in other tabs point to causes.",
            font=ctk.CTkFont(size=13),
            anchor="w",
        )
        hdr.pack(fill="x", pady=(0, 6))

        self._chart = LiveTrendChart(scroll, height=260)
        self._chart.pack(fill="x", pady=(0, 10))

        self._cpu_bar = ctk.CTkProgressBar(scroll, width=400)
        self._cpu_bar.pack(fill="x", pady=4)
        self._cpu_bar.set(0)
        self._cpu_lbl = ctk.CTkLabel(scroll, text="CPU (all cores): —", anchor="w")
        self._cpu_lbl.pack(fill="x")

        self._ram_bar = ctk.CTkProgressBar(scroll, width=400)
        self._ram_bar.pack(fill="x", pady=(12, 4))
        self._ram_bar.set(0)
        self._ram_lbl = ctk.CTkLabel(scroll, text="RAM: —", anchor="w")
        self._ram_lbl.pack(fill="x")

        self._swap_lbl = ctk.CTkLabel(scroll, text="Page file: —", anchor="w")
        self._swap_lbl.pack(fill="x", pady=(4, 0))

        self._temp_lbl = ctk.CTkLabel(scroll, text="Temperature: —", anchor="w", text_color="#aed6f1")
        self._temp_lbl.pack(fill="x", pady=(10, 4))

        ctk.CTkLabel(scroll, text="Per-logical-CPU load", font=ctk.CTkFont(weight="bold")).pack(anchor="w", pady=(8, 4))
        self._cores_scroll = ctk.CTkScrollableFrame(scroll, height=160)
        self._cores_scroll.pack(fill="x", pady=(0, 8))

        io_fr = ctk.CTkFrame(scroll, fg_color="transparent")
        io_fr.pack(fill="x", pady=(8, 4))
        ctk.CTkLabel(io_fr, text="Disk I/O (aggregate)", font=ctk.CTkFont(weight="bold")).pack(anchor="w")
        self._io_lbl = ctk.CTkLabel(io_fr, text="Read: — MB/s   Write: — MB/s", anchor="w")
        self._io_lbl.pack(anchor="w")

        ctk.CTkLabel(scroll, text="Disk space by volume", font=ctk.CTkFont(weight="bold")).pack(anchor="w", pady=(12, 4))
        self._disk_frame = ctk.CTkScrollableFrame(scroll, height=200)
        self._disk_frame.pack(fill="both", expand=True, pady=(0, 8))

        self._boot_lbl = ctk.CTkLabel(scroll, text="Uptime: —", anchor="w")
        self._boot_lbl.pack(fill="x")
        self._cores_meta = ctk.CTkLabel(scroll, text="Logical processors: —", anchor="w", text_color="gray")
        self._cores_meta.pack(fill="x", pady=(6, 0))

        api_txt = self._api_url or "Local API disabled (--no-api or failed to bind)."
        self._api_hint = ctk.CTkLabel(scroll, text=f"API: {api_txt}  ·  OpenAPI docs at /docs", anchor="w", text_color="gray")
        self._api_hint.pack(fill="x", pady=(10, 0))

    def _build_software_tab(self, tab: ctk.CTkFrame) -> None:
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(
            tab,
            text="Software stress: high CPU/memory processes (sampled) plus Application log error patterns.",
            anchor="w",
            wraplength=900,
        ).grid(row=0, column=0, sticky="ew", pady=(0, 8))

        self._software_txt = ctk.CTkTextbox(tab, font=ctk.CTkFont(family="Consolas", size=12))
        self._software_txt.grid(row=1, column=0, sticky="nsew")

    def _build_updates_tab(self, tab: ctk.CTkFrame) -> None:
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(2, weight=1)

        top = ctk.CTkFrame(tab, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        ctk.CTkButton(top, text="Refresh update data", command=lambda: schedule_updates_refresh(self.shared)).pack(
            side="left", padx=(0, 8)
        )
        ctk.CTkButton(
            top,
            text="Update Defender signatures",
            command=self._gui_defender_update,
        ).pack(side="left", padx=(0, 8))
        ctk.CTkButton(top, text="Request Windows Update scan", command=self._gui_wu_scan).pack(side="left")

        self._updates_status = ctk.CTkLabel(tab, text="", anchor="w", text_color="gray")
        self._updates_status.grid(row=1, column=0, sticky="ew")

        self._updates_txt = ctk.CTkTextbox(tab, font=ctk.CTkFont(family="Consolas", size=11))
        self._updates_txt.grid(row=2, column=0, sticky="nsew")
        tab.grid_rowconfigure(2, weight=1)

    def _build_diagnostics_tab(self, diag: ctk.CTkFrame) -> None:
        diag.grid_columnconfigure(0, weight=1)
        diag.grid_rowconfigure(1, weight=1)

        top = ctk.CTkFrame(diag, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        top.grid_columnconfigure(1, weight=1)

        self._diag_status = ctk.CTkLabel(top, text="Last hardware scan: never", anchor="w")
        self._diag_status.grid(row=0, column=0, sticky="w")

        refresh = ctk.CTkButton(top, text="Scan now", width=100, command=self._request_diagnostics)
        refresh.grid(row=0, column=2, padx=(8, 0))

        self._summary_lbl = ctk.CTkLabel(top, text="", anchor="w", font=ctk.CTkFont(weight="bold"))
        self._summary_lbl.grid(row=1, column=0, columnspan=3, sticky="w", pady=(4, 0))

        self._findings_frame = ctk.CTkScrollableFrame(diag)
        self._findings_frame.grid(row=1, column=0, sticky="nsew")

        foot = ctk.CTkLabel(
            diag,
            text="Hardware / system scan. Run as Administrator for richer event/device data.",
            text_color="gray",
            wraplength=900,
            anchor="w",
        )
        foot.grid(row=2, column=0, sticky="ew", pady=(8, 0))

    def _build_disk_cleanup_tab(self, tab: ctk.CTkFrame) -> None:
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(2, weight=1)
        ctk.CTkLabel(
            tab,
            text=(
                "Install locations from the uninstall registry (heuristic categories), Program Files folder "
                "cross-check (needed vs. no registry match — not proof of unused), and common folders that are "
                "often trimmed for space. PC Checker does not move or delete anything — use Settings, Disk Cleanup, "
                "or each app's own tools. Refresh: run Scan now on Diagnostics (or wait for the scheduled scan)."
            ),
            anchor="w",
            wraplength=900,
        ).grid(row=0, column=0, sticky="ew", pady=(0, 6))
        top = ctk.CTkFrame(tab, fg_color="transparent")
        top.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        ctk.CTkButton(top, text="Copy report to clipboard", command=self._copy_disk_report).pack(side="left")

        self._disk_cleanup_txt = ctk.CTkTextbox(tab, font=ctk.CTkFont(family="Consolas", size=11))
        self._disk_cleanup_txt.grid(row=2, column=0, sticky="nsew")
        self._last_disk_report = ""
        self._refresh_disk_cleanup_text()

    def _copy_disk_report(self) -> None:
        if self._last_disk_report:
            self.clipboard_clear()
            self.clipboard_append(self._last_disk_report)

    def _refresh_disk_cleanup_text(self) -> None:
        if not hasattr(self, "_disk_cleanup_txt"):
            return
        d = self.shared.get_diagnostics_bundle().get("disk_hints") or {}
        lines: list[str] = []
        lines.append(d.get("notes") or "")
        disc = d.get("program_files_disclaimer")
        if disc:
            lines.append("\n--- Program Files & redundancy ---\n")
            lines.append(str(disc))
        lines.append("\n=== Program Files / Program Files (x86) — top-level folders vs. Uninstall registry ===\n")
        for row in d.get("program_files_top_level") or []:
            st = row.get("status", "")
            lines.append(f"[{st}] {row.get('path', '')}")
            prods = row.get("matched_products") or []
            if prods:
                lines.append("    Listed products (sample): " + "; ".join(str(p) for p in prods))
            note = row.get("matched_products_note")
            if note:
                lines.append(f"    {note}")
            lines.append(f"    {row.get('detail', '')}\n")
        lines.append("\n=== Apps (install folder — category — how to move safely) ===\n")
        for a in d.get("relocatable_apps") or []:
            lines.append(f"[{a.get('category', '')}] {a.get('name', '')}")
            lines.append(f"    Path: {a.get('install_location', '')}")
            lines.append(f"    How: {a.get('how_to_move', '')}\n")
        lines.append("\n=== Folders often trimmed for space (risk: low < medium < high) ===\n")
        for f in d.get("deletable_folders") or []:
            sz = f.get("size_mb")
            szt = f.get("size_note") or (f"~{sz} MB" if sz is not None else "size not measured")
            lines.append(f"[{str(f.get('risk', '?')).upper()}] {f.get('label', '')} — {szt}")
            lines.append(f"    {f.get('path', '')}")
            lines.append(f"    {f.get('notes', '')}\n")
        text = "\n".join(lines)
        self._last_disk_report = text
        self._disk_cleanup_txt.configure(state="normal")
        self._disk_cleanup_txt.delete("1.0", "end")
        self._disk_cleanup_txt.insert("1.0", text)
        self._disk_cleanup_txt.configure(state="disabled")

    def _build_insights_tab(self, tab: ctk.CTkFrame) -> None:
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(3, weight=1)
        ctk.CTkLabel(
            tab,
            text=(
                "Extended diagnostics (memory commit + pool aggregates, reliability stability metrics when available, "
                "disk reliability, startup Run keys, non-Windows auto services, scheduled tasks sample, 14-day error "
                "trend). Export bundles live + diagnostics "
                f"data. Last-scan file: {snapshot_path()}"
            ),
            anchor="w",
            wraplength=920,
        ).grid(row=0, column=0, sticky="ew", pady=(0, 6))

        top = ctk.CTkFrame(tab, fg_color="transparent")
        top.grid(row=1, column=0, sticky="ew", pady=(0, 6))
        ctk.CTkButton(top, text="Export JSON report…", command=self._export_json_report).pack(side="left", padx=(0, 8))
        ctk.CTkButton(top, text="Export HTML report…", command=self._export_html_report).pack(side="left", padx=(0, 8))
        ctk.CTkButton(top, text="Export PDF report…", command=self._export_pdf_report).pack(side="left", padx=(0, 8))

        tools = ctk.CTkFrame(tab, fg_color="transparent")
        tools.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        ctk.CTkLabel(tools, text="Built-in Windows shortcuts:", anchor="w").grid(row=0, column=0, sticky="w")
        tf = ctk.CTkFrame(tools, fg_color="transparent")
        tf.grid(row=1, column=0, sticky="w", pady=4)
        shortcuts = [
            ("Storage", "ms-settings:storagesense"),
            ("Apps & features", "ms-settings:appsfeatures"),
            ("Delivery Optimization", "ms-settings:delivery-optimization"),
            ("Disk Cleanup", "cleanmgr"),
        ]
        for i, (lab, uri) in enumerate(shortcuts):
            ctk.CTkButton(tf, text=lab, width=170, command=lambda u=uri: self._open_external(u)).grid(
                row=i // 2, column=i % 2, padx=4, pady=4, sticky="w"
            )
        rf = ctk.CTkFrame(tools, fg_color="transparent")
        rf.grid(row=2, column=0, sticky="w", pady=(6, 0))
        ctk.CTkLabel(rf, text="Repair (new cmd window — confirm; may need admin):", anchor="w").pack(side="left", padx=(0, 12))
        ctk.CTkButton(rf, text="sfc /scannow", width=120, command=lambda: self._launch_repair_shell("sfc /scannow")).pack(
            side="left", padx=4
        )
        ctk.CTkButton(
            rf,
            text="DISM RestoreHealth",
            width=150,
            command=lambda: self._launch_repair_shell("DISM /Online /Cleanup-Image /RestoreHealth"),
        ).pack(side="left", padx=4)

        self._insights_txt = ctk.CTkTextbox(tab, font=ctk.CTkFont(family="Consolas", size=11))
        self._insights_txt.grid(row=3, column=0, sticky="nsew")
        self._refresh_insights_text()

    def _open_external(self, target: str) -> None:
        try:
            if target == "cleanmgr":
                subprocess.Popen(["cleanmgr"], shell=False)
            else:
                os.startfile(target)  # type: ignore[attr-defined]
        except OSError:
            pass

    def _launch_repair_shell(self, inner: str) -> None:
        import tkinter.messagebox as mb

        if not mb.askokcancel(
            "Confirm",
            f"A new Command Prompt will start with:\n\n{inner}\n\n"
            "Administrator is often required. This can take many minutes. Continue?",
        ):
            return
        try:
            subprocess.Popen(
                ["cmd.exe", "/c", "start", "cmd", "/k", inner],
                cwd=os.environ.get("SystemRoot", r"C:\Windows"),
            )
        except OSError:
            pass

    def _export_json_report(self) -> None:
        from tkinter import filedialog

        snap = dict(self.shared.export_snapshot())
        snap["meta"] = {
            "app_version": __version__,
            "hostname": platform.node(),
            "platform": platform.platform(),
            "note": APP_ATTRIBUTION,
        }
        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON", "*.json"), ("All files", "*.*")],
            initialfile=f"PCChecker_report_{time.strftime('%Y%m%d_%H%M')}.json",
        )
        if path:
            write_json_report(Path(path), snap)

    def _export_html_report(self) -> None:
        from tkinter import filedialog

        snap = dict(self.shared.export_snapshot())
        snap["meta"] = {
            "app_version": __version__,
            "hostname": platform.node(),
            "platform": platform.platform(),
            "note": APP_ATTRIBUTION,
        }
        path = filedialog.asksaveasfilename(
            defaultextension=".html",
            filetypes=[("HTML", "*.html"), ("All files", "*.*")],
            initialfile=f"PCChecker_report_{time.strftime('%Y%m%d_%H%M')}.html",
        )
        if path:
            write_html_report(
                Path(path),
                snap,
                hostname=platform.node(),
                os_line=platform.platform(),
            )

    def _export_pdf_report(self) -> None:
        from tkinter import filedialog
        import tkinter.messagebox as mb

        snap = dict(self.shared.export_snapshot())
        snap["meta"] = {
            "app_version": __version__,
            "hostname": platform.node(),
            "platform": platform.platform(),
            "note": APP_ATTRIBUTION,
        }
        path = filedialog.asksaveasfilename(
            defaultextension=".pdf",
            filetypes=[("PDF", "*.pdf"), ("All files", "*.*")],
            initialfile=f"PCChecker_report_{time.strftime('%Y%m%d_%H%M')}.pdf",
        )
        if not path:
            return
        try:
            write_pdf_report(Path(path), snap)
        except RuntimeError as e:
            mb.showerror("PDF export", str(e))
        except Exception as e:  # noqa: BLE001
            mb.showerror("PDF export", str(e))

    def _build_settings_tab(self, tab: ctk.CTkFrame) -> None:
        tab.grid_columnconfigure(0, weight=1)
        scroll = ctk.CTkScrollableFrame(tab, fg_color="transparent")
        scroll.grid(row=0, column=0, sticky="nsew")
        tab.grid_rowconfigure(0, weight=1)

        def row(label: str, key: str, placeholder: str = "") -> ctk.CTkEntry:
            fr = ctk.CTkFrame(scroll, fg_color="transparent")
            fr.pack(fill="x", pady=3)
            ctk.CTkLabel(fr, text=label, width=260, anchor="w").pack(side="left", padx=(0, 8))
            e = ctk.CTkEntry(fr, width=420, placeholder_text=placeholder)
            e.pack(side="left", fill="x", expand=True)
            self._settings_entries[key] = e
            return e

        def chk(label: str, key: str) -> ctk.CTkCheckBox:
            fr = ctk.CTkFrame(scroll, fg_color="transparent")
            fr.pack(fill="x", pady=3)
            c = ctk.CTkCheckBox(fr, text=label)
            c.pack(anchor="w")
            self._settings_entries[key] = c
            return c

        ctk.CTkLabel(scroll, text="Polling & WMI", font=ctk.CTkFont(weight="bold")).pack(anchor="w", pady=(0, 6))
        st = self._st
        row("Live poll interval (ms)", "live_poll_ms").insert(0, str(st.live_poll_ms))
        row("View refresh interval (ms)", "view_poll_ms").insert(0, str(st.view_poll_ms))
        row("Diagnostics interval (ms)", "diag_interval_ms").insert(0, str(st.diag_interval_ms))
        row("Queue poll interval (ms)", "queue_poll_ms").insert(0, str(st.queue_poll_ms))
        row("WMI temperature cache TTL (seconds)", "wmi_temp_ttl_s").insert(0, str(st.wmi_temp_ttl_s))

        ctk.CTkLabel(scroll, text="Background & alerts", font=ctk.CTkFont(weight="bold")).pack(anchor="w", pady=(12, 6))
        cb_hide = chk("Hide attribution footer", "hide_attribution_banner")
        if st.hide_attribution_banner:
            cb_hide.select()
        cb_tray = chk("Enable system tray icon", "enable_tray")
        if st.enable_tray:
            cb_tray.select()
        cb_db = chk("Write metrics to SQLite", "enable_metrics_db")
        if st.enable_metrics_db:
            cb_db.select()
        row("Metrics sample interval (seconds)", "metrics_sample_interval_s").insert(0, str(st.metrics_sample_interval_s))
        row("Alert: CPU % (sustained)", "alert_cpu_pct").insert(0, str(st.alert_cpu_pct))
        row("Alert: RAM % (sustained)", "alert_ram_pct").insert(0, str(st.alert_ram_pct))
        row("Alert: disk free % (lowest volume)", "alert_disk_free_pct").insert(0, str(st.alert_disk_free_pct))
        row("Alert cooldown (seconds)", "alert_cooldown_s").insert(0, str(st.alert_cooldown_s))

        ctk.CTkLabel(scroll, text="Webhook & scheduled export", font=ctk.CTkFont(weight="bold")).pack(anchor="w", pady=(12, 6))
        row("Webhook URL (POST JSON)", "webhook_url", "https://example.com/hook").insert(0, st.webhook_url)
        row("Webhook Bearer token (optional; use for Render /api/ingest)", "webhook_bearer_token").insert(
            0, st.webhook_bearer_token
        )
        row("Webhook interval (minutes, 0=off)", "webhook_interval_min").insert(0, str(st.webhook_interval_min))
        row("Scheduled export interval (minutes, 0=off)", "scheduled_export_interval_min").insert(
            0, str(st.scheduled_export_interval_min)
        )
        row("Scheduled export directory (blank = LocalAppData\\PCChecker\\exports)", "scheduled_export_dir").insert(
            0, st.scheduled_export_dir
        )

        ctk.CTkButton(scroll, text="Save settings", command=self._save_settings_from_ui).pack(anchor="w", pady=16)

    def _save_settings_from_ui(self) -> None:
        import tkinter.messagebox as mb

        def gint(key: str, default: int) -> int:
            try:
                return int(cast(ctk.CTkEntry, self._settings_entries[key]).get().strip())
            except (KeyError, ValueError, TypeError):
                return default

        def gfloat(key: str, default: float) -> float:
            try:
                return float(cast(ctk.CTkEntry, self._settings_entries[key]).get().strip())
            except (KeyError, ValueError, TypeError):
                return default

        def gstr(key: str) -> str:
            try:
                return cast(ctk.CTkEntry, self._settings_entries[key]).get().strip()
            except (KeyError, TypeError):
                return ""

        def gbool(key: str) -> bool:
            try:
                v = cast(ctk.CTkCheckBox, self._settings_entries[key]).get()
                if isinstance(v, (int, float)):
                    return int(v) == 1
                return str(v).lower() in ("on", "true", "1", "yes")
            except (KeyError, TypeError, ValueError):
                return False

        new = AppSettings(
            live_poll_ms=max(250, gint("live_poll_ms", 1000)),
            view_poll_ms=max(400, gint("view_poll_ms", 1200)),
            diag_interval_ms=max(10_000, gint("diag_interval_ms", 75_000)),
            queue_poll_ms=max(50, gint("queue_poll_ms", 150)),
            wmi_temp_ttl_s=max(15.0, gfloat("wmi_temp_ttl_s", 45.0)),
            hide_attribution_banner=gbool("hide_attribution_banner"),
            enable_tray=gbool("enable_tray"),
            enable_metrics_db=gbool("enable_metrics_db"),
            metrics_sample_interval_s=max(10, gint("metrics_sample_interval_s", 60)),
            alert_cpu_pct=min(100.0, max(50.0, gfloat("alert_cpu_pct", 95.0))),
            alert_ram_pct=min(100.0, max(50.0, gfloat("alert_ram_pct", 92.0))),
            alert_disk_free_pct=min(50.0, max(1.0, gfloat("alert_disk_free_pct", 5.0))),
            alert_cooldown_s=max(120.0, gfloat("alert_cooldown_s", 3600.0)),
            webhook_url=gstr("webhook_url"),
            webhook_bearer_token=gstr("webhook_bearer_token"),
            webhook_interval_min=max(0, gint("webhook_interval_min", 0)),
            scheduled_export_interval_min=max(0, gint("scheduled_export_interval_min", 0)),
            scheduled_export_dir=gstr("scheduled_export_dir"),
        )
        save_settings(new)
        self._st = new
        self._live_interval_ms = new.live_poll_ms
        self._view_interval_ms = new.view_poll_ms
        self._diag_interval_ms = new.diag_interval_ms
        self._queue_poll_ms = new.queue_poll_ms
        for key in ("live", "view", "queue"):
            aid = self._after_ids.get(key)
            if aid:
                self.after_cancel(aid)
                self._after_ids[key] = None
        self._schedule_live()
        self._schedule_queue_poll()
        self._schedule_view_poll()
        if self._after_ids.get("diag"):
            self.after_cancel(cast(str, self._after_ids["diag"]))
        self._after_ids["diag"] = self.after(self._diag_interval_ms, self._diag_timer)
        if new.hide_attribution_banner:
            self._footer_lbl.grid_remove()
        else:
            self._footer_lbl.grid(row=self._ui_tabs_row + 1, column=0, sticky="ew", padx=16, pady=(0, 10))
        mb.showinfo("Settings", "Saved. Tray/metrics toggles apply on next app launch; timers updated now.")

    def _format_insights_body(self, diag: dict[str, Any]) -> str:
        lines: list[str] = []
        cmp_txt = diag.get("scan_compare_summary") or ""
        lines.append("=== Compare vs last scan (LocalAppData\\PCChecker\\last_scan.json) ===\n")
        lines.append(cmp_txt + "\n")
        ext = diag.get("extended") or {}
        lines.append("=== Extended diagnostics (JSON sections) ===\n")
        sec = ext.get("sections") or ext
        if isinstance(sec, dict):
            for name in (
                "hardware_identity",
                "memory_pressure",
                "memory_pool_counters",
                "disk_reliability",
                "reliability_stability",
                "startup_items",
                "services_auto_nonwindows",
                "scheduled_tasks_non_microsoft",
                "error_trend_14d",
            ):
                blob = sec.get(name)
                lines.append(f"--- {name} ---\n{json.dumps(blob, indent=2, default=str)}\n")
        else:
            lines.append(json.dumps(ext, indent=2, default=str))
        return "\n".join(lines)

    def _refresh_insights_text(self) -> None:
        if self._insights_txt is None:
            return
        diag = self.shared.get_diagnostics_bundle()
        text = self._format_insights_body(diag)
        self._insights_txt.configure(state="normal")
        self._insights_txt.delete("1.0", "end")
        self._insights_txt.insert("1.0", text)
        self._insights_txt.configure(state="disabled")

    def _gui_defender_update(self) -> None:
        from pc_checker.services.update_fetch import get_defender_status, trigger_defender_signature_update

        def work() -> None:
            ok, msg = trigger_defender_signature_update()
            self.shared.set_defender(get_defender_status())
            self._result_queue.put(("toast", ("defender", ok, msg)))

        threading.Thread(target=work, daemon=True).start()
        self._updates_status.configure(text="Defender signature update requested…")

    def _gui_wu_scan(self) -> None:
        from pc_checker.services.update_fetch import trigger_windows_update_scan

        def work() -> None:
            ok, msg = trigger_windows_update_scan()
            self._result_queue.put(("toast", ("wu", ok, msg)))

        threading.Thread(target=work, daemon=True).start()
        self._updates_status.configure(text="Windows Update scan requested…")

    def _schedule_live(self) -> None:
        self._tick_live()
        self._after_ids["live"] = self.after(self._live_interval_ms, self._schedule_live)

    def _ensure_core_bars(self, n: int) -> None:
        if len(self._core_rows) == n:
            return
        for w in self._cores_scroll.winfo_children():
            w.destroy()
        self._core_rows.clear()
        for i in range(n):
            fr = ctk.CTkFrame(self._cores_scroll, fg_color="transparent")
            fr.pack(fill="x", pady=1)
            ctk.CTkLabel(fr, text=f"CPU {i}", width=52, anchor="w").pack(side="left", padx=(0, 6))
            bar = ctk.CTkProgressBar(fr, height=10)
            bar.pack(side="left", fill="x", expand=True)
            bar.set(0)
            self._core_rows.append(bar)

    def _tick_live(self) -> None:
        cpu = psutil.cpu_percent(interval=None)
        self._cpu_bar.set(min(1.0, cpu / 100.0))
        self._cpu_lbl.configure(text=f"CPU (all cores): {cpu:.0f}%")

        vm = psutil.virtual_memory()
        self._ram_bar.set(min(1.0, vm.percent / 100.0))
        self._ram_lbl.configure(
            text=f"RAM: {vm.percent:.0f}% used  ({vm.available / (1024**3):.2f} GB free of {vm.total / (1024**3):.1f} GB)"
        )

        sw = psutil.swap_memory()
        if sw.total:
            self._swap_lbl.configure(
                text=f"Page file: {sw.percent:.0f}% used  ({sw.used / (1024**3):.2f} / {sw.total / (1024**3):.2f} GB)"
            )
        else:
            self._swap_lbl.configure(text="Page file: not reported")

        temps = read_temperatures_c()
        if temps:
            parts = [f"{k}: {v:.1f}°C" for k, v in sorted(temps.items())[:8]]
            self._temp_lbl.configure(text="Temperature: " + "  ·  ".join(parts))
        else:
            self._temp_lbl.configure(
                text="Temperature: not available (common on desktops without WMI thermal zones or sensor drivers)."
            )

        per = psutil.cpu_percent(interval=None, percpu=True) or []
        self._ensure_core_bars(len(per))
        for bar, pct in zip(self._core_rows, per):
            bar.set(min(1.0, float(pct) / 100.0))

        rb, wb = self._disk_io_mbps()
        self._io_lbl.configure(text=f"Read: {rb:.2f} MB/s   Write: {wb:.2f} MB/s")

        self._ensure_disk_rows()
        self._update_disk_rows()

        boot = psutil.boot_time()
        up = time.time() - boot
        d, h = int(up // 86400), int((up % 86400) // 3600)
        self._boot_lbl.configure(text=f"Uptime: {d}d {h}h since last boot")

        n = psutil.cpu_count(logical=True) or 0
        p = psutil.cpu_count(logical=False) or 0
        self._cores_meta.configure(text=f"Logical processors: {n}  (physical cores: {p})")

        swp = float(sw.percent) if sw.total else None
        swu = float(sw.used / (1024**3)) if sw.total else None
        swt = float(sw.total / (1024**3)) if sw.total else None
        self.shared.record_live_sample(
            cpu=float(cpu),
            ram_percent=float(vm.percent),
            ram_available_gb=float(vm.available / (1024**3)),
            ram_total_gb=float(vm.total / (1024**3)),
            per_cpu=[float(x) for x in per],
            temps_c={k: float(v) for k, v in temps.items()},
            disk_read_mbps=float(rb),
            disk_write_mbps=float(wb),
            swap_percent=swp,
            swap_used_gb=swu,
            swap_total_gb=swt,
            uptime_seconds=float(up),
        )
        _, hc, hr = self.shared.get_history_lists()
        self._chart.set_history(hc, hr)

    def _disk_io_mbps(self) -> tuple[float, float]:
        cur = psutil.disk_io_counters(perdisk=False)
        t = time.time()
        if cur is None:
            return 0.0, 0.0
        if self._io_prev is None or self._io_tprev is None:
            self._io_prev = cur
            self._io_tprev = t
            return 0.0, 0.0
        dt = t - self._io_tprev
        if dt <= 0:
            return 0.0, 0.0
        rb = (cur.read_bytes - self._io_prev.read_bytes) / dt / (1024**2)
        wb = (cur.write_bytes - self._io_prev.write_bytes) / dt / (1024**2)
        self._io_prev = cur
        self._io_tprev = t
        return rb, wb

    def _partition_list(self) -> list[tuple[str, str, float]]:
        rows: list[tuple[str, str, float]] = []
        for part in psutil.disk_partitions(all=False):
            try:
                u = psutil.disk_usage(part.mountpoint)
            except OSError:
                continue
            free_pct = 100.0 * u.free / u.total if u.total else 100.0
            label = part.device or part.mountpoint
            rows.append((label, part.mountpoint, free_pct))
        return rows

    def _ensure_disk_rows(self) -> None:
        parts = self._partition_list()
        keys = [p[0] for p in parts]
        existing = [r[0] for r in self._disk_rows]
        if keys == existing:
            return
        for w in self._disk_frame.winfo_children():
            w.destroy()
        self._disk_rows.clear()
        for dev, mount, _ in parts:
            fr = ctk.CTkFrame(self._disk_frame, fg_color="transparent")
            fr.pack(fill="x", pady=4)
            bar = ctk.CTkProgressBar(fr)
            bar.pack(fill="x", pady=(0, 2))
            lbl = ctk.CTkLabel(fr, text="", anchor="w", font=ctk.CTkFont(size=12))
            lbl.pack(anchor="w")
            self._disk_rows.append((dev, bar, lbl))

    def _update_disk_rows(self) -> None:
        parts = {p[0]: p for p in self._partition_list()}
        for dev, bar, lbl in self._disk_rows:
            if dev not in parts:
                continue
            _, mount, free_pct = parts[dev]
            used_pct = max(0.0, min(100.0, 100.0 - free_pct))
            bar.set(used_pct / 100.0)
            sev = "green"
            if free_pct < 3:
                sev = "red"
            elif free_pct < 10:
                sev = "orange"
            lbl.configure(
                text=f"{dev}  ({mount})  —  {free_pct:.0f}% free",
                text_color=sev,
            )

    def _schedule_queue_poll(self) -> None:
        try:
            while True:
                kind, payload = self._result_queue.get_nowait()
                if kind == "findings":
                    self._apply_findings(cast(list[Finding], payload))
                elif kind == "diag_done":
                    self._diag_busy = False
                    self._diag_status.configure(text=f"Last hardware scan: {time.strftime('%H:%M:%S')}")
                elif kind == "toast":
                    _which, ok, msg = cast(tuple[Any, bool, str], payload)
                    self._updates_status.configure(text=("OK: " if ok else "Issue: ") + msg)
        except queue.Empty:
            pass
        self._after_ids["queue"] = self.after(self._queue_poll_ms, self._schedule_queue_poll)

    def _schedule_view_poll(self) -> None:
        self._refresh_software_text()
        self._refresh_updates_text()
        self._refresh_disk_cleanup_text()
        self._refresh_insights_text()
        self._after_ids["view"] = self.after(self._view_interval_ms, self._schedule_view_poll)

    def _refresh_software_text(self) -> None:
        bundle = self.shared.get_live_bundle()
        diag = self.shared.get_diagnostics_bundle()
        lines: list[str] = []
        lines.append("=== Top processes by CPU (approx., refreshed every few seconds) ===\n")
        for r in bundle.get("top_processes") or []:
            lines.append(
                f"{r.get('cpu_percent', 0):5.1f}% CPU  {r.get('memory_percent', 0):5.1f}% RAM  "
                f"pid={r.get('pid')}  {r.get('name')}"
            )
        lines.append("\n=== Application log insights (last full scan) ===\n")
        for f in diag.get("software_findings") or []:
            lines.append(f"[{f.get('severity', '').upper()}] {f.get('title')}\n{f.get('detail')}\n")
        text = "\n".join(lines)
        self._software_txt.configure(state="normal")
        self._software_txt.delete("1.0", "end")
        self._software_txt.insert("1.0", text)
        self._software_txt.configure(state="disabled")

    def _refresh_updates_text(self) -> None:
        u = self.shared.get_updates_bundle()
        busy = u.get("refresh_busy")
        lines: list[str] = []
        if self._api_url:
            lines.append(f"Local HTTP API: {self._api_url}")
            lines.append("Endpoints: GET /api/v1/live, /diagnostics, /updates  ·  POST /api/v1/updates/refresh")
            lines.append("Actions: POST /api/v1/actions/defender-signatures  ·  POST /api/v1/actions/windows-update-scan")
            lines.append("Docs: GET /docs\n")
        else:
            lines.append("Local API not running.\n")
        lines.append(f"Catalog refresh busy: {bool(busy)}\n")
        lines.append("=== Microsoft Defender (Get-MpComputerStatus) ===\n")
        lines.append(json.dumps(u.get("defender") or {}, indent=2, default=str))
        lines.append("\n=== Pending Windows Updates (COM search; can take minutes) ===\n")
        wu = u.get("windows_update") or {}
        if wu.get("error"):
            lines.append("Error: " + str(wu["error"]) + "\n")
        for it in wu.get("items") or []:
            lines.append(f"- {it.get('title')}  (mandatory={it.get('mandatory')}, reboot={it.get('reboot_required')})")
        lines.append("\n=== winget upgrades (third-party packages) ===\n")
        wg = u.get("winget") or {}
        if wg.get("error"):
            lines.append("Error: " + str(wg["error"]) + "\n")
        for it in (wg.get("items") or [])[:80]:
            lines.append(
                f"- {it.get('name')}  [{it.get('id')}]  {it.get('installed_version')} -> {it.get('available_version')}"
            )
        text = "\n".join(lines)
        self._updates_txt.configure(state="normal")
        self._updates_txt.delete("1.0", "end")
        self._updates_txt.insert("1.0", text)
        self._updates_txt.configure(state="disabled")

    def _diag_timer(self) -> None:
        self._request_diagnostics()
        self._after_ids["diag"] = self.after(self._diag_interval_ms, self._diag_timer)

    def _request_diagnostics(self) -> None:
        if self._diag_busy:
            return
        self._diag_busy = True
        self._diag_status.configure(text="Scanning hardware / system…")

        def worker() -> None:
            try:
                hardware = collect_hardware_findings()
                software = check_application_faults()
                try:
                    disk = collect_disk_hints()
                except Exception:
                    disk = {
                        "relocatable_apps": [],
                        "deletable_folders": [],
                        "program_files_top_level": [],
                        "program_files_disclaimer": "",
                        "notes": "Disk hints could not be collected this run.",
                    }
                self.shared.set_findings(hardware)
                self.shared.set_software_findings(software)
                self.shared.set_disk_hints(disk)
                self._result_queue.put(("findings", hardware))
            except Exception:
                err = [
                    Finding(
                        "warn",
                        "Scan failed",
                        "An error occurred while running diagnostics. Try again or use --cli.",
                    )
                ]
                self.shared.set_findings(err)
                self._result_queue.put(("findings", err))
            finally:
                try:
                    ext = collect_extended_diagnostics()
                    self.shared.set_extended_diagnostics(ext)
                    finalize_scan_after_update(self.shared)
                except Exception:
                    self.shared.set_scan_compare_summary(
                        "Extended diagnostics or scan history step failed."
                    )
                self._result_queue.put(("diag_done", None))

        threading.Thread(target=worker, daemon=True).start()

    def _apply_findings(self, findings: list[Finding]) -> None:
        sev_order = {"critical": 0, "warn": 1, "ok": 2}
        findings = sorted(findings, key=lambda f: (sev_order.get(f.severity, 9), f.title))

        crit = sum(1 for f in findings if f.severity == "critical")
        warn = sum(1 for f in findings if f.severity == "warn")
        if crit:
            self._summary_lbl.configure(text=f"{crit} critical, {warn} warning(s)", text_color="#E74C3C")
        elif warn:
            self._summary_lbl.configure(text=f"{warn} warning(s)", text_color="#F39C12")
        else:
            self._summary_lbl.configure(text="No critical or warning items from these checks", text_color="#2ECC71")

        for w in self._findings_frame.winfo_children():
            w.destroy()

        colors = {"critical": "#E74C3C", "warn": "#F39C12", "ok": "#2ECC71"}
        for f in findings:
            row = ctk.CTkFrame(self._findings_frame)
            row.pack(fill="x", pady=4, padx=2)
            row.grid_columnconfigure(1, weight=1)

            badge = ctk.CTkLabel(
                row,
                text=f.severity.upper(),
                width=88,
                text_color=colors.get(f.severity, "white"),
                font=ctk.CTkFont(weight="bold"),
            )
            badge.grid(row=0, column=0, sticky="nw", padx=(8, 8), pady=8)

            title = ctk.CTkLabel(row, text=f.title, font=ctk.CTkFont(weight="bold"), anchor="w")
            title.grid(row=0, column=1, sticky="ew", pady=(8, 0))

            detail = ctk.CTkLabel(
                row,
                text=f.detail,
                anchor="w",
                justify="left",
                wraplength=780,
            )
            detail.grid(row=1, column=1, sticky="ew", pady=(0, 4))
            if f.next_steps:
                steps = "\n".join(f"  • {s}" for s in f.next_steps)
                st = ctk.CTkLabel(
                    row,
                    text="Next steps:\n" + steps,
                    anchor="w",
                    justify="left",
                    wraplength=760,
                    text_color="#aed6f1",
                    font=ctk.CTkFont(size=12),
                )
                st.grid(row=2, column=1, sticky="ew", pady=(0, 8))


def run_app(*, enable_api: bool = True, no_tray: bool = False) -> None:
    hide_attached_console_window()
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
    app = PCCheckerApp(enable_api=enable_api)
    try:
        start_background_services(app, skip_tray=no_tray)
    except Exception:
        logging.getLogger(__name__).exception("Background services failed to start")
    app.mainloop()
