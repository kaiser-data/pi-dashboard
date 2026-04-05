#!/usr/bin/env python3
"""
Pi Dashboard — minimal system monitor with history charts
Serves a single-page dashboard on port 19999
"""

import collections
import json
import os
import re
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

# ── Storage ────────────────────────────────────────────────────────────────────
# In-memory: last 24h at 5s resolution
HISTORY_LEN  = 17280
history      = collections.deque(maxlen=HISTORY_LEN)
history_lock = threading.Lock()

# On-disk: minute-averages, up to 60 days (86400 points)
DISK_PATH    = "/var/lib/pi-dashboard/history.jsonl"
DISK_MAX     = 86400   # 60 days × 1440 min/day
disk_lock    = threading.Lock()

os.makedirs(os.path.dirname(DISK_PATH), exist_ok=True)

# Accumulator for minute averages
_minute_buf  = []
_minute_lock = threading.Lock()


def flush_minute_average():
    """Average the last ~12 readings and append one record to disk."""
    with _minute_lock:
        if not _minute_buf:
            return
        avg = {k: round(sum(r[k] for r in _minute_buf) / len(_minute_buf), 1)
               for k in ("cpu_temp", "fan_speed", "ram_pct", "cpu_pct")}
        avg["ts"] = int(time.time())
        _minute_buf.clear()

    with disk_lock:
        # Append
        with open(DISK_PATH, "a") as f:
            f.write(json.dumps(avg) + "\n")
        # Trim to DISK_MAX lines
        with open(DISK_PATH) as f:
            lines = f.readlines()
        if len(lines) > DISK_MAX:
            with open(DISK_PATH, "w") as f:
                f.writelines(lines[-DISK_MAX:])


def load_disk_history():
    """Load disk history into memory deque on startup."""
    if not os.path.exists(DISK_PATH):
        return
    with disk_lock:
        with open(DISK_PATH) as f:
            lines = f.readlines()
    with history_lock:
        for line in lines[-HISTORY_LEN:]:
            try:
                history.append(json.loads(line))
            except Exception:
                pass


def get_disk_history(since_ts):
    """Return all disk records newer than since_ts."""
    if not os.path.exists(DISK_PATH):
        return []
    with disk_lock:
        with open(DISK_PATH) as f:
            lines = f.readlines()
    result = []
    for line in lines:
        try:
            r = json.loads(line)
            if r.get("ts", 0) >= since_ts:
                result.append(r)
        except Exception:
            pass
    return result


