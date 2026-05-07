"""
批量策略适配分析
对 CSV 中所有标的跑近1年历史数据，输出：
  - 当前综合信号
  - 趋势 / 震荡 / 量价 属性
  - 各策略胜率统计（历史信号命中率）
  - 推荐权重配置

用法：
    python3 batch_scan.py [--csv ../Sheet_20260507.csv] [--days 250]
"""
import sys, time, warnings, argparse, datetime, json
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).parent))

import pandas as pd
import numpy as np

# ── 颜色 ─────────────────────────────────────────────────
R    = "\033[0m"
RED  = "\033[91m"
GRN  = "\033[92m"
YLW  = "\033[93m"
CYN  = "\033[96m"
BOLD = "\033[1m"
DIM  = "\033[2m"


def fetch(code: str, days: int = 250) -> pd.DataFrame:
    import akshare as ak
    sh_code = f"sh{code}" if code.startswith(("6", "5")) else f"sz{code}"
    end   = datetime.datetime.now().strftime("%Y%m%d")
    start = (datetime.datetime.now() - datetime.timedelta(days=days)).strftime("%Y%m%d")
    df = ak.stock_zh_a_daily(symbol=sh_code, start_date=start, end_date=end, adjust="qfq")
    df["date"] = df.index
    df = df.reset_index(drop=True)
    df.columns = [c.lower() for c in df.columns]
    df = df.rename(columns={"vol": "volume"})
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = df[col].astype(float)
    return df


def classify_stock(df: pd.DataFrame) -> dict:
    """
    根据历史数据特征给股票分类：
      trend_score    (0-100)  高=趋势股
      oscillate_score(0-100)  高=震荡股
      volume_score   (0-100)  高=有主力量能
      volatility_pct          日均振幅%
      adx_val                 当前ADX
    """
    from strategies.indicators import adx, atr, turnover_anomaly

    # ADX 趋势强度
    plus_di, minus_di, adx_s = adx(df["high"], df["low"], df["close"], 14)
    adx_val = float(adx_s.dropna().iloc[-1]) if not adx_s.dropna().empty else 20.0

    # 日均振幅
    daily_range = (df["high"] - df["low"]) / df["close"]
    volatility  = float(daily_range.mean() * 100)

    # 量能异动频率（近60日中异动天数比例）
    vol_ratio = turnover_anomaly(df["volume"], 20)
    anomaly_freq = float((vol_ratio > 2.0).tail(60).mean())  # 2倍以上算异动

    # 价格与60日均线的关系（判断是否有趋势）
    ma60 = df["close"].rolling(60).mean()
    above_pct = float((df["close"] > ma60).tail(60).mean())  # 近60日站上均线比例

    # 均线粘合度（标准差越小越震荡）
    ma5  = df["close"].rolling(5).mean()
    ma20 = df["close"].rolling(20).mean()
    ma_spread = float(((ma5 - ma20).abs() / df["close"]).tail(60).mean() * 100)

    # 趋势得分：ADX高 + 明显站上或站下60均线
    trend_score = min(100, adx_val * 1.5 + abs(above_pct - 0.5) * 100)

    # 震荡得分：ADX低 + 均线粘合
    oscillate_score = max(0, 100 - adx_val * 1.5 - ma_spread * 5)

    # 量能得分：异动频率
    volume_score = anomaly_freq * 100

    return {
        "adx":            round(adx_val, 1),
        "volatility":     round(volatility, 2),
        "anomaly_freq":   round(anomaly_freq, 2),
        "trend_score":    round(trend_score, 1),
        "oscillate_score":round(oscillate_score, 1),
        "volume_score":   round(volume_score, 1),
        "above_60ma_pct": round(above_pct * 100, 1),
    }


