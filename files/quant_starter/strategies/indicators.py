"""
所有技术指标的纯计算函数，输入 pd.Series / pd.DataFrame，输出数值。
不依赖任何网络请求，方便单元测试。
"""
import numpy as np
import pandas as pd
from typing import Tuple


# ─────────────────────────────────────────────────────────
# 均线
# ─────────────────────────────────────────────────────────

def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(period).mean()


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


# ─────────────────────────────────────────────────────────
# BOLL 布林带
# ─────────────────────────────────────────────────────────

def boll(close: pd.Series, period: int = 20, std_mult: float = 2.0) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """返回 (upper, mid, lower)"""
    mid   = sma(close, period)
    std   = close.rolling(period).std()
    upper = mid + std_mult * std
    lower = mid - std_mult * std
    width = (upper - lower) / mid  # 带宽（归一化）
    return upper, mid, lower, width


# ─────────────────────────────────────────────────────────
# MACD（短线快参数 6/13/5）
# ─────────────────────────────────────────────────────────

def macd(close: pd.Series,
         fast: int = 6, slow: int = 13, signal: int = 5
         ) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """返回 (dif, dea, hist)"""
    dif  = ema(close, fast) - ema(close, slow)
    dea  = ema(dif, signal)
    hist = (dif - dea) * 2
    return dif, dea, hist


# ─────────────────────────────────────────────────────────
# KDJ
# ─────────────────────────────────────────────────────────

def kdj(high: pd.Series, low: pd.Series, close: pd.Series,
        n: int = 9, m1: int = 3, m2: int = 3
        ) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """返回 (K, D, J)"""
    lowest  = low.rolling(n).min()
    highest = high.rolling(n).max()
    rsv = (close - lowest) / (highest - lowest + 1e-10) * 100

    K = rsv.ewm(com=m1 - 1, adjust=False).mean()
    D = K.ewm(com=m2 - 1, adjust=False).mean()
    J = 3 * K - 2 * D
    return K, D, J


# ─────────────────────────────────────────────────────────
# ATR 平均真实波幅
# ─────────────────────────────────────────────────────────

def atr(high: pd.Series, low: pd.Series, close: pd.Series,
        period: int = 7) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low  - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(period).mean()


# ─────────────────────────────────────────────────────────
# DMI / ADX
# ─────────────────────────────────────────────────────────

def adx(high: pd.Series, low: pd.Series, close: pd.Series,
        period: int = 14) -> Tuple[pd.Series, pd.Series, pd.Series]:
    """返回 (+DI, -DI, ADX)"""
    atr_val = atr(high, low, close, period)
    up   = high.diff()
    down = -low.diff()
    plus_dm  = up.where((up > down) & (up > 0), 0.0)
    minus_dm = down.where((down > up) & (down > 0), 0.0)

    plus_di  = 100 * sma(plus_dm, period)  / (atr_val + 1e-10)
    minus_di = 100 * sma(minus_dm, period) / (atr_val + 1e-10)
    dx       = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di + 1e-10)
    adx_val  = sma(dx, period)
    return plus_di, minus_di, adx_val


# ─────────────────────────────────────────────────────────
# OBV 能量潮
# ─────────────────────────────────────────────────────────

def obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    direction = close.diff().apply(lambda x: 1 if x > 0 else (-1 if x < 0 else 0))
    return (direction * volume).cumsum()


# ─────────────────────────────────────────────────────────
# RSI
# ─────────────────────────────────────────────────────────

def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain  = delta.where(delta > 0, 0.0).rolling(period).mean()
    loss  = (-delta.where(delta < 0, 0.0)).rolling(period).mean()
    rs    = gain / loss.replace(0, float("nan"))
    r     = 100 - 100 / (1 + rs)
    r[(loss == 0) & (gain > 0)] = 100.0
    return r


# ─────────────────────────────────────────────────────────
# 换手率异动检测
# ─────────────────────────────────────────────────────────

def turnover_anomaly(turnover: pd.Series, lookback: int = 20) -> pd.Series:
    """返回当日换手率相对近 lookback 日均值的倍数"""
    avg = turnover.rolling(lookback).mean()
    return turnover / (avg + 1e-10)


# ─────────────────────────────────────────────────────────
# 量价背离检测（简化版）
# ─────────────────────────────────────────────────────────

def volume_price_divergence(close: pd.Series, volume: pd.Series,
                             period: int = 5) -> float:
    """
    返回 -1（顶背离：价涨量缩）/ +1（底背离：价跌量缩）/ 0（无背离）
    """
    price_chg  = close.iloc[-1] - close.iloc[-period]
    volume_chg = volume.iloc[-1] - volume.iloc[-period]
    if price_chg > 0 and volume_chg < 0:
        return -1.0   # 顶背离，看空
    if price_chg < 0 and volume_chg < 0:
        return 1.0    # 底背离，看多
    return 0.0
