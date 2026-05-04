"""Write JSON + minimal HTML report from a snapshot dict."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any


def write_json_report(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


def write_pdf_report(path: Path, data: dict[str, Any]) -> None:
    """Flatten JSON into a simple multi-page PDF (requires fpdf2)."""
    try:
        from fpdf import FPDF
    except ImportError as e:
        raise RuntimeError("Install fpdf2 for PDF export: pip install fpdf2") from e

    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=12)
    pdf.set_margins(12, 12, 12)
    pdf.add_page()
    pdf.set_font("Helvetica", size=7)
    text = json.dumps(data, indent=2, default=str)
    safe = text.encode("latin-1", errors="replace").decode("latin-1")
    w = pdf.w - pdf.l_margin - pdf.r_margin
    for line in safe.splitlines():
        chunk = line[:500] if len(line) > 500 else line
        pdf.multi_cell(w=w, h=3.2, text=chunk)
    pdf.output(str(path))


def write_html_report(path: Path, data: dict[str, Any], *, hostname: str, os_line: str) -> None:
    body = html.escape(json.dumps(data, indent=2, default=str))
    title = html.escape(f"PC Checker report — {hostname}")
    sub = html.escape(os_line)
    page = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/><title>{title}</title>
<style>body{{font-family:Segoe UI,system-ui,sans-serif;margin:16px;background:#111;color:#e8e8e8;}}
pre{{white-space:pre-wrap;background:#1a1a1a;padding:12px;border-radius:8px;border:1px solid #333;}}
h1{{font-size:1.25rem;}} .sub{{color:#9aa0a6;margin-bottom:16px;}}</style></head>
<body><h1>{title}</h1><p class="sub">{sub}</p><p class="sub">Full JSON payload below (open .json export for machine parsing).</p>
<pre>{body}</pre></body></html>"""
    path.write_text(page, encoding="utf-8")
