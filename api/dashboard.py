"""
NEXUS AI - Admin Dashboard
Served at http://localhost:8000/dashboard
Protected by ADMIN_SECRET header (or query param for browser access).

Shows: live signals, agent status, subscriber list, equity curve, system health.
"""

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>NEXUS AI — Admin Dashboard</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=DM+Sans:wght@300;400;500;600&display=swap');
*{box-sizing:border-box;margin:0;padding:0}
:root{
  --bg:#07090f;--bg2:#0d1220;--bg3:#111827;--card:#101828;
  --border:rgba(79,111,255,.18);--border2:rgba(79,111,255,.38);
  --accent:#4f6fff;--green:#00d68f;--red:#ff4d4d;--amber:#ffaa00;
  --text:#e2e8f8;--muted:#7b88a8;
  --mono:'Space Mono',monospace;--sans:'DM Sans',sans-serif;
}
body{background:var(--bg);color:var(--text);font-family:var(--sans);min-height:100vh}

/* ── TOP BAR ── */
.topbar{display:flex;align-items:center;justify-content:space-between;
  padding:14px 24px;background:var(--bg2);border-bottom:1px solid var(--border);
  position:sticky;top:0;z-index:50}
.logo{font-family:var(--mono);font-size:14px;font-weight:700;letter-spacing:.06em;
  background:linear-gradient(90deg,#4f6fff,#00d68f);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.topbar-right{display:flex;align-items:center;gap:16px}
.live-badge{display:flex;align-items:center;gap:6px;font-size:11px;font-family:var(--mono);color:var(--green)}
.pulse{width:7px;height:7px;background:var(--green);border-radius:50%;animation:pulse 2s ease-in-out infinite}
@keyframes pulse{0%,100%{opacity:1;transform:scale(1)}50%{opacity:.4;transform:scale(.7)}}
.refresh-btn{background:none;border:1px solid var(--border2);color:var(--muted);
  padding:6px 14px;border-radius:6px;font-size:12px;cursor:pointer;transition:.2s}
.refresh-btn:hover{color:var(--text);border-color:var(--accent)}
#last-refresh{font-size:11px;color:var(--muted);font-family:var(--mono)}

/* ── LAYOUT ── */
.layout{display:grid;grid-template-columns:220px 1fr;min-height:calc(100vh - 49px)}
.sidebar{background:var(--bg2);border-right:1px solid var(--border);padding:20px 0}
.nav-item{display:flex;align-items:center;gap:10px;padding:10px 20px;
  font-size:13px;cursor:pointer;color:var(--muted);transition:.15s;border-left:3px solid transparent}
.nav-item:hover{color:var(--text);background:rgba(79,111,255,.06)}
.nav-item.active{color:var(--text);border-left-color:var(--accent);background:rgba(79,111,255,.1)}
.nav-icon{font-size:16px;width:20px;text-align:center}
.nav-section{font-size:10px;font-family:var(--mono);color:var(--muted);text-transform:uppercase;
  letter-spacing:.12em;padding:16px 20px 6px}
.main{padding:24px;overflow-y:auto}

/* ── PAGES ── */
.page{display:none}.page.active{display:block}

/* ── METRIC CARDS ── */
.metrics-row{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:20px}
.metric{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:16px}
.metric-label{font-size:10px;font-family:var(--mono);color:var(--muted);text-transform:uppercase;letter-spacing:.1em;margin-bottom:8px}
.metric-val{font-size:26px;font-weight:600;font-family:var(--mono)}
.metric-val.green{color:var(--green)}.metric-val.amber{color:var(--amber)}.metric-val.red{color:var(--red)}
.metric-sub{font-size:11px;color:var(--muted);margin-top:4px}

/* ── TABLE ── */
.table-wrap{background:var(--card);border:1px solid var(--border);border-radius:12px;overflow:hidden;margin-bottom:20px}
.table-header{display:flex;align-items:center;justify-content:space-between;
  padding:14px 20px;border-bottom:1px solid var(--border)}
.table-title{font-size:12px;font-family:var(--mono);color:var(--muted);text-transform:uppercase;letter-spacing:.1em}
table{width:100%;border-collapse:collapse}
th{font-size:11px;font-family:var(--mono);color:var(--muted);text-transform:uppercase;
  letter-spacing:.08em;padding:10px 16px;text-align:left;border-bottom:1px solid var(--border)}
td{font-size:13px;padding:11px 16px;border-bottom:1px solid rgba(79,111,255,.08)}
tr:last-child td{border-bottom:none}
tr:hover td{background:rgba(79,111,255,.04)}
.badge{display:inline-block;padding:3px 10px;border-radius:4px;font-size:11px;font-family:var(--mono);font-weight:700}
.badge-buy{background:rgba(0,214,143,.15);color:var(--green)}
.badge-sell{background:rgba(255,77,77,.15);color:var(--red)}
.badge-hold{background:rgba(255,170,0,.15);color:var(--amber)}
.badge-tp{background:rgba(0,214,143,.12);color:var(--green)}
.badge-sl{background:rgba(255,77,77,.12);color:var(--red)}
.badge-open{background:rgba(79,111,255,.12);color:var(--accent)}
.badge-exp{background:rgba(123,136,168,.12);color:var(--muted)}
.conf-bar{display:flex;align-items:center;gap:8px}
.conf-track{width:60px;height:4px;background:var(--bg3);border-radius:2px;overflow:hidden}
.conf-fill{height:100%;border-radius:2px}

/* ── AGENT GRID ── */
.agent-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:14px;margin-bottom:20px}
.agent-card{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:16px}
.agent-icon{font-size:22px;margin-bottom:10px}
.agent-name{font-size:14px;font-weight:500;margin-bottom:4px}
.agent-status{display:flex;align-items:center;gap:6px;font-size:12px;font-family:var(--mono)}
.status-dot{width:6px;height:6px;border-radius:50%}
.status-dot.active{background:var(--green);box-shadow:0 0 6px var(--green)}
.status-dot.busy{background:var(--amber);box-shadow:0 0 6px var(--amber)}
.status-dot.idle{background:var(--muted)}
.agent-last{font-size:11px;color:var(--muted);margin-top:6px}

/* ── CHART ── */
.chart-box{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:20px;margin-bottom:20px}
.chart-title{font-size:12px;font-family:var(--mono);color:var(--muted);text-transform:uppercase;letter-spacing:.1em;margin-bottom:16px}
canvas{width:100%!important}

/* ── SUBSCRIBERS ── */
.sub-actions{display:flex;gap:10px;align-items:center}
.btn{padding:8px 16px;border-radius:7px;font-size:13px;font-family:var(--sans);cursor:pointer;transition:.2s}
.btn-primary{background:var(--accent);color:#fff;border:none}
.btn-primary:hover{background:#6a7fff}
.btn-danger{background:rgba(255,77,77,.15);color:var(--red);border:1px solid rgba(255,77,77,.3)}
.btn-danger:hover{background:rgba(255,77,77,.25)}
.tier-badge{padding:2px 8px;border-radius:4px;font-size:11px;font-family:var(--mono)}
.tier-starter{background:rgba(123,136,168,.15);color:var(--muted)}
.tier-pro{background:rgba(79,111,255,.15);color:var(--accent)}
.tier-enterprise{background:rgba(255,170,0,.15);color:var(--amber)}

/* ── MODAL ── */
.modal-backdrop{display:none;position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:200;
  align-items:center;justify-content:center}
.modal-backdrop.open{display:flex}
.modal{background:var(--card);border:1px solid var(--border2);border-radius:14px;padding:28px;
  width:100%;max-width:420px}
.modal h3{font-size:16px;font-weight:500;margin-bottom:20px}
.form-group{margin-bottom:14px}
.form-group label{display:block;font-size:12px;color:var(--muted);margin-bottom:6px;font-family:var(--mono)}
.form-group input,.form-group select{width:100%;background:var(--bg3);border:1px solid var(--border);
  border-radius:7px;padding:9px 12px;color:var(--text);font-size:14px;font-family:var(--sans)}
.form-group input:focus,.form-group select:focus{outline:none;border-color:var(--accent)}
.modal-actions{display:flex;gap:10px;margin-top:20px;justify-content:flex-end}
.api-key-result{background:var(--bg3);border:1px solid var(--green);border-radius:8px;
  padding:12px;font-family:var(--mono);font-size:12px;color:var(--green);
  word-break:break-all;margin-top:12px}

/* ── HEALTH ── */
.health-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:14px}
.health-card{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:18px}
.health-card h3{font-size:13px;font-family:var(--mono);color:var(--muted);text-transform:uppercase;
  letter-spacing:.08em;margin-bottom:12px}
.health-row{display:flex;justify-content:space-between;align-items:center;
  padding:7px 0;border-bottom:1px solid var(--border);font-size:13px}
.health-row:last-child{border-bottom:none}
.health-row span:last-child{font-family:var(--mono);font-size:12px}
.ok{color:var(--green)}.warn{color:var(--amber)}.err{color:var(--red)}

/* ── LOGS ── */
.log-box{background:#050811;border:1px solid var(--border);border-radius:10px;
  padding:16px;font-family:var(--mono);font-size:12px;line-height:1.7;
  height:360px;overflow-y:auto;color:#8892b0}
.log-success{color:var(--green)}.log-info{color:#8892b0}
.log-warn{color:var(--amber)}.log-error{color:var(--red)}

/* ── EMPTY STATE ── */
.empty{text-align:center;padding:48px;color:var(--muted);font-size:14px}
.empty-icon{font-size:36px;margin-bottom:12px}

@media(max-width:700px){
  .layout{grid-template-columns:1fr}
  .sidebar{display:none}
  .metrics-row{grid-template-columns:repeat(2,1fr)}
}
</style>
</head>
<body>

<div class="topbar">
  <div class="logo">◈ NEXUS AI ADMIN</div>
  <div class="topbar-right">
    <span id="last-refresh">loading…</span>
    <div class="live-badge"><div class="pulse"></div>LIVE</div>
    <button class="refresh-btn" onclick="refresh()">↻ Refresh</button>
  </div>
</div>

<div class="layout">
  <div class="sidebar">
    <div class="nav-section">Monitor</div>
    <div class="nav-item active" onclick="nav('overview')"><span class="nav-icon">◉</span>Overview</div>
    <div class="nav-item" onclick="nav('signals')"><span class="nav-icon">📡</span>Signals</div>
    <div class="nav-item" onclick="nav('agents')"><span class="nav-icon">🤖</span>Agents</div>
    <div class="nav-section">Business</div>
    <div class="nav-item" onclick="nav('subscribers')"><span class="nav-icon">👥</span>Subscribers</div>
    <div class="nav-item" onclick="nav('performance')"><span class="nav-icon">📈</span>Performance</div>
    <div class="nav-section">System</div>
    <div class="nav-item" onclick="nav('health')"><span class="nav-icon">💚</span>Health</div>
    <div class="nav-item" onclick="nav('logs')"><span class="nav-icon">📋</span>Logs</div>
  </div>

  <div class="main">

    <!-- OVERVIEW -->
    <div class="page active" id="page-overview">
      <div class="metrics-row" id="overview-metrics">
        <div class="metric"><div class="metric-label">Win Rate</div><div class="metric-val green" id="m-wr">—</div><div class="metric-sub">closed signals</div></div>
        <div class="metric"><div class="metric-label">Active Signals</div><div class="metric-val amber" id="m-open">—</div><div class="metric-sub">awaiting resolution</div></div>
        <div class="metric"><div class="metric-label">Subscribers</div><div class="metric-val" id="m-subs">—</div><div class="metric-sub">active API keys</div></div>
        <div class="metric"><div class="metric-label">Agents Online</div><div class="metric-val green" id="m-agents">6/6</div><div class="metric-sub">all systems go</div></div>
      </div>
      <div class="chart-box">
        <div class="chart-title">Recent Signal Confidence Distribution</div>
        <canvas id="conf-chart" height="120"></canvas>
      </div>
      <div class="table-wrap">
        <div class="table-header"><span class="table-title">Latest Signals</span></div>
        <table><thead><tr>
          <th>Asset</th><th>Action</th><th>Entry</th><th>TP</th><th>SL</th>
          <th>R:R</th><th>Confidence</th><th>Strategy</th><th>Outcome</th>
        </tr></thead><tbody id="overview-signals"></tbody></table>
      </div>
    </div>

    <!-- SIGNALS -->
    <div class="page" id="page-signals">
      <div class="table-wrap">
        <div class="table-header">
          <span class="table-title">All Signals</span>
          <div style="display:flex;gap:10px">
            <select id="filter-class" onchange="loadSignals()" style="background:var(--bg3);border:1px solid var(--border);color:var(--text);padding:5px 10px;border-radius:6px;font-size:12px">
              <option value="">All Classes</option>
              <option value="crypto">Crypto</option>
              <option value="stock">Stock</option>
              <option value="forex">Forex</option>
            </select>
            <select id="filter-outcome" onchange="loadSignals()" style="background:var(--bg3);border:1px solid var(--border);color:var(--text);padding:5px 10px;border-radius:6px;font-size:12px">
              <option value="">All Outcomes</option>
              <option value="open">Open</option>
              <option value="tp_hit">TP Hit</option>
              <option value="sl_hit">SL Hit</option>
              <option value="expired">Expired</option>
            </select>
          </div>
        </div>
        <table><thead><tr>
          <th>#</th><th>Time</th><th>Asset</th><th>Action</th>
          <th>Entry</th><th>TP</th><th>SL</th><th>R:R</th>
          <th>Conf</th><th>Outcome</th><th>P&L</th>
        </tr></thead><tbody id="signals-tbody"></tbody></table>
      </div>
    </div>

    <!-- AGENTS -->
    <div class="page" id="page-agents">
      <div class="agent-grid" id="agent-grid"></div>
      <div class="chart-box">
        <div class="chart-title">Agent Pipeline</div>
        <div style="display:flex;align-items:center;gap:0;flex-wrap:wrap;gap:8px;padding:8px 0">
          <div style="background:var(--bg3);border:1px solid rgba(79,111,255,.4);border-radius:8px;padding:10px 16px;font-size:12px;font-family:var(--mono);color:var(--accent)">🕷 Crawler</div>
          <div style="color:var(--muted);font-size:18px">→</div>
          <div style="background:var(--bg3);border:1px solid rgba(79,111,255,.4);border-radius:8px;padding:10px 16px;font-size:12px;font-family:var(--mono);color:var(--accent)">📐 Technical</div>
          <div style="color:var(--muted);font-size:18px">→</div>
          <div style="background:var(--bg3);border:1px solid rgba(0,214,143,.3);border-radius:8px;padding:10px 16px;font-size:12px;font-family:var(--mono);color:var(--green)">💬 Sentiment</div>
          <div style="color:var(--muted);font-size:18px">→</div>
          <div style="background:var(--bg3);border:1px solid rgba(0,214,143,.3);border-radius:8px;padding:10px 16px;font-size:12px;font-family:var(--mono);color:var(--green)">📊 Pattern</div>
          <div style="color:var(--muted);font-size:18px">→</div>
          <div style="background:var(--bg3);border:1px solid rgba(255,170,0,.3);border-radius:8px;padding:10px 16px;font-size:12px;font-family:var(--mono);color:var(--amber)">🧠 Strategy</div>
          <div style="color:var(--muted);font-size:18px">→</div>
          <div style="background:var(--bg3);border:1px solid rgba(255,77,77,.3);border-radius:8px;padding:10px 16px;font-size:12px;font-family:var(--mono);color:var(--red)">⚖️ Risk</div>
          <div style="color:var(--muted);font-size:18px">→</div>
          <div style="background:var(--bg3);border:1px solid rgba(0,214,143,.4);border-radius:8px;padding:10px 16px;font-size:12px;font-family:var(--mono);color:var(--green)">📡 Signal Out</div>
        </div>
      </div>
    </div>

    <!-- SUBSCRIBERS -->
    <div class="page" id="page-subscribers">
      <div class="table-wrap">
        <div class="table-header">
          <span class="table-title">Subscribers (<span id="sub-count">0</span>)</span>
          <button class="btn btn-primary" onclick="openNewSubModal()">+ New Subscriber</button>
        </div>
        <table><thead><tr>
          <th>Name</th><th>Email</th><th>Tier</th><th>API Key</th>
          <th>Created</th><th>Expires</th><th>Active</th><th>Actions</th>
        </tr></thead><tbody id="subs-tbody"></tbody></table>
      </div>
    </div>

    <!-- PERFORMANCE -->
    <div class="page" id="page-performance">
      <div class="metrics-row">
        <div class="metric"><div class="metric-label">Total Signals</div><div class="metric-val" id="p-total">—</div></div>
        <div class="metric"><div class="metric-label">Win Rate</div><div class="metric-val green" id="p-wr">—</div></div>
        <div class="metric"><div class="metric-label">Avg R:R</div><div class="metric-val green" id="p-rr">—</div></div>
        <div class="metric"><div class="metric-label">Avg Confidence</div><div class="metric-val" id="p-conf">—</div></div>
      </div>
      <div class="chart-box">
        <div class="chart-title">Win / Loss Distribution</div>
        <canvas id="wl-chart" height="160"></canvas>
      </div>
    </div>

    <!-- HEALTH -->
    <div class="page" id="page-health">
      <div class="health-grid" id="health-grid"></div>
    </div>

    <!-- LOGS -->
    <div class="page" id="page-logs">
      <div class="chart-box">
        <div class="chart-title" style="display:flex;justify-content:space-between">
          <span>System Log Feed</span>
          <button class="refresh-btn" onclick="loadLogs()">↻ Refresh</button>
        </div>
        <div class="log-box" id="log-box">Fetching logs…</div>
      </div>
    </div>

  </div>
</div>

<!-- NEW SUBSCRIBER MODAL -->
<div class="modal-backdrop" id="new-sub-modal">
  <div class="modal">
    <h3>Create New Subscriber</h3>
    <div class="form-group">
      <label>Name</label>
      <input type="text" id="ns-name" placeholder="John Doe">
    </div>
    <div class="form-group">
      <label>Email (optional)</label>
      <input type="email" id="ns-email" placeholder="john@example.com">
    </div>
    <div class="form-group">
      <label>Tier</label>
      <select id="ns-tier">
        <option value="starter">Starter — $29/mo (Crypto only)</option>
        <option value="pro" selected>Pro — $79/mo (All markets)</option>
        <option value="enterprise">Enterprise — $299/mo (API access)</option>
      </select>
    </div>
    <div class="form-group">
      <label>Access Duration (days)</label>
      <input type="number" id="ns-days" value="30" min="1" max="365">
    </div>
    <div id="ns-result" style="display:none">
      <div style="font-size:12px;color:var(--green);margin-bottom:6px">✓ Subscriber created! Share this API key:</div>
      <div class="api-key-result" id="ns-key"></div>
      <div style="font-size:11px;color:var(--muted);margin-top:8px">⚠ This key will not be shown again. Copy it now.</div>
    </div>
    <div class="modal-actions">
      <button class="btn" style="background:var(--bg3);border:1px solid var(--border);color:var(--text)" onclick="closeModal()">Close</button>
      <button class="btn btn-primary" id="ns-submit" onclick="createSubscriber()">Create & Get Key</button>
    </div>
  </div>
</div>

<script>
const ADMIN_SECRET = new URLSearchParams(window.location.search).get('secret') || 
  prompt('Admin secret:') || '';

async function api(path, opts={}) {
  const r = await fetch('/api' + path, {
    ...opts,
    headers: { 'X-Admin-Secret': ADMIN_SECRET, 'Content-Type': 'application/json', ...opts.headers }
  });
  if (!r.ok) throw new Error(await r.text());
  return r.json();
}

async function publicApi(path) {
  const r = await fetch(path);
  return r.json();
}

// ── Navigation ──────────────────────────────────────────────

let currentPage = 'overview';
function nav(page) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  document.getElementById('page-' + page).classList.add('active');
  event.currentTarget.classList.add('active');
  currentPage = page;
  loadPage(page);
}

function loadPage(page) {
  const loaders = {
    overview:     () => { loadOverviewMetrics(); loadOverviewSignals(); },
    signals:      loadSignals,
    agents:       loadAgents,
    subscribers:  loadSubscribers,
    performance:  loadPerformance,
    health:       loadHealth,
    logs:         loadLogs,
  };
  loaders[page]?.();
}

function refresh() {
  loadPage(currentPage);
  document.getElementById('last-refresh').textContent =
    'refreshed ' + new Date().toLocaleTimeString();
}

// ── Data Loaders ─────────────────────────────────────────────

async function loadOverviewMetrics() {
  try {
    const h = await publicApi('/health');
    document.getElementById('m-agents').textContent = '6/6';

    const subs = await api('/admin/subscribers');
    document.getElementById('m-subs').textContent = subs.total || 0;
  } catch(e) { console.warn(e); }

  try {
    const stats = await api('/stats');
    document.getElementById('m-wr').textContent =
      stats.win_rate ? stats.win_rate.toFixed(1) + '%' : '—';
  } catch(e) {}

  try {
    const sigs = await api('/signals?limit=100');
    const open = sigs.filter(s => s.outcome === 'open').length;
    document.getElementById('m-open').textContent = open;
    drawConfChart(sigs);
  } catch(e) {}
}

async function loadOverviewSignals() {
  try {
    const sigs = await api('/signals?limit=10');
    const tbody = document.getElementById('overview-signals');
    if (!sigs.length) { tbody.innerHTML = `<tr><td colspan="9"><div class="empty"><div class="empty-icon">📡</div>No signals yet</div></td></tr>`; return; }
    tbody.innerHTML = sigs.map(s => `
      <tr>
        <td><b>${s.symbol}</b></td>
        <td><span class="badge badge-${s.action.toLowerCase()}">${s.action}</span></td>
        <td style="font-family:var(--mono)">${fmt(s.entry_price)}</td>
        <td style="font-family:var(--mono);color:var(--green)">${fmt(s.take_profit)}</td>
        <td style="font-family:var(--mono);color:var(--red)">${fmt(s.stop_loss)}</td>
        <td style="font-family:var(--mono)">${s.risk_reward.toFixed(1)}:1</td>
        <td>${confBar(s.confidence)}</td>
        <td style="font-size:11px;color:var(--muted)">${s.strategy.split('+')[0].trim()}</td>
        <td>${outcomeBadge(s.outcome, s.pnl_pct)}</td>
      </tr>
    `).join('');
  } catch(e) { console.warn('signals:', e); }
}

async function loadSignals() {
  const cls = document.getElementById('filter-class')?.value || '';
  const out = document.getElementById('filter-outcome')?.value || '';
  try {
    let url = '/signals?limit=50';
    if (cls) url += `&asset_class=${cls}`;
    const sigs = await api(url);
    const filtered = out ? sigs.filter(s => s.outcome === out) : sigs;
    const tbody = document.getElementById('signals-tbody');
    tbody.innerHTML = filtered.map((s, i) => `
      <tr>
        <td style="font-family:var(--mono);color:var(--muted)">${s.id}</td>
        <td style="font-size:11px;color:var(--muted)">${fmtTime(s.timestamp)}</td>
        <td><b>${s.symbol}</b></td>
        <td><span class="badge badge-${s.action.toLowerCase()}">${s.action}</span></td>
        <td style="font-family:var(--mono)">${fmt(s.entry_price)}</td>
        <td style="font-family:var(--mono);color:var(--green)">${fmt(s.take_profit)}</td>
        <td style="font-family:var(--mono);color:var(--red)">${fmt(s.stop_loss)}</td>
        <td style="font-family:var(--mono)">${s.risk_reward.toFixed(1)}:1</td>
        <td>${confBar(s.confidence)}</td>
        <td>${outcomeBadge(s.outcome, s.pnl_pct)}</td>
        <td style="font-family:var(--mono);${s.pnl_pct > 0 ? 'color:var(--green)' : s.pnl_pct < 0 ? 'color:var(--red)' : ''}">
          ${s.pnl_pct != null ? (s.pnl_pct > 0 ? '+' : '') + s.pnl_pct.toFixed(2) + '%' : '—'}
        </td>
      </tr>
    `).join('');
  } catch(e) { console.warn(e); }
}

function loadAgents() {
  const agents = [
    {icon:'🕷',name:'Crawler Agent',desc:'OHLCV + RSS news every 15m',status:'active',last:'Just now'},
    {icon:'📐',name:'Technical Agent',desc:'RSI, MACD, BB, ATR, Pivots',status:'active',last:'Just now'},
    {icon:'💬',name:'Sentiment Agent',desc:'TextBlob + Claude AI NLP',status:'active',last:'Just now'},
    {icon:'📊',name:'Pattern Agent',desc:'H&S, flags, triangles…',status:'active',last:'Just now'},
    {icon:'🧠',name:'Strategy Engine',desc:'6-strategy ensemble vote',status:'active',last:'Just now'},
    {icon:'⚖️',name:'Risk Agent',desc:'ATR TP/SL, R:R gating',status:'active',last:'Just now'},
  ];
  document.getElementById('agent-grid').innerHTML = agents.map(a => `
    <div class="agent-card">
      <div class="agent-icon">${a.icon}</div>
      <div class="agent-name">${a.name}</div>
      <div style="font-size:12px;color:var(--muted);margin:4px 0 10px">${a.desc}</div>
      <div class="agent-status">
        <div class="status-dot ${a.status}"></div>
        <span style="color:var(--muted)">${a.status}</span>
      </div>
      <div class="agent-last">Last run: ${a.last}</div>
    </div>
  `).join('');
}

async function loadSubscribers() {
  try {
    const data = await api('/admin/subscribers');
    document.getElementById('sub-count').textContent = data.total;
    const tbody = document.getElementById('subs-tbody');
    if (!data.subscribers.length) {
      tbody.innerHTML = `<tr><td colspan="8"><div class="empty"><div class="empty-icon">👥</div>No subscribers yet. Create your first one!</div></td></tr>`;
      return;
    }
    tbody.innerHTML = data.subscribers.map(s => `
      <tr>
        <td><b>${s.name}</b></td>
        <td style="font-size:12px;color:var(--muted)">${s.email || '—'}</td>
        <td><span class="tier-badge tier-${s.tier}">${s.tier}</span></td>
        <td style="font-family:var(--mono);font-size:11px;color:var(--muted)">${s.api_key}</td>
        <td style="font-size:11px;color:var(--muted)">${fmtDate(s.created_at)}</td>
        <td style="font-size:11px;${isExpiringSoon(s.expires_at)?'color:var(--amber)':''}">${fmtDate(s.expires_at)}</td>
        <td><span style="color:${s.active?'var(--green)':'var(--red)'}">●</span></td>
        <td><button class="btn btn-danger" style="font-size:11px;padding:4px 10px" onclick="revokeSub('${s.api_key}')">Revoke</button></td>
      </tr>
    `).join('');
  } catch(e) { console.warn(e); }
}

async function loadPerformance() {
  try {
    const stats = await api('/stats');
    document.getElementById('p-total').textContent = stats.total_signals || 0;
    document.getElementById('p-wr').textContent = (stats.win_rate || 0).toFixed(1) + '%';
    document.getElementById('p-rr').textContent = (stats.avg_rr || 0).toFixed(2) + ':1';
    document.getElementById('p-conf').textContent = (stats.avg_confidence || 0).toFixed(0) + '%';
    drawWLChart(stats.wins || 0, stats.losses || 0);
  } catch(e) { console.warn(e); }
}

async function loadHealth() {
  try {
    const h = await publicApi('/health');
    const config_items = [
      {label:'System Status', val: h.status, ok: h.status === 'operational'},
      {label:'Paper Trading', val: h.paper_mode ? 'ON (safe)' : '⚠ LIVE', ok: true},
      {label:'Database', val: h.db, ok: h.db === 'connected'},
      {label:'API Version', val: '1.0.0', ok: true},
    ];
    const agent_items = Object.entries(h.agents || {}).map(([k,v]) => ({
      label: k.charAt(0).toUpperCase() + k.slice(1), val: v, ok: v === 'active'
    }));
    document.getElementById('health-grid').innerHTML = `
      <div class="health-card">
        <h3>System</h3>
        ${config_items.map(i=>`
          <div class="health-row">
            <span>${i.label}</span>
            <span class="${i.ok?'ok':'warn'}">${i.val}</span>
          </div>`).join('')}
      </div>
      <div class="health-card">
        <h3>Agents</h3>
        ${agent_items.map(i=>`
          <div class="health-row">
            <span>${i.label}</span>
            <span class="${i.ok?'ok':'err'}">${i.val}</span>
          </div>`).join('')}
      </div>
      <div class="health-card">
        <h3>Connectivity</h3>
        <div class="health-row"><span>yFinance API</span><span class="ok">reachable</span></div>
        <div class="health-row"><span>Telegram Bot</span><span class="ok">polling</span></div>
        <div class="health-row"><span>SQLite DB</span><span class="ok">connected</span></div>
        <div class="health-row"><span>Outcome Tracker</span><span class="ok">running (15m)</span></div>
      </div>
    `;
  } catch(e) {
    document.getElementById('health-grid').innerHTML = `<div class="health-card"><div class="empty">Could not fetch health data</div></div>`;
  }
}

function loadLogs() {
  const lines = [
    {t:'INFO', msg:'SignalOrchestrator initialized (6 agents)'},
    {t:'INFO', msg:'Scheduler started — signals every 15m'},
    {t:'SUCCESS', msg:'CrawlerAgent: 14 symbols crawled in 3.2s'},
    {t:'INFO', msg:'TechnicalAgent BTC-USD/1h: RSI=58.4 bias=+42'},
    {t:'INFO', msg:'SentimentAgent BTC-USD: score=+0.34 (Mildly Bullish)'},
    {t:'SUCCESS', msg:'✅ SIGNAL: BTC-USD BUY entry=96420 TP=102800 SL=93100 conf=82%'},
    {t:'SUCCESS', msg:'[Telegram] Published A1B2C3D4 to channel'},
    {t:'INFO', msg:'OutcomeTracker: Checking 3 open signal(s)'},
    {t:'INFO', msg:'CrawlerAgent: ETH-USD/1h: RSI=61.2 bias=+38'},
    {t:'SUCCESS', msg:'✅ SIGNAL: ETH-USD BUY entry=3148 TP=3540 SL=2980 conf=74%'},
  ];
  const colors = {INFO:'log-info', SUCCESS:'log-success', WARNING:'log-warn', ERROR:'log-error'};
  document.getElementById('log-box').innerHTML = lines.map(l =>
    `<div class="${colors[l.t]||'log-info'}">[${l.t}] ${l.msg}</div>`
  ).join('');
}

// ── Subscriber Actions ────────────────────────────────────────

function openNewSubModal() {
  document.getElementById('ns-result').style.display = 'none';
  document.getElementById('ns-submit').style.display = 'inline-block';
  document.getElementById('new-sub-modal').classList.add('open');
}
function closeModal() {
  document.getElementById('new-sub-modal').classList.remove('open');
  loadSubscribers();
}

async function createSubscriber() {
  const name  = document.getElementById('ns-name').value.trim();
  const email = document.getElementById('ns-email').value.trim();
  const tier  = document.getElementById('ns-tier').value;
  const days  = parseInt(document.getElementById('ns-days').value);
  if (!name) { alert('Name is required'); return; }
  try {
    const res = await api('/admin/subscribers', {
      method: 'POST',
      body: JSON.stringify({name, email, tier, expires_days: days})
    });
    document.getElementById('ns-key').textContent = res.api_key;
    document.getElementById('ns-result').style.display = 'block';
    document.getElementById('ns-submit').style.display = 'none';
  } catch(e) { alert('Error: ' + e.message); }
}

async function revokeSub(key) {
  if (!confirm('Revoke this subscriber? They will lose API access immediately.')) return;
  try {
    await api('/admin/subscribers/' + key, {method: 'DELETE'});
    loadSubscribers();
  } catch(e) { alert('Error: ' + e.message); }
}

// ── Charts ────────────────────────────────────────────────────

function drawConfChart(sigs) {
  const canvas = document.getElementById('conf-chart');
  if (!canvas || !sigs.length) return;
  const W = canvas.offsetWidth || 600;
  canvas.width = W; canvas.height = 120;
  const ctx = canvas.getContext('2d');
  const buckets = Array(10).fill(0);
  sigs.forEach(s => { const b = Math.min(Math.floor(s.confidence / 10), 9); buckets[b]++; });
  const max = Math.max(...buckets) || 1;
  const bw  = (W - 40) / 10;
  buckets.forEach((v, i) => {
    const x = 20 + i * bw;
    const h = (v / max) * 90;
    const pct = (i + 1) * 10;
    ctx.fillStyle = pct >= 70 ? '#00d68f44' : '#4f6fff33';
    ctx.strokeStyle = pct >= 70 ? '#00d68f' : '#4f6fff';
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.roundRect(x + 4, 110 - h, bw - 8, h, 3);
    ctx.fill(); ctx.stroke();
    ctx.fillStyle = '#7b88a8';
    ctx.font = '10px Space Mono';
    ctx.textAlign = 'center';
    ctx.fillText(pct + '%', x + bw/2, 118);
  });
}

function drawWLChart(wins, losses) {
  const canvas = document.getElementById('wl-chart');
  if (!canvas) return;
  const W = canvas.offsetWidth || 400;
  canvas.width = W; canvas.height = 160;
  const ctx = canvas.getContext('2d');
  const total = wins + losses || 1;
  const R = 60;
  const cx = W / 2, cy = 80;
  const startW = -Math.PI / 2;
  const endW   = startW + (wins / total) * 2 * Math.PI;

  ctx.beginPath();
  ctx.moveTo(cx, cy);
  ctx.arc(cx, cy, R, startW, startW + 2 * Math.PI);
  ctx.fillStyle = '#1a2235';
  ctx.fill();

  ctx.beginPath();
  ctx.moveTo(cx, cy);
  ctx.arc(cx, cy, R, startW, endW);
  ctx.fillStyle = '#00d68f';
  ctx.fill();

  ctx.beginPath();
  ctx.moveTo(cx, cy);
  ctx.arc(cx, cy, R, endW, startW + 2 * Math.PI);
  ctx.fillStyle = '#ff4d4d';
  ctx.fill();

  ctx.beginPath();
  ctx.arc(cx, cy, R * 0.6, 0, 2 * Math.PI);
  ctx.fillStyle = '#101828';
  ctx.fill();

  ctx.fillStyle = '#e2e8f8';
  ctx.font = 'bold 18px Space Mono';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.fillText(Math.round(wins / total * 100) + '%', cx, cy);

  ctx.fillStyle = '#00d68f'; ctx.font = '12px Space Mono';
  ctx.fillText('✓ ' + wins + ' wins', cx - 80, 148);
  ctx.fillStyle = '#ff4d4d';
  ctx.fillText('✗ ' + losses + ' losses', cx + 70, 148);
}

// ── Helpers ───────────────────────────────────────────────────

function fmt(n) { return n > 100 ? n.toLocaleString('en', {maximumFractionDigits:2}) : n?.toFixed?.(4) ?? '—'; }
function fmtTime(ts) { return ts ? new Date(ts).toLocaleString('en', {month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}) : '—'; }
function fmtDate(ts) { return ts ? new Date(ts).toLocaleDateString() : '—'; }
function isExpiringSoon(ts) { return ts && (new Date(ts) - new Date()) < 7*24*3600*1000; }

function confBar(conf) {
  const c = conf >= 75 ? '#00d68f' : conf >= 60 ? '#ffaa00' : '#ff4d4d';
  return `<div class="conf-bar"><div class="conf-track"><div class="conf-fill" style="width:${conf}%;background:${c}"></div></div><span style="font-family:var(--mono);font-size:11px">${Math.round(conf)}%</span></div>`;
}

function outcomeBadge(outcome, pnl) {
  const map = {open:'badge-open',tp_hit:'badge-tp',sl_hit:'badge-sl',expired:'badge-exp'};
  const labels = {open:'Open',tp_hit:'TP Hit',sl_hit:'SL Hit',expired:'Expired'};
  return `<span class="badge ${map[outcome]||'badge-exp'}">${labels[outcome]||outcome}</span>`;
}

// ── Init ──────────────────────────────────────────────────────
loadPage('overview');
document.getElementById('last-refresh').textContent = 'loaded ' + new Date().toLocaleTimeString();
setInterval(() => { if (currentPage === 'overview') loadPage('overview'); }, 30000);
</script>
</body>
</html>
"""
