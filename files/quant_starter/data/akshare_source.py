"""
AKShare 数据源封装

特点：
- 完全免费，无需注册
- 数据源广，覆盖另类数据（北向资金、龙虎榜等）
- 稳定性依赖上游网站，建议盘后跑、控制请求间隔

用作 Tushare 的补充和备份
"""
import logging
import time
import pandas as pd

from utils.symbol import to_akshare_code
from utils.date_utils import to_tushare_date, DateLike
from utils.retry import call_with_retry

logger = logging.getLogger(__name__)


class AkshareSource:
    """AKShare 数据接口封装"""

    def __init__(self, request_interval: float = 0.2):
        """
        Args:
            request_interval: 成功请求后的限流等待（秒）
        """
        import akshare as ak
        self.ak = ak
        self.request_interval = request_interval

    def _sleep(self):
        """限流等待，仅在成功请求后调用"""
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

        Returns:
            DataFrame: trade_date, open, high, low, close, vol, amount, ...
            失败时返回空 DataFrame
        """
        symbol = to_akshare_code(code)
        start_date = to_tushare_date(start)
        end_date = to_tushare_date(end)
        logger.debug("get_daily: %s %s→%s adj=%s", symbol, start_date, end_date, adjust)

        df = call_with_retry(
            lambda: self.ak.stock_zh_a_hist(
                symbol=symbol,
                period="daily",
                start_date=start_date,
                end_date=end_date,
                adjust=adjust,
            ),
            caller="AkshareSource.get_daily",
        )
        self._sleep()

        if df.empty:
            logger.info("get_daily: 空结果 %s", symbol)
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
        logger.debug("get_stock_list")
        df = call_with_retry(
            lambda: self.ak.stock_info_a_code_name(),
            caller="AkshareSource.get_stock_list",
        )
        self._sleep()
        if df.empty:
            return df
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

        logger.debug("get_index_daily: %s %s→%s", code, start, end)

        df = call_with_retry(
            lambda: self.ak.stock_zh_index_daily(symbol=code),
            caller="AkshareSource.get_index_daily",
        )
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
        logger.debug("get_north_money")
        df = call_with_retry(
            lambda: self.ak.stock_hsgt_hist_em(symbol="北向资金"),
            caller="AkshareSource.get_north_money",
        )
        self._sleep()
        return df

    def get_index_components(self, index_code: str = "000300") -> pd.DataFrame:
        """
        获取指数成分股
        index_code: 000300 沪深300 / 000905 中证500 / 000852 中证1000
        """
        logger.debug("get_index_components: %s", index_code)
        df = call_with_retry(
            lambda: self.ak.index_stock_cons(symbol=index_code),
            caller="AkshareSource.get_index_components",
        )
        self._sleep()
        return df
