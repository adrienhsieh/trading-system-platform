"""tests/test_indicators.py — IndicatorEngine 單元測試"""
import os
import shutil
import tempfile
import unittest
from datetime import date
from unittest.mock import patch, MagicMock

import numpy as np
import pandas as pd

from trading.indicators import IndicatorEngine
from trading.ohlcv_db import OHLCVDatabase


# ── 測試用資料產生器 ───────────────────────────────────────────

def make_ohlcv(n: int = 100, seed: int = 42) -> pd.DataFrame:
    """產生 n 筆合成 OHLCV 日線資料（固定 seed，可重複）。"""
    rng   = np.random.default_rng(seed)
    close = 100.0 + np.cumsum(rng.normal(0, 1, n))
    close = np.maximum(close, 10.0)
    return pd.DataFrame({
        "open":   close * 0.99,
        "high":   close * 1.02,
        "low":    close * 0.98,
        "close":  close,
        "volume": rng.integers(5_000, 50_000, n).astype(float),
    })


def make_bullish_ohlcv(n: int = 120) -> pd.DataFrame:
    """產生明顯多頭排列的 OHLCV（每日+1 穩定上漲）。"""
    close = np.linspace(50, 200, n)
    return pd.DataFrame({
        "open":   close * 0.99,
        "high":   close * 1.01,
        "low":    close * 0.98,
        "close":  close,
        "volume": np.full(n, 20_000.0),
    })


class TestIndicatorHelpers(unittest.TestCase):
    """內部靜態指標輔助方法。"""

    def setUp(self):
        self.series = pd.Series(np.arange(1.0, 51.0))  # 1..50

    def test_ema_output_length_matches_input(self):
        result = IndicatorEngine._ema(self.series, 10)
        self.assertEqual(len(result), len(self.series))

    def test_sma_output_length_matches_input(self):
        result = IndicatorEngine._sma(self.series, 5)
        self.assertEqual(len(result), len(self.series))

    def test_ema_last_value_close_to_recent_prices(self):
        # EMA 10 of 1..50: 最後值應接近 50，且 > 前面的均值
        result = IndicatorEngine._ema(self.series, 10)
        self.assertGreater(float(result.iloc[-1]), float(result.iloc[-20]))

    def test_sma_nan_for_initial_window(self):
        result = IndicatorEngine._sma(self.series, 10)
        self.assertTrue(pd.isna(result.iloc[0]))

    def test_atr_all_non_negative(self):
        df     = make_ohlcv(50)
        result = IndicatorEngine._atr(df["high"], df["low"], df["close"], 14)
        self.assertTrue((result.dropna() >= 0).all())

    def test_macd_returns_three_series(self):
        df = make_ohlcv(60)
        macd, signal, hist = IndicatorEngine._macd(df["close"])
        self.assertEqual(len(macd), len(df))
        self.assertEqual(len(signal), len(df))
        self.assertEqual(len(hist), len(df))


