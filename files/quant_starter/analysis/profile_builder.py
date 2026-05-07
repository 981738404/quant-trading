"""
策略画像分析器

对 watchlist.json 中每只标的，拉取近 2 年日线数据，
自动计算并保存该标的最适合的策略权重 → strategy_profile.json

分析维度：
  1. ADX 分布  → 判断"趋势型" vs "震荡型" vs "混合型"
  2. ATR/价格比 → 判断波动率等级（高/中/低）
  3. 各指标历史信号买入胜率（5日持仓回测）
  4. 综合推荐策略权重

运行：
    cd files/quant_starter
    python3 analysis/profile_builder.py            # 全量分析（约2分钟）
    python3 analysis/profile_builder.py --code 600519  # 单只分析
    python3 analysis/profile_builder.py --days 365     # 只用1年数据
"""
import argparse
import json
import sys
import time
import datetime
from pathlib import Path

import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))
from strategies.indicators import (
    kdj, ema, boll, sma, atr as calc_atr, adx as calc_adx,
)

BASE_DIR  = Path(__file__).parent.parent
WATCHLIST = BASE_DIR / "watchlist.json"
OUTPUT    = BASE_DIR / "strategy_profile.json"

# ── 分类阈值 ────────────────────────────────────────────────────────────────
ADX_TREND_PCT_HIGH = 42   # trend_pct >= 42% → 趋势型
ADX_TREND_PCT_LOW  = 25   # trend_pct <= 25% → 震荡型
ATR_HIGH_PCT       = 3.0  # avg daily ATR/price >= 3% → 高波动
ATR_LOW_PCT        = 1.5  # avg daily ATR/price <= 1.5% → 低波动

# ── 策略权重模板（三种基础模板）────────────────────────────────────────────
# 趋势型：放大 MACD 和长均线，适合顺势追涨
WEIGHTS_TREND = {
    "kdj": 0.18, "macd": 0.30, "short_ma": 0.22,
    "volume": 0.12, "boll": 0.05, "long_ma": 0.13,
}
# 震荡型：放大 KDJ 和 BOLL，适合逢低买入/高位卖出
WEIGHTS_OSCILLATION = {
    "kdj": 0.32, "macd": 0.18, "short_ma": 0.15,
    "volume": 0.18, "boll": 0.15, "long_ma": 0.02,
}
# 混合型：默认权重（与 scanner.py 保持一致）
WEIGHTS_MIXED = {
    "kdj": 0.25, "macd": 0.25, "short_ma": 0.20,
    "volume": 0.15, "boll": 0.10, "long_ma": 0.05,
}


# ── 数据获取 ─────────────────────────────────────────────────────────────────

def fetch_hist(code: str, days: int = 520) -> pd.DataFrame:
    import akshare as ak
    sh = f"sh{code}" if code.startswith(("6", "5")) else f"sz{code}"
    end   = datetime.datetime.now().strftime("%Y%m%d")
    start = (datetime.datetime.now() - datetime.timedelta(days=days)).strftime("%Y%m%d")
    df = ak.stock_zh_a_daily(symbol=sh, start_date=start, end_date=end, adjust="qfq")
    df["date"] = df.index
    df = df.reset_index(drop=True)
    df.columns = [c.lower() for c in df.columns]
    df = df.rename(columns={"vol": "volume"})
    for col in ["open", "high", "low", "close", "volume"]:
        if col in df.columns:
            df[col] = df[col].astype(float)
    return df


# ── 指标统计 ─────────────────────────────────────────────────────────────────

def compute_adx_stats(df: pd.DataFrame) -> dict:
    """计算 ADX 分布，判断该标的趋势性强弱"""
    _, _, adx_s = calc_adx(df["high"], df["low"], df["close"], 14)
    clean = adx_s.dropna()
    if len(clean) < 30:
        return {"avg_adx": 20.0, "trend_pct": 30.0, "adx_p75": 25.0}
    return {
        "avg_adx":   round(float(clean.mean()), 1),
        "trend_pct": round(float((clean > 25).mean() * 100), 1),
        "adx_p75":   round(float(clean.quantile(0.75)), 1),
    }


