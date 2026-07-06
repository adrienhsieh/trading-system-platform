"""tests/test_scanner.py — StockScanner 單元測試"""
import unittest
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd

from trading.indicators import IndicatorEngine
from trading.scanner import StockScanner


def _make_ohlcv(n=100):
    close = np.linspace(100, 150, n)
    return pd.DataFrame({
        "open":   close * 0.99,
        "high":   close * 1.01,
        "low":    close * 0.98,
        "close":  close,
        "volume": np.full(n, 20_000.0),
    })


def _mock_twse_response(items: list):
    """建立模擬的 TWSE API JSON 回應。"""
    resp = MagicMock()
    resp.json.return_value = items
    return resp


class TestGetStockMap(unittest.TestCase):

    def setUp(self):
        self.scanner = StockScanner()

    def _side_effect_two_calls(self, twse_items, tpex_items=None):
        """回傳 side_effect list 供兩次 requests.get 呼叫（TWSE / TPEX主板）。"""
        def make_resp(items):
            resp = MagicMock()
            resp.json.return_value = items or []
            return resp
        return [make_resp(twse_items), make_resp(tpex_items or [])]

    @patch("requests.get")
    def test_returns_dict_on_success(self, mock_get):
        mock_get.side_effect = self._side_effect_two_calls([
            {"Code": "2330", "Name": "台積電"},
            {"Code": "2317", "Name": "鴻海"},
        ])
        result = self.scanner.get_stock_map()
        self.assertIsInstance(result, dict)
        self.assertIn("2330", result)
        self.assertEqual(result["2330"], "台積電")

    @patch("requests.get")
    def test_filters_non_4digit_codes(self, mock_get):
        mock_get.side_effect = self._side_effect_two_calls([
            {"Code": "2330",  "Name": "台積電"},
            {"Code": "00878", "Name": "ETF"},   # 5 位，應過濾
            {"Code": "abc",   "Name": "錯誤"},  # 非數字，應過濾
        ])
        result = self.scanner.get_stock_map()
        self.assertIn("2330",  result)
        self.assertNotIn("00878", result)
        self.assertNotIn("abc",   result)

    @patch("requests.get")
    def test_uses_cache_on_second_call(self, mock_get):
        mock_get.side_effect = self._side_effect_two_calls(
            [{"Code": "2330", "Name": "台積電"}]
        )
        self.scanner.get_stock_map()   # 第一次：呼叫 TWSE + TPEX（共 2 次）
        count_after_first = mock_get.call_count
        self.scanner.get_stock_map()   # 第二次：應使用快取，不再呼叫 API
        self.assertEqual(mock_get.call_count, count_after_first)

    @patch("requests.get")
    def test_returns_empty_dict_on_api_failure(self, mock_get):
        mock_get.side_effect = Exception("連線逾時")
        self.scanner._stock_cache = {}   # 清除快取
        result = self.scanner.get_stock_map()
        self.assertIsInstance(result, dict)

    @patch("requests.get")
    def test_tpex_stocks_included(self, mock_get):
        """TPEX 上櫃股票應加入 stock_map。"""
        mock_get.side_effect = self._side_effect_two_calls(
            twse_items=[{"Code": "2330", "Name": "台積電"}],
            tpex_items=[{"SecuritiesCompanyCode": "6547", "CompanyName": "高端疫苗"}],
        )
        result = self.scanner.get_stock_map()
        self.assertIn("6547", result)
        self.assertEqual(result["6547"], "高端疫苗")