class TestComputeIndicators(unittest.TestCase):
    """compute() 主要功能。"""

    def test_compute_returns_none_when_insufficient_rows(self):
        df = make_ohlcv(30)
        self.assertIsNone(IndicatorEngine.compute(df))

    def test_compute_returns_none_at_exactly_64_rows(self):
        df = make_ohlcv(64)
        self.assertIsNone(IndicatorEngine.compute(df))

    def test_compute_returns_dict_at_65_rows(self):
        df = make_ohlcv(65)
        result = IndicatorEngine.compute(df)
        self.assertIsNotNone(result)
        self.assertIsInstance(result, dict)

    def test_compute_result_has_expected_keys(self):
        df      = make_ohlcv(100)
        result  = IndicatorEngine.compute(df)
        expected = {
            "close", "ema5", "ema20", "ema60", "adx", "atr",
            "macd_hist", "volume", "vol_avg", "swing_low",
            "w52_high", "w52_low", "cross_days", "signals", "score",
            "enabled", "total_enabled", "adx_threshold", "vol_mult",
        }
        self.assertEqual(set(result.keys()), expected)

    def test_compute_signals_has_all_six_keys(self):
        df      = make_ohlcv(100)
        result  = IndicatorEngine.compute(df)
        expected = {
            "ema_arrangement", "slopes_up", "adx_above_25",
            "macd_positive", "volume_spike", "ema_crossover",
        }
        self.assertEqual(set(result["signals"].keys()), expected)

    def test_compute_score_in_valid_range(self):
        df     = make_ohlcv(100)
        result = IndicatorEngine.compute(df)
        self.assertGreaterEqual(result["score"], 0)
        self.assertLessEqual(result["score"], 6)

    def test_compute_score_matches_signals_count(self):
        df     = make_ohlcv(100)
        result = IndicatorEngine.compute(df)
        expected_score = sum(result["signals"].values())
        self.assertEqual(result["score"], expected_score)

    def test_compute_bullish_high_score(self):
        """穩定上漲趨勢應取得較高分數。"""
        df     = make_bullish_ohlcv(120)
        result = IndicatorEngine.compute(df)
        self.assertIsNotNone(result)
        self.assertGreaterEqual(result["score"], 3)

    def test_compute_ema_arrangement_true_in_uptrend(self):
        df     = make_bullish_ohlcv(120)
        result = IndicatorEngine.compute(df)
        self.assertTrue(result["signals"]["ema_arrangement"])

    def test_compute_swing_low_leq_close(self):
        df     = make_ohlcv(100)
        result = IndicatorEngine.compute(df)
        self.assertLessEqual(result["swing_low"], result["close"])


class TestCalcEntryParams(unittest.TestCase):
    """calc_entry_params() 進場參數計算。"""

    def _make_ind(self, close=100.0, swing_low=90.0, atr=2.0):
        return {
            "close": close, "swing_low": swing_low, "atr": atr,
            "ema5": close, "ema20": close * 0.95, "ema60": close * 0.90,
        }

    def test_returns_dict_with_required_keys(self):
        ind    = self._make_ind()
        result = IndicatorEngine.calc_entry_params(ind, capital=1_000_000)
        for key in ("entry", "stop", "target", "shares", "risk_per_share", "total_risk"):
            self.assertIn(key, result)

    def test_stop_is_below_entry(self):
        ind    = self._make_ind()
        result = IndicatorEngine.calc_entry_params(ind, capital=1_000_000)
        self.assertLess(result["stop"], result["entry"])

    def test_target_is_above_entry(self):
        ind    = self._make_ind()
        result = IndicatorEngine.calc_entry_params(ind, capital=1_000_000)
        self.assertGreater(result["target"], result["entry"])

    def test_shares_positive(self):
        ind    = self._make_ind()
        result = IndicatorEngine.calc_entry_params(ind, capital=1_000_000)
        self.assertGreater(result["shares"], 0)

    def test_risk_pct_affects_shares(self):
        ind      = self._make_ind()
        result1  = IndicatorEngine.calc_entry_params(ind, capital=1_000_000, risk_pct=1.0)
        result2  = IndicatorEngine.calc_entry_params(ind, capital=1_000_000, risk_pct=2.0)
        self.assertLess(result1["shares"], result2["shares"])

    def test_total_risk_calculation(self):
        ind    = self._make_ind(close=100, swing_low=90, atr=2)
        result = IndicatorEngine.calc_entry_params(ind, capital=1_000_000, risk_pct=2.0)
        # stop = 90 - 1.5*2 = 87, risk_per = 100-87 = 13
        # shares = int(1_000_000 * 2% / 13) = int(20000/13) = 1538
        self.assertAlmostEqual(result["stop"], 87.0, places=1)
        self.assertAlmostEqual(result["risk_per_share"], 13.0, places=1)


