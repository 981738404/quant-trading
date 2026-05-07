"""
每日14:30盘前总结报告

对 watchlist.json 中所有标的运行策略扫描 + 共识过滤，
输出今日操作建议（买入/卖出/观望），适合在收盘前30分钟执行。

用法：
    python3 daily_report.py                  # 使用默认 watchlist.json
    python3 daily_report.py --watch my.json  # 指定自定义股票池

watchlist.json 格式：
    [
      {"code": "605099", "name": "共创草坪"},
      {"code": "300274", "name": "阳光电源"}
    ]
"""
import sys, warnings, argparse, datetime, json
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).parent))

R    = "\033[0m"
RED  = "\033[91m"
GRN  = "\033[92m"
YLW  = "\033[93m"
CYN  = "\033[96m"
BOLD = "\033[1m"
DIM  = "\033[2m"
MAG  = "\033[95m"

WATCHLIST_DEFAULT = Path(__file__).parent / "watchlist.json"


def fetch_df(code: str, days: int = 300):
    import akshare as ak
    import pandas as pd, datetime as dt

    sh_code = f"sh{code}" if code.startswith(("6", "5")) else f"sz{code}"
    end   = dt.datetime.now().strftime("%Y%m%d")
    start = (dt.datetime.now() - dt.timedelta(days=days)).strftime("%Y%m%d")
    df = ak.stock_zh_a_daily(symbol=sh_code, start_date=start,
                             end_date=end, adjust="qfq")
    df["date"] = df.index
    df = df.reset_index(drop=True)
    df.columns = [c.lower() for c in df.columns]
    df = df.rename(columns={"vol": "volume"})
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
    return df


def fetch_rt_price(code: str):
    import akshare as ak
    try:
        mdf = ak.stock_zh_a_hist_min_em(symbol=code, period="1", adjust="qfq")
        if mdf is not None and not mdf.empty:
            return float(mdf["收盘"].iloc[-1])
    except Exception:
        pass
    return None


def analyze(code: str, name: str) -> dict:
    from strategies.scanner import scan, stop_loss_price
    from strategies.consensus import consensus_filter, consensus_strength
    from strategies.indicators import adx as calc_adx

    df = fetch_df(code)
    price_rt = fetch_rt_price(code)
    price    = price_rt if price_rt else float(df["close"].iloc[-1])
    prev     = float(df["close"].iloc[-2])
    pct      = (price / prev - 1) * 100

    # 日内振幅
    today_high = float(df["high"].iloc[-1])
    today_low  = float(df["low"].iloc[-1])
    amplitude  = (today_high - today_low) / prev * 100

    # 策略扫描
    final_weighted, score, signals = scan(df)

    # 共识过滤（叠加判断）
    consensus_type, agree_count, consensus_reason = consensus_filter(signals)
    confidence = consensus_strength(agree_count)

    # 是否与加权结论一致（双重确认）
    double_confirmed = (final_weighted == consensus_type
                        and final_weighted.value != "观望")

    # ADX
    _, _, adx_s = calc_adx(df["high"], df["low"], df["close"], 14)
    adx_val = float(adx_s.dropna().iloc[-1]) if not adx_s.dropna().empty else 20

    # 止损价
    sl = float(stop_loss_price(df))

    return {
        "code":              code,
        "name":              name,
        "price":             price,
        "pct":               pct,
        "amplitude":         amplitude,
        "weighted_signal":   final_weighted.value,
        "weighted_score":    score,
        "consensus_signal":  consensus_type.value,
        "agree_count":       agree_count,
        "confidence":        confidence,
        "double_confirmed":  double_confirmed,
        "consensus_reason":  consensus_reason,
        "stop_loss":         sl,
        "adx":               adx_val,
        "signals":           signals,
    }


def sig_color(val: str) -> str:
    if val == "买入": return f"{GRN}{BOLD}"
    if val == "卖出": return f"{RED}{BOLD}"
    return DIM


