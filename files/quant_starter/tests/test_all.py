"""
完整测试套件 — quant_starter
运行方式:
    cd quant_starter
    pytest tests/test_all.py -v
    pytest tests/test_all.py -v -k "rsi"        # 只跑 RSI 相关
    pytest tests/test_all.py -v --tb=short       # 简短错误栈
"""
import sys
from pathlib import Path
from datetime import datetime, date
from unittest.mock import MagicMock, patch
import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


# ===========================================================================
# SECTION 1: date_utils 测试
# ===========================================================================

from utils.date_utils import to_tushare_date, to_dash_date, today_str


class TestToTushareDate:
    """to_tushare_date() — 各种输入格式转换为 YYYYMMDD"""

    def test_yyyymmdd_string_passthrough(self):
        assert to_tushare_date("20240101") == "20240101"

    def test_dash_string_converted(self):
        assert to_tushare_date("2024-01-01") == "20240101"

    def test_slash_string_converted(self):
        assert to_tushare_date("2024/01/01") == "20240101"

    def test_datetime_object(self):
        assert to_tushare_date(datetime(2024, 1, 1)) == "20240101"

    def test_date_object(self):
        assert to_tushare_date(date(2024, 12, 31)) == "20241231"

    def test_year_end(self):
        assert to_tushare_date("20231231") == "20231231"

    def test_invalid_short_string_raises(self):
        with pytest.raises(ValueError):
            to_tushare_date("2024-1-1")  # 去掉 - 后长度 ≠ 8

    def test_invalid_type_raises(self):
        with pytest.raises(TypeError):
            to_tushare_date(20240101)  # int 不支持


class TestToDashDate:
    """to_dash_date() — 转换为 YYYY-MM-DD"""

    def test_from_yyyymmdd(self):
        assert to_dash_date("20240101") == "2024-01-01"

    def test_from_datetime(self):
        assert to_dash_date(datetime(2024, 6, 15)) == "2024-06-15"

    def test_from_date(self):
        assert to_dash_date(date(2023, 12, 31)) == "2023-12-31"

    def test_from_dash_string(self):
        assert to_dash_date("2024-03-08") == "2024-03-08"


class TestTodayStr:
    """today_str() — 基本冒烟测试"""

    def test_tushare_format_is_8_digits(self):
        result = today_str("tushare")
        assert len(result) == 8 and result.isdigit()

    def test_dash_format_shape(self):
        result = today_str("dash")
        assert len(result) == 10
        assert result[4] == "-" and result[7] == "-"


# ===========================================================================
# SECTION 2: symbol utils 测试
# ===========================================================================

from utils.symbol import to_tushare_code, to_akshare_code, to_six_digit, get_exchange


class TestToTushareCode:
    """to_tushare_code() — 6 位代码转 Tushare 格式"""

    def test_sh_stock_600xxx(self):
        assert to_tushare_code("600519") == "600519.SH"

    def test_sh_stock_688xxx(self):
        assert to_tushare_code("688001") == "688001.SH"

    def test_sz_stock_000xxx(self):
        assert to_tushare_code("000001") == "000001.SZ"

    def test_sz_stock_300xxx(self):
        assert to_tushare_code("300750") == "300750.SZ"

    def test_bj_stock_8xxxxx(self):
        assert to_tushare_code("835319") == "835319.BJ"

    def test_already_tushare_format_passthrough(self):
        assert to_tushare_code("600519.SH") == "600519.SH"

    def test_lowercase_suffix_uppercased(self):
        assert to_tushare_code("000001.sz") == "000001.SZ"

    def test_5digit_raises(self):
        with pytest.raises(ValueError):
            to_tushare_code("12345")

    def test_7digit_raises(self):
        with pytest.raises(ValueError):
            to_tushare_code("1234567")

    def test_non_digit_raises(self):
        with pytest.raises(ValueError):
            to_tushare_code("ABCDEF")


class TestToAkshareCode:
    """to_akshare_code() — 任意格式转 6 位"""

    def test_six_digit_passthrough(self):
        assert to_akshare_code("000001") == "000001"

    def test_strips_sh_suffix(self):
        assert to_akshare_code("600519.SH") == "600519"

    def test_strips_sz_suffix(self):
        assert to_akshare_code("000001.SZ") == "000001"


class TestGetExchange:
    """get_exchange() — 返回 SH / SZ / BJ"""

    def test_sh_exchange_6(self):
        assert get_exchange("600519") == "SH"

    def test_sz_exchange_0(self):
        assert get_exchange("000001") == "SZ"

    def test_sz_exchange_3(self):
        assert get_exchange("300750") == "SZ"

    def test_bj_exchange_8(self):
        assert get_exchange("835319") == "BJ"

    def test_from_tushare_code(self):
        assert get_exchange("600519.SH") == "SH"

    def test_unknown_prefix_raises(self):
        with pytest.raises(ValueError):
            get_exchange("100001")


# ===========================================================================
# SECTION 3: DataLoader._cache_key 测试
# ===========================================================================

from data.data_loader import DataLoader