def compute_volatility(df: pd.DataFrame) -> dict:
    """计算波动率及最大回撤"""
    atr_s = calc_atr(df["high"], df["low"], df["close"], 14).dropna()
    if len(atr_s) < 20:
        return {"avg_atr_pct": 2.0, "max_drawdown": 0.0, "annual_vol": 20.0}
    close_aligned = df["close"].loc[atr_s.index]
    atr_pct = (atr_s / (close_aligned + 1e-10)) * 100

    roll_max = df["close"].cummax()
    drawdown = (df["close"] - roll_max) / (roll_max + 1e-10)

    # 年化波动率（基于日收益率标准差）
    daily_ret  = df["close"].pct_change().dropna()
    annual_vol = round(float(daily_ret.std() * (252 ** 0.5) * 100), 1)

    return {
        "avg_atr_pct":  round(float(atr_pct.mean()), 2),
        "max_drawdown": round(float(drawdown.min() * 100), 1),
        "annual_vol":   annual_vol,
    }


def backtest_signals(df: pd.DataFrame) -> dict:
    """
    对每种指标进行简单买入信号回测（5日持仓）。
    规则：出现买入信号当日收盘买入，5日后收盘卖出，计算胜率和平均收益。
    """
    if len(df) < 60:
        return {}

    close  = df["close"]
    high   = df["high"]
    low    = df["low"]
    fwd5   = close.pct_change(5).shift(-5)  # 5日远期收益率
    results = {}

    # ── KDJ：J值超卖 + KD金叉 ──────────────────────────────────────────────
    try:
        K, D, J = kdj(high, low, close)
        kdj_buy = (J < 20) | ((K.shift(1) < D.shift(1)) & (K >= D) & (J < 50))
        # 去重：连续信号只取第一天
        signal_first = kdj_buy & ~kdj_buy.shift(1).fillna(False)
        trades = fwd5[signal_first].dropna()
        if len(trades) >= 5:
            results["KDJ"] = {
                "buy_win_rate":  round(float((trades > 0).mean() * 100), 1),
                "avg_5d_return": round(float(trades.mean() * 100), 2),
                "signal_count":  int(len(trades)),
            }
    except Exception:
        pass

    # ── MACD：DIF/DEA 金叉 ─────────────────────────────────────────────────
    try:
        dif = ema(close, 6) - ema(close, 13)
        dea = ema(dif, 5)
        macd_buy = (dif.shift(1) < dea.shift(1)) & (dif >= dea)
        trades = fwd5[macd_buy].dropna()
        if len(trades) >= 5:
            results["MACD"] = {
                "buy_win_rate":  round(float((trades > 0).mean() * 100), 1),
                "avg_5d_return": round(float(trades.mean() * 100), 2),
                "signal_count":  int(len(trades)),
            }
    except Exception:
        pass

    # ── BOLL：价格触及下轨 ─────────────────────────────────────────────────
    try:
        _, _, lower, _ = boll(close)
        boll_buy = close <= lower
        signal_first = boll_buy & ~boll_buy.shift(1).fillna(False)
        trades = fwd5[signal_first].dropna()
        if len(trades) >= 5:
            results["BOLL"] = {
                "buy_win_rate":  round(float((trades > 0).mean() * 100), 1),
                "avg_5d_return": round(float(trades.mean() * 100), 2),
                "signal_count":  int(len(trades)),
            }
    except Exception:
        pass

    # ── 短均线：MA3 上穿 MA5 ───────────────────────────────────────────────
    try:
        ma3 = sma(close, 3)
        ma5 = sma(close, 5)
        ma_buy = (ma3.shift(1) <= ma5.shift(1)) & (ma3 > ma5)
        trades = fwd5[ma_buy].dropna()
        if len(trades) >= 5:
            results["短均线"] = {
                "buy_win_rate":  round(float((trades > 0).mean() * 100), 1),
                "avg_5d_return": round(float(trades.mean() * 100), 2),
                "signal_count":  int(len(trades)),
            }
    except Exception:
        pass

    # ── 长均线：收盘 > MA60 持续 ────────────────────────────────────────────
    try:
        ma60 = sma(close, 60)
        above = close > ma60
        # 刚突破信号（从下方穿越到上方）
        cross_up = above & ~above.shift(1).fillna(False)
        trades = fwd5[cross_up].dropna()
        if len(trades) >= 5:
            results["长均线"] = {
                "buy_win_rate":  round(float((trades > 0).mean() * 100), 1),
                "avg_5d_return": round(float(trades.mean() * 100), 2),
                "signal_count":  int(len(trades)),
            }
    except Exception:
        pass

    return results


# ── 分类与权重推荐 ────────────────────────────────────────────────────────────

