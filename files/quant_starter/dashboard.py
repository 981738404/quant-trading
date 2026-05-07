"""
量化模拟盘可视化看板生成器

读取 portfolio.json + 实时行情 → 生成自包含的 dashboard.html
用法：python3 dashboard.py
然后在浏览器中打开 dashboard.html
"""
import json
import datetime
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).parent))

BASE       = Path(__file__).parent
PORT_FILE  = BASE / "portfolio.json"
SNAP_FILE  = BASE / "snapshots.json"
OUT_FILE   = BASE / "dashboard.html"
INIT_CASH  = 100_000.0


# ── 数据读取 ─────────────────────────────────────────────────────────────────

def load_portfolio() -> dict:
    if PORT_FILE.exists():
        return json.loads(PORT_FILE.read_text(encoding="utf-8"))
    return {"cash": INIT_CASH, "positions": {}, "history": [], "total_pnl": 0.0}


def fetch_prices(codes: list) -> dict:
    """批量拉取当前价格，失败则用成本价回退"""
    import akshare as ak
    prices = {}
    for code in codes:
        try:
            df = ak.stock_zh_a_hist_min_em(symbol=code, period="1", adjust="qfq")
            if df is not None and not df.empty:
                prices[code] = float(df["收盘"].iloc[-1])
        except Exception:
            pass
    return prices


def load_snapshots() -> list[dict]:
    if SNAP_FILE.exists():
        return json.loads(SNAP_FILE.read_text(encoding="utf-8"))
    return []


def save_snapshot(total: float, cash: float, market: float):
    snaps = load_snapshots()
    today = datetime.date.today().isoformat()
    # 同一天只更新，不追加
    existing = next((s for s in snaps if s["date"] == today), None)
    if existing:
        existing.update({"total": round(total, 2), "cash": round(cash, 2), "market": round(market, 2)})
    else:
        snaps.append({"date": today, "total": round(total, 2),
                      "cash": round(cash, 2), "market": round(market, 2)})
    SNAP_FILE.write_text(json.dumps(snaps, ensure_ascii=False, indent=2), encoding="utf-8")
    return snaps


# ── HTML 生成 ────────────────────────────────────────────────────────────────

def _pnl_color_class(val: float) -> str:
    if val > 0:  return "pos"
    if val < 0:  return "neg"
    return "zero"


def _fmt_pnl(val: float, pct=None) -> str:
    sign = "+" if val >= 0 else ""
    base = f'{sign}{val:,.2f}'
    if pct is not None:
        sign2 = "+" if pct >= 0 else ""
        base += f' ({sign2}{pct:.2f}%)'
    return base


