"""
多指标共识过滤器
只有当 N 个主要指标同向时，才输出最终信号，避免单一指标噪音。
"""
from typing import List, Tuple
from .base import Signal, SignalType


# 参与共识投票的主力策略（权重高的）
CONSENSUS_KEYS = {"KDJ", "MACD", "短均线", "BOLL", "量价"}

# 至少几个主力策略同向才触发
MIN_AGREE = 2


def consensus_filter(signals: List[Signal], min_agree: int = MIN_AGREE
                     ) -> Tuple[SignalType, int, str]:
    """
    对信号列表做共识过滤。

    返回:
        (共识方向, 同向策略数, 原因描述)
    """
    buy_sigs  = [s for s in signals
                 if s.type == SignalType.BUY  and s.strategy in CONSENSUS_KEYS and s.strength >= 40]
    sell_sigs = [s for s in signals
                 if s.type == SignalType.SELL and s.strategy in CONSENSUS_KEYS and s.strength >= 40]

    if len(buy_sigs) >= min_agree and len(buy_sigs) > len(sell_sigs):
        names  = "+".join(s.strategy for s in buy_sigs)
        reason = f"共识买入({len(buy_sigs)}项同向): {names}"
        return SignalType.BUY, len(buy_sigs), reason

    if len(sell_sigs) >= min_agree and len(sell_sigs) > len(buy_sigs):
        names  = "+".join(s.strategy for s in sell_sigs)
        reason = f"共识卖出({len(sell_sigs)}项同向): {names}"
        return SignalType.SELL, len(sell_sigs), reason

    reason = (f"买入信号{len(buy_sigs)}项 卖出信号{len(sell_sigs)}项 "
              f"未达共识阈值({min_agree})")
    return SignalType.HOLD, 0, reason


def consensus_strength(agree_count: int) -> str:
    """根据共识数量返回可信度描述"""
    if agree_count >= 4:
        return "极强"
    if agree_count == 3:
        return "强"
    if agree_count == 2:
        return "中"
    return "弱"
