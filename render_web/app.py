"""
PC Checker — full web dashboard on Render (Linux).

Serves the same static UI as the Windows app (`pc_checker/web/public`) and
implements the same JSON API shape from the last snapshot POSTed by your PC
(Settings → Webhook URL = `https://<service>.onrender.com/api/ingest`).

Windows WMI/diagnostics still run only on your machine; this service is a live
viewer — not a rewrite of collectors onto Linux (that cannot see your PC).
"""

from __future__ import annotations

import os
import re
import secrets
import threading
import time
from pathlib import Path
from typing import Annotated, Any, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.responses import Response

REPO_ROOT = Path(__file__).resolve().parent.parent
WEB_PUBLIC = REPO_ROOT / "pc_checker" / "web" / "public"

TOKEN = os.environ.get("PC_CHECKER_CLOUD_TOKEN", "").strip()

_lock = threading.Lock()
_last: dict[str, Any] = {}
_ingested_at: float = 0.0

app = FastAPI(title="PC Checker (cloud)", version="1")


def _package_version() -> str:
    init_p = REPO_ROOT / "pc_checker" / "__init__.py"
    if not init_p.is_file():
        return "0.0.0"
    for line in init_p.read_text(encoding="utf-8").splitlines():
        m = re.match(r'__version__\s*=\s*["\']([^"\']+)["\']', line.strip())
        if m:
            return m.group(1)
    return "0.0.0"


def _read_app_owner() -> str:
    init_p = REPO_ROOT / "pc_checker" / "__init__.py"
    if not init_p.is_file():
        return ""
    for line in init_p.read_text(encoding="utf-8").splitlines():
        m = re.match(r'APP_OWNER\s*=\s*["\']([^"\']*)["\']', line.strip())
        if m:
            return m.group(1)
    return ""


def _read_attribution() -> str:
    owner = _read_app_owner() or "the author"
    return (
        f"Personal application by {owner}; cloud view shows read-only snapshots "
        "pushed from your Windows PC. Not for public distribution."
    )


def _need_token_configured() -> str:
    if not TOKEN:
        raise HTTPException(
            503,
            "Set PC_CHECKER_CLOUD_TOKEN in Render environment variables and redeploy.",
        )
    return TOKEN


def _token_match(got: str) -> bool:
    if not TOKEN or not got:
        return False
    try:
        return secrets.compare_digest(got.strip(), TOKEN)
    except (TypeError, ValueError):
        return False


def _viewer(request: Request, authorization: Optional[str] = Header(None)) -> None:
    _need_token_configured()
    if authorization and authorization.lower().startswith("bearer "):
        if _token_match(authorization[7:]):
            return
    c = request.cookies.get("pc_checker_cloud") or ""
    if _token_match(c):
        return
    raise HTTPException(
        401,
        "Sign in: POST /api/v1/session with JSON {token} or send Authorization: Bearer <token>.",
    )


AuthViewer = Annotated[None, Depends(_viewer)]


class SessionBody(BaseModel):
    token: str


def _cookie_secure() -> bool:
    return os.environ.get("RENDER", "").lower() == "true"


def _snapshot() -> dict[str, Any]:
    with _lock:
        return dict(_last)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/ingest")
async def ingest(request: Request, authorization: Optional[str] = Header(None)) -> JSONResponse:
    _need_token_configured()
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "Use Authorization: Bearer <PC_CHECKER_CLOUD_TOKEN>")
    if not _token_match(authorization[7:]):
        raise HTTPException(403, "Invalid bearer token")
    try:
        body = await request.json()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"Invalid JSON: {exc}") from exc
    if not isinstance(body, dict):
        raise HTTPException(400, "JSON body must be an object")
    global _ingested_at
    with _lock:
        _last.clear()
        _last.update(body)
        _ingested_at = time.time()
    return JSONResponse({"ok": True, "keys": list(body.keys())[:50]})


@app.post("/api/v1/session")
def api_session(body: SessionBody, response: Response) -> dict[str, Any]:
    _need_token_configured()
    if not _token_match(body.token):
        raise HTTPException(403, "Invalid token")
    response.set_cookie(
        key="pc_checker_cloud",
        value=TOKEN,
        max_age=86400 * 90,
        httponly=True,
        samesite="lax",
        secure=_cookie_secure(),
        path="/",
    )
    return {"ok": True, "message": "Session cookie set for this browser."}


@app.post("/api/v1/session/logout")
def api_session_logout(response: Response) -> dict[str, Any]:
    response.delete_cookie("pc_checker_cloud", path="/")
    return {"ok": True}


@app.get("/api/v1/meta")
def api_meta() -> dict[str, Any]:
    """Public: no secrets; used by dashboard header before sign-in."""
    age: Optional[float] = None
    with _lock:
        if _ingested_at:
            age = round(time.time() - _ingested_at, 1)
    ext = os.environ.get("RENDER_EXTERNAL_URL", "").strip()
    return {
        "app": "PC Checker (cloud)",
        "version": _package_version(),
        "bind": "render",
        "port": 443 if ext else 0,
        "owner": _read_app_owner(),
        "attribution": _read_attribution(),
        "not_for_public_distribution": True,
        "cloud": True,
        "snapshot_age_seconds": age,
        "external_url": ext or None,
    }