def build_html(pf: dict, prices: dict, snaps: list[dict]) -> str:
    cash     = pf["cash"]
    positions = pf["positions"]
    history  = pf["history"]

    # 计算持仓市值
    rows = []
    total_market = 0.0
    total_unrealized = 0.0
    for code, pos in positions.items():
        cur = prices.get(code, pos["cost"])
        mv  = cur * pos["shares"]
        unr = (cur - pos["cost"]) * pos["shares"]
        unr_pct = (cur / pos["cost"] - 1) * 100 if pos["cost"] else 0
        total_market    += mv
        total_unrealized += unr
        rows.append({
            "code": code, "name": pos["name"],
            "shares": pos["shares"], "cost": pos["cost"],
            "cur": cur, "mv": mv,
            "unr": unr, "unr_pct": unr_pct,
            "buy_time": pos.get("buy_time", "")[:10],
        })
    rows.sort(key=lambda x: -x["unr_pct"])

    total_value  = cash + total_market
    total_pnl    = total_value - INIT_CASH
    total_pnl_pct = total_pnl / INIT_CASH * 100
    realized_pnl = pf.get("total_pnl", 0.0)

    # 今日盈亏（与昨日快照对比）
    today = datetime.date.today().isoformat()
    yesterday_snaps = [s for s in snaps if s["date"] < today]
    if yesterday_snaps:
        prev_total = yesterday_snaps[-1]["total"]
        day_pnl     = total_value - prev_total
        day_pnl_pct = day_pnl / prev_total * 100
    else:
        day_pnl = day_pnl_pct = 0.0

    # ── Chart 数据 ───────────────────────────────────────────────────────────

    # 1. 资产分布饼图
    pie_labels = ["可用资金"] + [r["name"] for r in rows]
    pie_values = [round(cash, 2)] + [round(r["mv"], 2) for r in rows]
    pie_colors = ["#4a9eff"] + [
        "#26a69a" if r["unr"] >= 0 else "#ef5350" for r in rows
    ]

    # 2. 各股浮盈柱状图
    bar_labels = [r["name"] for r in rows]
    bar_values = [round(r["unr"], 2) for r in rows]
    bar_colors = ["#26a69a" if v >= 0 else "#ef5350" for v in bar_values]

    # 3. 历史净值折线图
    snap_dates  = [s["date"] for s in snaps]
    snap_totals = [s["total"] for s in snaps]
    # 加入初始点
    if snaps and snaps[0]["date"] > "2026-05-06":
        snap_dates  = ["2026-05-06"] + snap_dates
        snap_totals = [INIT_CASH] + snap_totals

    # 4. 交易历史（最近20条，倒序）
    hist_rows = list(reversed(history[-20:]))

    # ── 持仓行 HTML ──────────────────────────────────────────────────────────
    holding_rows_html = ""
    for r in rows:
        cls  = _pnl_color_class(r["unr"])
        sign = "+" if r["unr"] >= 0 else ""
        holding_rows_html += f"""
        <tr>
          <td><span class="code-badge">{r['code']}</span></td>
          <td class="stock-name">{r['name']}</td>
          <td>{r['shares']}</td>
          <td>{r['cost']:.2f}</td>
          <td class="cur-price">{r['cur']:.2f}</td>
          <td class="{cls}">{sign}{r['unr']:,.2f}</td>
          <td class="{cls}">{sign}{r['unr_pct']:.2f}%</td>
          <td>{r['mv']:,.2f}</td>
          <td class="date-cell">{r['buy_time']}</td>
        </tr>"""

    # ── 交易记录 HTML ────────────────────────────────────────────────────────
    trade_rows_html = ""
    for h in hist_rows:
        action_class = "action-buy" if h["action"] == "BUY" else "action-sell"
        action_text  = "买入" if h["action"] == "BUY" else "卖出"
        pnl_cell = ""
        if "pnl" in h:
            cls  = _pnl_color_class(h["pnl"])
            sign = "+" if h["pnl"] >= 0 else ""
            pnl_cell = f'<span class="{cls}">{sign}{h["pnl"]:,.2f}</span>'
        trade_rows_html += f"""
        <tr>
          <td class="date-cell">{h['time'][:16]}</td>
          <td><span class="{action_class}">{action_text}</span></td>
          <td>{h['name']}({h['code']})</td>
          <td>{h['price']:.2f}</td>
          <td>{h['shares']}</td>
          <td>{h['amount']:,.2f}</td>
          <td>{pnl_cell}</td>
        </tr>"""

    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    day_pnl_cls  = _pnl_color_class(day_pnl)
    tot_pnl_cls  = _pnl_color_class(total_pnl)
    unr_pnl_cls  = _pnl_color_class(total_unrealized)
    real_pnl_cls = _pnl_color_class(realized_pnl)

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>量化模拟盘 · 看板</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<style>
  :root {{
    --bg:      #0d1117;
    --bg2:     #161b22;
    --bg3:     #21262d;
    --border:  #30363d;
    --text:    #e6edf3;
    --dim:     #8b949e;
    --pos:     #3fb950;
    --neg:     #f85149;
    --zero:    #8b949e;
    --blue:    #58a6ff;
    --yellow:  #d29922;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system, "PingFang SC", "Microsoft YaHei", monospace;
    font-size: 13px;
    line-height: 1.6;
  }}
  .header {{
    background: var(--bg2);
    border-bottom: 1px solid var(--border);
    padding: 14px 24px;
    display: flex;
    align-items: center;
    justify-content: space-between;
  }}
  .header h1 {{ font-size: 18px; font-weight: 600; }}
  .header .sub {{ color: var(--dim); font-size: 12px; margin-top: 2px; }}
  .update-time {{ color: var(--dim); font-size: 11px; }}

  .main {{ max-width: 1400px; margin: 0 auto; padding: 20px 24px; }}

  /* 卡片网格 */
  .cards {{ display: grid; grid-template-columns: repeat(6, 1fr); gap: 12px; margin-bottom: 20px; }}
  .card {{
    background: var(--bg2);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 14px 16px;
  }}
  .card .label {{ color: var(--dim); font-size: 11px; margin-bottom: 4px; }}
  .card .value {{ font-size: 20px; font-weight: 700; font-family: monospace; }}
  .card .sub-value {{ font-size: 11px; color: var(--dim); margin-top: 2px; }}

  /* 图表区 */
  .charts {{ display: grid; grid-template-columns: 1fr 1fr 2fr; gap: 12px; margin-bottom: 20px; }}
  .chart-box {{
    background: var(--bg2);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 16px;
  }}
  .chart-box h3 {{ font-size: 13px; font-weight: 600; margin-bottom: 12px; color: var(--dim); }}
  .chart-box canvas {{ max-height: 220px; }}

  /* 表格区 */
  .section {{
    background: var(--bg2);
    border: 1px solid var(--border);
    border-radius: 8px;
    margin-bottom: 16px;
    overflow: hidden;
  }}
  .section-header {{
    padding: 12px 16px;
    border-bottom: 1px solid var(--border);
    font-weight: 600;
    display: flex;
    align-items: center;
    gap: 8px;
  }}
  .badge {{
    background: var(--bg3);
    color: var(--dim);
    border-radius: 10px;
    padding: 1px 8px;
    font-size: 11px;
    font-weight: normal;
  }}
  table {{ width: 100%; border-collapse: collapse; }}
  thead th {{
    padding: 10px 14px;
    text-align: right;
    color: var(--dim);
    font-weight: 500;
    font-size: 11px;
    border-bottom: 1px solid var(--border);
    white-space: nowrap;
  }}
  thead th:first-child, thead th:nth-child(2) {{ text-align: left; }}
  tbody td {{
    padding: 10px 14px;
    text-align: right;
    border-bottom: 1px solid var(--border);
    font-family: monospace;
    font-size: 12px;
    white-space: nowrap;
  }}
  tbody td:first-child, tbody td:nth-child(2) {{ text-align: left; }}
  tbody tr:last-child td {{ border-bottom: none; }}
  tbody tr:hover {{ background: var(--bg3); }}

  .code-badge {{
    background: var(--bg3);
    color: var(--blue);
    border-radius: 4px;
    padding: 1px 6px;
    font-size: 11px;
  }}
  .stock-name {{ font-weight: 500; }}
  .cur-price {{ color: var(--blue); font-weight: 600; }}
  .date-cell {{ color: var(--dim); font-size: 11px; }}

  .pos  {{ color: var(--pos);    font-weight: 600; }}
  .neg  {{ color: var(--neg);    font-weight: 600; }}
  .zero {{ color: var(--zero); }}

  .action-buy  {{ background: rgba(63,185,80,.15); color: var(--pos); border-radius: 4px; padding: 1px 8px; }}
  .action-sell {{ background: rgba(248,81,73,.15);  color: var(--neg); border-radius: 4px; padding: 1px 8px; }}

  .empty {{ text-align: center; padding: 32px; color: var(--dim); }}

  @media (max-width: 1100px) {{
    .cards {{ grid-template-columns: repeat(3, 1fr); }}
    .charts {{ grid-template-columns: 1fr 1fr; }}
    .charts .chart-box:last-child {{ grid-column: 1 / -1; }}
  }}