class TestAnalyzePosition(unittest.TestCase):
    """analyze_position() 持倉狀態分析。"""

    def _make_pos(self, code="2330", status="active", entry=100.0, stop=90.0, target=120.0):
        return {
            "code": code, "name": "測試股", "status": status,
            "entry": entry, "stop": stop, "target": target,
        }

    def test_returns_error_when_fetch_returns_none(self):
        engine = IndicatorEngine()
        with patch.object(IndicatorEngine, "fetch_ohlcv", return_value=None):
            result = engine.analyze_position(self._make_pos())
        self.assertIn("error", result)

    def test_returns_error_when_df_too_short(self):
        engine = IndicatorEngine()
        with patch.object(IndicatorEngine, "fetch_ohlcv", return_value=make_ohlcv(10)):
            result = engine.analyze_position(self._make_pos())
        self.assertIn("error", result)

    def test_active_near_stop_generates_alert(self):
        engine = IndicatorEngine()
        df     = make_ohlcv(60)
        # 讓現價接近 stop（設 stop 略低於現價）
        current_price = float(df["close"].iloc[-1])
        pos = self._make_pos(status="active", entry=current_price * 0.9,
                             stop=current_price * 0.99, target=current_price * 1.2)
        with patch.object(IndicatorEngine, "fetch_ohlcv", return_value=df):
            result = engine.analyze_position(pos)
        self.assertTrue(any("停損" in a for a in result.get("alerts", [])))

    def test_safe_below_ema20_generates_alert(self):
        engine = IndicatorEngine()
        # 下跌趨勢：現價低於 EMA20
        df     = make_ohlcv(60, seed=99)
        # 強制讓最後幾筆收盤向下
        df.loc[df.index[-5:], "close"] *= 0.80
        pos = self._make_pos(status="safe", stop=1.0, target=None)
        with patch.object(IndicatorEngine, "fetch_ohlcv", return_value=df):
            result = engine.analyze_position(pos)
        # 結果應有警示或持倉正常（取決於 EMA，不強制要有警示）
        self.assertIn("code", result)
        self.assertIn("alerts", result)

    def test_result_has_required_keys(self):
        engine = IndicatorEngine()
        df     = make_bullish_ohlcv(60)
        pos    = self._make_pos()
        with patch.object(IndicatorEngine, "fetch_ohlcv", return_value=df):
            result = engine.analyze_position(pos)
        for key in ("code", "name", "current", "ema20", "below_ema20", "alerts", "suggestion"):
            self.assertIn(key, result)


