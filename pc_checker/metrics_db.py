"""SQLite time-series for background sampling (optional)."""

from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from pc_checker.settings_store import app_data_dir

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None


def db_path() -> Path:
    return app_data_dir() / "metrics.db"


def _get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(str(db_path()), check_same_thread=False)
        _conn.execute(
            """CREATE TABLE IF NOT EXISTS samples (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL,
                cpu REAL,
                ram_pct REAL,
                disk_min_free_pct REAL
            )"""
        )
        _conn.commit()
    return _conn


def insert_sample(*, cpu: float, ram_pct: float, disk_min_free_pct: float) -> None:
    with _lock:
        try:
            c = _get_conn()
            c.execute(
                "INSERT INTO samples (ts, cpu, ram_pct, disk_min_free_pct) VALUES (?,?,?,?)",
                (time.time(), cpu, ram_pct, disk_min_free_pct),
            )
            c.commit()
        except sqlite3.Error:
            pass


def recent_samples(limit: int = 500) -> list[dict[str, Any]]:
    with _lock:
        try:
            c = _get_conn()
            cur = c.execute(
                "SELECT ts, cpu, ram_pct, disk_min_free_pct FROM samples ORDER BY id DESC LIMIT ?",
                (limit,),
            )
            rows = cur.fetchall()
        except sqlite3.Error:
            return []
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append({"ts": r[0], "cpu": r[1], "ram_pct": r[2], "disk_min_free_pct": r[3]})
    return out