def backtest_signals(df: pd.DataFrame, lookahead: int = 5) -> dict:
    """
    对每个策略做历史信号回测：
    每次买入信号后 lookahead 天的收益率，计算胜率和平均收益。
    返回 {strategy_name: {win_rate, avg_return, signal_count}}
    """
    from strategies.scanner import (
        signal_kdj, signal_macd, signal_short_ma,
        signal_boll, signal_volume, signal_long_ma,
    )
    from strategies.base import SignalType

    strategy_fns = {
        "KDJ":   signal_kdj,
        "MACD":  signal_macd,
        "短均线":  signal_short_ma,
        "BOLL":  signal_boll,
        "量价":   signal_volume,
        "长均线":  signal_long_ma,
    }

    results = {}
    min_rows = 60

    for name, fn in strategy_fns.items():
        wins = 0
        losses = 0
        returns = []

        for i in range(min_rows, len(df) - lookahead):
            sub = df.iloc[:i + 1].copy()
            try:
                sig = fn(sub)
            except Exception:
                continue

            if sig.type == SignalType.HOLD or sig.strength < 40:
                continue

            buy_price  = float(df["close"].iloc[i])
            sell_price = float(df["close"].iloc[i + lookahead])
            ret = (sell_price / buy_price - 1) * 100

            if sig.type == SignalType.BUY:
                r = ret
            else:  # SELL信号对应做空方向
                r = -ret

            returns.append(r)
            if r > 0:
                wins += 1
            else:
                losses += 1

        total = wins + losses
        results[name] = {
            "signal_count": total,
            "win_rate":     round(wins / total * 100, 1) if total > 0 else 0,
            "avg_return":   round(float(np.mean(returns)), 2) if returns else 0,
        }

    return results


def recommend_weights(classify: dict, backtest: dict) -> dict:
    """根据股票特征 + 历史胜率，推荐策略权重"""
    base = {
        "kdj":      0.25,
        "macd":     0.25,
        "short_ma": 0.20,
        "volume":   0.15,
        "boll":     0.10,
        "long_ma":  0.05,
    }

    name_map = {
        "KDJ":  "kdj",
        "MACD": "macd",
        "短均线": "short_ma",
        "量价":  "volume",
        "BOLL": "boll",
        "长均线": "long_ma",
    }

    # ADX>25 → 趋势模式：提高 MACD/长均线，降低 BOLL/KDJ
    if classify["adx"] > 25:
        base["macd"]    = min(0.35, base["macd"]    + 0.10)
        base["long_ma"] = min(0.15, base["long_ma"] + 0.10)
        base["boll"]    -= 0.05
        base["kdj"]     -= 0.15
    # ADX<18 → 震荡模式：提高 BOLL/KDJ，降低 MACD/长均线
    elif classify["adx"] < 18:
        base["boll"]    = min(0.25, base["boll"]    + 0.15)
        base["kdj"]     = min(0.35, base["kdj"]     + 0.10)
        base["macd"]    -= 0.10
        base["long_ma"] -= 0.05

    # 量能频繁异动 → 提高量价权重
    if classify["volume_score"] > 40:
        base["volume"]  = min(0.30, base["volume"]  + 0.10)
        base["macd"]    = max(0.10, base["macd"]    - 0.05)
        base["boll"]    = max(0.05, base["boll"]    - 0.05)

    # 用历史胜率微调（胜率>60%加权，<40%降权）
    total_w = sum(base.values())
    for display, key in name_map.items():
        bt = backtest.get(display, {})
        if bt.get("signal_count", 0) >= 5:
            wr = bt["win_rate"]
            if wr > 60:
                base[key] = min(0.40, base[key] * 1.15)
            elif wr < 40:
                base[key] = max(0.03, base[key] * 0.85)

    # 归一化
    total_w = sum(base.values())
    return {k: round(v / total_w, 3) for k, v in base.items()}


def profile_label(classify: dict) -> str:
    adx = classify["adx"]
    vs  = classify["volume_score"]
    vlt = classify["volatility"]
    if adx > 28:
        tag = f"{RED}趋势强{R}"
    elif adx < 18:
        tag = f"{GRN}震荡盘{R}"
    else:
        tag = f"{YLW}中性{R}"
    if vs > 50:
        tag += f" {CYN}主力量能{R}"
    if vlt > 4.0:
        tag += f" {BOLD}高弹性{R}"
    return tag


def fmt_backtest(bt: dict) -> str:
    parts = []
    for name, v in bt.items():
        n  = v["signal_count"]
        wr = v["win_rate"]
        ar = v["avg_return"]
        if n == 0:
            continue
        color = GRN if wr >= 55 else (RED if wr < 45 else YLW)
        parts.append(f"{name}:{color}{wr:.0f}%{R}({n}次,{ar:+.1f}%)")
    return "  ".join(parts)


