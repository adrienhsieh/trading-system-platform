"""tests/test_ohlcv_daemon.py — OHLCVDaemon 單元測試"""
import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd


def _mock_yf_history(n=20):
    dates = pd.date_range("2026-04-01", periods=n, freq="B")
    close = np.linspace(100, 110, n)
    return pd.DataFrame({
        "Open": close - 0.5, "High": close + 1, "Low": close - 1,
        "Close": close, "Volume": np.full(n, 1e6),
    }, index=dates)


class TestOHLCVDaemon(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = str(Path(self.tmpdir) / "test_ohlcv.db")
        from trading.ohlcv_db import OHLCVDatabase
        self.db = OHLCVDatabase(db_path=self.db_path)
        self.mock_scanner = MagicMock()
        self.mock_scanner.get_stock_map.return_value = {"2330": "台積電", "2317": "鴻海"}

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_daemon(self):
        from trading.ohlcv_daemon import OHLCVDaemon
        return OHLCVDaemon(ohlcv_db=self.db, scanner=self.mock_scanner)

    def test_not_running_initially(self):
        d = self._make_daemon()
        self.assertFalse(d.is_running())

    def test_start_and_stop(self):
        d = self._make_daemon()
        started = threading.Event()
        def patched_loop():
            started.set()
        d._loop = patched_loop
        d.start()
        self.assertTrue(started.wait(timeout=2.0))
        d.stop()

    @patch("yfinance.Ticker")
    def test_fetch_one_success(self, mock_ticker):
        mock_ticker.return_value.history.return_value = _mock_yf_history()
        d = self._make_daemon()
        ok = d._fetch_one("2330", period="5d")
        self.assertTrue(ok)
        df = self.db.load("2330", days=30)
        self.assertIsNotNone(df)
        self.assertGreater(len(df), 0)

    @patch("yfinance.Ticker")
    def test_fetch_one_failure(self, mock_ticker):
        mock_ticker.return_value.history.return_value = pd.DataFrame()
        d = self._make_daemon()
        ok = d._fetch_one("9999", period="5d")
        self.assertFalse(ok)

    @patch("yfinance.Ticker")
    def test_incremental_update(self, mock_ticker):
        mock_ticker.return_value.history.return_value = _mock_yf_history()
        d = self._make_daemon()
        d.incremental_update()
        self.assertIsNotNone(self.db.load("2330", days=30))
        self.assertIsNotNone(self.db.load("2317", days=30))

    @patch("yfinance.Ticker")
    def test_backfill(self, mock_ticker):
        mock_ticker.return_value.history.return_value = _mock_yf_history(100)
        d = self._make_daemon()
        d.backfill()
        stats = self.db.stats()
        self.assertGreater(stats["total_rows"], 0)

    def test_get_all_codes(self):
        d = self._make_daemon()
        codes = d._get_all_codes()
        self.assertEqual(len(codes), 2)
        self.assertIn("2330", codes)

    def test_get_all_codes_failure(self):
        self.mock_scanner.get_stock_map.side_effect = Exception("network error")
        d = self._make_daemon()
        codes = d._get_all_codes()
        self.assertEqual(codes, [])
