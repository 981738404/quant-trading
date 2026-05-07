"""
信号扫描器：对每个标的运行所有策略，汇总得分，输出最终信号。
"""
import pandas as pd
import numpy as np
from typing import List, Dict, Tuple
from .base import Signal, SignalType
from .indicators import (
    sma, ema, boll, macd, kdj, atr, adx, obv, rsi,
    turnover_anomaly, volume_price_divergence,
)

# ── 短线权重配置 ──────────────────────────────────────────
WEIGHTS = {
    "kdj":       0.25,
    "macd":      0.25,
    "short_ma":  0.20,
    "volume":    0.15,
    "boll":      0.10,
    "long_ma":   0.05,
}

BUY_THRESHOLD  =  60.0
SELL_THRESHOLD = -60.0


def _last(s: pd.Series) -> float:
    return float(s.iloc[-1])

def _prev(s: pd.Series) -> float:
    return float(s.iloc[-2]) if len(s) >= 2 else _last(s)


# ─────────────────────────────────────────────────────────
# 各策略信号函数
# ─────────────────────────────────────────────────────────

def signal_kdj(df: pd.DataFrame) -> Signal:
    K, D, J = kdj(df["high"], df["low"], df["close"])
    k, d, j = _last(K), _last(D), _last(J)
    pk, pd_ = _prev(K), _prev(D)

    golden = (pk < pd_) and (k >= d)   # 金叉
    death  = (pk > pd_) and (k <= d)   # 死叉

    if j < 0 or (j < 20 and golden):
        return Signal("KDJ", SignalType.BUY,
                      min(100, 60 + (20 - j) * 2),
                      f"KDJ 超卖金叉 J={j:.1f}",
                      {"K": k, "D": d, "J": j})
    if j > 100 or (j > 80 and death):
        return Signal("KDJ", SignalType.SELL,
                      min(100, 60 + (j - 80) * 2),
                      f"KDJ 超买死叉 J={j:.1f}",
                      {"K": k, "D": d, "J": j})
    if golden:
        return Signal("KDJ", SignalType.BUY, 55,
                      f"KDJ 金叉 K={k:.1f} D={d:.1f}", {"K": k, "D": d, "J": j})
    if death:
        return Signal("KDJ", SignalType.SELL, 55,
                      f"KDJ 死叉 K={k:.1f} D={d:.1f}", {"K": k, "D": d, "J": j})
    return Signal("KDJ", SignalType.HOLD, 0,
                  f"KDJ 中性 K={k:.1f} D={d:.1f} J={j:.1f}", {"K": k, "D": d, "J": j})


def signal_macd(df: pd.DataFrame) -> Signal:
    dif, dea, hist = macd(df["close"], fast=6, slow=13, signal=5)
    d, e, h   = _last(dif), _last(dea), _last(hist)
    pd_, pe   = _prev(dif), _prev(dea)
    ph        = _prev(hist)

    golden = (pd_ < pe) and (d >= e)
    death  = (pd_ > pe) and (d <= e)
    bar_up = (ph <= 0) and (h > 0)    # 柱由负转正
    bar_dn = (ph >= 0) and (h < 0)    # 柱由正转负

    if golden or bar_up:
        strength = 70 if (golden and bar_up) else 55
        return Signal("MACD", SignalType.BUY, strength,
                       f"MACD {'金叉+柱转正' if golden and bar_up else '金叉' if golden else '柱转正'}",
                       {"DIF": d, "DEA": e, "HIST": h})
    if death or bar_dn:
        strength = 70 if (death and bar_dn) else 55
        return Signal("MACD", SignalType.SELL, strength,
                       f"MACD {'死叉+柱转负' if death and bar_dn else '死叉' if death else '柱转负'}",
                       {"DIF": d, "DEA": e, "HIST": h})
    sign = "多头" if d > 0 else "空头"
    return Signal("MACD", SignalType.HOLD, 0,
                  f"MACD {sign}区间 DIF={d:.3f}", {"DIF": d, "DEA": e, "HIST": h})


