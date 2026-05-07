"""
共创草坪（605099）实盘盯盘脚本

运行方式：
    python3 monitor_605099.py          # 默认每 3 分钟刷新
    python3 monitor_605099.py 60       # 自定义间隔（秒）

Ctrl+C 退出。
"""
import sys
import time
import warnings
import datetime

warnings.filterwarnings("ignore")

CODE    = "605099"
SH_CODE = f"sh{CODE}"
NAME    = "共创草坪"

RSI_OB   = 80.0
RSI_OS   = 30.0
PCT_WARN = 3.0

R = "\033[0m"
RED  = "\033[91m"
GRN  = "\033[92m"
YLW  = "\033[93m"
CYN  = "\033[96m"
BOLD = "\033[1m"


def snapshot():
    import pandas as pd
    import numpy as np
    import akshare as ak

    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n{'━'*56}")
    print(f"  {BOLD}{NAME}（{CODE}.SH）{R}   {now}")
    print(f"{'━'*56}")

    # ── 日线（近 60 天，用于 MA20 / RSI14）─────────────────
    end   = datetime.datetime.now().strftime("%Y%m%d")
    start = (datetime.datetime.now() - datetime.timedelta(days=90)).strftime("%Y%m%d")
    try:
        kl = ak.stock_zh_a_daily(symbol=SH_CODE, start_date=start,
                                  end_date=end, adjust="qfq")
        kl["date"] = pd.to_datetime(kl["date"])
        kl = kl.sort_values("date").reset_index(drop=True)
    except Exception as e:
        print(f"  {RED}日线获取失败: {e}{R}")
        return

    c = kl["close"]
    ma20 = float(c.rolling(20).mean().iloc[-1])

    delta = c.diff()
    gain  = delta.where(delta > 0, 0.0).rolling(14).mean()
    loss  = (-delta.where(delta < 0, 0.0)).rolling(14).mean()
    rs    = gain / loss.replace(0, float("nan"))
    rsi_s = 100 - 100 / (1 + rs)
    rsi_s[(loss == 0) & (gain > 0)] = 100.0
    rsi14 = float(rsi_s.iloc[-1])

    prev_close = float(c.iloc[-2])

    # ── 实时分钟线（单股，轻量）─────────────────────────────
    price = high = low = vol = amt = None
    src = "日线"
    try:
        mdf = ak.stock_zh_a_hist_min_em(symbol=CODE, period="1", adjust="qfq")
        if mdf is not None and not mdf.empty:
            price = float(mdf["收盘"].iloc[-1])
            high  = float(mdf["最高"].max())
            low   = float(mdf["最低"].min())
            vol   = float(mdf["成交量"].sum())
            amt   = float(mdf["成交额"].sum())
            src   = "实时"
    except Exception:
        pass

    if price is None:
        price = float(c.iloc[-1])
        high  = float(kl["high"].iloc[-1])
        low   = float(kl["low"].iloc[-1])
        vol   = float(kl["volume"].iloc[-1])
        amt   = float(kl["amount"].iloc[-1]) if "amount" in kl.columns else 0.0

    pct = (price / prev_close - 1) * 100

    # ── 输出 ────────────────────────────────────────────────
    pct_str = f"{RED}{BOLD}{pct:+.2f}%{R}" if pct > 0 else f"{GRN}{BOLD}{pct:+.2f}%{R}"
    rsi_str = (f"{RED}{BOLD}{rsi14:.2f}{R}" if rsi14 >= RSI_OB
               else f"{GRN}{BOLD}{rsi14:.2f}{R}" if rsi14 <= RSI_OS
               else f"{CYN}{rsi14:.2f}{R}")

    print(f"  当前价  {BOLD}{price:.2f}{R}  {pct_str}   （{src}）")
    print(f"  今日    开 {kl['open'].iloc[-1]:.2f}  高 {high:.2f}  低 {low:.2f}")
    print(f"  成交量  {vol/1e4:.1f} 万手  成交额 {amt/1e8:.2f} 亿")
    print(f"  MA20    {ma20:.2f}   RSI14 {rsi_str}")

    alerts = []
    if rsi14 >= RSI_OB:
        alerts.append(f"{RED}⚠ RSI 超买 {rsi14:.2f} ≥ {RSI_OB}（注意回调）{R}")
    elif rsi14 <= RSI_OS:
        alerts.append(f"{GRN}⚠ RSI 超卖 {rsi14:.2f} ≤ {RSI_OS}（关注反弹）{R}")

    if price > ma20:
        alerts.append(f"{RED}▲ 价格站上 MA20 +{(price/ma20-1)*100:.1f}%{R}")
    else:
        alerts.append(f"{GRN}▼ 价格跌破 MA20 -{(ma20/price-1)*100:.1f}%{R}")

    if abs(pct) >= PCT_WARN:
        d = "上涨" if pct > 0 else "下跌"
        alerts.append(f"{YLW}⚡ 今日{d}超 {PCT_WARN}%  当前 {pct:+.2f}%{R}")

    if alerts:
        print(f"\n  {'─'*48}")
        for a in alerts:
            print(f"  {a}")
    print(f"{'━'*56}")


if __name__ == "__main__":
    interval = int(sys.argv[1]) if len(sys.argv) > 1 else 180
    print(f"  盯盘启动  {NAME}（{CODE}）  每 {interval}s 刷新  Ctrl+C 退出")
    while True:
        snapshot()
        try:
            time.sleep(interval)
        except KeyboardInterrupt:
            print("\n  盯盘已停止。")
            sys.exit(0)
