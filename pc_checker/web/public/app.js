/* global fetch */

function $(id) {
  return document.getElementById(id);
}

function setBar(id, pct) {
  const el = $(id);
  if (el) el.style.width = `${Math.min(100, Math.max(0, pct))}%`;
}

function fmtUptime(sec) {
  const s = sec || 0;
  const d = Math.floor(s / 86400);
  const h = Math.floor((s % 86400) / 3600);
  return `${d}d ${h}h`;
}

function drawChart(cpuArr, ramArr) {
  const canvas = $("chart");
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  const w = canvas.width;
  const h = canvas.height;
  ctx.fillStyle = "#12151a";
  ctx.fillRect(0, 0, w, h);
  const n = Math.min(cpuArr.length, ramArr.length);
  if (n < 2) {
    ctx.fillStyle = "#666";
    ctx.font = "14px Segoe UI";
    ctx.fillText("Collecting samples…", 16, h / 2);
    return;
  }
  const pad = 8;
  const gw = w - pad * 2;
  const gh = h - pad * 2;
  const xs = (i) => pad + (i / (n - 1)) * gw;
  const ys = (v) => pad + gh - (v / 100) * gh;
  ctx.strokeStyle = "#333";
  for (let y = 0; y <= 4; y++) {
    const yy = pad + (y / 4) * gh;
    ctx.beginPath();
    ctx.moveTo(pad, yy);
    ctx.lineTo(w - pad, yy);
    ctx.stroke();
  }
  ctx.strokeStyle = "#3d8bfd";
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  for (let i = 0; i < n; i++) {
    const x = xs(i);
    const y = ys(cpuArr[i]);
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  }
  ctx.stroke();
  ctx.strokeStyle = "#e67e22";
  ctx.beginPath();
  for (let i = 0; i < n; i++) {
    const x = xs(i);
    const y = ys(ramArr[i]);
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  }
  ctx.stroke();
}

