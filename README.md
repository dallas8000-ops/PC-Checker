# PC Checker

**Repository:** [https://github.com/dallas8000-ops/PC-Checker](https://github.com/dallas8000-ops/PC-Checker)

```powershell
git clone https://github.com/dallas8000-ops/PC-Checker.git
cd PC-Checker
```

Windows **health and diagnostics** desktop application: live metrics, structured checks, local HTTP API, browser dashboard, and reporting — built as **product-shaped** software (state, threading, elevation, persistence), not a single-file tutorial script.

**Version:** `pc_checker/__init__.py` (`__version__`).

---

## What this project demonstrates (portfolio)

**1. Real desktop client** — [CustomTkinter](https://github.com/TomSchimansky/CustomTkinter) GUI with **multi-tab** workflow, **background timers** for live vs diagnostic refresh rates, **UAC-aware relaunch** for administrator token, optional **system tray** (pystray), **SQLite-backed** background metric samples, **settings** persisted to disk, and **live charts** (Matplotlib) for CPU/RAM history. This is closer to a small shipped utility than a CRUD demo.

**2. Deep OS integration** — Collectors use **PowerShell / WMI (CIM)** and Windows-specific sources (Event Log patterns, Defender / Windows Update / winget catalogs, registry-backed disk hints, **hardware identity** via WMI classes, reliability-style counters where available). Work is **structured** (individual checks under `pc_checker/checks/`, aggregated diagnostics, export pipeline **JSON / HTML / PDF**) rather than ad hoc `os.system` calls.

**3. Coherent local API + web UI** — A single **`SharedState`** model (thread-safe) feeds the **GUI**, the **FastAPI** surface (`pc_checker/api/server.py`), and the **`--web`** dashboard (`pc_checker/web_mode.py`). The same snapshot shape powers **Insights & export** and optional **webhook POST** payloads, so the architecture is intentionally **one brain, many faces**.

**4. Clear tradeoffs** — All **measurement and remediation triggers** (signatures, WU scan, full diagnostics) run **on the Windows machine** — by design. Anything that presents “the same” UI elsewhere (e.g. optional **Render** mirror in `render_web/`) is a **read-only viewer of pushed JSON snapshots**, not a second implementation of WMI on Linux. Stating that boundary reads as **engineering judgment**, not a missing feature.

---

## Architecture (high level)

| Layer | Role |
|--------|------|
| `pc_checker/state.py` | Thread-safe `SharedState`: live samples, history deques, findings, updates, extended diagnostics, disk hints, export snapshot. |
| `pc_checker/gui/` | CustomTkinter app; schedules scans; drives charts and tabs. |
| `pc_checker/api/server.py` | FastAPI: `/api/v1/*` JSON + static `web/public` + OpenAPI `/docs`. |
| `pc_checker/checks/` | Modular checks (memory, events, storage, hardware identity, deep system, etc.). |
| `pc_checker/diagnostics_collect.py` | Orchestrates full diagnostic passes into state. |
| `pc_checker/background_services.py` | Tray, alerts, optional webhook / scheduled JSON export, metrics DB writer loop. |
| `pc_checker/web/public/` | Vanilla HTML/CSS/JS dashboard consumed locally or by optional cloud mirror. |

---

## Personal use — not for distribution

This repository is **personal software** by its author (**edit `APP_OWNER` in `pc_checker/__init__.py` for a private fork**). It is **not** intended for public distribution, resale, sublicense, or republication. The same notice appears in the app (title, footer, CLI, `GET /api/v1/meta`, OpenAPI, web UI).

The tool is **not** a substitute for full malware scans, SMART / burn-in tests, or vendor support. It does **not** move, delete, or repair files automatically (read-only hints and reports).

---

## Optional: cloud mirror (Render)

**Live URLs:**
- [https://react-store-catalog-1.onrender.com](https://react-store-catalog-1.onrender.com)
- [https://react-store-catalog.onrender.com](https://react-store-catalog.onrender.com)

Collectors **cannot** run on Linux hosts. The optional **`render_web/`** service serves the **same** static dashboard and compatible **`/api/v1/*`** responses from the **last JSON snapshot** POSTed by your PC (**Settings → Webhook** to `/api/ingest`, Bearer token aligned with env `PC_CHECKER_CLOUD_TOKEN`). See `render.yaml` and `render_web/app.py` for deploy shape. **Actions** (scan, Defender, WU) still execute only on Windows; the cloud UI explains that when invoked.

---

## Requirements

- **OS:** Windows 10/11 (most features are Windows-specific).
- **Python:** 3.10+ recommended.
- **Dependencies:** `pip install -r requirements.txt` (includes pystray, Pillow, requests, fpdf2, FastAPI, uvicorn, matplotlib, CustomTkinter, psutil, rich).

Optional: run **elevated** (Administrator) for richer Event Log and system data.

**Logs:** `%LOCALAPPDATA%\PCChecker\logs\pc_checker.log` (rotating). **Settings:** `%LOCALAPPDATA%\PCChecker\settings.json` (also editable in the **Settings** tab).

---

## Install (from source)

```powershell
cd "C:\path\to\PC Checker"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

---

## How to run

### Graphical app (default)

```powershell
python launcher.py
```

Windows may prompt **UAC** so the app can restart **as Administrator** (broader logs and update actions). Approve **Yes** if you want that behavior.

- `python launcher.py --no-elevate` — No UAC relaunch (IDE-friendly).
- `python launcher.py --no-api` — GUI only; no local HTTP API.
- `python launcher.py --no-tray` — No tray icon (background webhook/export loop can still run if enabled in Settings).

Module entry: `python -m pc_checker`

### Command-line report

```powershell
python launcher.py --cli
```

### Web dashboard (local)

```powershell
python launcher.py --web
```

Starts uvicorn and opens the browser; see `pc_checker/web_mode.py` for host/port environment variables.

---

## GUI overview

| Tab | Purpose |
|-----|--------|
| **Live** | CPU, RAM, swap, per-core load, disk space bars, disk I/O, optional temps, trend chart, optional local API URL. |
| **Software** | Top processes + Application log error patterns (from last scan). |
| **Updates & API** | Defender / WU / winget snapshot; refresh actions where permitted. |
| **Diagnostics** | Hardware/system findings; **Scan now** or periodic scan; **Next steps** on key findings. |
| **Disk & cleanup** | Install heuristics, Program Files vs Uninstall registry, cleanup path hints, **Copy report** (read-only). |
| **Settings** | Poll intervals, WMI temp cache TTL, footer, tray, SQLite metrics, alerts, webhook URL + optional Bearer token + interval, scheduled export path + interval. |
| **Insights & export** | Extended diagnostics (hardware identity, reliability-style data, trends, etc.); **JSON / HTML / PDF** export. |

---

## Local HTTP API

With API enabled (default GUI launch unless `--no-api`):

| Endpoint | Purpose |
|----------|---------|
| `GET /api/v1/live` | Live metrics + history + top processes. |
| `GET /api/v1/diagnostics` | Findings, software findings, `disk_hints`, `extended`, `scan_compare_summary`. |
| `GET /api/v1/updates` | Defender, Windows Update, winget bundles. |
| `GET /api/v1/disks` | Volume free/used summary. |
| `GET /api/v1/metrics/samples` | Recent SQLite samples (if enabled). |
| `POST /api/v1/diagnostics/scan` | Queue full diagnostics refresh. |

Interactive docs: **`/docs`** on the same host/port.

---

## Building `PCChecker.exe`

```powershell
pwsh -File .\scripts\Build-PCCheckerExe.ps1
```

Output: **`dist\PCChecker.exe`** (windowed). The script does not auto-launch the app.

---

## Repository layout

| Path | Role |
|------|------|
| `launcher.py` | Entry for PyInstaller / `python launcher.py`. |
| `pc_checker/main.py` | CLI, elevation, mode dispatch. |
| `pc_checker/gui/` | CustomTkinter UI. |
| `pc_checker/api/` | FastAPI + static web assets. |
| `pc_checker/checks/` | Diagnostic modules + disk hints. |
| `pc_checker/web/public/` | Web dashboard (HTML/CSS/JS). |
| `render_web/` | Optional cloud mirror (snapshot ingest + same UI). |
| `scripts/Build-PCCheckerExe.ps1` | One-file EXE build. |

---

## Troubleshooting

- **No UAC prompt** — `--no-elevate`, UAC off, or shell already elevated. Run without `--no-elevate` for the standard prompt.
- **Temperature missing** — Common without WMI thermal zones; collection is throttled/cached so the UI stays responsive (`pc_checker/sensors.py`).
- **API disabled / port in use** — Avoid `--no-api`; set `PC_CHECKER_API_HOST` / `PC_CHECKER_API_PORT` where supported.

---

## Development

Run `python launcher.py --no-elevate` for a predictable console. See `pc_checker/elevation.py` for `PC_CHECKER_KEEP_CONSOLE` behavior.

---

## Test status (current build)

- **Commit under test:** `1dfdfbd`
- **Command run:** `python -m pytest -q`
- **Result:** `2 passed in 0.03s`
- **Notes:** Current automated coverage is minimal (`tests/test_finding.py`); most validation today is runtime/manual on Windows (GUI flow, WMI/PowerShell collectors, API routes, export actions).
