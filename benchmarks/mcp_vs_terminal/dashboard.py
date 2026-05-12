#!/usr/bin/env python3
"""
dashboard.py – Benchmark comparison dashboard.

    pip install flask
    python dashboard.py            # http://localhost:5050
"""

import json
from flask import Flask, jsonify, render_template_string, request
from db import (
    init_db,
    get_all_runs,
    get_run_results,
    get_summary_stats,
    get_all_results,
    get_run_artifacts,
    get_baseline_run,
    get_latest_terminal_run,
    set_baseline_run,
    get_mcp_runs,
    get_terminal_runs,
    get_run_comparison,
    get_run,
    parse_mcp_version,
)

app = Flask(__name__)
init_db()


# ── API endpoints ───────────────────────────────────────────────────────────────

@app.get("/api/runs")
def api_runs():
    return jsonify(get_all_runs())


@app.get("/api/runs/<run_id>/results")
def api_run_results(run_id):
    return jsonify(get_run_results(run_id))


@app.get("/api/runs/<run_id>/artifacts")
def api_run_artifacts(run_id):
    return jsonify(get_run_artifacts(run_id))


@app.get("/api/runs/<run_id>/comparison")
def api_run_comparison(run_id):
    result = get_run_comparison(run_id)
    if result is None:
        return jsonify({"error": "Run not found"}), 404
    return jsonify(result)


@app.get("/api/summary")
def api_summary():
    return jsonify(get_summary_stats())


@app.get("/api/all_results")
def api_all_results():
    return jsonify(get_all_results())


@app.get("/api/baseline")
def api_baseline():
    baseline = get_baseline_run()
    if not baseline:
        fallback = get_latest_terminal_run()
        return jsonify(fallback or {"error": "No baseline available"})
    results = get_run_results(baseline["run_id"])
    return jsonify({**baseline, "results": results})


@app.post("/api/baseline/<run_id>")
def api_set_baseline(run_id):
    run = get_run(run_id)
    if not run:
        return jsonify({"error": "Run not found"}), 404
    set_baseline_run(run_id)
    return jsonify({"success": True, "run_id": run_id})


@app.get("/api/mcp_runs")
def api_mcp_runs():
    return jsonify(get_mcp_runs())


@app.get("/api/terminal_runs")
def api_terminal_runs():
    return jsonify(get_terminal_runs())


# ── Dashboard HTML ────────────────────────────────────────────────────────────