function renderFindings(container, items) {
  if (!container) return;
  container.innerHTML = "";
  (items || []).forEach((f) => {
    const div = document.createElement("div");
    div.className = `finding ${f.severity || "ok"}`;
    const steps = (f.next_steps || []).map((s) => `<li>${escapeHtml(s)}</li>`).join("");
    const stepsHtml = steps ? `<p class="small"><strong>Next steps</strong></p><ul class="small">${steps}</ul>` : "";
    div.innerHTML = `<strong>[${(f.severity || "").toUpperCase()}] ${escapeHtml(f.title || "")}</strong><p class="small">${escapeHtml(
      f.detail || ""
    )}</p>${stepsHtml}`;
    container.appendChild(div);
  });
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

async function refreshLive() {
  const r = await fetch("/api/v1/live");
  const j = await r.json();
  const live = j.live || {};
  const hist = j.history || {};
  const cpu = live.cpu_percent ?? 0;
  const ram = live.ram_percent ?? 0;
  setBar("cpu-bar", cpu);
  setBar("ram-bar", ram);
  $("cpu-val").textContent = `${cpu.toFixed(0)}%`;
  $("ram-val").textContent = `${ram.toFixed(0)}% (${(live.ram_available_gb || 0).toFixed(2)} / ${(live.ram_total_gb || 0).toFixed(1)} GB free)`;
  const sp = live.swap_percent;
  if (sp != null && live.swap_total_gb) {
    $("swap-val").textContent = `Page file: ${sp.toFixed(0)}% (${(live.swap_used_gb || 0).toFixed(2)} / ${(live.swap_total_gb || 0).toFixed(2)} GB)`;
  } else {
    $("swap-val").textContent = "Page file: —";
  }
  $("io-val").textContent = `Disk I/O: read ${(live.disk_read_mbps || 0).toFixed(2)} MB/s · write ${(live.disk_write_mbps || 0).toFixed(2)} MB/s`;
  const temps = live.temperatures_c || {};
  const tk = Object.keys(temps);
  if (tk.length) {
    $("temp-val").textContent =
      "Temperature: " +
      tk
        .sort()
        .slice(0, 8)
        .map((k) => `${k}: ${temps[k].toFixed(1)}°C`)
        .join(" · ");
  } else {
    $("temp-val").textContent = "Temperature: not available on this system";
  }
  $("uptime-val").textContent = `Uptime: ${fmtUptime(live.uptime_seconds)} since last boot`;
  drawChart(hist.cpu_percent || [], hist.ram_percent || []);

  const per = live.per_cpu_percent || [];
  const wrap = $("percpu");
  wrap.innerHTML = "";
  per.forEach((p, i) => {
    const row = document.createElement("div");
    row.className = "percpu-row";
    row.innerHTML = `<span>CPU ${i}</span><div class="bar"><i style="width:${Math.min(100, p)}%;display:block;height:100%;background:linear-gradient(90deg,#3d8bfd,#6eb6ff);border-radius:5px"></i></div><span>${p.toFixed(0)}%</span>`;
    wrap.appendChild(row);
  });

  const tb = $("procs").querySelector("tbody");
  tb.innerHTML = "";
  (j.top_processes || []).slice(0, 24).forEach((p) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${(p.cpu_percent || 0).toFixed(1)}</td><td>${(p.memory_percent || 0).toFixed(1)}</td><td>${p.pid}</td><td>${escapeHtml(p.name || "")}</td>`;
    tb.appendChild(tr);
  });
}

function renderDiskHintsPre(dh) {
  const el = $("disk-hints-pre");
  if (!el) return;
  const d = dh || {};
  const lines = [];
  lines.push(d.notes || "");
  if (d.program_files_disclaimer) {
    lines.push("\n--- Program Files & redundancy ---\n");
    lines.push(d.program_files_disclaimer);
  }
  lines.push("\n=== Program Files / Program Files (x86) — top-level vs. Uninstall registry ===\n");
  (d.program_files_top_level || []).forEach((row) => {
    lines.push(`[${row.status || ""}] ${row.path || ""}`);
    const prods = row.matched_products || [];
    if (prods.length) lines.push(`    Listed products (sample): ${prods.join("; ")}`);
    if (row.matched_products_note) lines.push(`    ${row.matched_products_note}`);
    lines.push(`    ${row.detail || ""}\n`);
  });
  lines.push("\n=== Apps (install folder — category — how to move) ===\n");
  (d.relocatable_apps || []).forEach((a) => {
    lines.push(`[${a.category || ""}] ${a.name || ""}`);
    lines.push(`    Path: ${a.install_location || ""}`);
    lines.push(`    How: ${a.how_to_move || ""}\n`);
  });
  lines.push("\n=== Folders often trimmed (risk: low / medium / high) ===\n");
  (d.deletable_folders || []).forEach((f) => {
    const sz = f.size_note || (f.size_mb != null ? `~${f.size_mb} MB` : "size not measured");
    lines.push(`[${(f.risk || "?").toUpperCase()}] ${f.label || ""} — ${sz}`);
    lines.push(`    ${f.path || ""}`);
    lines.push(`    ${f.notes || ""}\n`);
  });
  el.textContent = lines.join("\n");
}

function renderExtendedPre(ext, cmp) {
  const el = $("extended-pre");
  if (!el) return;
  const lines = [];
  if (cmp) {
    lines.push("=== Compare vs last scan ===\n");
    lines.push(cmp + "\n");
  }
  lines.push("=== Extended diagnostics (JSON) ===\n");
  lines.push(JSON.stringify(ext || {}, null, 2));
  el.textContent = lines.join("\n");
}

async function refreshDiagnostics() {
  const r = await fetch("/api/v1/diagnostics");
  const j = await r.json();
  renderFindings($("findings"), j.findings);
  renderFindings($("soft"), j.software_findings);
  renderDiskHintsPre(j.disk_hints);
  renderExtendedPre(j.extended, j.scan_compare_summary);
}

async function refreshDisks() {
  const r = await fetch("/api/v1/disks");
  const j = await r.json();
  const wrap = $("disks");
  wrap.innerHTML = "";
  (j.volumes || []).forEach((v) => {
    const used = v.used_percent ?? 0;
    const row = document.createElement("div");
    row.className = "disk-row";
    const free = v.free_percent ?? 0;
    const col = free < 10 ? "#f4b400" : "#9aa0a6";
    row.innerHTML = `<span style="color:${col}">${escapeHtml(v.device || "")} (${escapeHtml(v.mountpoint || "")}) — ${free.toFixed(0)}% free</span><span>${used.toFixed(0)}% used</span><div class="bar"><i style="width:${Math.min(100, used)}%;display:block;height:100%;background:${free < 3 ? "#ea4335" : free < 10 ? "#f4b400" : "#34a853"};border-radius:5px"></i></div>`;
    wrap.appendChild(row);
  });
}