</style>
</head>
<body>

<div class="header">
  <div>
    <h1>📊 量化模拟盘看板</h1>
    <div class="sub">策略：多指标加权 + 共识过滤 · 初始资金 100,000 元</div>
  </div>
  <div class="update-time">更新时间：{now_str}</div>
</div>

<div class="main">

  <!-- 账户概览卡片 -->
  <div class="cards">
    <div class="card">
      <div class="label">账户总值</div>
      <div class="value">{total_value:,.2f}</div>
      <div class="sub-value">初始 100,000.00</div>
    </div>
    <div class="card">
      <div class="label">总盈亏</div>
      <div class="value {tot_pnl_cls}">{_fmt_pnl(total_pnl)}</div>
      <div class="sub-value {tot_pnl_cls}">收益率 {'+'if total_pnl_pct>=0 else ''}{total_pnl_pct:.2f}%</div>
    </div>
    <div class="card">
      <div class="label">今日盈亏</div>
      <div class="value {day_pnl_cls}">{_fmt_pnl(day_pnl)}</div>
      <div class="sub-value {day_pnl_cls}">{'+'if day_pnl_pct>=0 else ''}{day_pnl_pct:.2f}%</div>
    </div>
    <div class="card">
      <div class="label">持仓浮盈</div>
      <div class="value {unr_pnl_cls}">{_fmt_pnl(total_unrealized)}</div>
      <div class="sub-value">持仓 {len(positions)} 只</div>
    </div>
    <div class="card">
      <div class="label">已实现盈亏</div>
      <div class="value {real_pnl_cls}">{_fmt_pnl(realized_pnl)}</div>
      <div class="sub-value">历史累计</div>
    </div>
    <div class="card">
      <div class="label">可用资金</div>
      <div class="value" style="color:var(--blue)">{cash:,.2f}</div>
      <div class="sub-value">仓位 {total_market/total_value*100:.1f}%</div>
    </div>
  </div>

  <!-- 图表区 -->
  <div class="charts">
    <div class="chart-box">
      <h3>资产分布</h3>
      <canvas id="pieChart"></canvas>
    </div>
    <div class="chart-box">
      <h3>各股浮盈（元）</h3>
      <canvas id="barChart"></canvas>
    </div>
    <div class="chart-box">
      <h3>历史净值曲线</h3>
      <canvas id="lineChart"></canvas>
    </div>
  </div>

  <!-- 持仓明细 -->
  <div class="section">
    <div class="section-header">
      💼 持仓明细
      <span class="badge">{len(rows)} 只</span>
    </div>
    {"<table><thead><tr><th>代码</th><th>名称</th><th>持仓(股)</th><th>成本价</th><th>现价</th><th>浮盈(元)</th><th>浮盈率</th><th>持仓市值</th><th>买入日期</th></tr></thead><tbody>" + holding_rows_html + "</tbody></table>" if rows else '<div class="empty">当前空仓</div>'}
  </div>

  <!-- 交易记录 -->
  <div class="section">
    <div class="section-header">
      📋 交易记录
      <span class="badge">最近 {min(20, len(history))} 条</span>
    </div>
    {"<table><thead><tr><th>时间</th><th>操作</th><th>标的</th><th>价格</th><th>数量</th><th>金额</th><th>本次盈亏</th></tr></thead><tbody>" + trade_rows_html + "</tbody></table>" if hist_rows else '<div class="empty">暂无交易记录</div>'}
  </div>