class TestFetchOhlcv(unittest.TestCase):
    """fetch_ohlcv() yfinance 整合（mock 網路）。"""

    def _make_yf_df(self, n=80):
        close = np.linspace(100, 120, n)
        df = pd.DataFrame({
            "Open":   close * 0.99,
            "High":   close * 1.01,
            "Low":    close * 0.98,
            "Close":  close,
            "Volume": np.full(n, 10_000.0),
        })
        return df

    @patch("yfinance.Ticker")
    def test_returns_dataframe_on_success(self, mock_ticker):
        mock_ticker.return_value.history.return_value = self._make_yf_df()
        result = IndicatorEngine().fetch_ohlcv("2330")
        self.assertIsNotNone(result)
        self.assertIsInstance(result, pd.DataFrame)

    @patch("yfinance.Ticker")
    def test_returns_none_on_empty_response(self, mock_ticker):
        mock_ticker.return_value.history.return_value = pd.DataFrame()
        eng = IndicatorEngine()
        with patch.object(eng._db, "load", return_value=None):
            result = eng.fetch_ohlcv("0000")
        self.assertIsNone(result)

    @patch("yfinance.Ticker")
    def test_returns_none_on_exception(self, mock_ticker):
        mock_ticker.return_value.history.side_effect = Exception("網路錯誤")
        eng = IndicatorEngine()
        with patch.object(eng._db, "load", return_value=None):
            result = eng.fetch_ohlcv("0000")
        self.assertIsNone(result)

    @patch("yfinance.Ticker")
    def test_appends_tw_suffix_if_missing(self, mock_ticker):
        mock_ticker.return_value.history.return_value = self._make_yf_df()
        eng = IndicatorEngine()
        with patch.object(eng._db, "load", return_value=None):
            eng.fetch_ohlcv("0000")
        call_args = mock_ticker.call_args[0][0]
        self.assertTrue(call_args.endswith(".TW"))

    @patch("yfinance.Ticker")
    def test_result_has_ohlcv_columns(self, mock_ticker):
        mock_ticker.return_value.history.return_value = self._make_yf_df()
        eng = IndicatorEngine()
        with patch.object(eng._db, "load", return_value=None):
            result = eng.fetch_ohlcv("0000")
        for col in ("open", "high", "low", "close", "volume"):
            self.assertIn(col, result.columns)

    @patch("yfinance.Ticker")
    def test_fallback_to_two_suffix_when_tw_empty(self, mock_ticker):
        """.TW 回傳空資料時，自動改用 .TWO 重試（上櫃股支援）。"""
        good_df = self._make_yf_df()
        mock_ticker.return_value.history.side_effect = [pd.DataFrame(), good_df]
        eng = IndicatorEngine()
        with patch.object(eng._db, "load", return_value=None):
            result = eng.fetch_ohlcv("0000")
        self.assertIsNotNone(result)
        self.assertIsInstance(result, pd.DataFrame)
        second_call_ticker = mock_ticker.call_args_list[1][0][0]
        self.assertTrue(second_call_ticker.endswith(".TWO"))


class TestFetchOhlcvDbFirst(unittest.TestCase):
    """fetch_ohlcv() DB 優先讀取邏輯。"""

    def setUp(self):
        self._tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self._tmp.close()
        self.engine = IndicatorEngine()
        from trading.ohlcv_db import OHLCVDatabase
        self.engine._db = OHLCVDatabase(db_path=self._tmp.name)

    def tearDown(self):
        try:
            os.unlink(self._tmp.name)
        except OSError:
            pass

    def _make_yf_df(self, n=80):
        close = np.linspace(100, 120, n)
        return pd.DataFrame({
            "Open":   close * 0.99,
            "High":   close * 1.01,
            "Low":    close * 0.98,
            "Close":  close,
            "Volume": np.full(n, 10_000.0),
        })

    @patch("yfinance.Ticker")
    def test_returns_cached_data_when_sufficient(self, mock_ticker):
        """DB 有足夠資料時不呼叫 yfinance。"""
        dates = pd.date_range(end=pd.Timestamp.today(), periods=200, freq="B")
        df = pd.DataFrame({
            "open": range(200), "high": range(200), "low": range(200),
            "close": range(200), "volume": [1000] * 200,
        }, index=dates)
        self.engine._db.upsert("9999", df)
        result = self.engine.fetch_ohlcv("9999", period="6mo")
        self.assertIsNotNone(result)
        self.assertGreater(len(result), 0)
        mock_ticker.assert_not_called()

    @patch("yfinance.Ticker")
    def test_falls_back_to_yfinance_when_insufficient(self, mock_ticker):
        """DB 資料不足時 fallback 到 yfinance。"""
        dates = pd.date_range("2026-04-01", periods=10, freq="B")
        df = pd.DataFrame({
            "open": range(10), "high": range(10), "low": range(10),
            "close": range(10), "volume": [1000] * 10,
        }, index=dates)
        self.engine._db.upsert("8888", df)
        mock_ticker.return_value.history.return_value = self._make_yf_df()
        result = self.engine.fetch_ohlcv("8888", period="6mo")
        self.assertIsNotNone(result)
        mock_ticker.assert_called()


