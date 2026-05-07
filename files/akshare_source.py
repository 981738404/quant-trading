"""
AKShare 数据源封装

特点：
- 完全免费，无需注册
- 数据源广，覆盖另类数据（北向资金、龙虎榜等）
- 稳定性依赖上游网站，建议盘后跑、控制请求间隔

用作 Tushare 的补充和备份
"""
from typing import Optional
import time
import pandas as pd

from utils.symbol import to_akshare_code
from utils.date_utils import to_tushare_date, DateLike


class AkshareSource:
    """AKShare 数据接口封装"""

    def __init__(self, request_interval: float = 0.2):
        """
        Args:
            request_interval: 请求间隔（秒），避免被限流
        """
        import akshare as ak
        self.ak = ak
        self.request_interval = request_interval

    def _sleep(self):
        if self.request_interval > 0:
            time.sleep(self.request_interval)

    def get_daily(
        self,
        code: str,
        start: DateLike,
        end: DateLike,
        adjust: str = "qfq",
    ) -> pd.DataFrame:
        """
        获取日线行情

        Args:
            code: 6 位股票代码
            adjust: 'qfq' 前复权 / 'hfq' 后复权 / '' 不复权
        """
        symbol = to_akshare_code(code)
        df = self.ak.stock_zh_a_hist(
            symbol=symbol,
            period="daily",
            start_date=to_tushare_date(start),
            end_date=to_tushare_date(end),
            adjust=adjust,
        )
        self._sleep()

        if df.empty:
            return df

        # 字段重命名为统一格式（AKShare 返回中文字段名）
        df = df.rename(columns={
            "日期": "trade_date",
            "开盘": "open",
            "最高": "high",
            "最低": "low",
            "收盘": "close",
            "成交量": "vol",
            "成交额": "amount",
            "振幅": "amplitude",
            "涨跌幅": "pct_chg",
            "涨跌额": "change",
            "换手率": "turnover_rate",
        })
        df["trade_date"] = pd.to_datetime(df["trade_date"])
        df = df.sort_values("trade_date").reset_index(drop=True)
        return df

    def get_stock_list(self) -> pd.DataFrame:
        """获取所有 A 股股票列表"""
        # 沪深京 A 股
        df = self.ak.stock_info_a_code_name()
        self._sleep()
        df = df.rename(columns={"code": "symbol", "name": "name"})
        return df

    def get_index_daily(
        self,
        code: str,
        start: DateLike,
        end: DateLike,
    ) -> pd.DataFrame:
        """
        获取指数日线
        常用代码：
            sh000001 - 上证综指
            sh000300 - 沪深 300
            sh000905 - 中证 500
            sz399006 - 创业板指
        """
        # AKShare 指数接口需要带前缀
        if not code.startswith(("sh", "sz")):
            six = to_akshare_code(code)
            prefix = "sh" if six.startswith(("0", "6")) else "sz"
            code = f"{prefix}{six}"

        df = self.ak.stock_zh_index_daily(symbol=code)
        self._sleep()

        if df.empty:
            return df

        df["date"] = pd.to_datetime(df["date"])
        df = df.rename(columns={"date": "trade_date", "volume": "vol"})

        # 过滤日期范围
        start_dt = pd.to_datetime(to_tushare_date(start))
        end_dt = pd.to_datetime(to_tushare_date(end))
        df = df[(df["trade_date"] >= start_dt) & (df["trade_date"] <= end_dt)]
        return df.sort_values("trade_date").reset_index(drop=True)

    def get_north_money(self) -> pd.DataFrame:
        """
        获取北向资金（沪股通+深股通）历史数据
        AKShare 的特色数据之一
        """
        df = self.ak.stock_hsgt_hist_em(symbol="北向资金")
        self._sleep()
        return df

    def get_index_components(self, index_code: str = "000300") -> pd.DataFrame:
        """
        获取指数成分股
        index_code: 000300 沪深300 / 000905 中证500 / 000852 中证1000
        """
        df = self.ak.index_stock_cons(symbol=index_code)
        self._sleep()
        return df