</div>

<script>
Chart.defaults.color = '#8b949e';
Chart.defaults.borderColor = '#30363d';
Chart.defaults.font.family = 'monospace';
Chart.defaults.font.size   = 11;

// 1. 资产分布饼图
new Chart(document.getElementById('pieChart'), {{
  type: 'doughnut',
  data: {{
    labels: {json.dumps(pie_labels, ensure_ascii=False)},
    datasets: [{{
      data:            {json.dumps(pie_values)},
      backgroundColor: {json.dumps(pie_colors)},
      borderWidth: 1,
      borderColor: '#161b22',
    }}]
  }},
  options: {{
    responsive: true,
    plugins: {{
      legend: {{
        position: 'right',
        labels: {{ boxWidth: 10, padding: 8, font: {{ size: 10 }} }}
      }},
      tooltip: {{
        callbacks: {{
          label: ctx => ` ${{ctx.label}}: ¥${{ctx.parsed.toLocaleString('zh-CN', {{minimumFractionDigits:2}})}}`
        }}
      }}
    }}
  }}
}});

// 2. 各股浮盈柱状图
new Chart(document.getElementById('barChart'), {{
  type: 'bar',
  data: {{
    labels: {json.dumps(bar_labels, ensure_ascii=False)},
    datasets: [{{
      label: '浮盈(元)',
      data:             {json.dumps(bar_values)},
      backgroundColor:  {json.dumps(bar_colors)},
      borderWidth: 0,
      borderRadius: 3,
    }}]
  }},
  options: {{
    responsive: true,
    plugins: {{ legend: {{ display: false }} }},
    scales: {{
      x: {{ ticks: {{ maxRotation: 45 }} }},
      y: {{
        ticks: {{ callback: v => v.toLocaleString() }},
        grid:  {{ color: '#21262d' }}
      }}
    }}
  }}
}});