def analyze_one(code: str, name: str, days: int):
    try:
        df = fetch(code, days)
        if len(df) < 60:
            print(f"  {YLW}数据不足（{len(df)}行），跳过{R}")
            return None

        from strategies.scanner import scan
        final, score, signals = scan(df)

        classify = classify_stock(df)
        backtest = backtest_signals(df, lookahead=5)
        weights  = recommend_weights(classify, backtest)

        return {
            "code":     code,
            "name":     name,
            "rows":     len(df),
            "signal":   final.value,
            "score":    round(score, 1),
            "classify": classify,
            "backtest": backtest,
            "weights":  weights,
            "signals":  [
                {"strategy": s.strategy, "type": s.type.value,
                 "strength": s.strength, "reason": s.reason}
                for s in signals
            ],
        }
    except Exception as e:
        print(f"  {RED}失败: {e}{R}")
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv",  default="../Sheet_20260507.csv")
    parser.add_argument("--days", type=int, default=250)
    parser.add_argument("--out",  default="batch_result.json")
    parser.add_argument("--sleep", type=float, default=1.5,
                        help="每只股请求间隔秒（避免限速）")
    args = parser.parse_args()

    csv_path = Path(__file__).parent / args.csv
    raw = pd.read_csv(csv_path, dtype=str)
    raw.columns = [c.strip().strip('"') for c in raw.columns]

    # 去重（同一代码可能出现在多个图片编号里）
    stocks = (raw[["股票名称", "股票代码"]]
              .drop_duplicates(subset=["股票代码"])
              .reset_index(drop=True))
    stocks["股票代码"] = stocks["股票代码"].str.strip().str.strip('"')
    stocks["股票名称"] = stocks["股票名称"].str.strip().str.strip('"')

    total  = len(stocks)
    results = []

    print(f"\n{BOLD}批量策略适配分析{R}  共 {total} 只标的  近 {args.days} 日数据")
    print(f"{'═'*72}\n")

    for i, row in stocks.iterrows():
        code = row["股票代码"]
        name = row["股票名称"]
        print(f"[{i+1:>2}/{total}] {BOLD}{name}（{code}）{R}", end="  ", flush=True)

        r = analyze_one(code, name, args.days)
        if r:
            results.append(r)
            label = profile_label(r["classify"])
            sig_color = GRN if r["signal"] == "买入" else (RED if r["signal"] == "卖出" else DIM)
            print(f"{label}  ADX={r['classify']['adx']}  "
                  f"信号:{sig_color}{r['signal']}{R}({r['score']:+.1f})")
            print(f"         回测胜率: {fmt_backtest(r['backtest'])}")
            best = sorted(r["weights"].items(), key=lambda x: -x[1])[:3]
            best_str = " > ".join(f"{k}({v:.0%})" for k, v in best)
            print(f"         推荐权重: {CYN}{best_str}{R}")
        print()

        if i < total - 1:
            time.sleep(args.sleep)

    # 保存 JSON
    out_path = Path(__file__).parent / args.out
    out_path.write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # ── 汇总排行 ─────────────────────────────────────────
    print(f"\n{'═'*72}")
    print(f"{BOLD}汇总：当前信号{R}")
    buy_list  = [r for r in results if r["signal"] == "买入"]
    sell_list = [r for r in results if r["signal"] == "卖出"]
    hold_list = [r for r in results if r["signal"] == "观望"]

    if buy_list:
        print(f"\n  {GRN}{BOLD}买入信号 ({len(buy_list)}只):{R}")
        for r in sorted(buy_list, key=lambda x: -x["score"]):
            print(f"    {r['name']}({r['code']})  得分 {r['score']:+.1f}  "
                  f"ADX={r['classify']['adx']}")

    if sell_list:
        print(f"\n  {RED}{BOLD}卖出信号 ({len(sell_list)}只):{R}")
        for r in sorted(sell_list, key=lambda x: x["score"]):
            print(f"    {r['name']}({r['code']})  得分 {r['score']:+.1f}  "
                  f"ADX={r['classify']['adx']}")

    print(f"\n  {DIM}观望 ({len(hold_list)}只):{R} "
          + "、".join(f"{r['name']}" for r in hold_list))

    print(f"\n{BOLD}详细结果已保存至 {out_path}{R}\n")


if __name__ == "__main__":
    main()