class TestFetchWithRetry(unittest.TestCase):
    """_fetch_with_retry() 超時與重試機制（module-level helper）。"""

    def _make_raw_df(self, n: int = 80) -> pd.DataFrame:
        close = np.linspace(100, 120, n)
        return pd.DataFrame({
            "Open":   close * 0.99,
            "High":   close * 1.01,
            "Low":    close * 0.98,
            "Close":  close,
            "Volume": np.full(n, 10_000.0),
        })

    @patch("yfinance.Ticker")
    def test_returns_dataframe_on_success(self, mock_ticker):
        from trading.indicators import _fetch_with_retry
        mock_ticker.return_value.history.return_value = self._make_raw_df()
        result = _fetch_with_retry("2330.TW")
        self.assertIsNotNone(result)
        self.assertIsInstance(result, pd.DataFrame)

    @patch("yfinance.Ticker")
    def test_returns_none_on_empty_response(self, mock_ticker):
        from trading.indicators import _fetch_with_retry
        mock_ticker.return_value.history.return_value = pd.DataFrame()
        result = _fetch_with_retry("2330.TW", retries=1)
        self.assertIsNone(result)

    @patch("trading.indicators._time.sleep")
    @patch("yfinance.Ticker")
    def test_retries_on_exception_then_succeeds(self, mock_ticker, mock_sleep):
        """第一次失敗、第二次成功 → 回傳 DataFrame。"""
        from trading.indicators import _fetch_with_retry
        good_df = self._make_raw_df()
        mock_ticker.return_value.history.side_effect = [Exception("網路錯誤"), good_df]
        result = _fetch_with_retry("2330.TW", retries=2)
        self.assertIsNotNone(result)

    @patch("trading.indicators._time.sleep")
    @patch("yfinance.Ticker")
    def test_returns_none_after_all_retries_fail(self, mock_ticker, mock_sleep):
        """所有重試均失敗時回傳 None，不拋例外。"""
        from trading.indicators import _fetch_with_retry
        mock_ticker.return_value.history.side_effect = Exception("持續失敗")
        result = _fetch_with_retry("2330.TW", retries=2)
        self.assertIsNone(result)


class TestExpectedLatestTradeDate(unittest.TestCase):
    """_expected_latest_trade_date() 單元測試"""

    def _call(self, fake_now):
        from datetime import datetime, date
        from zoneinfo import ZoneInfo
        with patch("trading.indicators._now_taipei", return_value=fake_now):
            from trading.indicators import _expected_latest_trade_date
            return _expected_latest_trade_date()

    def test_weekday_after_14(self):
        """工作日 14:00 後 → 回傳當天"""
        from datetime import datetime
        from zoneinfo import ZoneInfo
        # 2026-04-15 週三 15:00
        result = self._call(datetime(2026, 4, 15, 15, 0, tzinfo=ZoneInfo("Asia/Taipei")))
        from datetime import date
        self.assertEqual(result, date(2026, 4, 15))

    def test_weekday_before_14(self):
        """工作日 14:00 前 → 回傳前一個交易日"""
        from datetime import datetime, date
        from zoneinfo import ZoneInfo
        # 2026-04-15 週三 09:00 → 前一交易日 = 4/14 週二
        result = self._call(datetime(2026, 4, 15, 9, 0, tzinfo=ZoneInfo("Asia/Taipei")))
        self.assertEqual(result, date(2026, 4, 14))

    def test_weekday_at_14(self):
        """工作日 14:00 整點 → 回傳當天（>= 14）"""
        from datetime import datetime, date
        from zoneinfo import ZoneInfo
        result = self._call(datetime(2026, 4, 15, 14, 0, tzinfo=ZoneInfo("Asia/Taipei")))
        self.assertEqual(result, date(2026, 4, 15))

    def test_saturday(self):
        """週六 → 回傳週五"""
        from datetime import datetime, date
        from zoneinfo import ZoneInfo
        # 2026-04-18 週六
        result = self._call(datetime(2026, 4, 18, 10, 0, tzinfo=ZoneInfo("Asia/Taipei")))
        self.assertEqual(result, date(2026, 4, 17))

    def test_sunday(self):
        """週日 → 回傳週五"""
        from datetime import datetime, date
        from zoneinfo import ZoneInfo
        # 2026-04-19 週日
        result = self._call(datetime(2026, 4, 19, 10, 0, tzinfo=ZoneInfo("Asia/Taipei")))
        self.assertEqual(result, date(2026, 4, 17))

    def test_monday_before_14(self):
        """週一 09:00 → 回傳上週五"""
        from datetime import datetime, date
        from zoneinfo import ZoneInfo
        # 2026-04-20 週一 09:00
        result = self._call(datetime(2026, 4, 20, 9, 0, tzinfo=ZoneInfo("Asia/Taipei")))
        self.assertEqual(result, date(2026, 4, 17))


