"""Persistent settings in %LOCALAPPDATA%\\PCChecker\\settings.json."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


def app_data_dir() -> Path:
    local = os.environ.get("LOCALAPPDATA", "")
    root = Path(local) if local else Path.home()
    d = root / "PCChecker"
    d.mkdir(parents=True, exist_ok=True)
    return d


def settings_path() -> Path:
    return app_data_dir() / "settings.json"


_INT_KEYS = frozenset(
    {
        "live_poll_ms",
        "view_poll_ms",
        "diag_interval_ms",
        "queue_poll_ms",
        "metrics_sample_interval_s",
        "webhook_interval_min",
        "scheduled_export_interval_min",
    }
)
_FLOAT_KEYS = frozenset({"wmi_temp_ttl_s", "alert_cpu_pct", "alert_ram_pct", "alert_disk_free_pct", "alert_cooldown_s"})
_BOOL_KEYS = frozenset({"hide_attribution_banner", "enable_tray", "enable_metrics_db"})


@dataclass
class AppSettings:
    live_poll_ms: int = 1000
    view_poll_ms: int = 1200
    diag_interval_ms: int = 75_000
    queue_poll_ms: int = 150
    wmi_temp_ttl_s: float = 45.0
    hide_attribution_banner: bool = False
    enable_tray: bool = True
    enable_metrics_db: bool = True
    metrics_sample_interval_s: int = 60
    alert_cpu_pct: float = 95.0
    alert_ram_pct: float = 92.0
    alert_disk_free_pct: float = 5.0
    alert_cooldown_s: float = 3600.0
    webhook_url: str = ""
    webhook_bearer_token: str = ""
    webhook_interval_min: int = 0
    scheduled_export_interval_min: int = 0
    scheduled_export_dir: str = ""

    def to_json_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AppSettings:
        d = asdict(cls())
        for k, raw in data.items():
            if k not in d:
                continue
            try:
                if k in _INT_KEYS:
                    d[k] = int(raw)
                elif k in _FLOAT_KEYS:
                    d[k] = float(raw)
                elif k in _BOOL_KEYS:
                    d[k] = bool(raw)
                else:
                    d[k] = str(raw)
            except (TypeError, ValueError):
                pass
        return cls(**d)  # type: ignore[arg-type]


def load_settings() -> AppSettings:
    p = settings_path()
    if not p.is_file():
        return AppSettings()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return AppSettings()
        return AppSettings.from_dict(data)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return AppSettings()


def save_settings(s: AppSettings) -> None:
    settings_path().write_text(json.dumps(s.to_json_dict(), indent=2), encoding="utf-8")
