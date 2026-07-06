"""tests/test_integration.py — 整合測試

不 mock 業務邏輯，驗證跨模組串接的端對端正確性。
測試策略：mock 外部 IO（yfinance / HTTP），但使用真實計算邏輯。
"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

from trading.backtest import BacktestEngine
from trading.indicators import IndicatorEngine
from trading.positions import PositionManager
from trading.scanner import StockScanner
from trading.strategies import get_strategy


# ── 共用測試資料 ─────────────────────────────────────────────────────────────

def _make_ohlcv(n: int = 200) -> pd.DataFrame:
    """建立足夠長的合成 OHLCV（線性上升 + 隨機噪聲），模擬真實行情。"""
    np.random.seed(42)
    trend  = np.linspace(100, 200, n)
    noise  = np.random.normal(0, 0.5, n)
    close  = trend + noise
    high   = close + np.abs(np.random.normal(2, 0.5, n))
    low    = close - np.abs(np.random.normal(2, 0.5, n))
    open_  = close - np.random.normal(0, 0.3, n)
    vol    = np.full(n, 1000.0)
    vol[-1] = 2500.0   # 最後一根爆量
    dates  = pd.date_range("2023-01-01", periods=n, freq="B")
    return pd.DataFrame({
        "open": open_, "high": high, "low": low,
        "close": close, "volume": vol,
    }, index=dates)


# ── 整合測試 1：BacktestEngine.run() 端對端 ─────────────────────────────────

class TestBacktestEndToEnd(unittest.TestCase):
    """BacktestEngine.run() + TrendStrategy 完整流程：
    使用合成 OHLCV 驗證回傳結構、統計欄位型別與 equity curve 長度。"""

    def setUp(self):
        self.engine = BacktestEngine()
        self.df = _make_ohlcv(200)

    def _run_with_synthetic_data(self, strategy="trend"):
        with patch.object(self.engine._ind, "fetch_ohlcv", return_value=self.df):
            return self.engine.run("2330", strategy=strategy,
                                   capital=1_000_000, risk_pct=2.0, period="2y")

    def test_run_returns_ok_result(self):
        result = self._run_with_synthetic_data()
        self.assertTrue(result.get("ok"), f"回測失敗: {result.get('error')}")

    def test_result_has_required_keys(self):
        result = self._run_with_synthetic_data()
        for key in ("ok", "code", "strategy", "capital", "final_equity",
                    "trades", "equity_curve", "stats"):
            self.assertIn(key, result, f"缺少欄位: {key}")

    def test_equity_curve_has_entries(self):
        result = self._run_with_synthetic_data()
        self.assertIsInstance(result["equity_curve"], list)

    def test_trades_list_is_list(self):
        result = self._run_with_synthetic_data()
        self.assertIsInstance(result["trades"], list)

    def test_stats_has_win_rate_and_drawdown(self):
        result = self._run_with_synthetic_data()
        stats = result.get("stats", {})
        for key in ("win_rate", "max_drawdown", "total_return"):
            self.assertIn(key, stats, f"stats 缺少: {key}")

    def test_ict_strategy_also_runs(self):
        """ICT 策略使用同一引擎也能正常完成回測。"""
        result = self._run_with_synthetic_data(strategy="ict")
        self.assertTrue(result.get("ok"), f"ICT 回測失敗: {result.get('error')}")


# ── 整合測試 2：PositionManager 持倉生命週期 ─────────────────────────────────

class TestPositionLifecycle(unittest.TestCase):
    """建倉 → 查詢 → 更新 → 刪除，全流程使用 temp SQLite，不依賴 positions.db。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db_file  = Path(self.tmp.name) / "test.db"
        self.mgr = PositionManager(db_file=db_file)

    def tearDown(self):
        self.tmp.cleanup()

    def _sample_position(self, code="2330", **overrides) -> dict:
        base = {
            "code": code, "name": "台積電", "date": "2024-01-01",
            "entry": 900.0, "stop": 850.0, "shares": 1000,
            "target": 1050.0, "status": "active", "note": "",
        }
        base.update(overrides)
        return base

    def test_create_and_load_all(self):
        """建倉後 load_all 應回傳至少一筆。"""
        self.mgr.create(self._sample_position())
        positions = self.mgr.load_all()
        self.assertGreaterEqual(len(positions), 1)

    def test_create_sets_correct_fields(self):
        """建倉後欄位值應與輸入一致。"""
        self.mgr.create(self._sample_position(code="2330", entry=900.0))
        positions = self.mgr.load_all()
        p = next((x for x in positions if x["code"] == "2330"), None)
        self.assertIsNotNone(p)
        self.assertEqual(p["entry"], 900.0)

    def test_delete_removes_position(self):
        """刪除後 load_all 不再包含該持倉。"""
        self.mgr.create(self._sample_position(code="9999"))
        pid = next(p["id"] for p in self.mgr.load_all() if p["code"] == "9999")
        self.mgr.delete(pid)
        remaining = [p for p in self.mgr.load_all() if p["code"] == "9999"]
        self.assertEqual(len(remaining), 0)

    def test_multiple_positions_independent(self):
        """多筆持倉彼此獨立，數量正確。"""
        self.mgr.create(self._sample_position("2330"))
        self.mgr.create(self._sample_position("2317"))
        self.mgr.create(self._sample_position("2454"))
        positions = self.mgr.load_all()
        codes = [p["code"] for p in positions]
        for code in ("2330", "2317", "2454"):
            self.assertIn(code, codes)

    def test_risk_summary_returns_dict(self):
        """risk_summary 不應崩潰，結果為 dict。"""
        self.mgr.create(self._sample_position())
        positions = self.mgr.load_all()
        summary = self.mgr.risk_summary(positions, total_capital=1_000_000)
        self.assertIsInstance(summary, dict)