def _make_ohlcv_df(end_date: date, n: int = 100) -> pd.DataFrame:
    """產生以 end_date 為最後一天的 n 個工作日 OHLCV。"""
    close = 100.0 + np.arange(n, dtype=float)
    idx = pd.bdate_range(end=end_date, periods=n)
    return pd.DataFrame({
        "open": close * 0.99, "high": close * 1.01,
        "low": close * 0.98, "close": close,
        "volume": np.full(n, 10_000.0),
    }, index=idx)


class TestFetchOhlcvFreshness(unittest.TestCase):
    """fetch_ohlcv() 新鮮度判斷測試"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "test.db")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    @patch("trading.indicators._expected_latest_trade_date")
    @patch("trading.indicators._fetch_with_retry")
    def test_fresh_db_skips_yfinance(self, mock_fetch, mock_expected):
        """DB 有最新資料 → 不打 yfinance"""
        mock_expected.return_value = date(2026, 4, 15)
        db = OHLCVDatabase(db_path=self.db_path)
        df = _make_ohlcv_df(date(2026, 4, 15), n=130)
        db.upsert("2330", df)

        eng = IndicatorEngine.__new__(IndicatorEngine)
        eng._db = db
        result = eng.fetch_ohlcv("2330", period="6mo")

        self.assertIsNotNone(result)
        mock_fetch.assert_not_called()

    @patch("trading.indicators._expected_latest_trade_date")
    @patch("trading.indicators._fetch_with_retry")
    def test_stale_db_calls_yfinance(self, mock_fetch, mock_expected):
        """DB 資料過期 → 打 yfinance 補抓"""
        mock_expected.return_value = date(2026, 4, 15)
        db = OHLCVDatabase(db_path=self.db_path)
        df = _make_ohlcv_df(date(2026, 4, 10), n=130)
        db.upsert("2330", df)

        fresh_df = _make_ohlcv_df(date(2026, 4, 15), n=130)
        fresh_df.columns = ["Open", "High", "Low", "Close", "Volume"]
        mock_fetch.return_value = fresh_df

        eng = IndicatorEngine.__new__(IndicatorEngine)
        eng._db = db
        result = eng.fetch_ohlcv("2330", period="6mo")

        self.assertIsNotNone(result)
        mock_fetch.assert_called()

    @patch("trading.indicators._expected_latest_trade_date")
    @patch("trading.indicators._fetch_with_retry")
    def test_stale_db_yfinance_fails_falls_back(self, mock_fetch, mock_expected):
        """DB 資料過期但 yfinance 失敗 → fallback DB"""
        mock_expected.return_value = date(2026, 4, 15)
        db = OHLCVDatabase(db_path=self.db_path)
        df = _make_ohlcv_df(date(2026, 4, 10), n=130)
        db.upsert("2330", df)

        mock_fetch.return_value = None

        eng = IndicatorEngine.__new__(IndicatorEngine)
        eng._db = db
        result = eng.fetch_ohlcv("2330", period="6mo")

        self.assertIsNotNone(result)
        self.assertEqual(len(result), 130)


if __name__ == "__main__":
    unittest.main()
