"""Heuristics for apps that are easier to relocate vs Windows-protected installs, and common cleanup folders.

This is guidance only: moving Program Files trees or deleting caches can break software or Windows if done wrong.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any


def _norm(p: str) -> str:
    return os.path.normcase(os.path.normpath(os.path.expandvars(p)))


def _is_under(path: str, parent: str) -> bool:
    try:
        p = Path(path).resolve()
        q = Path(parent).resolve()
        return q in p.parents or p == q
    except (OSError, ValueError):
        return False


def _windir() -> str:
    return _norm(os.environ.get("SystemRoot", r"C:\Windows"))


def _os_drive() -> str:
    return Path(os.environ.get("SystemDrive", "C:")).drive.upper()


def _iter_uninstall_pairs() -> list[tuple[str, str]]:
    """All (DisplayName, InstallLocation) with a valid directory, for registry matching."""
    if sys.platform != "win32":
        return []
    import winreg

    roots: list[tuple[int, str]] = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    ]
    out: list[tuple[str, str]] = []
    seen: set[str] = set()

    for hive, sub in roots:
        try:
            k = winreg.OpenKey(hive, sub)
        except OSError:
            continue
        try:
            i = 0
            while True:
                try:
                    name = winreg.EnumKey(k, i)
                except OSError:
                    break
                i += 1
                try:
                    sk = winreg.OpenKey(k, name)
                except OSError:
                    continue
                try:
                    try:
                        disp = winreg.QueryValueEx(sk, "DisplayName")[0]
                    except OSError:
                        continue
                    if not isinstance(disp, str) or not disp.strip():
                        continue
                    try:
                        loc = winreg.QueryValueEx(sk, "InstallLocation")[0]
                    except OSError:
                        continue
                    if not isinstance(loc, str) or not loc.strip():
                        continue
                    loc_exp = _norm(loc.strip().strip('"'))
                    if not loc_exp or not os.path.isdir(loc_exp):
                        continue
                    key = f"{disp}|{loc_exp}"
                    if key in seen:
                        continue
                    seen.add(key)
                    out.append((disp.strip(), loc_exp))
                finally:
                    sk.Close()
        finally:
            k.Close()

    out.sort(key=lambda t: t[0].lower())
    return out


def _enum_uninstall_entries() -> list[tuple[str, str]]:
    """Subset for the relocatable-apps list (cap keeps UI small)."""
    pairs = _iter_uninstall_pairs()
    return pairs[:200]


def _program_files_top_level_review(pairs: list[tuple[str, str]]) -> list[dict[str, Any]]:
    """
    Each direct child of Program Files and Program Files (x86): does any Uninstall InstallLocation
    point at that folder or inside it? This does NOT prove a folder is unused if unmatched.
    """
    if sys.platform != "win32":
        return []

    pf = _norm(os.environ.get("ProgramFiles", r"C:\Program Files"))
    pfx86 = os.environ.get("ProgramFiles(x86)")
    roots: list[str] = [pf]
    if pfx86:
        roots.append(_norm(pfx86))

    norm_pairs: list[tuple[str, str]] = []
    for disp, loc in pairs:
        nl = _norm(loc)
        if os.path.isdir(nl):
            norm_pairs.append((disp, nl))

    store_managed = {"windowsapps", "modifiablewindowsapps"}
    rows: list[dict[str, Any]] = []

    for root in roots:
        if not root or not os.path.isdir(root):
            continue
        root_key = root.rstrip(os.sep).lower()
        try:
            names = os.listdir(root)
        except OSError:
            continue
        for name in names:
            child = _norm(os.path.join(root, name))
            if not os.path.isdir(child):
                continue
            base = os.path.basename(child).lower()
            is_pf64 = root_key == pf.rstrip(os.sep).lower()

            if is_pf64 and base in store_managed:
                rows.append(
                    {
                        "path": child,
                        "parent": root,
                        "status": "store_managed",
                        "matched_products": [],
                        "detail": (
                            "Store / packaged apps live here. Do not delete manually; remove apps via "
                            "Settings → Apps or the Store. Not covered by classic Uninstall registry paths."
                        ),
                    }
                )
                continue

            all_matched: list[str] = []
            for disp, loc in norm_pairs:
                if loc == child or loc.startswith(child + os.sep):
                    if disp not in all_matched:
                        all_matched.append(disp)

            if all_matched:
                matched = all_matched[:8]
                extra = max(0, len(all_matched) - 8)
                tail = f" (+{extra} more)" if extra > 0 else None
                rows.append(
                    {
                        "path": child,
                        "parent": root,
                        "status": "matched_in_uninstall_registry",
                        "matched_products": matched,
                        "matched_products_note": tail,
                        "detail": (
                            "At least one Add/Remove Programs entry references this folder (or a path inside it). "
                            "Treat it as required for those products. Redundant *files inside* the product folder "
                            "(old DLLs, duplicates) cannot be judged from the registry — use the app's uninstall/repair, "
                            "or vendor cleanup tools, not manual guessing."
                        ),
                    }
                )
            else:
                rows.append(
                    {
                        "path": child,
                        "parent": root,
                        "status": "no_installlocation_match",
                        "matched_products": [],
                        "detail": (
                            "No InstallLocation in the scanned Uninstall keys matched this top-level folder. "
                            "It can still be required: drivers, optional components, portable installs, "
                            "or installers that did not write InstallLocation. Do not delete based on this alone — "
                            "verify with the vendor, Settings → Apps, or disk tools before removing."
                        ),
                    }
                )

    status_order = {"matched_in_uninstall_registry": 0, "store_managed": 1, "no_installlocation_match": 2}
    rows.sort(key=lambda r: (status_order.get(str(r.get("status")), 9), str(r.get("path", "")).lower()))
    return rows


def _classify_app(loc: str) -> tuple[str, str]:
    """Return (category, how_to_move)."""
    loc_l = loc.lower()
    wind = _windir().lower()
    if loc_l.startswith(wind) or "\\windows\\" in loc_l:
        return ("system_windows", "Do not move — under Windows. Use optional features / DISM for component store, not drag-and-drop.")

    if "steamapps" in loc_l or "\\steam\\" in loc_l:
        return (
            "steam_or_game_client",
            "Steam: Steam → Settings → Storage → select drive → Move content / add library folder. "
            "Epic/others: use the store app's library or repair tools — do not move the folder in Explorer alone.",
        )

    drive = Path(loc).drive.upper() if Path(loc).drive else ""
    os_drive = _os_drive()
    local = _norm(os.environ.get("LOCALAPPDATA", ""))
    roaming = _norm(os.environ.get("APPDATA", ""))
    pf = os.path.normcase(os.environ.get("ProgramFiles", r"C:\Program Files"))
    pfx86 = os.path.normcase(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))

    if drive and drive != os_drive:
        return (
            "already_off_system_volume",
            "Already on a non–system drive. To consolidate: move via the app's own settings when available; "
            "otherwise uninstall and reinstall to the target path. Avoid moving while the app is running.",
        )

    if local and _is_under(loc, local):
        return (
            "per_user_install",
            "Per-user install. Prefer Settings → Apps → Installed apps → … → Move (if shown). "
            "If Move is missing: uninstall, then reinstall and pick a folder on another drive during setup.",
        )

    if roaming and _is_under(loc, roaming):
        return (
            "per_user_roaming",
            "Under Roaming AppData — usually config/saves mixed with binaries. Prefer uninstall + reinstall to a new path "
            "or the vendor's documented migration; do not only drag the folder.",
        )

    if loc_l.startswith(pf) or loc_l.startswith(pfx86):
        return (
            "program_files_classic",
            "Classic Program Files install: do not cut/paste the folder. Use uninstall, then reinstall choosing another location, "
            "or a junction/symlink only if you understand repair/upgrade impact.",
        )

    return (
        "other_path",
        "Check the vendor docs. General pattern: quit the app, uninstall from Settings, reinstall to the new directory, "
        "or use the app's built-in library/folder move if it has one.",
    )


def _bounded_dir_size_mb(root: Path, *, max_files: int = 10_000) -> tuple[float | None, bool]:
    """Return (size_mb, truncated). None if unreadable."""
    total = 0
    n = 0
    truncated = False
    try:
        for dirpath, _dirnames, filenames in os.walk(root, topdown=True):
            for fn in filenames:
                fp = Path(dirpath) / fn
                try:
                    total += fp.stat().st_size
                except OSError:
                    pass
                n += 1
                if n >= max_files:
                    truncated = True
                    return (round(total / (1024 * 1024), 1), truncated)
    except OSError:
        return (None, False)
    return (round(total / (1024 * 1024), 1), truncated)


def _deletable_candidates() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    paths: list[tuple[str, str, str, str]] = []
    temp = os.environ.get("TEMP") or os.environ.get("TMP")
    if temp:
        paths.append(
            (
                "low",
                temp,
                "User TEMP",
                "Programs recreate these files. Close apps first; prefer Settings → Storage or empty files inside.",
            )
        )
    local = os.environ.get("LOCALAPPDATA")
    if local:
        paths.append(
            (
                "low",
                os.path.join(local, "Temp"),
                "LocalAppData\\Temp",
                "Same idea as %TEMP%; clear when apps are closed.",
            )
        )
        windir = os.environ.get("SystemRoot", r"C:\Windows")
        paths.append(
            (
                "medium",
                os.path.join(windir, "SoftwareDistribution", "Download"),
                "Windows Update download cache",
                "Optional: pause updates / use Disk Cleanup 'Windows Update Cleanup' rather than deleting mid-install.",
            )
        )
        paths.append(
            (
                "medium",
                os.path.join(local, "Microsoft", "Windows", "INetCache"),
                "INetCache (legacy web cache)",
                "Browsers may refill; close apps that use the old stack first.",
            )
        )
        edge_cache = os.path.join(local, "Microsoft", "Edge", "User Data", "Default", "Cache")
        paths.append(
            (
                "medium",
                edge_cache,
                "Microsoft Edge cache",
                "Close Edge first; prefer Edge → Settings → Privacy → Clear browsing data.",
            )
        )
        chrome_cache = os.path.join(local, "Google", "Chrome", "User Data", "Default", "Cache")
        paths.append(
            (
                "medium",
                chrome_cache,
                "Google Chrome cache",
                "Exit Chrome; prefer Chrome's clear browsing data.",
            )
        )
        do = os.path.join(local, "Microsoft", "Windows", "DeliveryOptimization", "Cache")
        paths.append(
            (
                "high",
                do,
                "Delivery Optimization cache",
                "Large at times; adjust in Settings → Windows Update → Advanced → Delivery Optimization instead of blind delete.",
            )
        )

    sysdrive = os.environ.get("SystemDrive", "C:")
    wo = os.path.join(sysdrive, "Windows.old")
    paths.append(
        (
            "high",
            wo,
            "Windows.old",
            "Only if you do not need upgrade rollback. Use Disk Cleanup → 'Previous Windows installation(s)'.",
        )
    )

    for risk, raw, label, notes in paths:
        p = _norm(raw)
        if not p or not os.path.isdir(p):
            continue
        size_mb, truncated = _bounded_dir_size_mb(Path(p))
        suffix = " (partial scan; size is a lower bound)" if truncated else ""
        row: dict[str, Any] = {
            "path": p,
            "label": label,
            "risk": risk,
            "notes": notes,
        }
        if size_mb is not None:
            row["size_mb"] = size_mb
            row["size_note"] = f"~{size_mb} MB under this folder{suffix}" if size_mb else "0 MB (empty or unreadable)"
        rows.append(row)

    return rows


def collect_disk_hints() -> dict[str, Any]:
    """Structured hints for the GUI/API — not automated moves or deletes."""
    if sys.platform != "win32":
        return {
            "relocatable_apps": [],
            "deletable_folders": [],
            "program_files_top_level": [],
            "program_files_disclaimer": "",
            "notes": "Disk hints are implemented for Windows only.",
        }

    pairs = _iter_uninstall_pairs()
    apps: list[dict[str, Any]] = []
    for disp, loc in pairs[:200]:
        cat, how = _classify_app(loc)
        if cat == "system_windows":
            continue
        apps.append(
            {
                "name": disp,
                "install_location": loc,
                "category": cat,
                "how_to_move": how,
            }
        )

    # Prefer showing non–system-volume and game-client rows first
    order = {
        "already_off_system_volume": 0,
        "steam_or_game_client": 1,
        "per_user_install": 2,
        "per_user_roaming": 3,
        "program_files_classic": 4,
        "other_path": 5,
    }
    apps.sort(key=lambda r: (order.get(r["category"], 9), r["name"].lower()))

    pf_scan = _program_files_top_level_review(pairs)
    pf_disclaimer = (
        "Program Files scan: only compares top-level folders to InstallLocation values in the classic Uninstall registry. "
        "It cannot detect redundant files *inside* an installed product (duplicate DLLs, caches, old versions) — only "
        "uninstall/repair tools or the vendor can do that safely. "
        "\"No match\" does not mean safe to delete; \"matched\" means at least one listed app claims that tree."
    )

    return {
        "relocatable_apps": apps[:120],
        "deletable_folders": _deletable_candidates(),
        "program_files_top_level": pf_scan,
        "program_files_disclaimer": pf_disclaimer,
        "notes": (
            "Read-only hints. Moving apps: prefer vendor/store tools or uninstall+reinstall; dragging folders often breaks "
            "shortcuts, services, and updates. Deleting: prefer Windows Settings → Storage or Disk Cleanup; avoid deleting "
            "random folders under C:\\Windows. Run as Administrator for a fuller uninstall registry view."
        ),
    }
