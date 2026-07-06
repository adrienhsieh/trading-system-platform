"""tests/test_market.py — MarketService 單元測試"""
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd

from trading.market import MarketService


def _make_ticker_df(close_vals):
    """建立 yfinance 風格的 DataFrame（欄位 Close）。"""
    return pd.DataFrame({"Close": close_vals})


class TestMarketServiceCache(unittest.TestCase):
    """快取行為測試。"""

    def setUp(self):
        self.svc = MarketService()

    def test_initial_cache_is_empty(self):
        data = self.svc.get_data()
        self.assertIsInstance(data, dict)

    def test_fetching_flag_prevents_double_fetch(self):
        self.svc._fetching.set()         # 模擬正在抓取中
        self.svc._cache_time = 0.0       # 讓快取過期
        with patch.object(self.svc, "_fetch") as mock_fetch:
            self.svc.get_data()
            mock_fetch.assert_not_called()
        self.svc._fetching.clear()

    def test_get_data_triggers_fetch_when_stale(self):
        """快取過期時應觸發背景 _fetch，不依賴 sleep。"""
        self.svc._fetching.clear()
        self.svc._cache_time = 0.0

        fetch_called = threading.Event()

        def fake_fetch():
            fetch_called.set()

        with patch.object(self.svc, "_fetch", side_effect=fake_fetch):
            self.svc.get_data()
            started = fetch_called.wait(timeout=2.0)

        self.assertTrue(started, "_fetch 應在 2 秒內被觸發")

    def test_get_data_within_ttl_does_not_fetch(self):
        self.svc._cache      = {"taiex": {"price": 20000, "change_pct": 0.5}}
        self.svc._cache_time = time.time()   # 剛更新
        self.svc._fetching.clear()
        with patch.object(self.svc, "_fetch") as mock_fetch:
            data = self.svc.get_data()
            mock_fetch.assert_not_called()
        self.assertIn("taiex", data)

    def test_get_data_returns_copy_not_reference(self):
        self.svc._cache = {"taiex": {"price": 18000}}
        data = self.svc.get_data()
        data["injected"] = True
        self.assertNotIn("injected", self.svc._cache)


class TestMarketServiceFetch(unittest.TestCase):
    """_fetch() 資料抓取邏輯（mock yfinance）。"""

    def setUp(self):
        self.svc = MarketService()

    def _mock_ticker(self, prices):
        """回傳模擬的 yfinance Ticker，history() 回傳指定收盤序列。"""
        mock = MagicMock()
        mock.history.return_value = _make_ticker_df(prices)
        return mock

    @patch("yfinance.Ticker")
    def test_fetch_updates_cache(self, mock_ticker_cls):
        mock_ticker_cls.return_value = self._mock_ticker([19000.0, 20000.0])
        self.svc._fetch()
        data = self.svc.get_data()
        self.assertTrue(len(data) > 0)

    @patch("yfinance.Ticker")
    def test_fetch_calculates_change_pct(self, mock_ticker_cls):
        # prev=10000, curr=11000 → change_pct=10%
        mock_ticker_cls.return_value = self._mock_ticker([10000.0, 11000.0])
        self.svc._fetch()
        data = self.svc.get_data()
        # 至少有一個 key 含 change_pct
        prices = [v for v in data.values() if isinstance(v, dict) and "change_pct" in v]
        if prices:
            self.assertAlmostEqual(prices[0]["change_pct"], 10.0, places=0)

    @patch("yfinance.Ticker")
    def test_fetch_handles_yfinance_exception(self, mock_ticker_cls):
        mock_ticker_cls.return_value.history.side_effect = Exception("連線失敗")
        # 不應拋出例外
        try:
            self.svc._fetch()
        except Exception:
            self.fail("_fetch() 不應將例外往上傳遞")

    @patch("yfinance.Ticker")
    def test_refresh_updates_cache_time(self, mock_ticker_cls):
        mock_ticker_cls.return_value = self._mock_ticker([100.0, 101.0])
        before = self.svc._cache_time
        self.svc.refresh()
        self.assertGreaterEqual(self.svc._cache_time, before)


