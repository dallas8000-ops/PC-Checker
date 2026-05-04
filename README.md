# PC Checker

**Repository:** [https://github.com/dallas8000-ops/PC-Checker](https://github.com/dallas8000-ops/PC-Checker)

```powershell
git clone https://github.com/dallas8000-ops/PC-Checker.git
cd PC-Checker
```

Lightweight **Windows** diagnostics: live CPU/RAM/disk/temperature sampling, hardware and application log checks, update catalogs (Defender, Windows Update, winget), and **read-only** disk hints (install paths, Program Files registry cross-check, common cleanup folders). **Version:** see `pc_checker/__init__.py` (`__version__`).

## Personal use — not for distribution

**Author-facing / hardwired policy:** This repository is **personal software** by its author (**edit `APP_OWNER` in `pc_checker/__init__.py` if you adapt a private fork**). It is **not** intended for public distribution, resale, sublicense, or republication. The same notice is embedded in the app (window title, footer, CLI, API `GET /api/v1/meta`, OpenAPI description, and web UI via meta).

This tool is **not** a substitute for full malware scans, SMART/hardware burn-in tests, or vendor support. It does **not** move, delete, or repair files automatically.

---

## Live dashboard on Render (full web UI in the browser)

WMI, Event Log, Defender, and disk diagnostics **only run on Windows**. You cannot move that collector stack onto Render’s Linux hosts. What you *can* do is run the **same dashboard** on Render and feed it with **snapshots pushed from your PC**.

- **`render_web/app.py`** — FastAPI app that serves `pc_checker/web/public` (HTML/CSS/JS) and implements **`/api/v1/*`** the same way the local API does, backed by the **last ingested JSON** from your machine.
- **Your Windows PC** — Keep using the graphical app; in **Settings**, set **Webhook URL** to `https://<your-service>.onrender.com/api/ingest`, **Webhook Bearer token** to the same value as Render env **`PC_CHECKER_CLOUD_TOKEN`**, and a non‑zero **Webhook interval** (e.g. 5 minutes). Each POST sends a full export (live + **history** for charts, findings, extended, updates, **disk volumes**, disk hints, etc.).
- **First visit** — Open your Render URL, paste the token in the **Save session** bar at the top so the browser gets an **HttpOnly cookie**; then the dashboard loads data like the local web mode. **Scan / update / Defender** buttons respond with a message that those actions run on the PC only.

**Deploy on Render:** create a **Web Service**, connect this repo, set **Root Directory** to **`.`** (repository root), **Build** `pip install -r render_web/requirements.txt`, **Start** `uvicorn render_web.app:app --host 0.0.0.0 --port $PORT`, add env **`PC_CHECKER_CLOUD_TOKEN`** (long random secret). Optional: use `render.yaml` in the repo as a blueprint. Free dynos spin down when idle — snapshots resume when the PC posts again after wake.

---

## Requirements

- **OS:** Windows 10/11 (most features are Windows-specific).
- **Python:** 3.10+ recommended (for running from source).
- **Dependencies:** `pip install -r requirements.txt` (includes **pystray**, **Pillow**, **requests**, **fpdf2** for tray/background features and PDF export).

Optional: run **elevated** (Administrator) for richer Event Log and system data; many checks still work without admin.

**Logs:** rotating file log at `%LOCALAPPDATA%\PCChecker\logs\pc_checker.log` (GUI launch enables this). **Settings** persist in `%LOCALAPPDATA%\PCChecker\settings.json` (edit via **Settings** tab).

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

On a normal account, Windows may show **UAC** so the app can restart **as Administrator** (broader log and update visibility). Choose **Yes** to approve.

- **`python launcher.py --no-elevate`** — Skip the UAC relaunch; run with your current token (useful from IDEs or when you do not want elevation).
- **`python launcher.py --no-api`** — GUI only; do not start the local HTTP API.
- **`python launcher.py --no-tray`** — No system tray icon (background metrics export / webhook loop still runs if enabled in Settings).

Equivalent module entry:

```powershell
python -m pc_checker
```

### Command-line report

```powershell
python launcher.py --cli
```

Text table of diagnostic findings (no GUI).

### Web dashboard

```powershell
python launcher.py --web
```

Starts a local server (default host/port from environment; see code in `pc_checker/web_mode.py`) and opens the browser to the HTML dashboard.

---

## GUI overview

| Tab | Purpose |
|-----|--------|
| **Live** | CPU, RAM, swap, per-core load, disk space bars, disk I/O, optional temps, trend chart, optional local API URL. |
| **Software** | Top processes + Application log error patterns (from last scan). |
| **Updates & API** | Defender / WU / winget snapshot; buttons for signature refresh and WU scan (where permitted). |
| **Diagnostics** | Hardware/system findings; **Scan now** or periodic background scan. Optional **Next steps** bullets on key findings (RAM, events). |
| **Disk & cleanup** | Heuristic install locations, **Program Files** top-level folders vs. Uninstall registry, cache/cleanup path hints, **Copy report**. Read-only guidance — no deletes or moves. |
| **Settings** | Poll intervals, WMI temperature cache TTL, hide attribution footer, tray + SQLite metrics toggles, **alert thresholds** (CPU/RAM/disk + cooldown), **webhook URL** + interval (POST JSON snapshot), **scheduled export** directory + interval. Save applies timers immediately; tray/metrics toggles note “next launch” in the dialog. |
| **Insights & export** | **Extended diagnostics** include **hardware identity** (OEM **PC brand/model**, motherboard, BIOS, CPU, **GPUs**, **RAM DIMMs** with part numbers, **disk models**, **monitors** via WMI, **sound** and **network** adapters, sample **USB/HID/Bluetooth**). Plus memory/reliability/startup/services/tasks/trends; **export** JSON/HTML/PDF; shortcuts + repair launchers. |

---

## Local HTTP API

When the GUI starts with API enabled, FastAPI serves endpoints such as:

- `GET /api/v1/live` — Live metrics and history.
- `GET /api/v1/diagnostics` — Findings + software insights + `disk_hints` + `extended` + `scan_compare_summary`.
- `GET /api/v1/metrics/samples?limit=200` — Recent background SQLite samples (if enabled).
- `GET /api/v1/updates` — Defender / WU / winget bundles.
- `GET /api/v1/disks` — Volume free/used summary.
- `POST /api/v1/diagnostics/scan` — Queue a full diagnostics refresh.

Interactive docs: **`/docs`** on the same host/port.

---

## Building `PCChecker.exe`

From the repo root (requires PyInstaller):

```powershell
pwsh -File .\scripts\Build-PCCheckerExe.ps1
```

Output: **`dist\PCChecker.exe`** (windowed, no console). Run the `.exe` when the build finishes; it does not auto-start after the script exits.

---

## Repository layout (high level)

| Path | Role |
|------|------|
| `launcher.py` | PyInstaller entry; calls `pc_checker.main`. |
| `pc_checker/main.py` | CLI args, elevation, mode dispatch. |
| `pc_checker/gui/` | CustomTkinter UI. |
| `pc_checker/api/` | FastAPI app for local API + static web assets. |
| `pc_checker/checks/` | Individual diagnostic checks + disk hints. |
| `pc_checker/web/public/` | Web dashboard static files. |
| `scripts/Build-PCCheckerExe.ps1` | One-file EXE build. |

---

## Troubleshooting

- **No UAC prompt** — You may have used `--no-elevate`, UAC may be disabled, or the shell is already elevated. Run `python launcher.py` without `--no-elevate` for the standard prompt (when not already admin).
- **Temperature missing** — Common on desktops without WMI thermal zones; the app may probe WMI on a schedule without blocking the UI aggressively.
- **API disabled** — Use default launch without `--no-api`, or check that the port is not in use (`PC_CHECKER_API_HOST` / `PC_CHECKER_API_PORT` environment variables can override bind settings where supported).

---

## Contributing / development

Install dev dependencies as needed, run from source with `python launcher.py --no-elevate` for a predictable console during debugging. Set `PC_CHECKER_KEEP_CONSOLE=1` if you need the attached console window behavior described in `pc_checker/elevation.py`.
