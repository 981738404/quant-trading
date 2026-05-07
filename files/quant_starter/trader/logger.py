"""
交易日志记录器：每次买入/卖出自动追加到 trading_log.md
"""
import datetime
from pathlib import Path

LOG_FILE = Path(__file__).parent.parent / "trading_log.md"


def _ensure_header():
    if not LOG_FILE.exists():
        LOG_FILE.write_text(
            "# 模拟盘交易日志\n\n"
            "初始资金：100,000.00 元  \n"
            "开始日期：{}\n\n"
            "---\n".format(datetime.date.today().strftime("%Y-%m-%d")),
            encoding="utf-8",
        )


def log_trade(action: str, code: str, name: str, price: float,
              shares: int, amount: float, cash_after: float,
              pnl: float = None, reason: str = ""):
    """记录一笔交易"""
    _ensure_header()
    now  = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    date = datetime.date.today().strftime("%Y-%m-%d")

    if action == "BUY":
        pnl_str = ""
        emoji   = "🟢"
        action_str = "买入"
    else:
        sign    = "盈利" if (pnl or 0) >= 0 else "亏损"
        pnl_str = f"  {sign} **{abs(pnl or 0):,.2f}**"
        emoji   = "🔴"
        action_str = "卖出"

    entry = (
        f"\n### {emoji} {now}  {action_str} {name}（{code}）\n\n"
        f"| 项目 | 数值 |\n"
        f"|------|------|\n"
        f"| 操作 | {action_str} {shares} 股 |\n"
        f"| 价格 | {price:.2f} 元 |\n"
        f"| 金额 | {amount:,.2f} 元 |\n"
    )
    if pnl is not None:
        entry += f"| 本次盈亏 | {'+' if pnl>=0 else ''}{pnl:,.2f} 元 |\n"
    entry += (
        f"| 操作后可用资金 | {cash_after:,.2f} 元 |\n"
    )
    if reason:
        entry += f"| 策略依据 | {reason} |\n"
    entry += "\n"

    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(entry)


def log_daily_report(date_str: str, cash: float, positions: dict,
                     prices: dict, realized_pnl: float):
    """记录每日收盘总结"""
    _ensure_header()

    # 计算浮盈
    unrealized = 0.0
    pos_lines  = []
    for code, pos in positions.items():
        cur_price = prices.get(code, pos["cost"])
        float_pnl = (cur_price - pos["cost"]) * pos["shares"]
        unrealized += float_pnl
        pnl_str = f"+{float_pnl:,.2f}" if float_pnl >= 0 else f"{float_pnl:,.2f}"
        pos_lines.append(
            f"| {pos['name']}({code}) | {pos['shares']}股 | "
            f"成本{pos['cost']:.2f} | 现价{cur_price:.2f} | {pnl_str} |"
        )

    market_value = cash + sum(
        prices.get(c, p["cost"]) * p["shares"]
        for c, p in positions.items()
    )
    total_pnl    = market_value - 100000.0
    total_ret    = total_pnl / 100000.0 * 100

    entry = (
        f"\n---\n\n"
        f"## 📊 {date_str} 每日总结\n\n"
        f"| 指标 | 金额 |\n"
        f"|------|------|\n"
        f"| 可用资金 | {cash:,.2f} 元 |\n"
        f"| 持仓市值 | {market_value - cash:,.2f} 元 |\n"
        f"| 账户总值 | **{market_value:,.2f} 元** |\n"
        f"| 已实现盈亏 | {'+' if realized_pnl>=0 else ''}{realized_pnl:,.2f} 元 |\n"
        f"| 持仓浮盈 | {'+' if unrealized>=0 else ''}{unrealized:,.2f} 元 |\n"
        f"| **总盈亏** | **{'+' if total_pnl>=0 else ''}{total_pnl:,.2f} 元 "
        f"({'+' if total_ret>=0 else ''}{total_ret:.2f}%)** |\n\n"
    )

    if pos_lines:
        entry += (
            "**持仓明细：**\n\n"
            "| 股票 | 持仓 | 成本价 | 现价 | 浮盈 |\n"
            "|------|------|--------|------|------|\n"
        )
        entry += "\n".join(pos_lines) + "\n\n"
    else:
        entry += "当前空仓\n\n"

    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(entry)