def signal_short_ma(df: pd.DataFrame) -> Signal:
    ma3  = sma(df["close"], 3)
    ma5  = sma(df["close"], 5)
    ma10 = sma(df["close"], 10)
    c  = _last(df["close"])
    m3, m5, m10 = _last(ma3), _last(ma5), _last(ma10)
    pm3, pm5    = _prev(ma3), _prev(ma5)

    bull = (m3 > m5 > m10)   # 多头排列
    bear = (m3 < m5 < m10)   # 空头排列
    cross_up   = (_prev(ma3) <= _prev(ma5)) and (m3 > m5)
    cross_down = (_prev(ma3) >= _prev(ma5)) and (m3 < m5)

    if bull and cross_up:
        return Signal("短均线", SignalType.BUY, 70,
                      f"3/5/10日均线多头排列+金叉",
                      {"MA3": m3, "MA5": m5, "MA10": m10})
    if bear and cross_down:
        return Signal("短均线", SignalType.SELL, 70,
                      f"3/5/10日均线空头排列+死叉",
                      {"MA3": m3, "MA5": m5, "MA10": m10})
    if bull:
        return Signal("短均线", SignalType.BUY, 45,
                      f"均线多头排列",
                      {"MA3": m3, "MA5": m5, "MA10": m10})
    if bear:
        return Signal("短均线", SignalType.SELL, 45,
                      f"均线空头排列",
                      {"MA3": m3, "MA5": m5, "MA10": m10})
    return Signal("短均线", SignalType.HOLD, 0,
                  f"均线纠缠 MA3={m3:.2f} MA5={m5:.2f}",
                  {"MA3": m3, "MA5": m5, "MA10": m10})


def signal_boll(df: pd.DataFrame) -> Signal:
    upper, mid, lower, width = boll(df["close"])
    c = _last(df["close"])
    u, m, l, w = _last(upper), _last(mid), _last(lower), _last(width)

    pos = (c - l) / (u - l + 1e-10)   # 0=下轨 1=上轨

    # 带宽历史分位（判断挤压）
    width_pct = float((width < w).mean())   # 当前带宽比历史多少天更窄

    if c >= u:
        return Signal("BOLL", SignalType.SELL, 65,
                      f"价格触及上轨 上轨={u:.2f}",
                      {"upper": u, "mid": m, "lower": l, "pos": pos})
    if c <= l:
        return Signal("BOLL", SignalType.BUY, 65,
                      f"价格触及下轨 下轨={l:.2f}",
                      {"upper": u, "mid": m, "lower": l, "pos": pos})
    if pos > 0.8:
        return Signal("BOLL", SignalType.SELL, 40,
                      f"价格接近上轨 位置={pos:.0%}",
                      {"upper": u, "mid": m, "lower": l, "pos": pos})
    if pos < 0.2:
        return Signal("BOLL", SignalType.BUY, 40,
                      f"价格接近下轨 位置={pos:.0%}",
                      {"upper": u, "mid": m, "lower": l, "pos": pos})
    return Signal("BOLL", SignalType.HOLD, 0,
                  f"BOLL 中轨附近 位置={pos:.0%}",
                  {"upper": u, "mid": m, "lower": l, "pos": pos})


def signal_volume(df: pd.DataFrame) -> Signal:
    vol = df["volume"] if "volume" in df.columns else df.get("vol", pd.Series())
    if vol.empty or len(vol) < 5:
        return Signal("量价", SignalType.HOLD, 0, "成交量数据不足", {})

    ratio = _last(turnover_anomaly(vol, 20))
    div   = volume_price_divergence(df["close"], vol, 5)

    reason_parts = [f"换手倍数={ratio:.1f}x"]
    base_type  = SignalType.HOLD
    base_str   = 0

    if ratio >= 3.0:
        reason_parts.append("成交量异常放大")
        # 结合价格方向判断
        if _last(df["close"]) > _prev(df["close"]):
            base_type, base_str = SignalType.BUY, 60
        else:
            base_type, base_str = SignalType.SELL, 60
    elif ratio <= 0.3:
        reason_parts.append("地量横盘")
        base_str = 30  # 方向不明，低强度

    if div == -1:
        reason_parts.append("量价顶背离")
        base_type, base_str = SignalType.SELL, max(base_str, 55)
    elif div == 1:
        reason_parts.append("量价底背离")
        base_type, base_str = SignalType.BUY, max(base_str, 55)

    return Signal("量价", base_type, base_str,
                  " | ".join(reason_parts), {"vol_ratio": ratio, "divergence": div})


