from __future__ import annotations

import os
import threading
from pathlib import Path

import psutil
import uvicorn
from fastapi import BackgroundTasks, FastAPI, HTTPException
from starlette.responses import FileResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles

from pc_checker import APP_ATTRIBUTION, APP_NOT_FOR_PUBLIC_DISTRIBUTION, APP_OWNER, __version__
from pc_checker.diagnostics_collect import apply_full_diagnostics_to_state
from pc_checker.metrics_db import recent_samples
from pc_checker.services.update_fetch import (
    fetch_all_updates,
    get_defender_status,
    trigger_defender_signature_update,
    trigger_windows_update_scan,
)
from pc_checker.state import SharedState

WEB_PUBLIC = Path(__file__).resolve().parent.parent / "web" / "public"


def create_app(state: SharedState) -> FastAPI:
    app = FastAPI(
        title="PC Checker API",
        description=f"{APP_ATTRIBUTION} Not for public distribution.",
        version=__version__,
        docs_url="/docs",
        redoc_url=None,
    )

    @app.get("/api/v1/live")
    def api_live() -> dict:
        return state.get_live_bundle()

    @app.get("/api/v1/diagnostics")
    def api_diagnostics() -> dict:
        return state.get_diagnostics_bundle()

    @app.get("/api/v1/updates")
    def api_updates() -> dict:
        return state.get_updates_bundle()

    @app.get("/api/v1/metrics/samples")
    def api_metrics_samples(limit: int = 200) -> dict:
        lim = max(1, min(int(limit), 2000))
        return {"samples": recent_samples(lim)}

    @app.get("/api/v1/disks")
    def api_disks() -> dict:
        rows: list[dict] = []
        for part in psutil.disk_partitions(all=False):
            try:
                u = psutil.disk_usage(part.mountpoint)
            except OSError:
                continue
            total = u.total or 1
            rows.append(
                {
                    "device": part.device or part.mountpoint,
                    "mountpoint": part.mountpoint,
                    "free_percent": round(100.0 * u.free / total, 2),
                    "used_percent": round(100.0 * u.used / total, 2),
                }
            )
        return {"volumes": rows}

    @app.post("/api/v1/diagnostics/scan")
    def api_diagnostics_scan(background_tasks: BackgroundTasks) -> dict:
        background_tasks.add_task(apply_full_diagnostics_to_state, state)
        return {"accepted": True, "message": "Diagnostics scan started."}

    @app.post("/api/v1/updates/refresh")
    def api_updates_refresh(background_tasks: BackgroundTasks) -> dict:
        background_tasks.add_task(fetch_all_updates, state)
        return {
            "accepted": True,
            "message": "Refresh started in background. Poll GET /api/v1/updates until refresh_busy is false.",
        }

    @app.post("/api/v1/actions/defender-signatures")
    def api_defender_signatures() -> dict:
        ok, msg = trigger_defender_signature_update()
        if not ok:
            raise HTTPException(status_code=500, detail=msg)
        state.set_defender(get_defender_status())
        return {"ok": True, "message": msg}

    @app.post("/api/v1/actions/windows-update-scan")
    def api_windows_update_scan() -> dict:
        ok, msg = trigger_windows_update_scan()
        return {"ok": ok, "message": msg}

    @app.get("/api/v1/meta")
    def api_meta() -> dict:
        return {
            "app": "PC Checker",
            "version": __version__,
            "bind": os.environ.get("PC_CHECKER_API_HOST", "127.0.0.1"),
            "port": int(os.environ.get("PC_CHECKER_API_PORT", "8765")),
            "owner": APP_OWNER,
            "attribution": APP_ATTRIBUTION,
            "not_for_public_distribution": APP_NOT_FOR_PUBLIC_DISTRIBUTION,
        }

    if WEB_PUBLIC.is_dir():
        app.mount("/assets", StaticFiles(directory=str(WEB_PUBLIC)), name="assets")

        @app.get("/", response_model=None)
        async def spa_index() -> Response:
            idx = WEB_PUBLIC / "index.html"
            if not idx.is_file():
                return PlainTextResponse("Web UI missing (pc_checker/web/public/index.html).", status_code=404)
            return FileResponse(idx)

    return app


def start_api_background(state: SharedState) -> str:
    host = os.environ.get("PC_CHECKER_API_HOST", "127.0.0.1")
    port = int(os.environ.get("PC_CHECKER_API_PORT", "8765"))
    app = create_app(state)

    def run() -> None:
        uvicorn.run(app, host=host, port=port, log_level="warning")

    threading.Thread(target=run, daemon=True).start()
    return f"http://{host}:{port}"
