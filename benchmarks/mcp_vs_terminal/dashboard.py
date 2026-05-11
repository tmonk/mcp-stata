"""
dashboard.py – Benchmark comparison dashboard.

    pip install flask
    python dashboard.py            # http://localhost:5050
"""

import json
from flask import Flask, jsonify, render_template_string
from db import (
    init_db,
    get_all_runs,
    get_run_results,
    get_summary_stats,
    get_all_results,
    get_run_artifacts,
)

app = Flask(__name__)
init_db()


# ── API endpoints ──────────────────────────────────────────────────────────────

@app.get("/api/runs")
def api_runs():
    return jsonify(get_all_runs())


@app.get("/api/runs/<run_id>/results")
def api_run_results(run_id):
    return jsonify(get_run_results(run_id))


@app.get("/api/runs/<run_id>/artifacts")
def api_run_artifacts(run_id):
    return jsonify(get_run_artifacts(run_id))


@app.get("/api/summary")
def api_summary():
    return jsonify(get_summary_stats())


@app.get("/api/all_results")
def api_all_results():
    return jsonify(get_all_results())


# ── Dashboard HTML ─────────────────────────────────────────────────────────────

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

  header {
    padding: 20px 32px;
    border-bottom: 1px solid #1e2535;
    display: flex;
    align-items: center;
    gap: 12px;
  }
  header h1 { font-size: 1.25rem; font-weight: 600; letter-spacing: -.01em; }
  header span { font-size: .8rem; color: #64748b; }

  .run-pill {
    display: inline-flex; align-items: center; gap: 8px;
    background: #1e2535; border: 1px solid #2d3748; border-radius: 6px;
    padding: 4px 10px; font-size: .75rem; cursor: pointer;
    transition: background .15s, border-color .15s;
    user-select: none;
  }
  .run-pill input[type=checkbox] { accent-color: #6366f1; width: 13px; height: 13px; }
  .run-pill:hover { background: #252d40; }

  .layout { display: grid; grid-template-columns: 280px 1fr; min-height: calc(100vh - 61px); }

  aside {
    padding: 20px 16px;
    border-right: 1px solid #1e2535;
    overflow-y: auto;
  }
  aside h2 { font-size: .7rem; text-transform: uppercase; letter-spacing: .08em; color: #64748b; margin-bottom: 12px; }

  .run-card {
    background: #1a2030;
    border: 1px solid #252d40;
    border-radius: 8px;
    padding: 12px;
    margin-bottom: 8px;
    cursor: pointer;
    transition: border-color .15s;
  }
  .run-card.selected { border-color: #6366f1; }
  .run-card .run-id { font-size: .7rem; font-family: monospace; color: #94a3b8; }
  .run-card .run-model { font-size: .85rem; font-weight: 500; margin: 4px 0 2px; }
  .run-card .run-meta { font-size: .72rem; color: #64748b; }
  .run-card .badge {
    display: inline-block; font-size: .65rem; padding: 1px 6px;
    border-radius: 9999px; margin-left: 6px; vertical-align: middle;
  }
  .badge-live    { background: #064e3b; color: #34d399; }
  .badge-ingested { background: #1e3a5f; color: #60a5fa; }

  main { padding: 24px 28px; overflow-y: auto; }

  .stats-row {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
    gap: 12px;
    margin-bottom: 28px;
  }
  .stat-card {
    background: #1a2030;
    border: 1px solid #252d40;
    border-radius: 8px;
    padding: 16px;
  }
  .stat-card .label { font-size: .7rem; color: #64748b; text-transform: uppercase; letter-spacing: .05em; }
  .stat-card .value { font-size: 1.6rem; font-weight: 700; margin-top: 4px; }
  .stat-card .sub   { font-size: .72rem; color: #64748b; margin-top: 2px; }

  .charts-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(460px, 1fr));
    gap: 20px;
    margin-bottom: 28px;
  }
  .chart-card {
    background: #1a2030;
    border: 1px solid #252d40;
    border-radius: 8px;
    padding: 20px;
  }
  .chart-card h3 { font-size: .85rem; font-weight: 600; margin-bottom: 14px; color: #cbd5e1; }
  .chart-card canvas { max-height: 260px; }

  table { width: 100%; border-collapse: collapse; font-size: .78rem; }
  th {
    text-align: left; padding: 8px 12px;
    background: #1a2030; border-bottom: 1px solid #252d40;
    font-size: .7rem; text-transform: uppercase; letter-spacing: .05em; color: #64748b;
  }
  td { padding: 8px 12px; border-bottom: 1px solid #1a2030; }
  tr:hover td { background: #1a2030; }
  .table-wrap {
    background: #12161f;
    border: 1px solid #252d40;
    border-radius: 8px;
    overflow: hidden;
    margin-bottom: 28px;
  }

  .empty { text-align: center; padding: 80px 0; color: #4b5563; font-size: .9rem; }

  .chip {
    display: inline-block; width: 10px; height: 10px;
    border-radius: 2px; margin-right: 5px; vertical-align: middle;
  }

  .section-title {
    font-size: .75rem;
    text-transform: uppercase;
    letter-spacing: .08em;
    color: #64748b;
    margin: 18px 0 10px;
  }

  .artifact-card {
    background: #1a2030;
    border: 1px solid #252d40;
    border-radius: 8px;
    padding: 12px;
    margin-bottom: 10px;
  }

  .artifact-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    padding: 8px 0;
    border-top: 1px solid #252d40;
  }
  .artifact-row:first-child { border-top: none; padding-top: 0; }
  .artifact-meta { color: #94a3b8; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: .72rem; }
  .artifact-sub  { color: #64748b; font-size: .72rem; margin-top: 2px; }

  .btn {
    appearance: none;
    border: 1px solid #2d3748;
    background: #12161f;
    color: #e2e8f0;
    border-radius: 6px;
    padding: 6px 10px;
    font-size: .72rem;
    cursor: pointer;
    transition: background .15s, border-color .15s;
    white-space: nowrap;
  }
  .btn:hover { background: #1a2030; border-color: #3b82f6; }

  /* Modal */
  .modal-backdrop {
    position: fixed;
    inset: 0;
    background: rgba(2, 6, 23, 0.72);
    display: none;
    align-items: center;
    justify-content: center;
    padding: 24px;
    z-index: 9999;
  }
  .modal {
    width: min(1100px, 96vw);
    max-height: min(82vh, 860px);
    background: #0b1020;
    border: 1px solid #252d40;
    border-radius: 10px;
    overflow: hidden;
    box-shadow: 0 24px 70px rgba(0,0,0,0.45);
    display: flex;
    flex-direction: column;
  }
  .modal-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    padding: 12px 14px;
    border-bottom: 1px solid #1e2535;
    background: #0f172a;
  }
  .modal-title {
    font-size: .8rem;
    color: #cbd5e1;
    font-weight: 600;
    font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .modal-body {
    padding: 12px 14px;
    overflow: auto;
  }
  pre.log {
    white-space: pre-wrap;
    word-break: break-word;
    font-size: .75rem;
    line-height: 1.35;
    color: #e2e8f0;
  }
</style>
</head>
<body>
<header>
  <svg width="22" height="22" viewBox="0 0 22 22" fill="none">
    <rect x="2" y="10" width="4" height="10" rx="1" fill="#6366f1"/>
    <rect x="9" y="5" width="4" height="15" rx="1" fill="#818cf8"/>
    <rect x="16" y="1" width="4" height="19" rx="1" fill="#a5b4fc"/>
  </svg>
  <h1>Benchmark Dashboard</h1>
  <span id="db-info"></span>
</header>

<div class="layout">
  <aside>
    <h2>Runs</h2>
    <div id="run-list"></div>
  </aside>

  <main>
    <div id="content">
      <div class="empty">Select one or more runs from the sidebar.</div>
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

let allRuns = [];
let allResults = [];
let selectedRuns = new Set();
let artifactsByRun = {}; // run_id -> artifacts[]

// ── Fetch data ─────────────────────────────────────────────────────────────

async function load() {
  [allRuns, allResults] = await Promise.all([
    fetch('/api/runs').then(r => r.json()),
    fetch('/api/all_results').then(r => r.json())
  ]);
  document.getElementById('db-info').textContent =
    `${allRuns.length} run${allRuns.length !== 1 ? 's' : ''} in DB`;
  renderSidebar();
}

// ── Sidebar ────────────────────────────────────────────────────────────────

function renderSidebar() {
  const el = document.getElementById('run-list');
  if (!allRuns.length) {
    el.innerHTML = '<div style="color:#4b5563;font-size:.8rem">No runs yet.</div>';
    return;
  }
  el.innerHTML = allRuns.map(r => {
    const date = r.created_at ? r.created_at.slice(0,16).replace('T',' ') : '—';
    const badge = r.source === 'ingested'
      ? '<span class="badge badge-ingested">ingested</span>'
      : '<span class="badge badge-live">live</span>';
    const sel = selectedRuns.has(r.run_id) ? 'selected' : '';
    return `
      <div class="run-card ${sel}" onclick="toggleRun('${r.run_id}')">
        <div class="run-id">${r.run_id}</div>
        <div class="run-model">${r.model_name}${badge}</div>
        <div class="run-meta">${date} &nbsp;·&nbsp; ${r.result_count || 0} results</div>
        ${r.notes ? `<div class="run-meta" style="margin-top:3px;font-style:italic">${r.notes}</div>` : ''}
      </div>`;
  }).join('');
}

function toggleRun(runId) {
  if (selectedRuns.has(runId)) selectedRuns.delete(runId);
  else selectedRuns.add(runId);
  renderSidebar();
  renderMain();
}

// ── Main panel ─────────────────────────────────────────────────────────────

async function renderMain() {
  const content = document.getElementById('content');
  if (!selectedRuns.size) {
    content.innerHTML = '<div class="empty">Select one or more runs from the sidebar.</div>';
    return;
  }

  const selIds = [...selectedRuns];
  const runs = allRuns.filter(r => selIds.includes(r.run_id));
  const results = allResults.filter(r => selIds.includes(r.run_id));

  // Fetch artifacts for selected runs (cached)
  await Promise.all(selIds.map(async (rid) => {
    if (artifactsByRun[rid]) return;
    artifactsByRun[rid] = await fetch(`/api/runs/${encodeURIComponent(rid)}/artifacts`).then(r => r.json());
  }));

  content.innerHTML = `
    <div class="stats-row" id="stats-row"></div>
    <div class="charts-grid">
      <div class="chart-card"><h3>Input Tokens by Task</h3><canvas id="chart-input"></canvas></div>
      <div class="chart-card"><h3>Output Tokens by Task</h3><canvas id="chart-output"></canvas></div>
      <div class="chart-card"><h3>Turns by Task</h3><canvas id="chart-turns"></canvas></div>
      <div class="chart-card"><h3>Total Tokens per Run</h3><canvas id="chart-totals"></canvas></div>
    </div>
    <div class="section-title">Artifacts</div>
    <div id="artifacts"></div>
    <div class="table-wrap"><table id="detail-table"></table></div>
  `;

  renderStats(runs, results);
  renderCharts(runs, results);
  renderArtifacts(runs);
  renderTable(results);
}

// ── Stats cards ────────────────────────────────────────────────────────────

function renderStats(runs, results) {
  const totalIn  = results.reduce((s,r) => s + (r.input_tokens||0), 0);
  const totalOut = results.reduce((s,r) => s + (r.output_tokens||0), 0);
  const avgTurns = results.length
    ? (results.reduce((s,r) => s + (r.turns||0), 0) / results.length).toFixed(1)
    : '—';
  const tasks = new Set(results.map(r => r.task_id)).size;

  document.getElementById('stats-row').innerHTML = `
    ${statCard('Runs selected', runs.length, '')}
    ${statCard('Total tasks', tasks, 'unique task IDs')}
    ${statCard('Input tokens', totalIn.toLocaleString(), 'across all runs')}
    ${statCard('Output tokens', totalOut.toLocaleString(), 'across all runs')}
    ${statCard('Avg turns', avgTurns, 'per task result')}
  `;
}

function statCard(label, value, sub) {
  return `
    <div class="stat-card">
      <div class="label">${label}</div>
      <div class="value">${value}</div>
      <div class="sub">${sub}</div>
    </div>`;
}

// ── Charts ─────────────────────────────────────────────────────────────────

let chartInstances = {};

function destroyChart(id) {
  if (chartInstances[id]) { chartInstances[id].destroy(); delete chartInstances[id]; }
}

function makeBarChart(canvasId, labels, datasets, opts = {}) {
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
        y: { ticks: { color: '#64748b', font: { size: 10 } }, grid: { color: '#1e2535' },
             beginAtZero: true, ...opts.yScale }
      },
      ...opts.extra
    }
  });
}

function renderCharts(runs, results) {
  const selIds = runs.map(r => r.run_id);
  const taskIds = [...new Set(results.map(r => r.task_id))].sort();
  const approaches = [...new Set(results.map(r => r.approach))].sort();

  // Group: per (run_id, task_id, approach) → tokens / turns
  const key = (runId, taskId, approach) => `${runId}||${taskId}||${approach}`;
  const lookup = {};
  for (const r of results) {
    lookup[key(r.run_id, r.task_id, r.approach)] = r;
  }

  // Labels: taskId – approach
  const barLabels = [];
  for (const tid of taskIds) for (const ap of approaches) barLabels.push(`${tid} / ${ap}`);

  let colorIdx = 0;
  const inputDS = [], outputDS = [], turnsDS = [];

  for (const [ri, runId] of selIds.entries()) {
    const run = runs.find(r => r.run_id === runId);
    const label = `${run.model_name} · ${run.run_id.slice(-10)}`;
    const color = PALETTE[ri % PALETTE.length];
    const inp = [], out = [], trns = [];
    for (const tid of taskIds) {
      for (const ap of approaches) {
        const r = lookup[key(runId, tid, ap)];
        inp.push(r ? (r.input_tokens || 0) : 0);
        out.push(r ? (r.output_tokens || 0) : 0);
        trns.push(r ? (r.turns || 0) : 0);
      }
    }
    const base = { label, data: inp, backgroundColor: color + 'cc', borderRadius: 3 };
    inputDS.push({ ...base });
    outputDS.push({ ...base, data: out });
    turnsDS.push({ ...base, data: trns });
  }

  makeBarChart('chart-input',  barLabels, inputDS);
  makeBarChart('chart-output', barLabels, outputDS);
  makeBarChart('chart-turns',  barLabels, turnsDS);

  // Totals doughnut / horizontal bar
  const totalLabels = selIds.map(id => {
    const r = runs.find(r => r.run_id === id);
    return r.run_id.slice(-14);
  });
  const totalIn  = selIds.map(id => results.filter(r => r.run_id === id).reduce((s,r) => s+(r.input_tokens||0),0));
  const totalOut = selIds.map(id => results.filter(r => r.run_id === id).reduce((s,r) => s+(r.output_tokens||0),0));

  destroyChart('chart-totals');
  const ctx = document.getElementById('chart-totals').getContext('2d');
  chartInstances['chart-totals'] = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: totalLabels,
      datasets: [
        { label: 'Input',  data: totalIn,  backgroundColor: '#6366f1cc', borderRadius: 3 },
        { label: 'Output', data: totalOut, backgroundColor: '#f59e0bcc', borderRadius: 3 }
      ]
    },
    options: {
      indexAxis: 'y',
      responsive: true, maintainAspectRatio: true,
      plugins: { legend: { labels: { color: '#94a3b8', font: { size: 11 } } } },
      scales: {
        x: { stacked: false, ticks: { color: '#64748b' }, grid: { color: '#1e2535' } },
        y: { ticks: { color: '#64748b', font: { size: 10 } }, grid: { color: '#1e2535' } }
      }
    }
  });
}

// ── Detail table ───────────────────────────────────────────────────────────

function renderTable(results) {
  const sorted = [...results].sort((a,b) => a.task_id.localeCompare(b.task_id) || a.approach.localeCompare(b.approach));
  const runIds = [...new Set(sorted.map(r => r.run_id))];
  const colorMap = Object.fromEntries(runIds.map((id,i) => [id, PALETTE[i % PALETTE.length]]));

  const rows = sorted.map(r => `
    <tr>
      <td><span class="chip" style="background:${colorMap[r.run_id]}"></span>${r.run_id.slice(-18)}</td>
      <td>${r.task_id}</td>
      <td>${r.approach}</td>
      <td>${(r.input_tokens||0).toLocaleString()}</td>
      <td>${(r.output_tokens||0).toLocaleString()}</td>
      <td>${r.turns ?? '—'}</td>
      <td style="max-width:320px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:#64748b">
        ${r.final_response || '—'}
      </td>
    </tr>`).join('');

  document.getElementById('detail-table').innerHTML = `
    <thead><tr>
      <th>Run</th><th>Task</th><th>Approach</th>
      <th>Input Tokens</th><th>Output Tokens</th><th>Turns</th><th>Final Response</th>
    </tr></thead>
    <tbody>${rows}</tbody>`;
}

// ── Artifacts ───────────────────────────────────────────────────────────────

function fmtBytes(n) {
  if (n == null) return '—';
  const units = ['B','KB','MB','GB'];
  let i = 0;
  let x = Number(n);
  while (x >= 1024 && i < units.length - 1) { x /= 1024; i++; }
  const v = (i === 0) ? String(Math.round(x)) : x.toFixed(1);
  return `${v} ${units[i]}`;
}

function renderArtifacts(runs) {
  const el = document.getElementById('artifacts');
  const cards = runs.map(r => {
    const arts = artifactsByRun[r.run_id] || [];
    const items = arts.length ? arts.map(a => {
      const title = `${a.kind} · ${a.filename}`;
      const meta = `${r.run_id} · ${fmtBytes(a.bytes)} · ${a.created_at ? a.created_at.slice(0,19).replace('T',' ') : '—'}`;
      const hasText = (a.content_text != null) && String(a.content_text).length > 0;
      return `
        <div class="artifact-row">
          <div>
            <div class="artifact-meta">${title}</div>
            <div class="artifact-sub">${meta}</div>
          </div>
          <div>
            ${hasText ? `<button class="btn" onclick="openModal('${r.run_id}', ${a.id})">View log</button>` : ''}
          </div>
        </div>
      `;
    }).join('') : `<div class="artifact-sub">No artifacts stored for this run.</div>`;

    return `
      <div class="artifact-card">
        <div class="artifact-meta">${r.run_id}</div>
        <div class="artifact-sub">${r.model_name} · ${r.source}</div>
        <div style="margin-top:8px">${items}</div>
      </div>
    `;
  }).join('');
  el.innerHTML = cards;
}

function openModal(runId, artifactId) {
  const arts = artifactsByRun[runId] || [];
  const art = arts.find(a => a.id === artifactId);
  if (!art) return;
  document.getElementById('modal-title').textContent = `${runId} · ${art.kind} · ${art.filename}`;
  document.getElementById('modal-content').textContent = art.content_text || '';
  const bd = document.getElementById('modal-backdrop');
  bd.style.display = 'flex';
}

function closeModal(evt) {
  // If invoked by clicking backdrop or close button
  const bd = document.getElementById('modal-backdrop');
  bd.style.display = 'none';
  document.getElementById('modal-content').textContent = '';
  document.getElementById('modal-title').textContent = '';
}

document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') closeModal();
});

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
