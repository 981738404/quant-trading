"""
交易执行器：统一入口，根据模式选择模拟盘或 easytrader 真实下单。

使用方式：
    from trader.executor import Executor
    ex = Executor(mode="paper")           # 模拟盘
    ex = Executor(mode="easytrader")      # 真实下单（需要同花顺客户端）
"""
import logging
from typing import Optional
from . import paper

logger = logging.getLogger(__name__)

# 每次信号触发的默认买入手数（1手=100股）
DEFAULT_LOTS = 1


class Executor:

    def __init__(self, mode: str = "paper"):
        """
        mode:
            "paper"      — 本地模拟盘（默认）
            "easytrader" — 通过同花顺客户端真实下单
        """
        self.mode = mode
        self._trader = None

        if mode == "easytrader":
            self._init_easytrader()

    def _init_easytrader(self):
        try:
            import easytrader
            self._trader = easytrader.use("tonghuashun")
            # 配置文件路径：quant_starter/trader/easytrader_config.json
            import json
            from pathlib import Path
            cfg_path = Path(__file__).parent / "easytrader_config.json"
            if not cfg_path.exists():
                # 自动生成模板
                template = {
                    "user":     "你的同花顺账号",
                    "password": "你的同花顺密码",
                    "exe_path": "C:/同花顺/xiadan.exe"
                }
                cfg_path.write_text(
                    json.dumps(template, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                raise RuntimeError(
                    f"请先填写 {cfg_path} 中的账号密码，再重新启动。"
                )
            self._trader.prepare(str(cfg_path))
            logger.info("easytrader 连接同花顺成功")
        except ImportError:
            raise RuntimeError(
                "未安装 easytrader，请运行：pip3 install easytrader"
            )

    # ── 公共接口 ──────────────────────────────────────────

    def buy(self, code: str, name: str, price: float,
            lots: int = DEFAULT_LOTS) -> str:
        shares = lots * 100
        if self.mode == "paper":
            result = paper.buy(code, name, price, shares)
            logger.info("模拟买入 %s %s股 @%.2f", code, shares, price)
            return result

        # easytrader 真实下单
        try:
            self._trader.buy(code, price=price, amount=shares)
            msg = f"✅ 已提交买入 {name}({code}) {shares}股 @{price:.2f}"
            logger.info(msg)
            return msg
        except Exception as e:
            msg = f"❌ 买入失败: {e}"
            logger.error(msg)
            return msg

    def sell(self, code: str, name: str, price: float,
             lots: Optional[int] = None) -> str:
        shares = lots * 100 if lots else None
        if self.mode == "paper":
            result = paper.sell(code, price, shares)
            logger.info("模拟卖出 %s @%.2f", code, price)
            return result

        # easytrader 真实下单
        try:
            sell_amount = shares or 0   # 0 = 全部
            self._trader.sell(code, price=price, amount=sell_amount)
            msg = f"✅ 已提交卖出 {name}({code}) @{price:.2f}"
            logger.info(msg)
            return msg
        except Exception as e:
            msg = f"❌ 卖出失败: {e}"
            logger.error(msg)
            return msg

    def summary(self) -> str:
        if self.mode == "paper":
            return paper.summary()
        # easytrader 查询持仓
        try:
            pos = self._trader.position
            return str(pos)
        except Exception as e:
            return f"持仓查询失败: {e}"