def print_report(results: list, executor):
    from strategies.base import SignalType
    from trader.executor import Executor

    now  = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    date = datetime.datetime.now().strftime("%Y年%m月%d日")

    print(f"\n{'═'*68}")
    print(f"  {BOLD}{MAG}每日量化盯盘报告{R}  {date}  {DIM}生成时间 {now}{R}")
    print(f"{'═'*68}")

    # ── 分档输出 ─────────────────────────────────────────
    double = [r for r in results if r["double_confirmed"]]
    single = [r for r in results
              if not r["double_confirmed"]
              and r["consensus_signal"] != "观望"]
    hold   = [r for r in results
              if r["consensus_signal"] == "观望"
              and r["weighted_signal"] == "观望"]

    # 双重确认信号
    if double:
        print(f"\n  {BOLD}★ 双重确认信号（加权+共识均同向）{R}")
        print(f"  {'─'*64}")
        for r in sorted(double,
                        key=lambda x: -x["weighted_score"] if x["weighted_signal"] == "买入"
                                      else x["weighted_score"]):
            _print_stock_row(r, executor, strong=True)

    # 单侧信号（仅共识方向，加权不一致）
    if single:
        print(f"\n  {BOLD}◇ 共识信号（仅供参考，加权结论不一致）{R}")
        print(f"  {'─'*64}")
        for r in single:
            _print_stock_row(r, executor, strong=False)

    # 观望
    if hold:
        hold_names = "、".join(f"{r['name']}" for r in hold)
        print(f"\n  {DIM}观望 ({len(hold)}只): {hold_names}{R}")

    # ── 持仓浮盈 + 完整盈亏摘要 ──────────────────────────
    print(f"\n{'─'*68}")
    _print_pnl_summary(results, executor)
    print(f"{'═'*68}\n")


def _print_stock_row(r: dict, executor, strong: bool):
    from strategies.base import SignalType
    sig   = r["consensus_signal"]
    sc    = sig_color(sig)
    price = r["price"]
    pct_c = RED if r["pct"] > 0 else GRN
    conf_c = (GRN if r["confidence"] in ("强", "极强")
              else YLW if r["confidence"] == "中" else DIM)

    marker = f"{BOLD}★{R}" if strong else "◇"

    print(f"\n  {marker} {BOLD}{r['name']}（{r['code']}）{R}  "
          f"现价 {price:.2f}  {pct_c}{r['pct']:+.2f}%{R}  "
          f"振幅 {r['amplitude']:.1f}%  ADX={r['adx']:.0f}")
    print(f"    加权信号: {sig_color(r['weighted_signal'])}{r['weighted_signal']}{R}"
          f"({r['weighted_score']:+.1f})  "
          f"共识信号: {sc}{sig}{R}  "
          f"可信度: {conf_c}{r['confidence']}({r['agree_count']}项同向){R}")
    print(f"    {DIM}{r['consensus_reason']}{R}")

    # 各策略明细（只显示非观望的）
    non_hold = [s for s in r["signals"] if s.type.value != "观望"]
    if non_hold:
        parts = []
        for s in non_hold:
            c = GRN if s.type.value == "买入" else RED
            parts.append(f"{s.strategy}:{c}{s.type.value}{R}({s.strength:.0f})")
        print(f"    指标: {'  '.join(parts)}")

    print(f"    止损价: {YLW}{r['stop_loss']:.2f}{R}"
          f"  (跌破此价位强制离场)")

    # 自动执行模拟盘
    if sig == "买入":
        result = executor.buy(r["code"], r["name"], price)
        print(f"    {GRN}▶ 模拟买入{R}: {result}")
    elif sig == "卖出":
        result = executor.sell(r["code"], r["name"], price)
        print(f"    {RED}▶ 模拟卖出{R}: {result}")