class TestGetTechStockMap(unittest.TestCase):

    def setUp(self):
        import time
        self.scanner = StockScanner()
        self.scanner._stock_cache = {
            "2330": "台積電",   # 半導體業 → 應包含
            "2317": "鴻海",    # 電子零組件業 → 應包含
            "1301": "台塑",    # 塑膠工業 → 應排除
        }
        self.scanner._stock_cache_time = time.time()
        # 直接注入產業別快取，不需要真實 API
        self.scanner._industry_cache = {
            "2330": "半導體業",
            "2317": "電子零組件業",
            "1301": "塑膠工業",
        }
        self.scanner._industry_cache_time = time.time()

    def test_includes_tech_stocks(self):
        result = self.scanner.get_tech_stock_map()
        self.assertIn("2330", result)
        self.assertIn("2317", result)

    def test_excludes_non_tech_stocks(self):
        result = self.scanner.get_tech_stock_map()
        self.assertNotIn("1301", result)

    def test_returns_dict_with_names(self):
        result = self.scanner.get_tech_stock_map()
        self.assertEqual(result.get("2330"), "台積電")

    def test_is_tech_by_code_electronics_range(self):
        self.assertTrue(StockScanner._is_tech_by_code("3034"))
        self.assertTrue(StockScanner._is_tech_by_code("6443"))

    def test_is_tech_by_code_non_electronics(self):
        self.assertFalse(StockScanner._is_tech_by_code("1301"))
        self.assertFalse(StockScanner._is_tech_by_code("2002"))


class TestGetStockName(unittest.TestCase):

    def setUp(self):
        import time
        scanner = StockScanner()
        scanner._stock_cache = {"2330": "台積電", "2317": "鴻海"}
        scanner._stock_cache_time = time.time()
        self.scanner = scanner

    def test_returns_name_when_found(self):
        self.assertEqual(self.scanner.get_stock_name("2330"), "台積電")

    def test_returns_code_when_not_found(self):
        self.assertEqual(self.scanner.get_stock_name("9999"), "9999")


class TestAnalyzeOne(unittest.TestCase):

    def setUp(self):
        import time
        self.scanner = StockScanner()
        self.scanner._stock_cache = {"2330": "台積電"}
        self.scanner._stock_cache_time = time.time()

    def test_returns_none_when_df_insufficient(self):
        with patch.object(IndicatorEngine, "fetch_ohlcv", return_value=_make_ohlcv(30)):
            result = self.scanner.analyze_one("2330", capital=1_000_000, risk_pct=2.0)
        self.assertIsNone(result)

    def test_returns_none_when_fetch_fails(self):
        with patch.object(IndicatorEngine, "fetch_ohlcv", return_value=None):
            result = self.scanner.analyze_one("2330", capital=1_000_000, risk_pct=2.0)
        self.assertIsNone(result)

    def test_returns_dict_on_success(self):
        with patch.object(IndicatorEngine, "fetch_ohlcv", return_value=_make_ohlcv(100)):
            result = self.scanner.analyze_one("2330", capital=1_000_000, risk_pct=2.0)
        self.assertIsNotNone(result)
        self.assertIsInstance(result, dict)

    def test_result_has_required_keys(self):
        with patch.object(IndicatorEngine, "fetch_ohlcv", return_value=_make_ohlcv(100)):
            result = self.scanner.analyze_one("2330", capital=1_000_000, risk_pct=2.0)
        for key in ("code", "name", "score", "ind", "params"):
            self.assertIn(key, result)

    def test_uses_provided_name(self):
        with patch.object(IndicatorEngine, "fetch_ohlcv", return_value=_make_ohlcv(100)):
            result = self.scanner.analyze_one("2330", capital=1_000_000, risk_pct=2.0, name="自訂名稱")
        self.assertEqual(result["name"], "自訂名稱")

    def test_returns_none_on_compute_exception(self):
        from trading.strategies.trend import TrendStrategy
        with patch.object(IndicatorEngine, "fetch_ohlcv", return_value=_make_ohlcv(100)), \
             patch.object(TrendStrategy, "compute", side_effect=Exception("計算失敗")):
            result = self.scanner.analyze_one("2330", capital=1_000_000, risk_pct=2.0)
        self.assertIsNone(result)