// 3. 历史净值折线图
new Chart(document.getElementById('lineChart'), {{
  type: 'line',
  data: {{
    labels: {json.dumps(snap_dates)},
    datasets: [{{
      label: '账户总值',
      data:        {json.dumps(snap_totals)},
      borderColor: '#58a6ff',
      backgroundColor: 'rgba(88,166,255,0.08)',
      borderWidth: 2,
      pointRadius: 3,
      fill: true,
      tension: 0.3,
    }}, {{
      label: '基准 100,000',
      data: Array({len(snap_totals)}).fill(100000),
      borderColor: '#30363d',
      borderWidth: 1,
      borderDash: [4, 4],
      pointRadius: 0,
      fill: false,
    }}]
  }},
  options: {{
    responsive: true,
    plugins: {{
      legend: {{ labels: {{ boxWidth: 12 }} }},
      tooltip: {{
        callbacks: {{
          label: ctx => ` ${{ctx.dataset.label}}: ¥${{ctx.parsed.y.toLocaleString('zh-CN', {{minimumFractionDigits:2}})}}`
        }}
      }}
    }},
    scales: {{
      x: {{ grid: {{ display: false }} }},
      y: {{
        ticks: {{ callback: v => '¥' + (v/10000).toFixed(1) + 'w' }},
        grid:  {{ color: '#21262d' }}
      }}
    }}
  }}
}});
</script>
</body>
</html>"""


# ── 主程序 ───────────────────────────────────────────────────────────────────

def main():
    print("📊 正在生成量化看板...")
    pf = load_portfolio()

    codes = list(pf["positions"].keys())
    if codes:
        print(f"   拉取 {len(codes)} 只持仓实时行情...")
        prices = fetch_prices(codes)
        # 对拉不到价格的用成本价
        for code, pos in pf["positions"].items():
            prices.setdefault(code, pos["cost"])
    else:
        prices = {}

    # 计算总值并保存快照
    cash   = pf["cash"]
    market = sum(prices.get(c, p["cost"]) * p["shares"] for c, p in pf["positions"].items())
    total  = cash + market
    snaps  = save_snapshot(total, cash, market)

    html = build_html(pf, prices, snaps)
    OUT_FILE.write_text(html, encoding="utf-8")

    print(f"   ✅ 看板已生成：{OUT_FILE}")
    print(f"   账户总值：{total:,.2f}  持仓市值：{market:,.2f}  可用资金：{cash:,.2f}")
    print(f"   在浏览器打开：file://{OUT_FILE}")

    # 尝试自动用系统默认浏览器打开
    import subprocess, platform
    try:
        if platform.system() == "Darwin":
            subprocess.run(["open", str(OUT_FILE)], check=False)
        elif platform.system() == "Linux":
            subprocess.run(["xdg-open", str(OUT_FILE)], check=False)
    except Exception:
        pass


if __name__ == "__main__":
    main()
