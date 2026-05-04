"""Tray icon, SQLite metrics sampling, threshold alerts, webhook POST, scheduled JSON export."""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any

import psutil

from pc_checker.export_report import write_json_report
from pc_checker.metrics_db import insert_sample
from pc_checker.settings_store import app_data_dir, load_settings
from pc_checker.volumes_snapshot import volumes_snapshot

_log = logging.getLogger(__name__)

_last_alert: dict[str, float] = {}


def _min_disk_free_pct() -> float:
    best = 100.0
    for part in psutil.disk_partitions(all=False):
        try:
            u = psutil.disk_usage(part.mountpoint)
        except OSError:
            continue
        if u.total:
            pct = 100.0 * u.free / u.total
            if pct < best:
                best = pct
    return best


def _webhook_post(url: str, payload: dict[str, Any], bearer_token: str = "") -> None:
    try:
        import requests

        headers: dict[str, str] = {}
        t = str(bearer_token).strip()
        if t:
            headers["Authorization"] = f"Bearer {t}"
        requests.post(url, json=payload, headers=headers or None, timeout=30)
    except Exception as e:  # noqa: BLE001
        _log.warning("Webhook failed: %s", e)


def _background_loop(app: Any, stop: threading.Event) -> None:
    last_webhook = 0.0
    last_export = 0.0
    consec_high_cpu = 0
    consec_high_ram = 0
    while not stop.is_set():
        s = load_settings()
        now = time.time()
        try:
            live = app.shared.get_live_bundle().get("live") or {}
            cpu = float(live.get("cpu_percent") or 0.0)
            ram = float(live.get("ram_percent") or 0.0)
            disk_free = _min_disk_free_pct()

            if s.enable_metrics_db:
                insert_sample(cpu=cpu, ram_pct=ram, disk_min_free_pct=disk_free)

            cool = max(60.0, float(s.alert_cooldown_s))
            if cpu >= float(s.alert_cpu_pct):
                consec_high_cpu += 1
            else:
                consec_high_cpu = 0
            if ram >= float(s.alert_ram_pct):
                consec_high_ram += 1
            else:
                consec_high_ram = 0

            icon = getattr(app, "_tray_icon", None)
            if icon is not None:
                if consec_high_cpu >= 3 and now - _last_alert.get("cpu", 0) > cool:
                    _last_alert["cpu"] = now
                    try:
                        icon.notify("PC Checker — CPU high", f"CPU ~{cpu:.0f}% (threshold {s.alert_cpu_pct:.0f}%)")
                    except Exception:
                        pass
                if consec_high_ram >= 3 and now - _last_alert.get("ram", 0) > cool:
                    _last_alert["ram"] = now
                    try:
                        icon.notify("PC Checker — RAM high", f"RAM ~{ram:.0f}% (threshold {s.alert_ram_pct:.0f}%)")
                    except Exception:
                        pass
                if disk_free <= float(s.alert_disk_free_pct) and now - _last_alert.get("disk", 0) > cool:
                    _last_alert["disk"] = now
                    try:
                        icon.notify("PC Checker — low disk space", f"Lowest volume free ~{disk_free:.1f}%")
                    except Exception:
                        pass

            if s.webhook_url and s.webhook_interval_min > 0:
                interval_s = s.webhook_interval_min * 60
                if now - last_webhook >= interval_s:
                    last_webhook = now
                    snap = dict(app.shared.export_snapshot())
                    snap["disks"] = volumes_snapshot()
                    snap["meta"] = {"kind": "webhook", "ts": now}
                    _webhook_post(s.webhook_url, snap, s.webhook_bearer_token)

            if s.scheduled_export_interval_min > 0:
                interval_s = s.scheduled_export_interval_min * 60
                if now - last_export >= interval_s:
                    last_export = now
                    base = Path(s.scheduled_export_dir) if str(s.scheduled_export_dir).strip() else app_data_dir() / "exports"
                    base.mkdir(parents=True, exist_ok=True)
                    fn = base / f"scheduled_export_{time.strftime('%Y%m%d_%H%M%S')}.json"
                    try:
                        write_json_report(fn, dict(app.shared.export_snapshot()))
                    except OSError as e:
                        _log.warning("Scheduled export failed: %s", e)
        except Exception as e:  # noqa: BLE001
            _log.debug("background loop: %s", e)

        wait_s = max(10.0, float(s.metrics_sample_interval_s))
        stop.wait(wait_s)


def start_background_services(app: Any, *, skip_tray: bool = False) -> None:
    stop = threading.Event()
    app._bg_stop = stop

    s = load_settings()
    if s.enable_tray and not skip_tray:
        try:
            from PIL import Image
            import pystray
            from pystray import Menu, MenuItem
        except ImportError:
            _log.warning("pystray/Pillow not installed — tray icon disabled.")
        else:
            image = Image.new("RGB", (64, 64), color=(32, 120, 180))

            def show(_: object = None) -> None:
                app.after(0, app.deiconify)
                app.after(0, app.lift)

            def export_now(_: object = None) -> None:
                def work() -> None:
                    base = app_data_dir() / "exports"
                    base.mkdir(parents=True, exist_ok=True)
                    path = base / f"tray_export_{time.strftime('%Y%m%d_%H%M%S')}.json"
                    try:
                        write_json_report(path, dict(app.shared.export_snapshot()))
                        ic = getattr(app, "_tray_icon", None)
                        if ic:
                            ic.notify("PC Checker", f"Export saved:\n{path}")
                    except OSError as e:
                        _log.warning("Tray export failed: %s", e)

                threading.Thread(target=work, daemon=True).start()

            def quit_app(_: object = None) -> None:
                app.after(0, app._on_close)

            menu = Menu(
                MenuItem("Show window", show),
                MenuItem("Export JSON snapshot", export_now),
                MenuItem("Quit", quit_app),
            )
            icon = pystray.Icon("pc_checker", image, "PC Checker", menu)
            app._tray_icon = icon
            threading.Thread(target=icon.run, daemon=True, name="pc_checker_tray").start()

    threading.Thread(target=_background_loop, args=(app, stop), daemon=True, name="pc_checker_bg").start()


def stop_tray_if_present(app: Any) -> None:
    if getattr(app, "_bg_stop", None):
        app._bg_stop.set()
    icon = getattr(app, "_tray_icon", None)
    if icon is not None:
        try:
            icon.stop()
        except Exception:
            pass
