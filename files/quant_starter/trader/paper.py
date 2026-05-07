"""
模拟盘：本地记录持仓、交易历史和盈亏，不需要任何券商账户。
数据持久化到 portfolio.json。
"""
import json
import datetime
from pathlib import Path
from typing import Optional
from . import logger as _logger

PORTFOLIO_FILE = Path(__file__).parent.parent / "portfolio.json"

_INIT = {
    "cash":     100000.0,   # 初始资金 10 万
    "positions": {},        # {code: {name, shares, cost, buy_price, buy_time}}
    "history":   [],        # 交易记录
    "total_pnl": 0.0,
}


def _load() -> dict:
    if PORTFOLIO_FILE.exists():
        return json.loads(PORTFOLIO_FILE.read_text(encoding="utf-8"))
    return _INIT.copy()


def _save(data: dict):
    PORTFOLIO_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def status() -> dict:
    return _load()


def buy(code: str, name: str, price: float, shares: int = 100) -> str:
    """模拟买入，返回执行结果描述"""
    pf   = _load()
    cost = price * shares * 1.0003   # 含万3佣金

    if pf["cash"] < cost:
        return f"❌ 资金不足：需要 {cost:.2f}，可用 {pf['cash']:.2f}"

    if code in pf["positions"]:
        pos = pf["positions"][code]
        total_shares = pos["shares"] + shares
        total_cost   = pos["cost"] * pos["shares"] + price * shares
        pos["shares"]    = total_shares
        pos["cost"]      = total_cost / total_shares
        pos["buy_price"] = price
        pos["buy_time"]  = datetime.datetime.now().isoformat()
    else:
        pf["positions"][code] = {
            "name":      name,
            "shares":    shares,
            "cost":      price,
            "buy_price": price,
            "buy_time":  datetime.datetime.now().isoformat(),
        }

    pf["cash"] -= cost
    pf["history"].append({
        "time":   datetime.datetime.now().isoformat(),
        "action": "BUY",
        "code":   code,
        "name":   name,
        "price":  price,
        "shares": shares,
        "amount": cost,
    })
    _save(pf)
    _logger.log_trade("BUY", code, name, price, shares, cost, pf["cash"])
    return f"✅ 模拟买入 {name}({code}) {shares}股 @{price:.2f}  成本 {cost:.2f}  剩余资金 {pf['cash']:.2f}"


def sell(code: str, price: float, shares: Optional[int] = None) -> str:
    """模拟卖出，shares=None 则全部卖出"""
    pf  = _load()
    pos = pf["positions"].get(code)
    if not pos:
        return f"❌ 未持有 {code}"

    sell_shares = shares or pos["shares"]
    if sell_shares > pos["shares"]:
        return f"❌ 持仓不足：持有 {pos['shares']} 股，要卖 {sell_shares} 股"

    revenue = price * sell_shares * (1 - 0.001 - 0.0003)  # 印花税1‰+佣金3/10000
    pnl     = (price - pos["cost"]) * sell_shares
    name    = pos["name"]

    if sell_shares == pos["shares"]:
        del pf["positions"][code]
    else:
        pos["shares"] -= sell_shares

    pf["cash"]      += revenue
    pf["total_pnl"] += pnl
    pf["history"].append({
        "time":   datetime.datetime.now().isoformat(),
        "action": "SELL",
        "code":   code,
        "name":   name,
        "price":  price,
        "shares": sell_shares,
        "amount": revenue,
        "pnl":    pnl,
    })
    _save(pf)
    _logger.log_trade("SELL", code, name, price, sell_shares, revenue, pf["cash"], pnl)
    sign = "盈利" if pnl >= 0 else "亏损"
    return (f"✅ 模拟卖出 {name}({code}) {sell_shares}股 @{price:.2f}  "
            f"{sign} {abs(pnl):.2f}  到账 {revenue:.2f}  总资金 {pf['cash']:.2f}")


def summary() -> str:
    """输出持仓摘要"""
    pf   = _load()
    cash = pf["cash"]
    lines = [
        f"  {'─'*50}",
        f"  📊 模拟账户摘要",
        f"  可用资金: {cash:>12,.2f}",
        f"  累计盈亏: {pf['total_pnl']:>+12,.2f}",
    ]
    if pf["positions"]:
        lines.append(f"  持仓列表:")
        for code, pos in pf["positions"].items():
            lines.append(
                f"    {pos['name']}({code})  {pos['shares']}股"
                f"  成本 {pos['cost']:.2f}"
                f"  买入时间 {pos['buy_time'][:10]}"
            )
    else:
        lines.append("  当前空仓")
    lines.append(f"  {'─'*50}")
    return "\n".join(lines)


def reset():
    """重置模拟账户"""
    _save(_INIT.copy())
    return "模拟账户已重置，初始资金 100,000.00"
