"""Windows UAC: detect administrator token and relaunch with elevation."""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys

_SW_HIDE = 0


def hide_attached_console_window() -> None:
    """
    Hide a standalone console window allocated to this process (e.g. python.exe
    started via double-click or Start-Process).

    If this process shares a console with a parent shell (Cursor, cmd, PowerShell),
    GetConsoleProcessList reports multiple processes — we do not hide, so the
    terminal is not minimized or closed.

    Set PC_CHECKER_KEEP_CONSOLE=1 to skip (useful when debugging print output).
    """
    if os.environ.get("PC_CHECKER_KEEP_CONSOLE", "").strip().lower() in ("1", "true", "yes"):
        return
    if sys.platform != "win32":
        return
    try:
        buf = (ctypes.c_ulong * 64)()
        n = int(ctypes.windll.kernel32.GetConsoleProcessList(buf, 64))
        if n != 1:
            return
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, _SW_HIDE)
    except Exception:
        pass


def gui_interpreter_exe() -> str:
    """Prefer pythonw.exe next to python.exe so new processes do not allocate a console."""
    if sys.platform != "win32":
        return sys.executable
    exe = sys.executable
    if exe.lower().endswith("python.exe"):
        cand = exe[:-10] + "pythonw.exe"
        if os.path.isfile(cand):
            return cand
    return exe


def is_admin() -> bool:
    """True if the current process has an elevated admin token (Windows) or on non-Windows."""
    if sys.platform != "win32":
        return True
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_elevated_same_args() -> bool:
    """
    Start a new elevated instance with the same interpreter and arguments.

    Returns True if an elevated process was queued — the caller should exit immediately.
    Returns False if already admin, not Windows, or the elevation request failed (e.g. UAC denied).
    """
    if sys.platform != "win32":
        return False
    if is_admin():
        return False

    # ShellExecute lpParameters must include the script for `python launcher.py …`;
    # argv[1:] alone is empty and produced no visible elevated app / confusing UAC behavior.
    if getattr(sys, "frozen", False):
        interpreter = sys.executable
        params = subprocess.list2cmdline(sys.argv[1:])
    else:
        interpreter = gui_interpreter_exe()
        script = os.path.abspath(sys.argv[0])
        params = subprocess.list2cmdline([script, *sys.argv[1:]])

    # SW_SHOWNORMAL
    rc = ctypes.windll.shell32.ShellExecuteW(
        None,
        "runas",
        interpreter,
        params,
        None,
        1,
    )
    return int(rc) > 32