def downsample(records, target=600):
    """Reduce records to at most target points by averaging buckets."""
    if len(records) <= target:
        return records
    bucket = len(records) / target
    out = []
    i = 0
    while i < len(records):
        chunk = records[int(i):int(i + bucket)]
        avg = {k: round(sum(r[k] for r in chunk) / len(chunk), 1)
               for k in ("cpu_temp", "fan_speed", "ram_pct", "cpu_pct")}
        avg["ts"] = chunk[len(chunk) // 2].get("ts", 0)
        out.append(avg)
        i += bucket
    return out

HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>pi-claw-agent</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: #0f0f0f;
    color: #e0e0e0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    padding: 24px;
    min-height: 100vh;
  }
  h1 {
    font-size: 18px; font-weight: 600; color: #fff;
    margin-bottom: 24px; letter-spacing: 0.5px;
  }
  h1 span { color: #555; font-weight: 400; font-size: 13px; margin-left: 10px; }
  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
    gap: 14px;
    margin-bottom: 20px;
  }
  .card {
    background: #1a1a1a;
    border: 1px solid #2a2a2a;
    border-radius: 12px;
    padding: 18px;
  }
  .card-label {
    font-size: 10px; text-transform: uppercase;
    letter-spacing: 1px; color: #555; margin-bottom: 6px;
  }
  .card-value {
    font-size: 34px; font-weight: 700; color: #fff; line-height: 1;
  }
  .card-value.warn { color: #f59e0b; }
  .card-value.hot  { color: #ef4444; }
  .card-unit { font-size: 13px; color: #555; margin-left: 2px; }
  .bar-wrap {
    background: #2a2a2a; border-radius: 4px;
    height: 5px; margin-top: 10px; overflow: hidden;
  }
  .bar { height: 100%; border-radius: 4px; background: #3b82f6; transition: width 0.5s ease; }
  .bar.warn { background: #f59e0b; }
  .bar.hot  { background: #ef4444; }

  /* Tabs */
  .tabs {
    display: flex; gap: 2px; margin-bottom: 24px;
    border-bottom: 1px solid #1f1f1f; padding-bottom: 0;
  }
  .tab {
    padding: 8px 18px; font-size: 13px; font-weight: 500;
    color: #444; cursor: pointer; border-bottom: 2px solid transparent;
    margin-bottom: -1px; transition: all 0.15s;
  }
  .tab:hover { color: #888; }
  .tab.active { color: #fff; border-bottom-color: #3b82f6; }
  .tab-panel { display: none; }
  .tab-panel.active { display: block; }

  /* Agent cards */
  .agent-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
    gap: 14px; margin-bottom: 20px;
  }
  .agent-card {
    background: #1a1a1a; border: 1px solid #2a2a2a;
    border-radius: 12px; padding: 18px;
  }
  .agent-card.active-card { border-color: #1e3a5f; }
  .agent-header {
    display: flex; align-items: center; gap: 10px; margin-bottom: 14px;
  }
  .agent-emoji { font-size: 22px; line-height: 1; }
  .agent-name { font-size: 15px; font-weight: 600; color: #fff; }
  .agent-bot  { font-size: 11px; color: #444; margin-top: 1px; }
  .agent-stat { display: flex; justify-content: space-between; padding: 5px 0;
                border-bottom: 1px solid #1f1f1f; font-size: 12px; }
  .agent-stat:last-child { border-bottom: none; }
  .stat-label { color: #555; }
  .stat-val   { color: #ccc; font-weight: 500; }

  /* Activity chart */
  .activity-card {
    background: #1a1a1a; border: 1px solid #2a2a2a;
    border-radius: 12px; padding: 18px; margin-bottom: 20px;
  }
  .activity-card .card-label { margin-bottom: 14px; }

  /* Time selector */
  .time-selector {
    display: flex; gap: 6px; margin-bottom: 16px; flex-wrap: wrap;
  }
  .time-btn {
    background: #1a1a1a; border: 1px solid #2a2a2a;
    color: #555; font-size: 11px; font-weight: 600;
    padding: 5px 12px; border-radius: 6px; cursor: pointer;
    letter-spacing: 0.5px; transition: all 0.15s;
  }
  .time-btn:hover { border-color: #444; color: #aaa; }
  .time-btn.active { background: #2a2a2a; border-color: #3b82f6; color: #3b82f6; }

  /* Charts */
  .charts {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 14px;
    margin-bottom: 20px;
  }
  @media (max-width: 600px) { .charts { grid-template-columns: 1fr; } }
  .chart-card {
    background: #1a1a1a;
    border: 1px solid #2a2a2a;
    border-radius: 12px;
    padding: 16px;
  }
  .chart-card .card-label { margin-bottom: 10px; }
  canvas { display: block; width: 100%; }

  /* Services */
  .services { margin-bottom: 20px; }
  .svc {
    display: flex; align-items: center;
    justify-content: space-between;
    padding: 10px 0;
    border-bottom: 1px solid #1f1f1f;
    font-size: 13px;
  }
  .svc:last-child { border-bottom: none; }
  .dot {
    width: 8px; height: 8px; border-radius: 50%;
    margin-right: 10px; display: inline-block;
  }
  .dot.active   { background: #10b981; box-shadow: 0 0 6px #10b981; }
  .dot.inactive { background: #ef4444; }
  .svc-name { color: #ccc; }
  .svc-status { color: #555; font-size: 11px; }
  .updated { color: #2a2a2a; font-size: 11px; text-align: right; }
</style>
</head>
<body>
<h1>pi-claw-agent <span id="clock"></span></h1>

<div class="tabs">
  <div class="tab active" onclick="showTab('system',this)">System</div>
  <div class="tab" onclick="showTab('agents',this)">Agents</div>
</div>

<div id="panel-system" class="tab-panel active">
<div class="grid">
  <div class="card">
    <div class="card-label">CPU Temp</div>
    <div class="card-value" id="temp-val">—<span class="card-unit">°C</span></div>
    <div class="bar-wrap"><div class="bar" id="temp-bar" style="width:0%"></div></div>
  </div>
  <div class="card">
    <div class="card-label">Fan Speed</div>
    <div class="card-value" id="fan-val">—<span class="card-unit">%</span></div>
    <div class="bar-wrap"><div class="bar" id="fan-bar" style="width:0%"></div></div>
  </div>
  <div class="card">
    <div class="card-label">RAM Used</div>
    <div class="card-value" id="ram-val">—<span class="card-unit">%</span></div>
    <div class="bar-wrap"><div class="bar" id="ram-bar" style="width:0%"></div></div>
  </div>
  <div class="card">
    <div class="card-label">CPU Load</div>
    <div class="card-value" id="cpu-val">—<span class="card-unit">%</span></div>
    <div class="bar-wrap"><div class="bar" id="cpu-bar" style="width:0%"></div></div>
  </div>
  <div class="card">
    <div class="card-label">Disk Used</div>
    <div class="card-value" id="disk-val">—<span class="card-unit">%</span></div>
    <div class="bar-wrap"><div class="bar" id="disk-bar" style="width:0%"></div></div>
  </div>
  <div class="card">
    <div class="card-label">Uptime</div>
    <div class="card-value" style="font-size:20px;padding-top:8px" id="uptime-val">—</div>
  </div>
</div>

<div class="time-selector">
  <button class="time-btn" onclick="setWindow(600,this)">10m</button>
  <button class="time-btn active" onclick="setWindow(1800,this)">30m</button>
  <button class="time-btn" onclick="setWindow(3600,this)">1h</button>
  <button class="time-btn" onclick="setWindow(21600,this)">6h</button>
  <button class="time-btn" onclick="setWindow(86400,this)">24h</button>
  <button class="time-btn" onclick="setWindow(172800,this)">2d</button>
  <button class="time-btn" onclick="setWindow(604800,this)">7d</button>
  <button class="time-btn" onclick="setWindow(2592000,this)">30d</button>
</div>

<div class="charts">
  <div class="chart-card">
    <div class="card-label">CPU Temp — last 30 min</div>
    <canvas id="chart-temp" height="140"></canvas>
  </div>
  <div class="chart-card">
    <div class="card-label">Fan Speed — last 30 min</div>
    <canvas id="chart-fan" height="140"></canvas>
  </div>
  <div class="chart-card">
    <div class="card-label">RAM — last 30 min</div>
    <canvas id="chart-ram" height="140"></canvas>
  </div>
  <div class="chart-card">
    <div class="card-label">CPU Load — last 30 min</div>
    <canvas id="chart-cpu" height="140"></canvas>
  </div>
</div>

<div class="card services">
  <div class="card-label" style="margin-bottom:4px">Services</div>
  <div class="svc"><span><span class="dot" id="svc-openclaw"></span><span class="svc-name">openclaw-gateway</span></span><span class="svc-status" id="svc-openclaw-s">—</span></div>
  <div class="svc"><span><span class="dot" id="svc-fan"></span><span class="svc-name">fan-control</span></span><span class="svc-status" id="svc-fan-s">—</span></div>
  <div class="svc"><span><span class="dot" id="svc-tailscale"></span><span class="svc-name">tailscaled</span></span><span class="svc-status" id="svc-tailscale-s">—</span></div>
</div>

<div class="updated">auto-refresh every 5s</div>
</div><!-- /panel-system -->

<div id="panel-agents" class="tab-panel">
<div class="agent-grid" id="agent-cards"></div>

<div class="activity-card">
  <div class="card-label">Sessions started — last 14 days</div>
  <canvas id="chart-activity" height="140"></canvas>
</div>
<div class="updated" id="agents-updated">—</div>
</div><!-- /panel-agents -->

<script>
// ── Tab switcher ────────────────────────────────────────────────────────────
function showTab(name, el) {
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.getElementById('panel-' + name).classList.add('active');
  el.classList.add('active');
  if (name === 'agents') refreshAgents();
}

// ── Chart renderer ─────────────────────────────────────────────────────────
// windowSecs = selected time window in seconds
function drawChart(canvasId, data, color, unit, windowSecs, intervalSecs) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  const W = rect.width || canvas.offsetWidth || 300;
  const H = 140;
  canvas.width  = W * dpr;
  canvas.height = H * dpr;
  canvas.style.width  = W + 'px';
  canvas.style.height = H + 'px';
  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);

  if (data.length < 2) return;

  // Dynamic Y scale
  const rawMin = Math.min(...data);
  const rawMax = Math.max(...data);
  const yPad = Math.max((rawMax - rawMin) * 0.2, 1);
  const yMin = Math.floor(rawMin - yPad);
  const yMax = Math.ceil(rawMax + yPad);
  const yRange = yMax - yMin || 1;

  const pad = { top: 8, right: 6, bottom: 22, left: 32 };
  const cw = W - pad.left - pad.right;
  const ch = H - pad.top - pad.bottom;

  // X axis: full window width, data anchored to the right
  const totalPts  = Math.max(Math.ceil(windowSecs / intervalSecs), data.length);
  const xStep     = cw / (totalPts - 1);
  const xOffset   = (totalPts - data.length) * xStep;  // empty space on left
  const toX = i => pad.left + xOffset + i * xStep;
  const toY = v  => pad.top + ch - ((v - yMin) / yRange) * ch;

  // Horizontal grid lines
  ctx.strokeStyle = '#1f1f1f';
  ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i++) {
    const y = pad.top + (i / 4) * ch;
    ctx.beginPath(); ctx.moveTo(pad.left, y); ctx.lineTo(pad.left + cw, y); ctx.stroke();
  }

  // Filled area
  const grad = ctx.createLinearGradient(0, pad.top, 0, pad.top + ch);
  grad.addColorStop(0, color + '50');
  grad.addColorStop(1, color + '00');
  ctx.beginPath();
  ctx.moveTo(toX(0), toY(data[0]));
  data.forEach((v, i) => { if (i > 0) ctx.lineTo(toX(i), toY(v)); });
  ctx.lineTo(toX(data.length - 1), pad.top + ch);
  ctx.lineTo(toX(0), pad.top + ch);
  ctx.closePath();
  ctx.fillStyle = grad;
  ctx.fill();

  // Line
  ctx.beginPath();
  ctx.strokeStyle = color;
  ctx.lineWidth = 1.5;
  ctx.lineJoin = 'round';
  data.forEach((v, i) => {
    i === 0 ? ctx.moveTo(toX(i), toY(v)) : ctx.lineTo(toX(i), toY(v));
  });
  ctx.stroke();

  // Y-axis labels
  ctx.fillStyle = '#3a3a3a';
  ctx.font = '9px sans-serif';
  ctx.textAlign = 'right';
  [yMin, Math.round((yMin + yMax) / 2), yMax].forEach(v => {
    ctx.fillText(v + unit, pad.left - 3, toY(v) + 3);
  });

  // X-axis time labels
  ctx.fillStyle = '#3a3a3a';
  ctx.textAlign = 'center';
  const nowMs   = Date.now();
  const totalMs = windowSecs * 1000;
  const xLabels = 5;
  for (let i = 0; i <= xLabels; i++) {
    const frac  = i / xLabels;
    const x     = pad.left + frac * cw;
    const msAgo = totalMs - frac * totalMs;
    const t     = new Date(nowMs - msAgo);
    let label;
    if (windowSecs <= 86400) {
      label = t.getHours().toString().padStart(2,'0') + ':' + t.getMinutes().toString().padStart(2,'0');
    } else {
      label = (t.getMonth()+1) + '/' + t.getDate() + ' ' + t.getHours().toString().padStart(2,'0') + 'h';
    }
    ctx.fillText(label, x, H - 5);
    ctx.strokeStyle = '#1f1f1f';
    ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(x, pad.top); ctx.lineTo(x, pad.top + ch); ctx.stroke();
  }
}

// ── Card helpers ────────────────────────────────────────────────────────────
function colorClass(val, warn, hot) {
  return val >= hot ? 'hot' : val >= warn ? 'warn' : '';
}
function setCard(valId, barId, value, unit, warn, hot) {
  const el  = document.getElementById(valId);
  const bar = document.getElementById(barId);
  const cls = colorClass(value, warn, hot);
  el.className = 'card-value' + (cls ? ' ' + cls : '');
  el.innerHTML = value + '<span class="card-unit">' + unit + '</span>';
  bar.style.width = Math.min(value, 100) + '%';
  bar.className = 'bar' + (cls ? ' ' + cls : '');
}
function setSvc(id, active, detail) {
  document.getElementById('svc-' + id).className = 'dot ' + (active ? 'active' : 'inactive');
  document.getElementById('svc-' + id + '-s').textContent = detail;
}

// ── Time window (seconds) ────────────────────────────────────────���───────────
let currentWindow = 1800;

function setWindow(n, btn) {
  currentWindow = n;
  document.querySelectorAll('.time-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  refresh();
}

// ── Clock ───────────────────────────────────────────────────────────────────
function tick() {
  const now = new Date();
  document.getElementById('clock').textContent =
    now.toLocaleTimeString('de-DE', {hour:'2-digit', minute:'2-digit', second:'2-digit'});
}

// ── Main refresh ────────────────────────────────────────────────────────────
async function refresh() {
  try {
    const [sr, hr] = await Promise.all([
      fetch('/stats'),
      fetch('/history?s=' + currentWindow)
    ]);
    const d = await sr.json();
    const h = await hr.json();

    setCard('temp-val', 'temp-bar', d.cpu_temp,  '°C', 55, 70);
    setCard('fan-val',  'fan-bar',  d.fan_speed,  '%',  80, 95);
    setCard('ram-val',  'ram-bar',  d.ram_pct,    '%',  75, 90);
    setCard('cpu-val',  'cpu-bar',  d.cpu_pct,    '%',  70, 90);
    setCard('disk-val', 'disk-bar', d.disk_pct,   '%',  75, 90);
    document.getElementById('uptime-val').textContent = d.uptime;

    setSvc('openclaw',  d.services.openclaw_gateway, d.services.openclaw_gateway ? 'running' : 'stopped');
    setSvc('fan',       d.services.fan_control,      d.services.fan_control      ? 'running' : 'stopped');
    setSvc('tailscale', d.services.tailscaled,       d.services.tailscaled       ? 'running' : 'stopped');

    const iv = h.interval_secs || 5;
    if (h.cpu_temp.length)  drawChart('chart-temp', h.cpu_temp,  '#f59e0b', '°', currentWindow, iv);
    if (h.fan_speed.length) drawChart('chart-fan',  h.fan_speed, '#3b82f6', '%', currentWindow, iv);
    if (h.ram_pct.length)   drawChart('chart-ram',  h.ram_pct,   '#8b5cf6', '%', currentWindow, iv);
    if (h.cpu_pct.length)   drawChart('chart-cpu',  h.cpu_pct,   '#10b981', '%', currentWindow, iv);
  } catch(e) {}
}

// ── Activity bar chart ──────────────────────────────────────────────────────
function drawActivity(days, counts) {
  const canvas = document.getElementById('chart-activity');
  if (!canvas) return;
  const agents = Object.keys(counts);
  const colors = ['#3b82f6','#10b981','#f59e0b','#8b5cf6'];
  const dpr = window.devicePixelRatio || 1;
  const W = canvas.offsetWidth || 600;
  const H = 140;
  canvas.width  = W * dpr; canvas.height = H * dpr;
  canvas.style.width = W + 'px'; canvas.style.height = H + 'px';
  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);

  const pad = {top:8, right:8, bottom:28, left:28};
  const cw = W - pad.left - pad.right;
  const ch = H - pad.top - pad.bottom;
  const n  = days.length;
  const maxVal = Math.max(1, ...agents.flatMap(a => counts[a]));

  const groupW = cw / n;
  const barW   = Math.max(2, groupW / agents.length - 2);

  agents.forEach((aid, ai) => {
    ctx.fillStyle = colors[ai % colors.length];
    counts[aid].forEach((v, di) => {
      const x = pad.left + di * groupW + ai * (barW + 1);
      const bh = Math.max(1, (v / maxVal) * ch);
      ctx.fillRect(x, pad.top + ch - bh, barW, bh);
    });
  });

  // X labels (every 2 days)
  ctx.fillStyle = '#3a3a3a'; ctx.font = '9px sans-serif'; ctx.textAlign = 'center';
  days.forEach((d, i) => {
    if (i % 2 === 0) {
      const x = pad.left + i * groupW + groupW / 2;
      ctx.fillText(d.slice(5), x, H - 5);
    }
  });

  // Legend
  ctx.font = '9px sans-serif'; ctx.textAlign = 'left';
  const labels = ['Main','Fitness','Career','Learning'];
  agents.forEach((aid, ai) => {
    const lx = pad.left + ai * 70;
    ctx.fillStyle = colors[ai % colors.length];
    ctx.fillRect(lx, pad.top, 8, 8);
    ctx.fillStyle = '#555';
    ctx.fillText(labels[ai] || aid, lx + 11, pad.top + 8);
  });
}

// ── Agents refresh ──────────────────────────────────────────────────────────
async function refreshAgents() {
  try {
    const r = await fetch('/agents');
    const d = await r.json();
    const grid = document.getElementById('agent-cards');
    grid.innerHTML = d.agents.map(a => `
      <div class="agent-card${a.messages > 0 ? ' active-card' : ''}">
        <div class="agent-header">
          <span class="agent-emoji">${a.emoji}</span>
          <div><div class="agent-name">${a.name}</div><div class="agent-bot">${a.bot}</div></div>
        </div>
        <div class="agent-stat"><span class="stat-label">Sessions (30d)</span><span class="stat-val">${a.messages}</span></div>
        <div class="agent-stat"><span class="stat-label">Last seen</span><span class="stat-val">${a.last_seen}</span></div>
      </div>`).join('');
    drawActivity(d.activity.days, d.activity.counts);
    document.getElementById('agents-updated').textContent =
      'updated ' + new Date().toLocaleTimeString('de-DE', {hour:'2-digit',minute:'2-digit',second:'2-digit'});
  } catch(e) {}
}

setInterval(tick, 1000);
setInterval(refresh, 5000);
setInterval(refreshAgents, 30000);
tick();
refresh();
refreshAgents();
window.addEventListener('resize', refresh);
</script>
</body>
</html>
"""


# ── System readers ─────────────────────────────────────────────────────────

def read_cpu_temp():
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            return round(int(f.read().strip()) / 1000.0, 1)
    except Exception:
        return 0


def read_fan_speed():
    try:
        result = subprocess.run(
            ["journalctl", "-u", "fan-control", "-n", "1", "--no-pager", "--output=cat"],
            capture_output=True, text=True, timeout=3
        )
        m = re.search(r"Fan:\s*(\d+)%", result.stdout)
        return int(m.group(1)) if m else 0
    except Exception:
        return 0


def read_ram_pct():
    try:
        with open("/proc/meminfo") as f:
            lines = f.readlines()
        mem = {}
        for line in lines:
            k, v = line.split(":", 1)
            mem[k.strip()] = int(v.split()[0])
        return round((mem["MemTotal"] - mem["MemAvailable"]) / mem["MemTotal"] * 100)
    except Exception:
        return 0


_prev_cpu = None

def read_cpu_pct():
    global _prev_cpu
    try:
        with open("/proc/stat") as f:
            line = f.readline()
        vals = list(map(int, line.split()[1:8]))
        idle  = vals[3]
        total = sum(vals)
        if _prev_cpu:
            d_idle  = idle  - _prev_cpu[0]
            d_total = total - _prev_cpu[1]
            pct = round((1 - d_idle / max(d_total, 1)) * 100)
        else:
            pct = 0
        _prev_cpu = (idle, total)
        return max(0, min(100, pct))
    except Exception:
        return 0


def read_disk_pct():
    try:
        result = subprocess.run(["df", "/"], capture_output=True, text=True)
        m = re.search(r"(\d+)%", result.stdout.split("\n")[1])
        return int(m.group(1)) if m else 0
    except Exception:
        return 0


def read_uptime():
    try:
        with open("/proc/uptime") as f:
            secs = float(f.read().split()[0])
        days  = int(secs // 86400)
        hours = int((secs % 86400) // 3600)
        mins  = int((secs % 3600) // 60)
        if days:   return f"{days}d {hours}h"
        if hours:  return f"{hours}h {mins}m"
        return f"{mins}m"
    except Exception:
        return "—"


def service_active(name):
    try:
        r = subprocess.run(["systemctl", "is-active", name], capture_output=True, text=True)
        return r.stdout.strip() == "active"
    except Exception:
        return False


def get_stats():
    return {
        "cpu_temp":  read_cpu_temp(),
        "fan_speed": read_fan_speed(),
        "ram_pct":   read_ram_pct(),
        "cpu_pct":   read_cpu_pct(),
        "disk_pct":  read_disk_pct(),
        "uptime":    read_uptime(),
        "services": {
            "openclaw_gateway": service_active("openclaw-gateway"),
            "fan_control":      service_active("fan-control"),
            "tailscaled":       service_active("tailscaled"),
        }
    }


# ── Agent activity reader ──────────────────────────────────────────────────

AGENTS_BASE = "/home/openclaw/.openclaw/agents"

AGENTS = [
    {"id": "main",     "name": "MK-Pi-Claw",  "emoji": "🦀", "bot": "@MK_Pi_Claw_Bot"},
    {"id": "fitness",  "name": "FitClaw",      "emoji": "💪", "bot": "@MKFitnessBot"},
    {"id": "career",   "name": "CareerClaw",   "emoji": "💼", "bot": "@MKCareerCoachBot"},
    {"id": "learning", "name": "LearnClaw",    "emoji": "📚", "bot": "@MKLearningBot"},
]


def _read_session_timestamps(agent_id):
    """Return list of Unix timestamps for every session of this agent (last 30 days)."""
    sessions_dir = os.path.join(AGENTS_BASE, agent_id, "sessions")
    if not os.path.isdir(sessions_dir):
        return []

    cutoff = time.time() - 30 * 86400
    timestamps = []
    try:
        for fname in os.listdir(sessions_dir):
            if not fname.endswith(".jsonl"):
                continue
            fpath = os.path.join(sessions_dir, fname)
            try:
                with open(fpath) as f:
                    first = f.readline()
                d = json.loads(first)
                ts_str = d.get("timestamp", "")
                if ts_str:
                    # ISO 8601: "2026-04-05T08:19:32.172Z"
                    ts = time.mktime(time.strptime(ts_str[:19], "%Y-%m-%dT%H:%M:%S"))
                    # Adjust for UTC offset (strptime assumes local, timestamps are UTC)
                    ts -= time.timezone
                    if ts >= cutoff:
                        timestamps.append(ts)
            except Exception:
                pass
    except Exception:
        pass
    return timestamps


def get_agent_stats():
    """Count sessions per agent from their session JSONL files."""
    now = time.time()
    agents_out = []

    for agent in AGENTS:
        aid = agent["id"]
        timestamps = _read_session_timestamps(aid)
        session_count = len(timestamps)
        last_ts = max(timestamps) if timestamps else None

        if last_ts:
            diff = now - last_ts
            if diff < 60:
                last_seen = "just now"
            elif diff < 3600:
                last_seen = f"{int(diff//60)}m ago"
            elif diff < 86400:
                last_seen = f"{int(diff//3600)}h ago"
            else:
                last_seen = f"{int(diff//86400)}d ago"
        else:
            last_seen = "never"

        agents_out.append({
            "id":        aid,
            "name":      agent["name"],
            "emoji":     agent["emoji"],
            "bot":       agent["bot"],
            "messages":  session_count,
            "last_seen": last_seen,
            "last_ts":   int(last_ts) if last_ts else 0,
        })

    activity = _agent_activity_by_day()
    return {"agents": agents_out, "activity": activity}


def _agent_activity_by_day():
    """Count sessions per agent per day for last 14 days."""
    days = []
    for i in range(13, -1, -1):
        t = time.localtime(time.time() - i * 86400)
        days.append(time.strftime("%Y-%m-%d", t))

    counts = {d: {a["id"]: 0 for a in AGENTS} for d in days}

    for agent in AGENTS:
        aid = agent["id"]
        for ts in _read_session_timestamps(aid):
            day = time.strftime("%Y-%m-%d", time.localtime(ts))
            if day in counts:
                counts[day][aid] += 1

    return {
        "days":   days,
        "counts": {a["id"]: [counts[d][a["id"]] for d in days] for a in AGENTS}
    }


# ── Background collector ───────────────────────────────────────────────────

_tick_count = 0

def collector():
    global _tick_count
    while True:
        try:
            snap = {
                "cpu_temp":  read_cpu_temp(),
                "fan_speed": read_fan_speed(),
                "ram_pct":   read_ram_pct(),
                "cpu_pct":   read_cpu_pct(),
            }
            with history_lock:
                history.append(snap)
            with _minute_lock:
                _minute_buf.append(snap)
            _tick_count += 1
            # Flush minute average every 12 ticks (~60s)
            if _tick_count % 12 == 0:
                flush_minute_average()
        except Exception:
            pass
        time.sleep(5)


# ── HTTP handler ───────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def send_json(self, data):
        body = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/agents":
            self.send_json(get_agent_stats())
        elif self.path == "/stats":
            self.send_json(get_stats())
        elif self.path.startswith("/history"):
            secs = 1800  # default 30 min
            if "?s=" in self.path:
                try: secs = int(self.path.split("?s=")[1])
                except Exception: pass

            since_ts = int(time.time()) - secs

            if secs <= 86400:
                # Use in-memory 5s-resolution data
                n = secs // 5
                with history_lock:
                    snap = list(history)[-n:]
                interval = 5
            else:
                # Use disk minute-averaged data
                snap = get_disk_history(since_ts)
                snap = downsample(snap, 600)
                interval = max(60, secs // 600)

            self.send_json({
                "cpu_temp":     [s["cpu_temp"]  for s in snap],
                "fan_speed":    [s["fan_speed"] for s in snap],
                "ram_pct":      [s["ram_pct"]   for s in snap],
                "cpu_pct":      [s["cpu_pct"]   for s in snap],
                "interval_secs": interval,
            })
        else:
            body = HTML.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", len(body))
            self.end_headers()
            self.wfile.write(body)


if __name__ == "__main__":
    load_disk_history()
    t = threading.Thread(target=collector, daemon=True)
    t.start()
    server = HTTPServer(("127.0.0.1", 19999), Handler)
    print("Pi Dashboard running on http://127.0.0.1:19999", flush=True)
    server.serve_forever()
