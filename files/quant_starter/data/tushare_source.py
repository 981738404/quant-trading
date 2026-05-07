"""
Tushare Pro 数据源封装

特点：
- 数据规范、质量高，适合做基本面量化
- 部分高级接口需要积分（如分钟线、Level-2）
- 频控相对严格

注意事项：
- 务必使用前复权（qfq）数据回测，避免除权除息造成的价格跳跃
- Tushare 的 daily 接口返回的是不复权价格，复权需要使用 pro_bar
"""
import logging
import pandas as pd

from config import TUSHARE_TOKEN, has_tushare_token
from utils.symbol import to_tushare_code
from utils.date_utils import to_tushare_date, DateLike
from utils.retry import call_with_retry

logger = logging.getLogger(__name__)


class TushareSource:
    """Tushare Pro API 封装"""

    def __init__(self):
        if not has_tushare_token():
            raise RuntimeError(
                "Tushare token 未配置。请在 .env 中设置 TUSHARE_TOKEN，"
                "或访问 https://tushare.pro/register 注册获取。"
            )
        import tushare as ts
        ts.set_token(TUSHARE_TOKEN)
        self.pro = ts.pro_api()
        self.ts = ts

    def get_daily(
        self,
        code: str,
        start: DateLike,
        end: DateLike,
        adjust: str = "qfq",
    ) -> pd.DataFrame:
        """
        获取日线行情（带复权）

        Args:
            code: 股票代码（任意格式，会自动转换）
            start: 起始日期
            end: 结束日期
            adjust: 复权方式，'qfq' 前复权 / 'hfq' 后复权 / None 不复权

        Returns:
            DataFrame 字段: trade_date, open, high, low, close, vol, amount
            按时间升序排列，失败时返回空 DataFrame
        """
        ts_code = to_tushare_code(code)
        start_date = to_tushare_date(start)
        end_date = to_tushare_date(end)
        logger.debug("get_daily: %s %s→%s adj=%s", ts_code, start_date, end_date, adjust)

        def _fetch():
            result = self.ts.pro_bar(
                ts_code=ts_code,
                start_date=start_date,
                end_date=end_date,
                adj=adjust,
                asset="E",
            )
            if result is None:
                raise ValueError("pro_bar 返回 None（可能触发频控或 token 无效）")
            return result

        df = call_with_retry(_fetch, caller="TushareSource.get_daily")

        if df.empty:
            logger.info("get_daily: 空结果 %s", ts_code)
            return pd.DataFrame()

        df = df.sort_values("trade_date").reset_index(drop=True)
        df["trade_date"] = pd.to_datetime(df["trade_date"])
        return df

    def get_stock_list(self, list_status: str = "L") -> pd.DataFrame:
        """
        获取股票列表

        Args:
            list_status: L 上市 / D 退市 / P 暂停上市

        Returns:
            DataFrame 字段: ts_code, symbol, name, area, industry, list_date
        """
        logger.debug("get_stock_list: status=%s", list_status)

        def _fetch():
            return self.pro.stock_basic(
                exchange="",
                list_status=list_status,
                fields="ts_code,symbol,name,area,industry,market,list_date,delist_date",
            )

        return call_with_retry(_fetch, caller="TushareSource.get_stock_list")

    def get_trade_calendar(
        self,
        start: DateLike,
        end: DateLike,
        exchange: str = "SSE",
    ) -> pd.DataFrame:
        """
        获取交易日历

        Args:
            exchange: SSE 上交所 / SZSE 深交所
        """
        logger.debug("get_trade_calendar: %s %s→%s", exchange, start, end)

        def _fetch():
            df = self.pro.trade_cal(
                exchange=exchange,
                start_date=to_tushare_date(start),
                end_date=to_tushare_date(end),
                is_open="1",
            )
            df["cal_date"] = pd.to_datetime(df["cal_date"])
            return df

        return call_with_retry(_fetch, caller="TushareSource.get_trade_calendar")

    def get_index_daily(
        self,
        code: str,
        start: DateLike,
        end: DateLike,
    ) -> pd.DataFrame:
        """
        获取指数日线
        常用代码：
            000001.SH - 上证综指
            000300.SH - 沪深 300
            000905.SH - 中证 500
            399006.SZ - 创业板指
        """
        ts_code = to_tushare_code(code)
        logger.debug("get_index_daily: %s %s→%s", ts_code, start, end)

        df = call_with_retry(
            lambda: self.pro.index_daily(
                ts_code=ts_code,
                start_date=to_tushare_date(start),
                end_date=to_tushare_date(end),
            ),
            caller="TushareSource.get_index_daily",
        )
        if df.empty:
            return df
        df = df.sort_values("trade_date").reset_index(drop=True)
        df["trade_date"] = pd.to_datetime(df["trade_date"])
        return df

    def get_financial_indicator(
        self,
        code: str,
        start: DateLike,
        end: DateLike,
    ) -> pd.DataFrame:
        """
        获取财务指标（PE、PB、ROE 等）

        返回字段示例: end_date, eps, dt_eps, total_revenue_ps, roe, roa, ...
        """
        ts_code = to_tushare_code(code)
        logger.debug("get_financial_indicator: %s %s→%s", ts_code, start, end)
        return call_with_retry(
            lambda: self.pro.fina_indicator(
                ts_code=ts_code,
                start_date=to_tushare_date(start),
                end_date=to_tushare_date(end),
            ),
            caller="TushareSource.get_financial_indicator",
        )

    def get_daily_basic(
        self,
        code: str,
        start: DateLike,
        end: DateLike,
    ) -> pd.DataFrame:
        """
        获取每日基本面指标（PE、PB、市值、换手率等，按日更新）

        返回字段: trade_date, pe, pe_ttm, pb, ps, ps_ttm,
                 total_share, float_share, total_mv, circ_mv, turnover_rate
        """
        ts_code = to_tushare_code(code)
        logger.debug("get_daily_basic: %s %s→%s", ts_code, start, end)

        df = call_with_retry(
            lambda: self.pro.daily_basic(
                ts_code=ts_code,
                start_date=to_tushare_date(start),
                end_date=to_tushare_date(end),
            ),
            caller="TushareSource.get_daily_basic",
        )
        if df.empty:
            return df
        df = df.sort_values("trade_date").reset_index(drop=True)
        df["trade_date"] = pd.to_datetime(df["trade_date"])
        return df