@app.get("/api/v1/live")
def api_live(_: AuthViewer) -> dict[str, Any]:
    s = _snapshot()
    if not s:
        return {"live": {}, "history": {"timestamp": [], "cpu_percent": [], "ram_percent": []}, "top_processes": []}
    hist = dict(s.get("history") or {})
    hist.setdefault("timestamp", [])
    hist.setdefault("cpu_percent", [])
    hist.setdefault("ram_percent", [])
    return {
        "live": dict(s.get("live") or {}),
        "history": hist,
        "top_processes": list(s.get("top_processes") or []),
    }


@app.get("/api/v1/diagnostics")
def api_diagnostics(_: AuthViewer) -> dict[str, Any]:
    s = _snapshot()
    return {
        "findings": list(s.get("findings") or []),
        "software_findings": list(s.get("software_findings") or []),
        "disk_hints": dict(s.get("disk_hints") or {}),
        "extended": dict(s.get("extended") or {}),
        "scan_compare_summary": str(s.get("scan_compare_summary") or ""),
    }


@app.get("/api/v1/updates")
def api_updates(_: AuthViewer) -> dict[str, Any]:
    s = _snapshot()
    u = dict(s.get("updates") or {})
    return {
        "defender": dict(u.get("defender") or {}),
        "windows_update": dict(u.get("windows_update") or {"items": [], "error": None, "fetched_at": None}),
        "winget": dict(u.get("winget") or {"items": [], "error": None, "fetched_at": None}),
        "refresh_busy": False,
    }


@app.get("/api/v1/disks")
def api_disks(_: AuthViewer) -> dict[str, Any]:
    s = _snapshot()
    d = s.get("disks")
    if isinstance(d, dict) and "volumes" in d:
        return dict(d)
    return {"volumes": []}


@app.get("/api/v1/metrics/samples")
def api_metrics_samples(_: AuthViewer, limit: int = 200) -> dict[str, Any]:
    _ = limit
    return {"samples": []}


def _action_stub() -> dict[str, Any]:
    return {
        "accepted": False,
        "message": "This action runs only on your Windows PC. Use the desktop app there; the cloud view shows the last pushed snapshot.",
    }


@app.post("/api/v1/diagnostics/scan")
def api_diagnostics_scan(_: AuthViewer) -> dict[str, Any]:
    return _action_stub()


@app.post("/api/v1/updates/refresh")
def api_updates_refresh(_: AuthViewer) -> dict[str, Any]:
    return _action_stub()


@app.post("/api/v1/actions/defender-signatures")
def api_defender_signatures(_: AuthViewer) -> dict[str, Any]:
    return _action_stub()


@app.post("/api/v1/actions/windows-update-scan")
def api_windows_update_scan(_: AuthViewer) -> dict[str, Any]:
    return _action_stub()


_CLOUD_INJECT = """
<div id="pc-checker-cloud-login" style="background:#1e2836;padding:10px 16px;border-bottom:1px solid #30363d;font-family:system-ui,sans-serif;color:#e6edf3;font-size:14px;">
  <strong>Cloud view</strong> — Data is pushed from your Windows PC (PC Checker → Settings → Webhook).
  Use the same secret as Render env <code style="background:#111;padding:2px 6px;border-radius:4px;">PC_CHECKER_CLOUD_TOKEN</code>:
  <input type="password" id="pc-checker-cloud-token-input" placeholder="Token" autocomplete="off" style="padding:6px 10px;width:min(280px,40vw);margin:0 8px;border-radius:6px;border:1px solid #444;background:#0d1117;color:#e6edf3;"/>
  <button type="button" id="pc-checker-cloud-token-save" style="padding:6px 14px;border-radius:6px;border:1px solid #30363d;background:#21262d;color:#e6edf3;cursor:pointer;">Save session</button>
  <span id="pc-checker-cloud-login-msg" style="margin-left:10px;color:#8b949e;"></span>
</div>
<script>
(function(){
  function go(){
    var t=document.getElementById("pc-checker-cloud-token-input");
    var msg=document.getElementById("pc-checker-cloud-login-msg");
    var btn=document.getElementById("pc-checker-cloud-token-save");
    if(!t||!msg||!btn) return;
    btn.onclick=function(){
      msg.textContent="…";
      fetch("/api/v1/session",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({token:t.value.trim()})})
        .then(function(r){return r.json().then(function(j){return{r:r,j:j};});})
        .then(function(x){
          if(x.r.ok){msg.textContent="OK — reloading";location.reload();}
          else{msg.textContent=(x.j&&x.j.detail)||JSON.stringify(x.j)||("HTTP "+x.r.status);}
        }).catch(function(e){msg.textContent=String(e);});
    };
  }
  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",go);else go();
})();
</script>
"""


@app.get("/", response_model=None)
async def spa_index() -> Response:
    idx = WEB_PUBLIC / "index.html"
    if not idx.is_file():
        return PlainTextResponse(
            "Web UI missing. Deploy from repository root so pc_checker/web/public exists.",
            status_code=404,
        )
    html = idx.read_text(encoding="utf-8")
    sub = (
        '<p class="sub">Cloud dashboard — metrics and diagnostics reflect the '
        "<strong>last snapshot</strong> POSTed from your Windows PC. Actions (scan, updates) run on the PC only.</p>"
    )
    html = html.replace(
        "<p class=\"sub\">Local dashboard — HTML/CSS in your browser. API + live metrics on this machine only.</p>",
        sub,
        1,
    )
    html = html.replace("<body>", "<body>" + _CLOUD_INJECT, 1)
    return Response(content=html, media_type="text/html; charset=utf-8")


if WEB_PUBLIC.is_dir():
    app.mount("/assets", StaticFiles(directory=str(WEB_PUBLIC)), name="assets")
