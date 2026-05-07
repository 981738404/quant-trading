"""
量化盯盘主程序

用法：
    python3 monitor.py --code 605099 --name 共创草坪
    python3 monitor.py --code 605099 --name 共创草坪 --interval 180
    python3 monitor.py --code 605099 --name 共创草坪 --mode easytrader  # 真实下单

Ctrl+C 退出。
"""
import sys
import time
import warnings
import argparse
import datetime

warnings.filterwarnings("ignore")

# ── 颜色 ─────────────────────────────────────────────────
R    = "\033[0m"
RED  = "\033[91m"
GRN  = "\033[92m"
YLW  = "\033[93m"
CYN  = "\033[96m"
BOLD = "\033[1m"
DIM  = "\033[2m"


def fetch_data(code: str, days: int = 300):
    """拉取日线数据（新浪前复权，不触发全市场接口）"""
    import pandas as pd
    import akshare as ak

    sh_code = f"sh{code}" if code.startswith(("6", "5")) else f"sz{code}"
    end   = datetime.datetime.now().strftime("%Y%m%d")
    start = (datetime.datetime.now() - datetime.timedelta(days=days)).strftime("%Y%m%d")

    df = ak.stock_zh_a_daily(symbol=sh_code, start_date=start,
                              end_date=end, adjust="qfq")
    df["date"]   = df.index if "date" not in df.columns else df["date"]
    df = df.reset_index(drop=True)
    df.columns   = [c.lower() for c in df.columns]

    # 统一列名
    rename = {"vol": "volume", "成交量": "volume", "成交额": "amount"}
    df = df.rename(columns=rename)

    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
    return df


def fetch_realtime_price(code: str):
    """单股分钟线取最新价（轻量，不加载全市场）"""
    import akshare as ak
    try:
        mdf = ak.stock_zh_a_hist_min_em(symbol=code, period="1", adjust="qfq")
        if mdf is not None and not mdf.empty:
            return float(mdf["收盘"].iloc[-1])
    except Exception:
        pass
    return None


def sig_color(stype) -> str:
    from strategies.base import SignalType
    if stype == SignalType.BUY:  return f"{GRN}{BOLD}"
    if stype == SignalType.SELL: return f"{RED}{BOLD}"
    return DIM


def print_snapshot(code: str, name: str, df, executor):
    from strategies.scanner import scan, stop_loss_price
    from strategies.base import SignalType

    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    price_rt = fetch_realtime_price(code)
    price_kl = float(df["close"].iloc[-1])
    price    = price_rt if price_rt else price_kl
    src      = "实时" if price_rt else "日线"
    prev     = float(df["close"].iloc[-2])
    pct      = (price / prev - 1) * 100
    pct_str  = f"{RED}{BOLD}{pct:+.2f}%{R}" if pct > 0 else f"{GRN}{BOLD}{pct:+.2f}%{R}"

    print(f"\n{'━'*60}")
    print(f"  {BOLD}{name}（{code}）{R}  {now}")
    print(f"  当前价 {BOLD}{price:.2f}{R}  {pct_str}  （{src}）")
    print(f"{'━'*60}")

    # ── 运行所有策略 ──────────────────────────────────────
    final, score, signals = scan(df)

    # 打印各策略明细
    print(f"  {'策略':<8} {'信号':<6} {'强度':>4}  说明")
    print(f"  {'─'*54}")
    for sig in signals:
        col  = sig_color(sig.type)
        typ  = sig.type.value
        print(f"  {sig.strategy:<8} {col}{typ:<6}{R}  {sig.strength:>3.0f}   {sig.reason}")

    # ── 综合结论 ─────────────────────────────────────────
    print(f"  {'─'*54}")
    fcol = sig_color(final)
    print(f"  综合得分 {score:+.1f}   最终信号: {fcol}{BOLD}{final.value}{R}")

    sl = stop_loss_price(df)
    print(f"  建议止损 {YLW}{sl:.2f}{R}  （当前价 - 2×ATR7）")

    # ── 自动执行 ─────────────────────────────────────────
    if final == SignalType.BUY:
        result = executor.buy(code, name, price)
        print(f"\n  {GRN}▶ 触发买入{R}  {result}")
    elif final == SignalType.SELL:
        result = executor.sell(code, name, price)
        print(f"\n  {RED}▶ 触发卖出{R}  {result}")

    # ── 持仓摘要 ─────────────────────────────────────────
    print()
    print(executor.summary())
    print(f"{'━'*60}")


def main():
    parser = argparse.ArgumentParser(description="量化盯盘系统")
    parser.add_argument("--code",     required=True,  help="股票代码，如 605099")
    parser.add_argument("--name",     default="",     help="股票名称（显示用）")
    parser.add_argument("--interval", type=int, default=180, help="刷新间隔秒数（默认180）")
    parser.add_argument("--mode",     default="paper",
                        choices=["paper", "easytrader"],
                        help="交易模式：paper=模拟盘  easytrader=真实下单")
    args = parser.parse_args()

    from trader.executor import Executor
    executor = Executor(mode=args.mode)

    print(f"\n  {BOLD}量化盯盘启动{R}")
    print(f"  标的: {args.name or args.code}（{args.code}）")
    print(f"  模式: {'📄 模拟盘' if args.mode == 'paper' else '💰 真实下单'}")
    print(f"  刷新: 每 {args.interval}s  |  Ctrl+C 退出\n")

    while True:
        try:
            df = fetch_data(args.code)
            print_snapshot(args.code, args.name or args.code, df, executor)
        except KeyboardInterrupt:
            print(f"\n  盯盘已停止。{executor.summary()}")
            sys.exit(0)
        except Exception as e:
            print(f"  {RED}数据获取失败: {e}{R}")

        try:
            time.sleep(args.interval)
        except KeyboardInterrupt:
            print(f"\n  盯盘已停止。{executor.summary()}")
            sys.exit(0)


if __name__ == "__main__":
    main()