def _print_pnl_summary(results: list, executor):
    """打印完整盈亏摘要，并写入日志"""
    from trader import paper as _paper
    from trader.logger import log_daily_report

    pf    = _paper.status()
    cash  = pf["cash"]
    positions = pf["positions"]

    # 从本次扫描结果里取现价
    prices = {r["code"]: r["price"] for r in results}

    unrealized    = 0.0
    pos_lines     = []
    holding_value = 0.0
    for code, pos in positions.items():
        cur  = prices.get(code, pos["cost"])
        fp   = (cur - pos["cost"]) * pos["shares"]
        unrealized    += fp
        holding_value += cur * pos["shares"]
        fp_str  = f"{GRN}+{fp:,.2f}{R}" if fp >= 0 else f"{RED}{fp:,.2f}{R}"
        pct_str = f"{(cur/pos['cost']-1)*100:+.1f}%"
        pos_lines.append(
            f"    {pos['name']}({code})  {pos['shares']}股  "
            f"成本{pos['cost']:.2f} → 现价{cur:.2f}({pct_str})  浮盈{fp_str}"
        )

    market_value = cash + holding_value
    total_pnl    = market_value - 100_000.0
    total_ret    = total_pnl / 100_000.0 * 100
    realized     = pf.get("total_pnl", 0.0)

    pnl_c   = GRN if total_pnl >= 0 else RED
    sign    = "+" if total_pnl >= 0 else ""

    print(f"\n  {BOLD}💰 账户盈亏总览{R}")
    print(f"  {'─'*50}")
    print(f"  初始资金      100,000.00")
    print(f"  可用资金      {cash:>12,.2f}")
    print(f"  持仓市值      {holding_value:>12,.2f}")
    print(f"  账户总值      {BOLD}{market_value:>12,.2f}{R}")
    print(f"  {'─'*50}")
    print(f"  已实现盈亏    {GRN if realized>=0 else RED}{realized:>+12,.2f}{R}")
    print(f"  持仓浮盈      {GRN if unrealized>=0 else RED}{unrealized:>+12,.2f}{R}")
    print(f"  总盈亏        {pnl_c}{BOLD}{sign}{total_pnl:>11,.2f}  ({sign}{total_ret:.2f}%){R}")

    if pos_lines:
        print(f"\n  {BOLD}持仓明细:{R}")
        for l in pos_lines:
            print(l)
    else:
        print(f"\n  {DIM}当前空仓{R}")

    # 写入日志
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    log_daily_report(today, cash, positions, prices, realized)
    print(f"\n  {DIM}📝 已写入 trading_log.md{R}")


def ensure_watchlist(path: Path):
    """如果 watchlist.json 不存在，从 batch_result.json 生成"""
    if path.exists():
        return

    batch = Path(__file__).parent / "batch_result.json"
    if batch.exists():
        data = json.loads(batch.read_text(encoding="utf-8"))
        wl   = [{"code": d["code"], "name": d["name"]} for d in data]
        path.write_text(json.dumps(wl, ensure_ascii=False, indent=2),
                        encoding="utf-8")
        print(f"  已从 batch_result.json 生成 watchlist.json（{len(wl)} 只标的）")
    else:
        # 默认只放一只演示标的
        default = [{"code": "605099", "name": "共创草坪"}]
        path.write_text(json.dumps(default, ensure_ascii=False, indent=2),
                        encoding="utf-8")
        print(f"  已创建默认 watchlist.json，请手动编辑添加标的")


def main():
    parser = argparse.ArgumentParser(description="每日量化盯盘报告（建议14:30运行）")
    parser.add_argument("--watch", default=str(WATCHLIST_DEFAULT),
                        help="股票池 JSON 文件路径")
    parser.add_argument("--mode",  default="paper",
                        choices=["paper", "easytrader"],
                        help="交易模式")
    parser.add_argument("--days",  type=int, default=300,
                        help="拉取历史数据天数")
    args = parser.parse_args()

    watch_path = Path(args.watch)
    ensure_watchlist(watch_path)

    watchlist = json.loads(watch_path.read_text(encoding="utf-8"))
    total = len(watchlist)

    from trader.executor import Executor
    executor = Executor(mode=args.mode)

    print(f"\n  {BOLD}正在扫描 {total} 只标的...{R}  "
          f"（建议每日14:30运行，收盘前30分钟操作）\n")

    results = []
    import time
    for i, item in enumerate(watchlist):
        code = item["code"]
        name = item.get("name", code)
        print(f"  [{i+1:>2}/{total}] {name}（{code}）...", end="\r", flush=True)
        try:
            r = analyze(code, name)
            results.append(r)
        except Exception as e:
            print(f"  [{i+1:>2}/{total}] {name}（{code}）  {RED}失败: {e}{R}")
        if i < total - 1:
            time.sleep(1.0)

    print(" " * 60, end="\r")  # 清除进度行
    print_report(results, executor)


if __name__ == "__main__":
    main()
