"""
全局配置模块
负责读取环境变量、设置数据缓存路径等
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# 加载 .env 文件
load_dotenv()

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.absolute()

# Tushare Token
TUSHARE_TOKEN = os.getenv("TUSHARE_TOKEN", "")

# 数据缓存目录
DATA_CACHE_DIR = Path(os.getenv("DATA_CACHE_DIR", PROJECT_ROOT / "cache"))
DATA_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# 默认参数
DEFAULT_ADJUST = "qfq"  # 前复权（用于回测）
DEFAULT_START_DATE = "20180101"  # 回测起始日期


def has_tushare_token() -> bool:
    """检查是否配置了 Tushare token"""
    return bool(TUSHARE_TOKEN and TUSHARE_TOKEN != "your_tushare_token_here")