class TestDataLoaderCacheKey:
    """DataLoader._cache_key() — 缓存键唯一性与格式"""

    def setup_method(self):
        self.loader = DataLoader(source="akshare", use_cache=False)

    def test_basic_key_format(self):
        key = self.loader._cache_key("000001", "20240101", "20241231", "qfq", "akshare")
        assert key == "000001_20240101_20241231_qfq_akshare"

    def test_tushare_suffix_stripped(self):
        key = self.loader._cache_key("600519.SH", "20240101", "20241231", "qfq", "tushare")
        assert key == "600519_20240101_20241231_qfq_tushare"

    def test_none_adjust_becomes_none_string(self):
        key = self.loader._cache_key("000001", "20240101", "20241231", None, "akshare")
        assert key == "000001_20240101_20241231_none_akshare"

    def test_dash_date_normalized(self):
        key = self.loader._cache_key("000001", "2024-01-01", "2024-12-31", "qfq", "akshare")
        assert key == "000001_20240101_20241231_qfq_akshare"

    def test_different_sources_give_different_keys(self):
        k1 = self.loader._cache_key("000001", "20240101", "20241231", "qfq", "akshare")
        k2 = self.loader._cache_key("000001", "20240101", "20241231", "qfq", "tushare")
        assert k1 != k2

    def test_different_adjust_give_different_keys(self):
        k1 = self.loader._cache_key("000001", "20240101", "20241231", "qfq", "akshare")
        k2 = self.loader._cache_key("000001", "20240101", "20241231", "hfq", "akshare")
        assert k1 != k2


# ===========================================================================
# SECTION 4: DataLoader 日期校验测试
# ===========================================================================

class TestDataLoaderDateValidation:
    """DataLoader.get_daily() — start > end 时抛出 ValueError"""

    def setup_method(self):
        self.loader = DataLoader(source="akshare", use_cache=False)

    def test_end_before_start_raises(self):
        with pytest.raises(ValueError, match="必须"):
            self.loader.get_daily("000001", "20241231", "20240101")

    def test_same_date_is_allowed(self):
        # 直接注入 _akshare，绕过 property 的懒加载（避免 import akshare）
        mock_ak = MagicMock()
        mock_ak.get_daily.return_value = pd.DataFrame()
        self.loader._akshare = mock_ak
        result = self.loader.get_daily("000001", "20240101", "20240101")
        assert isinstance(result, pd.DataFrame)

    def test_valid_range_calls_source(self):
        expected = pd.DataFrame({"trade_date": ["2024-01-02"], "close": [10.0]})
        mock_ak = MagicMock()
        mock_ak.get_daily.return_value = expected
        self.loader._akshare = mock_ak
        result = self.loader.get_daily("000001", "20240101", "20241231")
        mock_ak.get_daily.assert_called_once()
        assert len(result) == 1

    def test_dash_date_format_also_validated(self):
        with pytest.raises(ValueError):
            self.loader.get_daily("000001", "2024-12-31", "2024-01-01")


# ===========================================================================
# SECTION 5: AkshareSource 重试与错误处理测试
# ===========================================================================

from data.akshare_source import AkshareSource


def _make_akshare_source(mock_ak_module):
    """创建 AkshareSource，注入 mock 的 akshare 模块"""
    src = AkshareSource.__new__(AkshareSource)
    src.ak = mock_ak_module
    src.request_interval = 0.0  # 测试中不等待
    return src


