"""
基础使用示例

运行方式：
    cd quant_starter
    python examples/01_basic_usage.py
"""
import sys
from pathlib import Path

# 把项目根目录加入路径，方便直接运行
sys.path.insert(0, str(Path(__file__).parent.parent))

from data_loader import DataLoader


def demo_daily_kline():
    """示例 1: 获取单只股票的日线数据"""
    print("\n=== 示例 1: 平安银行（000001）日线 ===")
    loader = DataLoader()

    df = loader.get_daily(
        code="000001",          # 平安银行
        start="20240101",
        end="20241231",
        adjust="qfq",           # 前复权
    )
    print(f"数据形状: {df.shape}")
    print(df.head())
    print(f"\n字段: {list(df.columns)}")


def demo_index_kline():
    """示例 2: 获取沪深 300 指数"""
    print("\n=== 示例 2: 沪深 300 指数 ===")
    loader = DataLoader()

    df = loader.get_index_daily(
        code="000300.SH",
        start="20240101",
        end="20241231",
    )
    print(f"数据形状: {df.shape}")
    print(df.head())


def demo_stock_list():
    """示例 3: 获取股票列表"""
    print("\n=== 示例 3: A 股股票列表 ===")
    loader = DataLoader()

    df = loader.get_stock_list()
    print(f"股票总数: {len(df)}")
    print(df.head())


def demo_simple_strategy():
    """
    示例 4: 简单策略——计算 20 日均线和 RSI
    （只是演示数据流，不是有效策略）
    """
    print("\n=== 示例 4: 计算技术指标 ===")
    loader = DataLoader()

    df = loader.get_daily("600519", "20230101", "20241231")  # 贵州茅台

    # 20 日均线
    df["ma20"] = df["close"].rolling(20).mean()

    # RSI（相对强弱指标）
    delta = df["close"].diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = -delta.where(delta < 0, 0).rolling(14).mean()
    rs = gain / loss
    df["rsi14"] = 100 - 100 / (1 + rs)

    print(df[["trade_date", "close", "ma20", "rsi14"]].tail(10))


if __name__ == "__main__":
    demo_daily_kline()
    demo_index_kline()
    demo_stock_list()
    demo_simple_strategy()
