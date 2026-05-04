"""
Entry script for PyInstaller: builds a standalone graphical .exe (no Python window).
Run:  pwsh -File scripts\\Build-PCCheckerExe.ps1

Attribution and distribution policy are defined in pc_checker.__init__ (APP_ATTRIBUTION, etc.).
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
