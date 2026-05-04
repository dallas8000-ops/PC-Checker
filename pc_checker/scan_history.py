"""Save last diagnostics snapshot for local compare (no cloud)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pc_checker.settings_store import app_data_dir


def snapshot_path() -> Path:
    return app_data_dir() / "last_scan.json"


def load_previous_snapshot() -> dict[str, Any] | None:
    p = snapshot_path()
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def save_snapshot(data: dict[str, Any]) -> None:
    snapshot_path().write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


def _finding_keys(findings: list[dict[str, Any]]) -> set[str]:
    keys: set[str] = set()
    for f in findings:
        keys.add(f"{f.get('severity', '')}|{f.get('title', '')}")
    return keys


def compare_snapshots(previous: dict[str, Any] | None, current: dict[str, Any]) -> str:
    if not previous:
        return (
            "No previous scan file yet. After this run, "
            f"{snapshot_path()} will hold the last snapshot for comparison on the next scan."
        )
    lines: list[str] = []
    prev_h = _finding_keys(list(previous.get("findings") or []))
    curr_h = _finding_keys(list(current.get("findings") or []))
    new_h = curr_h - prev_h
    gone_h = prev_h - curr_h
    if new_h:
        lines.append(f"Hardware/system findings new or changed ({len(new_h)}): " + "; ".join(sorted(new_h)[:12]) + ("…" if len(new_h) > 12 else ""))
    if gone_h:
        lines.append(f"Cleared or no longer reported ({len(gone_h)}): " + "; ".join(sorted(gone_h)[:12]) + ("…" if len(gone_h) > 12 else ""))

    prev_s = _finding_keys(list(previous.get("software_findings") or []))
    curr_s = _finding_keys(list(current.get("software_findings") or []))
    new_s = curr_s - prev_s
    gone_s = prev_s - curr_s
    if new_s:
        lines.append(f"Software log insights new/changed ({len(new_s)}): " + "; ".join(sorted(new_s)[:10]) + ("…" if len(new_s) > 10 else ""))
    if gone_s:
        lines.append(f"Software insights cleared ({len(gone_s)}): " + "; ".join(sorted(gone_s)[:10]) + ("…" if len(gone_s) > 10 else ""))

    if not lines:
        lines.append("No material change in finding keys vs last scan (titles/severity match previous set).")
    return "\n".join(lines)


def finalize_scan_after_update(state: Any) -> None:
    """Call after findings, software, disk_hints, and extended are written to state."""
    snap = state.export_snapshot()
    prev = load_previous_snapshot()
    state.set_scan_compare_summary(compare_snapshots(prev, snap))
    save_snapshot(snap)
