"""
统一数据加载器

核心思路：
- 策略代码只调用 DataLoader，不直接依赖 Tushare 或 AKShare
- 内部根据可用性自动选择数据源
- 支持本地缓存（parquet），减少重复请求

后期可以扩展：
- 数据库存储（PostgreSQL / ClickHouse）
- 增量更新
- 数据校验（不同源对比）
"""
from typing import Optional, Literal
from pathlib import Path
import pandas as pd

from config import DATA_CACHE_DIR, has_tushare_token
from utils.symbol import to_six_digit
from utils.date_utils import to_tushare_date, DateLike

DataSource = Literal["tushare", "akshare", "auto"]


class DataLoader:
    """
    统一数据加载接口

    使用示例:
        loader = DataLoader()
        df = loader.get_daily('000001', '20240101', '20241231')
    """

    def __init__(
        self,
        source: DataSource = "auto",
        use_cache: bool = True,
    ):
        """
        Args:
            source: 'tushare' / 'akshare' / 'auto'（自动选择）
            use_cache: 是否使用本地 parquet 缓存
        """
        self.use_cache = use_cache
        self._tushare = None
        self._akshare = None

        # 决定主数据源
        if source == "auto":
            self.primary = "tushare" if has_tushare_token() else "akshare"
        else:
            self.primary = source

        # 缓存目录
        self.cache_dir = Path(DATA_CACHE_DIR) / "daily"
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    @property
    def tushare(self):
        """懒加载 Tushare 客户端"""
        if self._tushare is None:
            from data.tushare_source import TushareSource
            self._tushare = TushareSource()
        return self._tushare

    @property
    def akshare(self):
        """懒加载 AKShare 客户端"""
        if self._akshare is None:
            from data.akshare_source import AkshareSource
            self._akshare = AkshareSource()
        return self._akshare

    # -------------------- 日线数据 --------------------

    def get_daily(
        self,
        code: str,
        start: DateLike,
        end: DateLike,
        adjust: str = "qfq",
        source: Optional[DataSource] = None,
    ) -> pd.DataFrame:
        """
        获取日线数据（带缓存）

        Args:
            code: 股票代码（6 位或带后缀均可）
            start, end: 起止日期
            adjust: qfq 前复权 / hfq 后复权 / None 不复权
            source: 强制使用某个数据源，None 表示用主数据源

        Returns:
            DataFrame: trade_date, open, high, low, close, vol, amount
        """
        src = source or self.primary
        cache_key = self._cache_key(code, start, end, adjust, src)
        cache_path = self.cache_dir / f"{cache_key}.parquet"

        # 缓存命中
        if self.use_cache and cache_path.exists():
            return pd.read_parquet(cache_path)

        # 获取数据
        if src == "tushare":
            df = self.tushare.get_daily(code, start, end, adjust=adjust)
        elif src == "akshare":
            df = self.akshare.get_daily(code, start, end, adjust=adjust)
        else:
            raise ValueError(f"Unknown source: {src}")

        # 写缓存
        if self.use_cache and not df.empty:
            df.to_parquet(cache_path, index=False)

        return df

    # -------------------- 股票列表 --------------------

    def get_stock_list(self) -> pd.DataFrame:
        """获取 A 股股票列表"""
        if self.primary == "tushare":
            return self.tushare.get_stock_list()
        return self.akshare.get_stock_list()

    # -------------------- 指数数据 --------------------

    def get_index_daily(
        self,
        code: str,
        start: DateLike,
        end: DateLike,
    ) -> pd.DataFrame:
        """获取指数日线"""
        if self.primary == "tushare":
            return self.tushare.get_index_daily(code, start, end)
        return self.akshare.get_index_daily(code, start, end)

    # -------------------- 交易日历 --------------------

    def get_trade_calendar(
        self,
        start: DateLike,
        end: DateLike,
    ) -> pd.DataFrame:
        """获取交易日历（仅 Tushare 提供）"""
        if not has_tushare_token():
            raise RuntimeError("交易日历需要 Tushare token")
        return self.tushare.get_trade_calendar(start, end)

    # -------------------- 基本面数据 --------------------

    def get_daily_basic(
        self,
        code: str,
        start: DateLike,
        end: DateLike,
    ) -> pd.DataFrame:
        """获取每日基本面（PE/PB/市值等）—— 需要 Tushare token"""
        return self.tushare.get_daily_basic(code, start, end)

    # -------------------- 内部工具 --------------------

    def _cache_key(
        self,
        code: str,
        start: DateLike,
        end: DateLike,
        adjust: str,
        source: str,
    ) -> str:
        """生成缓存文件名"""
        c = to_six_digit(code)
        s = to_tushare_date(start)
        e = to_tushare_date(end)
        adj = adjust or "none"
        return f"{c}_{s}_{e}_{adj}_{source}"

    def clear_cache(self):
        """清空所有缓存"""
        for f in self.cache_dir.glob("*.parquet"):
            f.unlink()
