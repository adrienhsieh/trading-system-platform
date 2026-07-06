"""tests/test_ohlcv_db.py — OHLCVDatabase 單元測試"""
import os
import shutil
import tempfile
import unittest
from datetime import date, timedelta

import numpy as np
import pandas as pd

from trading.ohlcv_db import OHLCVDatabase


def _make_df(n: int = 100) -> pd.DataFrame:
    """產生最近 n 個工作日的 OHLCV（含今日）。"""
    close = 100.0 + np.arange(n, dtype=float)
    end   = date.today()
    idx   = pd.bdate_range(end=end, periods=n)
    return pd.DataFrame({
        "open":   close * 0.99,
        "high":   close * 1.01,
        "low":    close * 0.98,
        "close":  close,
        "volume": np.full(n, 10_000.0),
    }, index=idx)


class TestOHLCVDatabase(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "test.db")
        self.db = OHLCVDatabase(db_path=self.db_path)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_upsert_returns_row_count(self):
        df = _make_df(50)
        count = self.db.upsert("2330", df)
        self.assertEqual(count, 50)

    def test_load_returns_dataframe(self):
        df = _make_df(100)
        self.db.upsert("2330", df)
        result = self.db.load("2330", days=365)
        self.assertIsNotNone(result)
        self.assertIsInstance(result, pd.DataFrame)

    def test_load_returns_none_when_empty(self):
        result = self.db.load("9999", days=365)
        self.assertIsNone(result)

    def test_upsert_idempotent(self):
        df = _make_df(50)
        self.db.upsert("2330", df)
        self.db.upsert("2330", df)   # 重複寫入
        result = self.db.load("2330", days=365)
        self.assertEqual(len(result), 50)

    def test_latest_date_returns_string(self):
        df = _make_df(10)
        self.db.upsert("2330", df)
        latest = self.db.latest_date("2330")
        self.assertIsNotNone(latest)
        self.assertIsInstance(latest, str)
        self.assertEqual(len(latest), 10)   # YYYY-MM-DD

    def test_latest_date_returns_none_when_empty(self):
        result = self.db.latest_date("9999")
        self.assertIsNone(result)

    def test_stats_keys(self):
        df = _make_df(20)
        self.db.upsert("2330", df)
        stats = self.db.stats()
        for key in ("total_rows", "total_codes", "oldest_date", "newest_date"):
            self.assertIn(key, stats)

    def test_stats_counts(self):
        self.db.upsert("2330", _make_df(10))
        self.db.upsert("2317", _make_df(5))
        stats = self.db.stats()
        self.assertEqual(stats["total_rows"],  15)
        self.assertEqual(stats["total_codes"], 2)

    def test_list_codes(self):
        self.db.upsert("2330", _make_df(5))
        self.db.upsert("2317", _make_df(5))
        codes = self.db.list_codes()
        self.assertIn("2330", codes)
        self.assertIn("2317", codes)

    def test_delete_code(self):
        self.db.upsert("2330", _make_df(10))
        deleted = self.db.delete_code("2330")
        self.assertEqual(deleted, 10)
        self.assertIsNone(self.db.load("2330", days=365))

    def test_upsert_empty_df_returns_zero(self):
        df = pd.DataFrame()
        count = self.db.upsert("2330", df)
        self.assertEqual(count, 0)

    def test_load_columns_correct(self):
        df = _make_df(20)
        self.db.upsert("2330", df)
        result = self.db.load("2330", days=365)
        for col in ("open", "high", "low", "close", "volume"):
            self.assertIn(col, result.columns)


class TestOHLCVDatabaseStats(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "test.db")
        self.db = OHLCVDatabase(db_path=self.db_path)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_stats_empty_db(self):
        stats = self.db.stats()
        self.assertEqual(stats["total_rows"],  0)
        self.assertEqual(stats["total_codes"], 0)
        self.assertIsNone(stats["oldest_date"])
        self.assertIsNone(stats["newest_date"])

    def test_list_codes_empty(self):
        self.assertEqual(self.db.list_codes(), [])

    def test_delete_nonexistent_returns_zero(self):
        count = self.db.delete_code("9999")
        self.assertEqual(count, 0)


if __name__ == "__main__":
    unittest.main()