def classify_and_recommend(adx_stats: dict, vol_stats: dict, backtest: dict) -> dict:
    """
    基于 ADX / ATR 分类，结合回测历史微调权重。
    逻辑：
      1. 先用 trend_pct 确定基础权重模板
      2. 找到回测中表现最好的指标（胜率 × 平均收益），小幅提升其权重
      3. 根据 ATR 设置 BOLL 带宽系数和止损 ATR 倍数
    """
    trend_pct = adx_stats["trend_pct"]
    avg_atr   = vol_stats["avg_atr_pct"]

    # ── 股票类型 ──────────────────────────────────────────────────────────
    if trend_pct >= ADX_TREND_PCT_HIGH:
        stock_type = "趋势型"
        weights    = dict(WEIGHTS_TREND)
    elif trend_pct <= ADX_TREND_PCT_LOW:
        stock_type = "震荡型"
        weights    = dict(WEIGHTS_OSCILLATION)
    else:
        stock_type = "混合型"
        weights    = dict(WEIGHTS_MIXED)

    # ── 波动率等级 ─────────────────────────────────────────────────────────
    if avg_atr >= ATR_HIGH_PCT:
        volatility  = "高波动"
        boll_mult   = 2.2   # 带宽更宽，避免频繁触碰
        sl_atr_mult = 1.5   # 止损更近，控制风险
    elif avg_atr <= ATR_LOW_PCT:
        volatility  = "低波动"
        boll_mult   = 1.8   # 带宽更窄，信号更灵敏
        sl_atr_mult = 2.5   # 止损更远，给更多空间
    else:
        volatility  = "中波动"
        boll_mult   = 2.0
        sl_atr_mult = 2.0

    # ── 基于回测微调权重（找历史最优指标，小幅提权）────────────────────────
    name_to_key = {
        "KDJ": "kdj", "MACD": "macd",
        "BOLL": "boll", "短均线": "short_ma",
    }
    best_key, best_score = None, -999.0
    for name, stats in backtest.items():
        if stats.get("signal_count", 0) >= 5:
            wr   = stats["buy_win_rate"]
            ret5 = stats["avg_5d_return"]
            # 综合得分：超过随机胜率的部分 × 平均收益
            score = (wr - 50.0) * max(ret5, 0.0)
            if score > best_score:
                best_score = score
                best_key   = name_to_key.get(name)

    if best_key and best_key in weights and best_score > 0:
        bump = min(0.04, weights[best_key] * 0.15)
        weights[best_key] += bump
        # 从非最优中权重最低的扣减
        min_key = min(
            (k for k in weights if k != best_key),
            key=weights.get
        )
        weights[min_key] = max(0.01, weights[min_key] - bump)

    # 归一化（确保权重之和为1）
    total   = sum(weights.values())
    weights = {k: round(v / total, 4) for k, v in weights.items()}

    return {
        "stock_type":   stock_type,
        "volatility":   volatility,
        "weights":      weights,
        "boll_std_mult": boll_mult,
        "sl_atr_mult":  sl_atr_mult,
    }


# ── 单只分析 ──────────────────────────────────────────────────────────────────

def analyze_stock(code: str, name: str, days: int = 520) -> dict:
    df = fetch_hist(code, days)
    if df is None or len(df) < 60:
        return None

    adx_stats = compute_adx_stats(df)
    vol_stats  = compute_volatility(df)
    backtest   = backtest_signals(df)
    profile    = classify_and_recommend(adx_stats, vol_stats, backtest)

    return {
        "name":          name,
        "stock_type":    profile["stock_type"],
        "volatility":    profile["volatility"],
        "avg_adx":       adx_stats["avg_adx"],
        "trend_pct":     adx_stats["trend_pct"],
        "adx_p75":       adx_stats["adx_p75"],
        "avg_atr_pct":   vol_stats["avg_atr_pct"],
        "annual_vol":    vol_stats["annual_vol"],
        "max_drawdown":  vol_stats["max_drawdown"],
        "weights":       profile["weights"],
        "boll_std_mult": profile["boll_std_mult"],
        "sl_atr_mult":   profile["sl_atr_mult"],
        "backtest":      backtest,
        "data_days":     len(df),
        "analysis_date": datetime.date.today().isoformat(),
    }


# ── 汇总报告 ──────────────────────────────────────────────────────────────────

