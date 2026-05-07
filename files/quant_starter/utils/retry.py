"""
通用重试工具（指数退避）
供 AkshareSource 和 TushareSource 共用，避免代码重复。
"""
import time
import logging
import pandas as pd
from typing import Callable, TypeVar

logger = logging.getLogger(__name__)
T = TypeVar("T")

_MAX_RETRIES = 3
_RETRY_BASE_SECONDS = 1.0


def call_with_retry(
    fn: Callable[[], T],
    max_retries: int = _MAX_RETRIES,
    base_seconds: float = _RETRY_BASE_SECONDS,
    caller: str = "",
) -> T:
    """
    重试包装器，指数退避。
    网络/API 异常时最多重试 max_retries 次。
    最终失败返回空 DataFrame，并记录 ERROR 日志。

    Args:
        fn: 无参可调用对象，内部封装一次 API 请求
        max_retries: 最大尝试次数（含首次）
        base_seconds: 退避基数，第 n 次重试等待 base_seconds * 2^(n-1) 秒
        caller: 调用方名称，用于日志前缀
    """
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        if attempt > 0:
            wait = base_seconds * (2 ** (attempt - 1))
            logger.warning(
                "%s 第 %d/%d 次尝试失败，%.1fs 后重试: %s",
                caller, attempt, max_retries, wait, last_exc,
            )
            time.sleep(wait)
        try:
            return fn()
        except Exception as exc:
            last_exc = exc
    logger.error("%s 全部 %d 次尝试失败: %s", caller, max_retries, last_exc)
    return pd.DataFrame()