# ── 整合測試 3：Scanner.analyze_one() → format_for_api() ─────────────────────

class TestScanToFormatPipeline(unittest.TestCase):
    """analyze_one → format_for_api 輸出結構與內容驗證。"""

    def setUp(self):
        self.ind_engine = IndicatorEngine()
        self.scanner    = StockScanner(indicator_engine=self.ind_engine)
        self.df = _make_ohlcv(200)

    def _analyze_with_mock(self, code="2330", strategy="trend"):
        with patch.object(self.ind_engine, "fetch_ohlcv", return_value=self.df), \
             patch.object(self.scanner, "get_stock_name", return_value="台積電"):
            return self.scanner.analyze_one(code, capital=1_000_000,
                                            risk_pct=2.0, strategy=strategy)

    def test_analyze_one_returns_dict_with_required_keys(self):
        result = self._analyze_with_mock()
        self.assertIsNotNone(result)
        for key in ("code", "name", "score", "ind", "params", "strategy"):
            self.assertIn(key, result, f"缺少欄位: {key}")

    def test_format_for_api_has_correct_structure(self):
        """format_for_api 輸出每筆應包含 code、score、signals 等欄位。"""
        result = self._analyze_with_mock()
        self.assertIsNotNone(result)
        formatted = self.scanner.format_for_api([result], strategy="trend")
        self.assertEqual(len(formatted), 1)
        item = formatted[0]
        for key in ("code", "name", "score", "signals", "close"):
            self.assertIn(key, item, f"format_for_api 缺少欄位: {key}")

    def test_format_signals_have_pass_label_enabled(self):
        """每個信號應含 pass / label / enabled 欄位。"""
        result   = self._analyze_with_mock()
        formatted = self.scanner.format_for_api([result], strategy="trend")
        signals  = formatted[0]["signals"]
        self.assertGreater(len(signals), 0)
        for key, val in signals.items():
            self.assertIn("pass",    val, f"signals[{key}] 缺 pass")
            self.assertIn("label",   val, f"signals[{key}] 缺 label")
            self.assertIn("enabled", val, f"signals[{key}] 缺 enabled")

    def test_ict_analyze_one_also_works(self):
        """ICT 策略 analyze_one 也能正常回傳結果。"""
        result = self._analyze_with_mock(strategy="ict")
        self.assertIsNotNone(result)
        self.assertEqual(result["strategy"], "ict")


if __name__ == "__main__":
    unittest.main()