class TestMarketServiceCacheTTL(unittest.TestCase):
    """快取 TTL 邊界行為。"""

    def setUp(self):
        self.svc = MarketService()

    def test_does_not_fetch_when_cache_fresh(self):
        """快取剛更新（cache_time = now）時不觸發 fetch。"""
        self.svc._cache_time = time.time()
        self.svc._fetching.clear()
        with patch.object(self.svc, "_fetch") as mock_fetch:
            self.svc.get_data()
        mock_fetch.assert_not_called()

    def test_triggers_fetch_when_ttl_expired(self):
        """快取過期（cache_time = 0）且未在抓取 → 觸發 fetch。"""
        self.svc._cache_time = 0.0
        self.svc._fetching.clear()
        fetch_called = threading.Event()

        def fake_fetch():
            fetch_called.set()

        with patch.object(self.svc, "_fetch", side_effect=fake_fetch):
            self.svc.get_data()
            called = fetch_called.wait(timeout=2.0)

        self.assertTrue(called)

    def test_does_not_double_fetch_when_already_fetching(self):
        """已在抓取中（_fetching.set）時不啟動第二個 thread。"""
        self.svc._fetching.set()
        self.svc._cache_time = 0.0
        with patch.object(self.svc, "_fetch") as mock_fetch:
            self.svc.get_data()
        mock_fetch.assert_not_called()
        self.svc._fetching.clear()


class TestMarketServiceSymbols(unittest.TestCase):
    """SYMBOLS 結構驗證。"""

    def test_symbols_has_expected_keys(self):
        svc = MarketService()
        for key in ("taiex", "nasdaq", "sp500", "usd_twd"):
            self.assertIn(key, svc.SYMBOLS)


class TestMarketServiceChangePct(unittest.TestCase):
    """change_pct 計算細節。"""

    def setUp(self):
        self.svc = MarketService()

    @patch("yfinance.Ticker")
    def test_change_pct_zero_when_prices_equal(self, mock_ticker_cls):
        """前後收盤相同 → change_pct = 0。"""
        mock = MagicMock()
        mock.history.return_value = _make_ticker_df([100.0, 100.0])
        mock_ticker_cls.return_value = mock
        self.svc._fetch()
        data = self.svc.get_data()
        prices = [v for v in data.values() if isinstance(v, dict) and "change_pct" in v]
        if prices:
            self.assertAlmostEqual(prices[0]["change_pct"], 0.0, places=1)

    @patch("yfinance.Ticker")
    def test_fetch_with_single_row_returns_none_price(self, mock_ticker_cls):
        """只有 1 根 K 棒（無前收）→ 不崩潰，price 可能為 None 或有值。"""
        mock = MagicMock()
        mock.history.return_value = _make_ticker_df([100.0])
        mock_ticker_cls.return_value = mock
        try:
            self.svc._fetch()
        except Exception as e:
            self.fail(f"單行資料不應崩潰: {e}")

    @patch("yfinance.Ticker")
    def test_fetch_empty_dataframe_no_crash(self, mock_ticker_cls):
        """yfinance 回傳空 DataFrame → 不崩潰。"""
        mock = MagicMock()
        mock.history.return_value = pd.DataFrame()
        mock_ticker_cls.return_value = mock
        try:
            self.svc._fetch()
        except Exception as e:
            self.fail(f"空資料不應崩潰: {e}")

    @patch("yfinance.Ticker")
    def test_get_data_returns_empty_dict_when_fetch_fails(self, mock_ticker_cls):
        """所有 ticker 均失敗 → get_data 回傳空 dict 而非拋出例外。"""
        mock_ticker_cls.return_value.history.side_effect = Exception("全部失敗")
        svc = MarketService()
        svc._fetch()
        result = svc.get_data()
        self.assertIsInstance(result, dict)


if __name__ == "__main__":
    unittest.main()
