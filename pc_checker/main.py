from __future__ import annotations

import argparse
import sys

from pc_checker import APP_ATTRIBUTION


def main() -> int:
    parser = argparse.ArgumentParser(
        description="PC Checker — Windows health and freeze-risk hints.",
        epilog=APP_ATTRIBUTION,
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--cli",
        action="store_true",
        help="Run text report in the terminal instead of the graphical app.",
    )
    mode.add_argument(
        "--web",
        action="store_true",
        help="Open the HTML/CSS dashboard in your browser (local server on this PC).",
    )
    parser.add_argument(
        "--no-api",
        action="store_true",
        help="Do not start the local HTTP API when opening the CustomTkinter app (ignored with --web).",
    )
    parser.add_argument(
        "--no-elevate",
        action="store_true",
        help="Do not show the UAC prompt to restart as administrator.",
    )
    parser.add_argument(
        "--no-tray",
        action="store_true",
        help="Do not show the system tray icon (background export/webhook/metrics still run).",
    )
    args = parser.parse_args()

    if args.cli:
        from pc_checker.cli import run_cli

        return run_cli()

    if not args.no_elevate:
        from pc_checker.elevation import relaunch_elevated_same_args

        if relaunch_elevated_same_args():
            return 0

    if args.web:
        from pc_checker.web_mode import run_web_dashboard

        run_web_dashboard()
        return 0

    from pc_checker.logging_config import setup_app_logging

    setup_app_logging()

    from pc_checker.gui.app import run_app

    run_app(enable_api=not args.no_api, no_tray=args.no_tray)
    return 0


if __name__ == "__main__":
    sys.exit(main())