class TestAkshareSourceRetry:
    """AkshareSource — 网络错误时重试并返回空 DataFrame"""

    def test_network_error_returns_empty_df(self):
        mock_ak = MagicMock()
        mock_ak.stock_zh_a_hist.side_effect = ConnectionError("timeout")
        src = _make_akshare_source(mock_ak)

        with patch("utils.retry.time.sleep"):
            result = src.get_daily("000001", "20240101", "20241231")

        assert isinstance(result, pd.DataFrame) and result.empty

    def test_retries_3_times_on_failure(self):
        mock_ak = MagicMock()
        mock_ak.stock_zh_a_hist.side_effect = ConnectionError("timeout")
        src = _make_akshare_source(mock_ak)

        with patch("utils.retry.time.sleep"):
            src.get_daily("000001", "20240101", "20241231")

        assert mock_ak.stock_zh_a_hist.call_count == 3

    def test_succeeds_on_second_attempt(self):
        mock_ak = MagicMock()
        good_df = pd.DataFrame({
            "日期": ["2024-01-02"],
            "开盘": [10.0], "最高": [10.5], "最低": [9.8], "收盘": [10.2],
            "成交量": [1000], "成交额": [10200.0],
            "振幅": [0.7], "涨跌幅": [0.5], "涨跌额": [0.05], "换手率": [0.3],
        })
        mock_ak.stock_zh_a_hist.side_effect = [ConnectionError("timeout"), good_df]
        src = _make_akshare_source(mock_ak)

        with patch("utils.retry.time.sleep"):
            result = src.get_daily("000001", "20240101", "20241231")

        assert not result.empty
        assert "close" in result.columns
        assert mock_ak.stock_zh_a_hist.call_count == 2

    def test_empty_api_response_returned_as_is(self):
        mock_ak = MagicMock()
        mock_ak.stock_zh_a_hist.return_value = pd.DataFrame()
        src = _make_akshare_source(mock_ak)

        result = src.get_daily("000001", "20240101", "20241231")
        assert isinstance(result, pd.DataFrame) and result.empty

    def test_columns_renamed_to_english(self):
        mock_ak = MagicMock()
        mock_ak.stock_zh_a_hist.return_value = pd.DataFrame({
            "日期": ["2024-01-02"], "开盘": [10.0], "最高": [10.5],
            "最低": [9.8], "收盘": [10.2], "成交量": [1000], "成交额": [10200.0],
            "振幅": [0.7], "涨跌幅": [0.5], "涨跌额": [0.05], "换手率": [0.3],
        })
        src = _make_akshare_source(mock_ak)

        result = src.get_daily("000001", "20240101", "20241231")
        expected_cols = {"trade_date", "open", "high", "low", "close",
                         "vol", "amount", "amplitude", "pct_chg", "change", "turnover_rate"}
        assert expected_cols.issubset(set(result.columns))

    def test_rate_limit_sleep_called_once_on_success(self):
        """成功后只触发一次限流等待，不在重试等待中多次调用"""
        mock_ak = MagicMock()
        mock_ak.stock_zh_a_hist.return_value = pd.DataFrame({
            "日期": ["2024-01-02"], "开盘": [10.0], "最高": [10.5],
            "最低": [9.8], "收盘": [10.2], "成交量": [1000], "成交额": [10200.0],
            "振幅": [0.7], "涨跌幅": [0.5], "涨跌额": [0.05], "换手率": [0.3],
        })
        src = _make_akshare_source(mock_ak)
        src.request_interval = 0.2

        with patch("utils.retry.time.sleep"), \
             patch("data.akshare_source.time.sleep") as mock_sleep:
            src.get_daily("000001", "20240101", "20241231")

        # _sleep() 只调用一次（限流），不含重试等待
        mock_sleep.assert_called_once_with(0.2)


# ===========================================================================
# SECTION 6: RSI 计算正确性测试
# ===========================================================================

def _compute_rsi(prices: list, period: int = 14) -> pd.Series:
    """复制 examples/01_basic_usage.py 中修复后的 RSI 逻辑"""
    s = pd.Series(prices, dtype=float)
    delta = s.diff()
    gain = delta.where(delta > 0, 0.0).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(period).mean()
    rs = gain / loss.replace(0, float("nan"))
    rsi = 100 - 100 / (1 + rs)
    rsi[(loss == 0) & (gain > 0)] = 100.0
    return rsi


class TestRSICalculation:
    """RSI 修复后的正确性验证"""

    def test_all_up_bars_gives_100(self):
        prices = [float(i) for i in range(1, 20)]
        rsi = _compute_rsi(prices)
        valid = rsi.dropna()
        assert all(v == 100.0 for v in valid), f"期望全部 100，实际: {valid.values}"

    def test_all_down_bars_gives_0(self):
        prices = [float(20 - i) for i in range(20)]
        rsi = _compute_rsi(prices)
        valid = rsi.dropna()
        assert all(v == 0.0 for v in valid), f"期望全部 0，实际: {valid.values}"

    def test_flat_prices_gives_nan(self):
        prices = [10.0] * 20
        rsi = _compute_rsi(prices)
        assert all(pd.isna(v) for v in rsi.iloc[14:]), "完全平盘时 RSI 应为 NaN"

    def test_rsi_within_0_100(self):
        import random
        random.seed(42)
        prices = [100.0]
        for _ in range(50):
            prices.append(prices[-1] * (1 + random.uniform(-0.03, 0.03)))
        rsi = _compute_rsi(prices)
        valid = rsi.dropna()
        assert all(0.0 <= v <= 100.0 for v in valid), \
            f"RSI 越界: {valid[~valid.between(0, 100)]}"

    def test_no_inf_values(self):
        prices = list(range(1, 20))  # 全部上涨
        rsi = _compute_rsi(prices)
        assert not any(np.isinf(v) for v in rsi.dropna()), "不应出现 inf（除零 bug）"

    def test_alternating_gives_midrange(self):
        base = 100.0
        prices = []
        for i in range(30):
            base += 1.0 if i % 2 == 0 else -1.0
            prices.append(base)
        rsi = _compute_rsi(prices)
        valid = rsi.dropna()
        assert all(20.0 <= v <= 80.0 for v in valid), \
            f"交替涨跌时 RSI 应在中间区域，实际: {valid.values}"

    def test_first_period_minus_1_are_nan(self):
        # diff() 把 index=0 的 NaN 经 .where() 转为 0.0，rolling(14) 在 index=13 已有 14 个值。
        # 因此 NaN 区间为 index 0..12（共 period-1=13 个），index=13 起为有效值。
        prices = list(range(1, 25))
        rsi = _compute_rsi(prices, period=14)
        for i in range(13):  # 0..12
            assert pd.isna(rsi.iloc[i]), f"索引 {i} 应为 NaN，实际 {rsi.iloc[i]}"
        assert not pd.isna(rsi.iloc[13]), "索引 13 应已有有效 RSI 值"
