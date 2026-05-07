"""
日期格式工具
- Tushare: YYYYMMDD（如 20240101）
- AKShare: 部分用 YYYYMMDD，部分用 YYYY-MM-DD
- pandas: 通常用 YYYY-MM-DD 或 datetime
"""
from datetime import datetime, date
from typing import Union

DateLike = Union[str, datetime, date]


def to_tushare_date(d: DateLike) -> str:
    """转换为 Tushare 日期格式: YYYYMMDD"""
    if isinstance(d, str):
        # 处理 YYYY-MM-DD 或 YYYYMMDD
        d_clean = d.replace("-", "").replace("/", "")
        if len(d_clean) != 8:
            raise ValueError(f"Invalid date string: {d}")
        return d_clean
    if isinstance(d, (datetime, date)):
        return d.strftime("%Y%m%d")
    raise TypeError(f"Unsupported date type: {type(d)}")


def to_dash_date(d: DateLike) -> str:
    """转换为 YYYY-MM-DD 格式"""
    s = to_tushare_date(d)
    return f"{s[:4]}-{s[4:6]}-{s[6:8]}"


def today_str(format: str = "tushare") -> str:
    """获取今天的日期字符串"""
    if format == "tushare":
        return datetime.now().strftime("%Y%m%d")
    return datetime.now().strftime("%Y-%m-%d")
