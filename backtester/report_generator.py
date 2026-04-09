"""
NEXUS AI - Backtest Report Generator
Runs backtests and outputs a standalone HTML report with equity curve,
trade log, and performance metrics. Use this to build your public track record.

Usage:  python -m backtester.report_generator
"""

import asyncio
import json
from datetime import datetime
from backtester.backtest_engine import BacktestEngine, BacktestResult
from config import Config


def generate_html_report(results: list[BacktestResult]) -> str:
    """Generate a standalone HTML backtest performance report."""

    cards_html = ""
    for r in results:
        color = "#00d68f" if r.total_return > 0 else "#ff4d4d"
        cards_html += f"""
        <div class="card">
          <div class="card-sym">{r.symbol}</div>
          <div class="card-period">{r.start_date} → {r.end_date}</div>
          <div class="metrics">
            <div class="m"><div class="m-val" style="color:{color}">{r.total_return:+.1f}%</div><div class="m-lbl">Total Return</div></div>
            <div class="m"><div class="m-val">{r.win_rate:.1f}%</div><div class="m-lbl">Win Rate</div></div>
            <div class="m"><div class="m-val">{r.avg_rr:.2f}:1</div><div class="m-lbl">Avg R:R</div></div>
            <div class="m"><div class="m-val">{r.total_trades}</div><div class="m-lbl">Trades</div></div>
            <div class="m"><div class="m-val">{r.sharpe_ratio:.2f}</div><div class="m-lbl">Sharpe</div></div>
            <div class="m"><div class="m-val" style="color:#ff4d4d">{r.max_drawdown:.1f}%</div><div class="m-lbl">Max DD</div></div>
            <div class="m"><div class="m-val">{r.profit_factor:.2f}</div><div class="m-lbl">Profit Factor</div></div>
            <div class="m"><div class="m-val">{r.avg_bars_held:.0f}h</div><div class="m-lbl">Avg Hold</div></div>
          </div>
          <canvas id="eq-{r.symbol.replace('/','').replace('-','')}" height="80" style="width:100%;margin-top:16px"></canvas>
        </div>
        """

    equity_scripts = ""
    for r in results:
        if not r.equity_curve:
            continue
        sym_id = r.symbol.replace("/", "").replace("-", "")
        eq_json = json.dumps(r.equity_curve)
        color = "#00d68f" if r.total_return > 0 else "#ff4d4d"
        equity_scripts += f"""
        (function() {{
          const canvas = document.getElementById('eq-{sym_id}');
          if (!canvas) return;
          const ctx = canvas.getContext('2d');
          const data = {eq_json};
          const W = canvas.offsetWidth || 400;
          canvas.width = W; canvas.height = 80;
          const min = Math.min(...data), max = Math.max(...data);
          const range = max - min || 1;
          ctx.beginPath();
          data.forEach((v, i) => {{
            const x = (i / (data.length - 1)) * W;
            const y = 80 - ((v - min) / range) * 70 - 5;
            i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
          }});
          ctx.strokeStyle = '{color}';
          ctx.lineWidth = 1.5;
          ctx.stroke();
          const grad = ctx.createLinearGradient(0,0,0,80);
          grad.addColorStop(0, '{color}33');
          grad.addColorStop(1, 'transparent');
          ctx.lineTo(W, 80); ctx.lineTo(0, 80); ctx.closePath();
          ctx.fillStyle = grad; ctx.fill();
        }})();
        """

    generated = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>NEXUS AI — Backtest Report</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=DM+Sans:wght@300;400;500&display=swap');
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#06090f;color:#e8edf8;font-family:'DM Sans',sans-serif;padding:32px 24px}}
h1{{font-family:'Space Mono',monospace;font-size:22px;margin-bottom:4px;
  background:linear-gradient(90deg,#4f6fff,#00d68f);-webkit-background-clip:text;-webkit-text-fill-color:transparent}}
.sub{{color:#7b88a8;font-size:13px;margin-bottom:32px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:20px}}
.card{{background:#101828;border:1px solid rgba(79,111,255,.2);border-radius:14px;padding:24px}}
.card-sym{{font-family:'Space Mono',monospace;font-size:18px;font-weight:700;margin-bottom:4px}}
.card-period{{font-size:12px;color:#7b88a8;margin-bottom:18px}}
.metrics{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}}
.m{{text-align:center}}
.m-val{{font-size:17px;font-weight:600;font-family:'Space Mono',monospace}}
.m-lbl{{font-size:10px;color:#7b88a8;margin-top:2px;text-transform:uppercase;letter-spacing:.06em}}
footer{{margin-top:40px;font-size:11px;color:#444;text-align:center}}
</style>
</head>
<body>
<h1>NEXUS AI — Backtest Report</h1>
<div class="sub">Generated {generated} · 180-day walk-forward backtest · 1H timeframe</div>
<div class="grid">{cards_html}</div>
<footer>⚠️ Past backtest performance does not guarantee future results. For educational purposes only.</footer>
<script>
window.addEventListener('load', function() {{
  {equity_scripts}
}});
</script>
</body>
</html>"""


def run():
    engine  = BacktestEngine()
    symbols = Config.CRYPTO_WATCHLIST[:4] + Config.STOCKS_WATCHLIST[:3]
    print(f"Running backtests for: {symbols}")

    results = engine.run_portfolio(symbols, period="180d", interval="1h")
    html    = generate_html_report(results)

    fname = f"backtest_report_{datetime.utcnow().strftime('%Y%m%d_%H%M')}.html"
    with open(fname, "w") as f:
        f.write(html)

    print(f"\n✅ Report saved: {fname}")
    print(f"   Open in browser: file://$(pwd)/{fname}")


if __name__ == "__main__":
    run()