def print_summary(profiles: dict):
    """打印分析摘要"""
    if not profiles:
        return

    type_groups = {}
    vol_groups  = {}
    for code, p in profiles.items():
        t = p.get("stock_type", "未知")
        v = p.get("volatility",  "未知")
        type_groups.setdefault(t, []).append((code, p))
        vol_groups.setdefault(v,  []).append((code, p))

    print("\n" + "="*60)
    print("  策略画像分析报告摘要")
    print("="*60)

    for stock_type, items in sorted(type_groups.items()):
        print(f"\n【{stock_type}】共 {len(items)} 只")
        print(f"  {'代码':<8} {'名称':<10} {'ADX均值':>7} {'趋势%':>6} {'ATR%':>6} {'年化波动':>8}")
        print(f"  {'─'*54}")
        for code, p in sorted(items, key=lambda x: -x[1]["avg_adx"]):
            print(f"  {code:<8} {p['name']:<10} "
                  f"{p['avg_adx']:>7.1f} {p['trend_pct']:>5.1f}% "
                  f"{p['avg_atr_pct']:>5.1f}% {p['annual_vol']:>7.1f}%")

    print(f"\n{'─'*60}")
    print("  各指标历史买入信号胜率（均值）")
    stat_sums = {}
    stat_cnt  = {}
    for code, p in profiles.items():
        for ind, stats in p.get("backtest", {}).items():
            stat_sums.setdefault(ind, 0)
            stat_cnt.setdefault(ind, 0)
            stat_sums[ind] += stats["buy_win_rate"]
            stat_cnt[ind]  += 1
    for ind in ["KDJ", "MACD", "BOLL", "短均线", "长均线"]:
        if ind in stat_sums and stat_cnt[ind] > 0:
            avg = stat_sums[ind] / stat_cnt[ind]
            print(f"  {ind:<8}: {avg:.1f}% 胜率（{stat_cnt[ind]}只有效数据）")


# ── 主程序 ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="策略画像分析器")
    parser.add_argument("--code", help="只分析指定代码（不填则全量）")
    parser.add_argument("--days", type=int, default=520, help="历史天数 (default=520≈2年)")
    parser.add_argument("--force", action="store_true", help="强制重新分析（忽略已有结果）")
    args = parser.parse_args()

    watchlist = json.loads(WATCHLIST.read_text(encoding="utf-8"))
    if args.code:
        watchlist = [w for w in watchlist if w["code"] == args.code]
        if not watchlist:
            print(f"未在 watchlist.json 中找到 {args.code}")
            return

    # 增量更新：已有结果不重复分析（除非 --force）
    profiles = {}
    if OUTPUT.exists() and not args.force:
        try:
            profiles = json.loads(OUTPUT.read_text(encoding="utf-8"))
            skip = [w for w in watchlist if w["code"] in profiles]
            if skip:
                print(f"  已有 {len(skip)} 只结果，跳过（--force 可强制重跑）")
            watchlist = [w for w in watchlist if w["code"] not in profiles]
        except Exception:
            pass

    if not watchlist:
        print("所有标的已有画像，无需重新分析。")
        print_summary(profiles)
        return

    total = len(watchlist)
    print(f"\n分析 {total} 只标的（{args.days} 天历史数据）...\n")
    print(f"  {'代码':<8} {'名称':<10} {'类型':<6} {'波动':<6} {'ADX均值':>7} {'ATR%':>6} {'数据天':>6}")
    print(f"  {'─'*58}")

    success = 0
    for i, item in enumerate(watchlist):
        code = item["code"]
        name = item.get("name", code)
        print(f"  {code:<8} {name:<10}", end="  ", flush=True)

        try:
            p = analyze_stock(code, name, args.days)
            if p:
                profiles[code] = p
                print(f"{p['stock_type']:<6} {p['volatility']:<6} "
                      f"{p['avg_adx']:>7.1f} {p['avg_atr_pct']:>5.1f}% {p['data_days']:>5}天")
                success += 1
            else:
                print("数据不足，跳过")
        except Exception as e:
            print(f"失败: {e}")

        # 实时保存（避免中途崩溃丢数据）
        OUTPUT.write_text(
            json.dumps(profiles, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        if i < total - 1:
            time.sleep(1.2)  # 避免 AKShare 触发频率限制

    print(f"\n分析完成：成功 {success}/{total} 只，结果已保存 → strategy_profile.json")
    print_summary(profiles)


if __name__ == "__main__":
    main()
