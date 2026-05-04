from __future__ import annotations

import threading
import time
from typing import Any

import psutil

from pc_checker.sensors import read_temperatures_c
from pc_checker.state import SharedState


class _IOTracker:
    def __init__(self) -> None:
        self._prev: Any = None
        self._tprev: float | None = None

    def rates_mbps(self) -> tuple[float, float]:
        cur = psutil.disk_io_counters(perdisk=False)
        t = time.time()
        if cur is None:
            return 0.0, 0.0
        if self._prev is None or self._tprev is None:
            self._prev = cur
            self._tprev = t
            return 0.0, 0.0
        dt = t - self._tprev
        if dt <= 0:
            return 0.0, 0.0
        rb = (cur.read_bytes - self._prev.read_bytes) / dt / (1024**2)
        wb = (cur.write_bytes - self._prev.write_bytes) / dt / (1024**2)
        self._prev = cur
        self._tprev = t
        return rb, wb


def _live_tick(state: SharedState, io: _IOTracker) -> None:
    cpu = float(psutil.cpu_percent(interval=None))
    vm = psutil.virtual_memory()
    sw = psutil.swap_memory()
    per = [float(x) for x in (psutil.cpu_percent(interval=None, percpu=True) or [])]
    rb, wb = io.rates_mbps()
    temps = read_temperatures_c()
    boot = psutil.boot_time()
    uptime_s = max(0.0, time.time() - boot)
    sp = float(sw.percent) if sw.total else None
    su = float(sw.used / (1024**3)) if sw.total else None
    st = float(sw.total / (1024**3)) if sw.total else None
    state.record_live_sample(
        cpu=cpu,
        ram_percent=float(vm.percent),
        ram_available_gb=float(vm.available / (1024**3)),
        ram_total_gb=float(vm.total / (1024**3)),
        per_cpu=per,
        temps_c={k: float(v) for k, v in temps.items()},
        disk_read_mbps=float(rb),
        disk_write_mbps=float(wb),
        swap_percent=sp,
        swap_used_gb=su,
        swap_total_gb=st,
        uptime_seconds=float(uptime_s),
    )


def _proc_rank_loop(state: SharedState, stop: threading.Event) -> None:
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
            state.set_top_processes(rows[:32])
        except Exception:
            pass
        if stop.wait(3.2):
            break


def _live_loop(state: SharedState, stop: threading.Event, io: _IOTracker) -> None:
    psutil.cpu_percent(interval=None)
    while True:
        _live_tick(state, io)
        if stop.wait(1.0):
            break


def start_background_feed(state: SharedState, stop: threading.Event) -> None:
    io = _IOTracker()
    threading.Thread(target=_live_loop, args=(state, stop, io), daemon=True).start()
    threading.Thread(target=_proc_rank_loop, args=(state, stop), daemon=True).start()
