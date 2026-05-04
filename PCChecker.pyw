"""
Double-click this file in Explorer to open PC Checker with no console window
(requires Python installed; .pyw must open with pythonw.exe — default on Windows).
"""
from __future__ import annotations

import sys
from pathlib import Path

if not getattr(sys, "frozen", False):
    _root = Path(__file__).resolve().parent
    _r = str(_root)
    if _r not in sys.path:
        sys.path.insert(0, _r)

from pc_checker.main import main

if __name__ == "__main__":
    raise SystemExit(main())