def signal_long_ma(df: pd.DataFrame) -> Signal:
    """长均线作为趋势背景过滤器（不单独触发买卖，只输出方向）"""
    ma60  = sma(df["close"], 60)
    ma250 = sma(df["close"], 250) if len(df) >= 250 else sma(df["close"], len(df))
    c   = _last(df["close"])
    m60 = _last(ma60)
    m250 = _last(ma250)

    above_60  = c > m60
    above_250 = c > m250
    ma60_up   = _last(ma60) > _prev(ma60)   # 60日线向上

    if above_60 and above_250 and ma60_up:
        return Signal("长均线", SignalType.BUY, 80,
                      f"价格站上60/250日线 趋势向上",
                      {"MA60": m60, "MA250": m250})
    if above_60 and ma60_up:
        return Signal("长均线", SignalType.BUY, 50,
                      f"价格站上60日线",
                      {"MA60": m60, "MA250": m250})
    if not above_60:
        return Signal("长均线", SignalType.SELL, 60,
                      f"价格跌破60日线 趋势偏空",
                      {"MA60": m60, "MA250": m250})
    return Signal("长均线", SignalType.HOLD, 0,
                  f"长均线中性", {"MA60": m60, "MA250": m250})


# ─────────────────────────────────────────────────────────
# 主扫描器
# ─────────────────────────────────────────────────────────

def detect_limit_up(df: pd.DataFrame) -> bool:
    """检测最后一根K线是否为涨停（涨幅≥9.5%）"""
    if len(df) < 2:
        return False
    prev_close = float(df["close"].iloc[-2])
    curr_close = float(df["close"].iloc[-1])
    return (curr_close / prev_close - 1) >= 0.095


def apply_limit_up_override(signals: List[Signal], df: pd.DataFrame) -> List[Signal]:
    """
    涨停特殊规则：
    - 暂停 BOLL 卖出信号（上轨突破是强势体现，不是超买）
    - 若成交量未异常放大（换手<2倍），视为筹码锁定，降低 KDJ 卖出权重
    """
    vol = df["volume"]
    vol_ratio = float(vol.iloc[-1] / (vol.rolling(20).mean().iloc[-1] + 1e-10))
    light_volume = vol_ratio < 2.0   # 量未放大 → 筹码锁定

    new_signals = []
    for s in signals:
        if s.strategy == "BOLL" and s.type == SignalType.SELL:
            new_signals.append(Signal(
                "BOLL", SignalType.HOLD, 0,
                f"涨停日暂停BOLL卖出（强势突破上轨，换手{vol_ratio:.1f}x）",
                s.values,
            ))
        elif s.strategy == "KDJ" and s.type == SignalType.SELL and light_volume:
            new_signals.append(Signal(
                "KDJ", SignalType.HOLD, 0,
                f"涨停+低换手({vol_ratio:.1f}x)：KDJ卖出信号降权，筹码锁定",
                s.values,
            ))
        else:
            new_signals.append(s)
    return new_signals


def scan(df: pd.DataFrame) -> Tuple[SignalType, float, List[Signal]]:
    """
    对一个标的运行所有策略，返回 (最终信号类型, 综合得分, 各策略信号列表)
    """
    runners = {
        "kdj":      signal_kdj,
        "macd":     signal_macd,
        "short_ma": signal_short_ma,
        "boll":     signal_boll,
        "volume":   signal_volume,
        "long_ma":  signal_long_ma,
    }

    signals: List[Signal] = []
    composite = 0.0

    for key, fn in runners.items():
        try:
            sig = fn(df)
        except Exception as e:
            sig = Signal(key, SignalType.HOLD, 0, f"计算异常: {e}", {})
        signals.append(sig)

    # 涨停特殊规则：覆盖 BOLL/KDJ 卖出信号
    if detect_limit_up(df):
        signals = apply_limit_up_override(signals, df)

    strategy_to_key = {fn(pd.DataFrame()).__class__.__name__: k
                       for k, fn in {}.items()}
    name_to_key = {
        "KDJ": "kdj", "MACD": "macd", "短均线": "short_ma",
        "BOLL": "boll", "量价": "volume", "长均线": "long_ma",
    }
    for sig in signals:
        wkey = name_to_key.get(sig.strategy, sig.strategy.lower())
        composite += sig.score() * WEIGHTS.get(wkey, 0)

    if composite >= BUY_THRESHOLD:
        final = SignalType.BUY
    elif composite <= SELL_THRESHOLD:
        final = SignalType.SELL
    else:
        final = SignalType.HOLD

    return final, composite, signals


def stop_loss_price(df: pd.DataFrame) -> float:
    """用 ATR 计算建议止损价（当前价 - 2×ATR7）"""
    atr_val = atr(df["high"], df["low"], df["close"], period=7)
    return float(df["close"].iloc[-1]) - 2 * float(atr_val.iloc[-1])