class TestRunScan(unittest.TestCase):

    def setUp(self):
        self.scanner = StockScanner()
        self.scanner._stock_cache = {"2330": "台積電", "2317": "鴻海"}

    def test_empty_candidates_returns_empty(self):
        result = self.scanner.run_scan([], capital=1_000_000, risk_pct=2.0)
        self.assertEqual(result, [])

    def test_results_sorted_by_score_descending(self):
        def fake_analyze(code, capital, risk_pct, strategy="trend", name=""):
            scores = {"2330": 5, "2317": 3}
            score  = scores.get(code, 0)
            if score == 0:
                return None
            return {
                "code": code, "name": name, "score": score,
                "ind":    {"close": 100, "ema5": 100, "ema20": 98, "ema60": 95,
                           "adx": 30, "atr": 2, "macd_hist": 0.1,
                           "w52_high": 120, "w52_low": 80,
                           "signals": {"ema_arrangement": True, "slopes_up": True,
                                       "adx_above_25": True, "macd_positive": True,
                                       "volume_spike": True, "ema_crossover": False}},
                "params": {"entry": 100, "stop": 90, "target": 120, "shares": 1000, "total_risk": 10000},
            }

        with patch.object(self.scanner, "analyze_one", side_effect=fake_analyze):
            results = self.scanner.run_scan(["2330", "2317"], capital=1_000_000, risk_pct=2.0)

        self.assertEqual(len(results), 2)
        self.assertGreaterEqual(results[0]["score"], results[1]["score"])

    def test_excludes_none_results(self):
        with patch.object(self.scanner, "analyze_one", return_value=None):
            results = self.scanner.run_scan(["2330", "2317"], capital=1_000_000, risk_pct=2.0)
        self.assertEqual(results, [])


class TestFormatForApi(unittest.TestCase):

    def setUp(self):
        self.scanner = StockScanner()

    def _make_result(self, code="2330", score=4):
        return {
            "code": code, "name": "台積電", "score": score,
            "ind": {
                "close": 900.0, "ema5": 905.0, "ema20": 895.0, "ema60": 880.0,
                "adx": 28.5, "atr": 12.0, "macd_hist": 0.5,
                "w52_high": 1000.0, "w52_low": 700.0,
                "signals": {
                    "ema_arrangement": True, "slopes_up": True, "adx_above_25": True,
                    "macd_positive": True, "volume_spike": False, "ema_crossover": False,
                },
            },
            "params": {
                "entry": 900.0, "stop": 860.0, "target": 980.0,
                "shares": 555, "total_risk": 22_200,
            },
        }

    def test_returns_list(self):
        result = self.scanner.format_for_api([self._make_result()])
        self.assertIsInstance(result, list)

    def test_output_has_required_keys(self):
        result = self.scanner.format_for_api([self._make_result()])[0]
        for key in ("code", "name", "score", "close", "entry", "stop", "target", "signals"):
            self.assertIn(key, result)

    def test_signals_contain_pass_and_label(self):
        result  = self.scanner.format_for_api([self._make_result()])[0]
        signals = result["signals"]
        for sig in signals.values():
            self.assertIn("pass",  sig)
            self.assertIn("label", sig)

    def test_empty_input_returns_empty_list(self):
        result = self.scanner.format_for_api([])
        self.assertEqual(result, [])


class TestFormatForApiFundamental(unittest.TestCase):
    """format_for_api() fundamental 策略額外欄位。"""

    def setUp(self):
        self.scanner = StockScanner()

    def _make_fundamental_result(self, code="2330"):
        return {
            "code": code, "name": "台積電", "score": 4, "strategy": "fundamental",
            "ind": {
                "close": 900.0, "pe": 15.2, "eps": 45.0, "forward_eps": 50.0,
                "pb": 2.1, "revenue_growth": 12.5, "swing_low": 860.0,
                "signals": {
                    "pe_reasonable": True, "eps_positive": True, "eps_growth": True,
                    "pb_reasonable": True, "revenue_growth": False,
                },
            },
            "params": {
                "entry": 900.0, "stop": 842.0, "target": 1016.0,
                "shares": 100, "total_risk": 5_800,
            },
        }

    def test_fundamental_extra_fields_present(self):
        result = self.scanner.format_for_api([self._make_fundamental_result()], strategy="fundamental")[0]
        for key in ("pe", "eps", "forward_eps", "pb", "revenue_growth"):
            self.assertIn(key, result)

    def test_fundamental_pe_value(self):
        result = self.scanner.format_for_api([self._make_fundamental_result()], strategy="fundamental")[0]
        self.assertEqual(result["pe"], 15.2)


if __name__ == "__main__":
    unittest.main()