async function refreshUpdates() {
  const r = await fetch("/api/v1/updates");
  const j = await r.json();
  const lines = [];
  lines.push(JSON.stringify(j.defender || {}, null, 2));
  lines.push("\n--- Windows Update (pending) ---\n");
  const wu = j.windows_update || {};
  if (wu.error) lines.push("Error: " + wu.error);
  (wu.items || []).forEach((it) => lines.push("- " + (it.title || "")));
  lines.push("\n--- winget upgrades ---\n");
  const wg = j.winget || {};
  if (wg.error) lines.push("Error: " + wg.error);
  (wg.items || []).slice(0, 60).forEach((it) => {
    lines.push(`- ${it.name} [${it.id}] ${it.installed_version} -> ${it.available_version}`);
  });
  $("updates-pre").textContent = lines.join("\n");
}

async function post(path) {
  const r = await fetch(path, { method: "POST" });
  const t = await r.json().catch(() => ({}));
  const d = t.detail;
  const detail = typeof d === "string" ? d : Array.isArray(d) ? d.map((x) => x.msg || x).join("; ") : "";
  $("action-msg").textContent = t.message || detail || (r.ok ? "OK" : `HTTP ${r.status}`);
}

async function initMeta() {
  const r = await fetch("/api/v1/meta");
  const j = await r.json();
  $("meta").textContent = `${j.app} v${j.version} · bound ${j.bind}:${j.port}`;
  const line = j.attribution || "";
  const foot = $("attribution");
  if (foot) foot.textContent = line;
  const banner = $("attribution-banner");
  if (banner) banner.textContent = line;
}

function wire() {
  $("btn-scan").addEventListener("click", async () => {
    await post("/api/v1/diagnostics/scan");
    setTimeout(refreshDiagnostics, 1500);
  });
  $("btn-updates").addEventListener("click", async () => {
    await post("/api/v1/updates/refresh");
    setTimeout(refreshUpdates, 2000);
  });
  $("btn-def").addEventListener("click", async () => {
    await post("/api/v1/actions/defender-signatures");
    setTimeout(refreshUpdates, 1500);
  });
  $("btn-wu").addEventListener("click", async () => {
    await post("/api/v1/actions/windows-update-scan");
  });
}

async function loop() {
  try {
    await refreshLive();
  } catch (e) {
    console.error(e);
  }
}

async function diskLoop() {
  try {
    await refreshDisks();
  } catch (e) {
    console.error(e);
  }
}

async function diagLoop() {
  try {
    await refreshDiagnostics();
  } catch (e) {
    console.error(e);
  }
}

async function upLoop() {
  try {
    await refreshUpdates();
  } catch (e) {
    console.error(e);
  }
}

initMeta();
wire();
loop();
diagLoop();
refreshDisks();
refreshUpdates();
setInterval(loop, 1000);
setInterval(diskLoop, 5000);
setInterval(diagLoop, 8000);
setInterval(upLoop, 12000);
