"""
信号基类定义
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class SignalType(Enum):
    BUY  = "买入"
    SELL = "卖出"
    HOLD = "观望"


@dataclass
class Signal:
    strategy: str        # 策略名称
    type:     SignalType # BUY / SELL / HOLD
    strength: float      # 0-100，越高越强
    reason:   str        # 人类可读的原因
    values:   dict = field(default_factory=dict)  # 指标具体数值，方便展示

    def score(self) -> float:
        """统一转换为 -100 ~ +100 的得分（正=看多，负=看空）"""
        if self.type == SignalType.BUY:
            return self.strength
        if self.type == SignalType.SELL:
            return -self.strength
        return 0.0
