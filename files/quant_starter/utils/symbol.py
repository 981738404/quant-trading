"""
股票代码格式工具
不同数据源使用的股票代码格式不一致：
- Tushare: 000001.SZ / 600000.SH
- AKShare: 000001 / 600000（部分接口需要 sz000001 / sh600000）
- 通用 6 位: 000001 / 600000
本模块提供统一的代码转换函数
"""


def to_tushare_code(code: str) -> str:
    """
    转换为 Tushare 格式: 000001.SZ / 600000.SH / 688001.SH / 300001.SZ

    Args:
        code: 6 位股票代码或带后缀的代码

    Returns:
        Tushare 格式代码
    """
    # 已经是 Tushare 格式
    if "." in code:
        return code.upper()

    code = code.strip()
    if len(code) != 6 or not code.isdigit():
        raise ValueError(f"Invalid stock code: {code}")

    # 6 开头的是上交所，0/3 开头的是深交所，4/8 开头的是北交所
    if code.startswith("6"):
        return f"{code}.SH"
    elif code.startswith(("0", "3")):
        return f"{code}.SZ"
    elif code.startswith(("4", "8")):
        return f"{code}.BJ"
    else:
        raise ValueError(f"Cannot determine exchange for code: {code}")


def to_akshare_code(code: str) -> str:
    """
    转换为 AKShare 通用格式（6 位纯数字）
    """
    if "." in code:
        return code.split(".")[0]
    return code.strip()


def to_six_digit(code: str) -> str:
    """转换为 6 位股票代码"""
    return to_akshare_code(code)


def get_exchange(code: str) -> str:
    """获取交易所简称: SH / SZ / BJ"""
    six_digit = to_six_digit(code)
    if six_digit.startswith("6"):
        return "SH"
    elif six_digit.startswith(("0", "3")):
        return "SZ"
    elif six_digit.startswith(("4", "8")):
        return "BJ"
    raise ValueError(f"Unknown exchange for code: {code}")
