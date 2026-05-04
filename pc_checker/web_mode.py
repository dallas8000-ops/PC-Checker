"""Browser dashboard: HTML/CSS/JS served locally; live metrics via background threads."""

from __future__ import annotations

import os
import threading
import time
import webbrowser

import uvicorn

from pc_checker.api.server import create_app
from pc_checker.diagnostics_collect import apply_full_diagnostics_to_state
from pc_checker.elevation import hide_attached_console_window
from pc_checker.metrics_background import start_background_feed
from pc_checker.services.update_fetch import schedule_updates_refresh
from pc_checker.state import SharedState


def run_web_dashboard() -> None:
    hide_attached_console_window()
    host = os.environ.get("PC_CHECKER_API_HOST", "127.0.0.1")
    port = int(os.environ.get("PC_CHECKER_API_PORT", "8765"))

    state = SharedState()
    stop = threading.Event()
    start_background_feed(state, stop)

    def diag_loop() -> None:
        time.sleep(0.5)
        while not stop.is_set():
            try:
                apply_full_diagnostics_to_state(state)
            except Exception:
                pass
            if stop.wait(75):
                break

    threading.Thread(target=diag_loop, daemon=True).start()

    def delayed_updates() -> None:
        time.sleep(2.0)
        schedule_updates_refresh(state)

    threading.Thread(target=delayed_updates, daemon=True).start()

    app = create_app(state)
    url = f"http://{host}:{port}/"

    def open_browser() -> None:
        time.sleep(0.9)
        webbrowser.open(url)

    threading.Thread(target=open_browser, daemon=True).start()

    uvicorn.run(app, host=host, port=port, log_level="info")