DASHBOARD_HTML = r"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8" />
<meta name="viewport" content="width=device-width, initial-scale=1.0" />
<title>Benchmark Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    background: #0f1117;
    color: #e2e8f0;
    min-height: 100vh;
  }

  a { color: #818cf8; text-decoration: none; }
  a:hover { text-decoration: underline; }

  header {
    padding: 16px 28px;
    border-bottom: 1px solid #1e2535;
    display: flex;
    align-items: center;
    gap: 16px;
    background: #0d1018;
  }
  header h1 { font-size: 1.1rem; font-weight: 600; letter-spacing: -.01em; }
  header .subtitle { font-size: .75rem; color: #64748b; }
  header .header-right { margin-left: auto; display: flex; align-items: center; gap: 12px; }

  .run-pill {
    display: inline-flex; align-items: center; gap: 8px;
    background: #1e2535; border: 1px solid #2d3748; border-radius: 6px;
    padding: 4px 10px; font-size: .75rem; cursor: pointer;
    transition: background .15s, border-color .15s;
    user-select: none;
  }
  .run-pill input[type=checkbox] { accent-color: #6366f1; width: 13px; height: 13px; }

  .layout { display: grid; grid-template-columns: 300px 1fr; min-height: calc(100vh - 57px); }

  aside {
    padding: 16px;
    border-right: 1px solid #1e2535;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: 16px;
  }
  aside h3 {
    font-size: .65rem; text-transform: uppercase; letter-spacing: .1em;
    color: #475569; margin-bottom: 6px; padding-left: 4px;
  }

  .section { }
  .section-header {
    display: flex; align-items: center; justify-content: space-between;
    margin-bottom: 8px;
  }
  .section-header span { font-size: .65rem; text-transform: uppercase; letter-spacing: .08em; color: #475569; }

  .run-card {
    background: #161b27;
    border: 1px solid #252d40;
    border-radius: 8px;
    padding: 10px 12px;
    margin-bottom: 6px;
    cursor: pointer;
    transition: border-color .15s;
  }
  .run-card.selected { border-color: #6366f1; }
  .run-card.is-baseline { border-color: #22c55e; }
  .run-card .run-id { font-size: .68rem; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; color: #64748b; }
  .run-card .run-version { font-size: .8rem; font-weight: 500; margin: 3px 0 1px; }
  .run-card .run-date { font-size: .68rem; color: #475569; }
  .run-card .run-meta { font-size: .68rem; color: #475569; margin-top: 2px; }

  .badge {
    display: inline-block; font-size: .6rem; padding: 1px 6px;
    border-radius: 9999px; vertical-align: middle; margin-left: 6px;
    font-weight: 600; letter-spacing: .03em;
  }
  .badge-baseline { background: #064e3b; color: #34d399; }
  .badge-mcp { background: #1e3a5f; color: #60a5fa; }
  .badge-terminal { background: #312e1e; color: #fbbf24; }

  .set-baseline-btn {
    display: block; width: 100%; margin-top: 6px;
    appearance: none; border: 1px solid #2d3748; background: transparent;
    color: #64748b; border-radius: 5px; padding: 3px 8px;
    font-size: .65rem; cursor: pointer; text-align: center;
    transition: background .15s, color .15s;
  }
  .set-baseline-btn:hover { background: #1a2d1a; color: #34d399; border-color: #22c55e; }

  main { padding: 20px 28px; overflow-y: auto; }

  .view-mode-badge {
    display: inline-block; font-size: .65rem; padding: 2px 10px;
    border-radius: 9999px; margin-bottom: 14px; font-weight: 500;
  }
  .mode-comparison { background: #1e3a5f; color: #60a5fa; }
  .mode-trend { background: #3b1f5f; color: #a78bfa; }
  .mode-solo { background: #1e2a3a; color: #94a3b8; }

  .stats-row {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
    gap: 12px;
    margin-bottom: 24px;
  }
  .stat-card {
    background: #161b27; border: 1px solid #252d40; border-radius: 8px;
    padding: 14px 16px;
  }
  .stat-card .label { font-size: .65rem; color: #475569; text-transform: uppercase; letter-spacing: .06em; }
  .stat-card .value { font-size: 1.5rem; font-weight: 700; margin-top: 4px; }
  .stat-card .sub { font-size: .68rem; color: #475569; margin-top: 2px; }
  .stat-card .delta { font-size: .72rem; margin-top: 3px; font-weight: 500; }
  .delta-pos { color: #34d399; }
  .delta-neg { color: #f87171; }

  .charts-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(520px, 1fr));
    gap: 18px;
    margin-bottom: 24px;
  }
  .chart-card {
    background: #161b27; border: 1px solid #252d40; border-radius: 8px;
    padding: 16px 18px;
  }
  .chart-card h3 { font-size: .8rem; font-weight: 600; margin-bottom: 12px; color: #94a3b8; }
  .chart-card canvas { max-height: 240px; }

  .section-title {
    font-size: .68rem; text-transform: uppercase; letter-spacing: .08em;
    color: #475569; margin: 20px 0 10px;
  }

  table { width: 100%; border-collapse: collapse; font-size: .75rem; }
  th {
    text-align: left; padding: 8px 12px; background: #161b27;
    border-bottom: 1px solid #252d40; font-size: .65rem;
    text-transform: uppercase; letter-spacing: .05em; color: #475569;
  }
  td { padding: 8px 12px; border-bottom: 1px solid #1a2030; }
  tr:hover td { background: #161b27; }
  .table-wrap {
    background: #12161f; border: 1px solid #252d40; border-radius: 8px;
    overflow: hidden; margin-bottom: 24px;
  }

  .chip {
    display: inline-block; width: 9px; height: 9px;
    border-radius: 2px; margin-right: 6px; vertical-align: middle; flex-shrink: 0;
  }

  .delta-cell { font-size: .72rem; font-weight: 500; }
  .delta-winner { color: #34d399; }
  .delta-loser { color: #f87171; }

  .empty { text-align: center; padding: 80px 0; color: #334155; font-size: .85rem; }

  .artifact-card {
    background: #161b27; border: 1px solid #252d40; border-radius: 8px;
    padding: 12px; margin-bottom: 10px;
  }
  .artifact-row {
    display: flex; align-items: center; justify-content: space-between;
    gap: 12px; padding: 7px 0; border-top: 1px solid #252d40;
  }
  .artifact-row:first-child { border-top: none; padding-top: 0; }
  .artifact-meta { color: #94a3b8; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: .7rem; }
  .artifact-sub { color: #475569; font-size: .68rem; margin-top: 2px; }

  .btn {
    appearance: none; border: 1px solid #2d3748; background: #0f1623;
    color: #94a3b8; border-radius: 6px; padding: 5px 10px;
    font-size: .7rem; cursor: pointer; transition: background .15s, border-color .15s;
    white-space: nowrap;
  }
  .btn:hover { background: #1a2535; border-color: #3b82f6; }

  .modal-backdrop {
    position: fixed; inset: 0; background: rgba(2, 6, 23, 0.72);
    display: none; align-items: center; justify-content: center;
    padding: 24px; z-index: 9999;
  }
  .modal {
    width: min(1100px, 96vw); max-height: min(82vh, 860px);
    background: #0b1020; border: 1px solid #252d40; border-radius: 10px;
    overflow: hidden; box-shadow: 0 24px 70px rgba(0,0,0,0.45);
    display: flex; flex-direction: column;
  }
  .modal-header {
    display: flex; align-items: center; justify-content: space-between;
    gap: 12px; padding: 12px 14px; border-bottom: 1px solid #1e2535; background: #0f172a;
  }
  .modal-title {
    font-size: .78rem; color: #cbd5e1; font-weight: 600;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }
  .modal-body { padding: 12px 14px; overflow: auto; flex: 1; }
  pre.log {
    white-space: pre-wrap; word-break: break-word; font-size: .73rem;
    line-height: 1.4; color: #cbd5e1;
  }

  .task-delta {
    display: inline-flex; align-items: center; gap: 4px;
    font-size: .68rem; font-weight: 500; padding: 1px 6px; border-radius: 4px;
  }
  .task-delta.pos { background: #064e3b22; color: #34d399; }
  .task-delta.neg { background: #7f1d1d22; color: #f87171; }
  .task-delta.neutral { background: #1e2535; color: #64748b; }

  .no-baseline-warning {
    background: #3b1f5f; border: 1px solid #5b21b6; border-radius: 8px;
    padding: 12px 16px; font-size: .78rem; color: #a78bfa;
    margin-bottom: 20px;
  }
  .no-baseline-warning strong { color: #c4b5fd; }
</style>
</head>
<body>
<header>
  <svg width="20" height="20" viewBox="0 0 22 22" fill="none">
    <rect x="2" y="10" width="4" height="10" rx="1" fill="#6366f1"/>
    <rect x="9" y="5" width="4" height="15" rx="1" fill="#818cf8"/>
    <rect x="16" y="1" width="4" height="19" rx="1" fill="#a5b4fc"/>
  </svg>
  <div>
    <h1>Benchmark Dashboard</h1>
    <div class="subtitle">mcp-stata vs terminal comparison</div>
  </div>
  <div class="header-right">
    <span id="db-info" style="font-size:.72rem;color:#475569;"></span>
  </div>
</header>

<div class="layout">
  <aside>
    <div class="section" id="section-baseline">
      <div class="section-header">
        <span>Baseline (Terminal)</span>
      </div>
      <div id="terminal-runs"></div>
    </div>
    <div class="section" id="section-mcp">
      <div class="section-header">
        <span>MCP Runs</span>
      </div>
      <div id="mcp-runs"></div>
    </div>
  </aside>

  <main>
    <div id="no-baseline-warning" class="no-baseline-warning" style="display:none">
      <strong>No baseline set.</strong> Select a terminal run from the sidebar and click "Set as baseline" to enable comparison view.
    </div>
    <div id="content">
      <div class="empty">Select runs from the sidebar to view comparisons.</div>
    </div>
  </main>
</div>

<div class="modal-backdrop" id="modal-backdrop" onclick="closeModal(event)">
  <div class="modal" role="dialog" aria-modal="true" onclick="event.stopPropagation()">
    <div class="modal-header">
      <div class="modal-title" id="modal-title"></div>
      <button class="btn" onclick="closeModal()">Close</button>
    </div>
    <div class="modal-body">
      <pre class="log" id="modal-content"></pre>
    </div>
  </div>
</div>

<script>
const PALETTE = [
  '#6366f1','#f59e0b','#10b981','#ef4444','#3b82f6',
  '#ec4899','#14b8a6','#f97316','#8b5cf6','#06b6d4'
];
const BASELINE_COLOR = '#475569';
const BASELINE_FILL = '#475569aa';

let allTerminalRuns = [];
let allMCPRuns = [];
let baselineRun = null;
let selectedRuns = new Set();
let artifactsByRun = {};
let chartInstances = {};

// ── Fetch data ─────────────────────────────────────────────────────────────

async function load() {
  const [terminalRuns, mcpRuns] = await Promise.all([
    fetch('/api/terminal_runs').then(r => r.json()),
    fetch('/api/mcp_runs').then(r => r.json()),
    fetch('/api/baseline').then(r => r.json()),
  ]);
  allTerminalRuns = terminalRuns;
  allMCPRuns = mcpRuns;
  baselineRun = (mcpRuns.length === 0 && terminalRuns.length > 0) ? null : mcpRuns.find(r => r.is_baseline) || null;
  if (!baselineRun) {
    const bl = await fetch('/api/baseline').then(r => r.json());
    if (bl && bl.run_id) baselineRun = bl;
  }
  document.getElementById('db-info').textContent =
    `${allTerminalRuns.length} terminal, ${allMCPRuns.length} MCP runs`;
  renderSidebar();
  checkBaselineWarning();
}

function checkBaselineWarning() {
  const hasBaseline = allTerminalRuns.some(r => r.is_baseline) || baselineRun !== null;
  document.getElementById('no-baseline-warning').style.display = hasBaseline ? 'none' : 'block';
}

// ── Sidebar ─────────────────────────────────────────────────────────────────

function renderSidebar() {
  const terminalEl = document.getElementById('terminal-runs');
  const mcpEl = document.getElementById('mcp-runs');

  // Terminal runs
  if (!allTerminalRuns.length) {
    terminalEl.innerHTML = '<div style="color:#334155;font-size:.72rem">No terminal runs.</div>';
  } else {
    terminalEl.innerHTML = allTerminalRuns.map(r => {
      const sel = selectedRuns.has(r.run_id) ? 'selected' : '';
      const isBaseline = r.is_baseline ? 'is-baseline' : '';
      const badge = r.is_baseline ? '<span class="badge badge-baseline">BASELINE</span>' : '';
      const date = fmtDate(r.created_at);
      return `
        <div class="run-card ${sel} ${isBaseline}" onclick="toggleRun('${r.run_id}')">
          <div class="run-id">${r.run_id}</div>
          <div class="run-version">Terminal${badge}</div>
          <div class="run-date">${date}</div>
          <div class="run-meta">${r.result_count || 0} tasks &nbsp;·&nbsp; ${r.source}</div>
          ${!r.is_baseline ? `<button class="set-baseline-btn" onclick="event.stopPropagation();setBaseline('${r.run_id}')">Set as baseline</button>` : ''}
        </div>`;
    }).join('');
  }

  // MCP runs
  if (!allMCPRuns.length) {
    mcpEl.innerHTML = '<div style="color:#334155;font-size:.72rem">No MCP runs yet.</div>';
  } else {
    mcpEl.innerHTML = allMCPRuns.map((r, i) => {
      const sel = selectedRuns.has(r.run_id) ? 'selected' : '';
      const color = PALETTE[i % PALETTE.length];
      const date = fmtDate(r.created_at);
      const version = r.mcp_version ? r.mcp_version : 'unknown';
      return `
        <div class="run-card ${sel}" onclick="toggleRun('${r.run_id}')">
          <div class="run-id" style="border-left:3px solid ${color};padding-left:6px;">${r.run_id}</div>
          <div class="run-version"><span class="chip" style="background:${color}"></span>${version}</div>
          <div class="run-date">${date}</div>
          <div class="run-meta">${r.result_count || 0} tasks</div>
        </div>`;
    }).join('');
  }
}

function fmtDate(ts) {
  if (!ts) return '—';
  return ts.slice(0, 16).replace('T', ' ');
}

async function setBaseline(runId) {
  await fetch(`/api/baseline/${encodeURIComponent(runId)}`, { method: 'POST' });
  await load();
  renderMain();
}

function toggleRun(runId) {
  if (selectedRuns.has(runId)) selectedRuns.delete(runId);
  else selectedRuns.add(runId);
  renderSidebar();
  renderMain();
}

// ── Main panel ──────────────────────────────────────────────────────────────

async function renderMain() {
  const content = document.getElementById('content');
  if (!selectedRuns.size) {
    content.innerHTML = '<div class="empty">Select runs from the sidebar to view comparisons.</div>';
    return;
  }

  const selIds = [...selectedRuns];

  // Fetch comparison data for all selected runs
  const comparisons = await Promise.all(
    selIds.map(async (rid) => {
      const r = await fetch(`/api/runs/${encodeURIComponent(rid)}/comparison`).then(r => r.json());
      return r;
    })
  );

  // Detect view mode
  const hasBaseline = selIds.some(id =>
    allTerminalRuns.find(r => r.run_id === id)
  );
  const mcpSelected = selIds.filter(id => allMCPRuns.find(r => r.run_id === id));
  let mode = 'solo';
  if (mcpSelected.length >= 2 && !hasBaseline) mode = 'trend';
  else if (mcpSelected.length >= 1 && hasBaseline) mode = 'comparison';
  else if (mcpSelected.length === 1 && !hasBaseline) mode = 'solo';

  // Fetch artifacts
  await Promise.all(selIds.map(async (rid) => {
    if (artifactsByRun[rid]) return;
    artifactsByRun[rid] = await fetch(`/api/runs/${encodeURIComponent(rid)}/artifacts`).then(r => r.json());
  }));

  content.innerHTML = `
    <div id="view-mode-badge"></div>
    <div class="stats-row" id="stats-row"></div>
    <div class="charts-grid">
      <div class="chart-card"><h3>Input Tokens by Task</h3><canvas id="chart-input"></canvas></div>
      <div class="chart-card"><h3>Output Tokens by Task</h3><canvas id="chart-output"></canvas></div>
      <div class="chart-card"><h3>Total Tokens by Task</h3><canvas id="chart-total"></canvas></div>
      <div class="chart-card"><h3>Turns by Task</h3><canvas id="chart-turns"></canvas></div>
    </div>
    <div class="section-title">Task Detail</div>
    <div id="task-table-wrap"></div>
    <div class="section-title">Artifacts</div>
    <div id="artifacts"></div>
  `;

  renderViewModeBadge(mode);
  renderStats(comparisons, mode, hasBaseline);
  renderCharts(comparisons, mode, hasBaseline, mcpSelected);
  renderTaskTable(comparisons, mode, hasBaseline, mcpSelected);
  renderArtifacts(selIds);
}

function renderViewModeBadge(mode) {
  const badges = {
    comparison: ['Comparison mode', 'mode-comparison'],
    trend: ['Version trend mode', 'mode-trend'],
    solo: ['Solo view (no baseline)', 'mode-solo'],
  };
  const [text, cls] = badges[mode] || ['Solo view', 'mode-solo'];
  document.getElementById('view-mode-badge').innerHTML =
    `<span class="view-mode-badge ${cls}">${text}</span>`;
}

// ── Stats cards ─────────────────────────────────────────────────────────────

function renderStats(comparisons, mode, hasBaseline) {
  const rows = [];

  for (const comp of comparisons) {
    if (!comp.run) continue;
    const run = comp.run;
    const isBaseline = !run.mcp_version;
    const delta = comp.baseline && comp.deltas ? computeTotals(comp.deltas) : null;
    const _results = run.results && typeof run.results === 'object' && !Array.isArray(run.results)
      ? Object.values(run.results)
      : (Array.isArray(run.results) ? run.results : []);
    const totalIn = _results.reduce((s, r) => s + (r.input_tokens||0), 0);
    const totalOut = _results.reduce((s, r) => s + (r.output_tokens||0), 0);
    const totalTokens = totalIn + totalOut;
    const avgTurns = _results.length
      ? (_results.reduce((s,r) => s+(r.turns||0), 0) / _results.length).toFixed(1)
      : '—';
    const taskCount = _results.length;

    let deltaStr = '';
    let deltaCls = '';
    if (!isBaseline && delta) {
      const pct = ((totalTokens / delta.total) - 1) * 100;
      const sign = pct >= 0 ? '+' : '';
      deltaStr = `${sign}${pct.toFixed(1)}% vs baseline`;
      deltaCls = pct <= 0 ? 'delta-pos' : 'delta-neg';
    }

    const label = isBaseline ? 'Baseline' : (run.mcp_version || run.run_id.slice(-8));
    const version = isBaseline ? '' : `<span style="color:#94a3b8;font-size:.68rem"> &nbsp;${run.mcp_version || ''}</span>`;

    rows.push(`
      <div class="stat-card">
        <div class="label">${label}${version}</div>
        <div class="value">${totalTokens.toLocaleString()}</div>
        <div class="sub">in=${totalIn.toLocaleString()} &nbsp; out=${totalOut.toLocaleString()}</div>
        ${deltaStr ? `<div class="delta ${deltaCls}">${deltaStr}</div>` : ''}
        <div class="sub" style="margin-top:4px">${taskCount} tasks &nbsp;·&nbsp; avg ${avgTurns} turns</div>
      </div>`);
  }

  document.getElementById('stats-row').innerHTML = rows.join('');
}

function computeTotals(deltas) {
  const mcpIn = deltas.reduce((s,d) => s + (d.mcp_input||0), 0);
  const mcpOut = deltas.reduce((s,d) => s + (d.mcp_output||0), 0);
  const baseIn = deltas.reduce((s,d) => s + (d.baseline_input||0), 0);
  const baseOut = deltas.reduce((s,d) => s + (d.baseline_output||0), 0);
  return { mcp: mcpIn+mcpOut, total: baseIn+baseOut };
}

// ── Charts ──────────────────────────────────────────────────────────────────

function destroyChart(id) {
  if (chartInstances[id]) { chartInstances[id].destroy(); delete chartInstances[id]; }
}

function makeBarChart(canvasId, labels, datasets, extra = {}) {
  destroyChart(canvasId);
  const ctx = document.getElementById(canvasId).getContext('2d');
  chartInstances[canvasId] = new Chart(ctx, {
    type: 'bar',
    data: { labels, datasets },
    options: {
      responsive: true, maintainAspectRatio: true,
      plugins: { legend: { labels: { color: '#94a3b8', font: { size: 11 } } } },
      scales: {
        x: { ticks: { color: '#64748b', font: { size: 10 } }, grid: { color: '#1e2535' } },
        y: { ticks: { color: '#64748b', font: { size: 10 } }, grid: { color: '#1e2535' }, beginAtZero: true }
      },
      ...extra
    }
  });
}

function renderCharts(comparisons, mode, hasBaseline, mcpSelected) {
  const baselineComp = comparisons.find(c => !c.run?.mcp_version);
  const mcpComps = comparisons.filter(c => !!c.run?.mcp_version);

  // Build task list from all comparisons
  const allTaskIds = [...new Set(comparisons.flatMap(c => {
      const res = c.run && c.run.results
        ? (Array.isArray(c.run.results) ? c.run.results : Object.values(c.run.results))
        : [];
      return res.map(r => r.task_id);
    }))].sort();

  // Colors: baseline = gray, MCP runs = palette
  // Datasets: one per selected run (grouped bars)
  const datasetsByMetric = {
    input: [],
    output: [],
    total: [],
    turns: [],
  };

  const allComps = mode === 'comparison'
    ? [baselineComp, ...mcpComps].filter(Boolean)
    : comparisons;

  for (let ri = 0; ri < allComps.length; ri++) {
    const comp = allComps[ri];
    const run = comp.run;
    if (!run) continue;
    const isBaseline = !run.mcp_version;
    const colorIdx = isBaseline ? -1 : ri - (baselineComp ? 1 : 0);
    const color = isBaseline ? BASELINE_COLOR : PALETTE[colorIdx % PALETTE.length];
    const label = isBaseline ? 'Baseline' : (run.mcp_version || run.run_id.slice(-8));
    const fill = isBaseline ? BASELINE_FILL : color + 'cc';

    const resultsArr = run.results && typeof run.results === 'object'
      ? (Array.isArray(run.results) ? run.results : Object.values(run.results))
      : [];
    const resultsMap = {};
    for (const r of resultsArr) resultsMap[r.task_id] = r;

    const inp = [], out = [], total = [], trns = [];
    for (const tid of allTaskIds) {
      const r = resultsMap[tid];
      inp.push(r ? (r.input_tokens||0) : 0);
      out.push(r ? (r.output_tokens||0) : 0);
      total.push(r ? ((r.input_tokens||0)+(r.output_tokens||0)) : 0);
      trns.push(r ? (r.turns||0) : 0);
    }

    const baseDS = { label, data: total, backgroundColor: fill, borderRadius: 3 };
    datasetsByMetric.input.push({ ...baseDS, label: label+' (in)', data: inp, backgroundColor: fill });
    datasetsByMetric.output.push({ ...baseDS, label: label+' (out)', data: out, backgroundColor: fill });
    datasetsByMetric.total.push({ ...baseDS });
    datasetsByMetric.turns.push({ ...baseDS, data: trns });
  }

  const barLabels = allTaskIds.map(tid => {
    const parts = tid.split('.');
    return parts.length > 1 ? `${parts[0]}.${parts[1]}` : tid;
  });

  makeBarChart('chart-input', barLabels, datasetsByMetric.input);
  makeBarChart('chart-output', barLabels, datasetsByMetric.output);
  makeBarChart('chart-total', barLabels, datasetsByMetric.total);
  makeBarChart('chart-turns', barLabels, datasetsByMetric.turns);
}

// ── Task detail table ───────────────────────────────────────────────────────

function renderTaskTable(comparisons, mode, hasBaseline, mcpSelected) {
  const baselineComp = comparisons.find(c => !c.run?.mcp_version);
  const mcpComps = comparisons.filter(c => !!c.run?.mcp_version);

  // Build rows from deltas if available
  if (mode === 'comparison' && baselineComp?.deltas?.length) {
    renderDeltaTable(baselineComp, mcpComps);
  } else {
    renderSimpleTable(comparisons);
  }
}

function renderDeltaTable(baselineComp, mcpComps) {
  const deltas = baselineComp.deltas;
  const runs = [baselineComp.run, ...mcpComps.map(c => c.run)];

  const thMCP = mcpComps.map((c, i) => {
    const color = PALETTE[i % PALETTE.length];
    return `<th style="color:${color}">${c.run.mcp_version || c.run.run_id.slice(-8)}</th>`;
  }).join('');

  const rows = deltas.map(d => {
    const taskId = d.task_id;
    const baseIn = d.baseline_input ?? 0;
    const baseOut = d.baseline_output ?? 0;
    const baseTot = baseIn + baseOut;

    const mcpCells = mcpComps.map((c, i) => {
      const color = PALETTE[i % PALETTE.length];
      const mcpIn = d.mcp_input || 0;
      const mcpOut = d.mcp_output || 0;
      const mcpTot = mcpIn + mcpOut;
      const inDelta = mcpIn - baseIn;
      const outDelta = mcpOut - baseOut;
      const totDelta = mcpTot - baseTot;
      const deltaStr = totDelta >= 0 ? `+${totDelta.toLocaleString()}` : totDelta.toLocaleString();
      const cls = totDelta <= 0 ? 'delta-winner' : 'delta-loser';
      return `<td>
        <span class="chip" style="background:${color}"></span>
        ${mcpIn.toLocaleString()} / ${mcpOut.toLocaleString()}
        <span class="delta-cell ${cls}">(${deltaStr})</span>
      </td>`;
    }).join('');

    const baseTotStr = baseTot > 0 ? baseTot.toLocaleString() : '—';
    return `<tr>
      <td>${taskId}</td>
      <td style="color:${BASELINE_COLOR}">${baseIn.toLocaleString()} / ${baseOut.toLocaleString()}</td>
      ${mcpCells}
    </tr>`;
  });

  document.getElementById('task-table-wrap').innerHTML = `
    <div class="table-wrap">
      <table>
        <thead><tr>
          <th>Task</th>
          <th style="color:${BASELINE_COLOR}">Baseline (in/out)</th>
          ${thMCP}
        </tr></thead>
        <tbody>${rows.join('')}</tbody>
      </table>
    </div>`;
}

function renderSimpleTable(comparisons) {
  const allComps = comparisons.filter(c => {
    if (!c.run) return false;
    const res = c.run.results;
    return res && (Array.isArray(res) ? res.length > 0 : Object.keys(res).length > 0);
  });
  if (!allComps.length) return;

  const allTaskIds = [...new Set(allComps.flatMap(c => {
    const res = c.run.results;
    const arr = Array.isArray(res) ? res : Object.values(res || {});
    return arr.map(r => r.task_id);
  }))].sort();
  const headers = allComps.map((c, i) => {
    const isBaseline = !c.run.mcp_version;
    const color = isBaseline ? BASELINE_COLOR : PALETTE[(i-1) % PALETTE.length];
    const label = isBaseline ? 'Baseline' : (c.run.mcp_version || c.run.run_id.slice(-8));
    return `<th style="color:${color}">${label}</th>`;
  }).join('');

  const rows = allTaskIds.map(tid => {
    const cells = allComps.map(c => {
      const res = c.run.results;
      const arr = Array.isArray(res) ? res : Object.values(res || {});
      const r = arr.find(r => r.task_id === tid);
      if (!r) return `<td>—</td>`;
      return `<td>${(r.input_tokens||0).toLocaleString()} / ${(r.output_tokens||0).toLocaleString()}</td>`;
    }).join('');
    return `<tr><td>${tid}</td>${cells}</tr>`;
  });

  document.getElementById('task-table-wrap').innerHTML = `
    <div class="table-wrap">
      <table>
        <thead><tr><th>Task</th>${headers}</tr></thead>
        <tbody>${rows.join('')}</tbody>
      </table>
    </div>`;
}

// ── Artifacts ───────────────────────────────────────────────────────────────

function fmtBytes(n) {
  if (n == null) return '—';
  const units = ['B','KB','MB','GB'];
  let i = 0, x = Number(n);
  while (x >= 1024 && i < units.length - 1) { x /= 1024; i++; }
  return `${(i===0?String(Math.round(x)):x.toFixed(1))} ${units[i]}`;
}

function renderArtifacts(runIds) {
  const el = document.getElementById('artifacts');
  const runs = (runIds.map(id =>
    allMCPRuns.find(r => r.run_id === id) || allTerminalRuns.find(r => r.run_id === id)
  )).filter(Boolean);

  if (!runs.length) {
    el.innerHTML = '<div style="color:#334155;font-size:.78rem">No artifacts.</div>';
    return;
  }

  el.innerHTML = runs.map(run => {
    const arts = artifactsByRun[run.run_id] || [];
    const isBaseline = !run.mcp_version;
    const color = isBaseline ? BASELINE_COLOR : PALETTE[0];
    const label = isBaseline ? 'Baseline' : (run.mcp_version || run.run_id.slice(-8));
    const items = arts.length ? arts.map(a => {
      const hasText = a.content_text && a.content_text.length > 0;
      return `
        <div class="artifact-row">
          <div>
            <div class="artifact-meta">${a.kind} · ${a.filename}</div>
            <div class="artifact-sub">${fmtBytes(a.bytes)} · ${fmtDate(a.created_at)}</div>
          </div>
          ${hasText ? `<button class="btn" onclick="openModal('${run.run_id}', ${a.id})">View</button>` : ''}
        </div>`;
    }).join('') : '<div class="artifact-sub" style="padding:4px 0">No artifacts.</div>';

    return `
      <div class="artifact-card">
        <div class="artifact-meta"><span class="chip" style="background:${color}"></span>${label} · ${run.run_id}</div>
        <div style="margin-top:8px">${items}</div>
      </div>`;
  }).join('');
}

function openModal(runId, artifactId) {
  const arts = artifactsByRun[runId] || [];
  const art = arts.find(a => a.id === artifactId);
  if (!art) return;
  document.getElementById('modal-title').textContent = `${runId} · ${art.kind} · ${art.filename}`;
  document.getElementById('modal-content').textContent = art.content_text || '';
  document.getElementById('modal-backdrop').style.display = 'flex';
}

function closeModal(evt) {
  document.getElementById('modal-backdrop').style.display = 'none';
  document.getElementById('modal-content').textContent = '';
  document.getElementById('modal-title').textContent = '';
}

document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeModal(); });

// ── Boot ───────────────────────────────────────────────────────────────────
load();
</script>
</body>
</html>
"""


@app.get("/")
def index():
    return render_template_string(DASHBOARD_HTML)


if __name__ == "__main__":
    print("Dashboard → http://localhost:5050")
    app.run(host="0.0.0.0", port=5050, debug=False)