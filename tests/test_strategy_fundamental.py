"""tests/test_strategy_fundamental.py — FundamentalStrategy 單元測試

涵蓋：REGISTRY 登錄、min_bars 防衛、各基本面信號判斷、calc_entry_params 數學正確性。
"""
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from trading.strategies import REGISTRY
from trading.strategies.fundamental import FundamentalStrategy, _get_fundamentals


# ── 測試資料工廠 ─────────────────────────────────────────────────────────────

def _make_df(n: int, base=100.0) -> pd.DataFrame:
    close = np.array([base] * n, dtype=float)
    return pd.DataFrame({
        "open":   close * 0.999,
        "high":   close + 2,
        "low":    close - 2,
        "close":  close,
        "volume": np.full(n, 1000.0),
    })


def _no_params(self):
    return {}


# ── REGISTRY ─────────────────────────────────────────────────────────────────

class TestFundamentalStrategyRegistry(unittest.TestCase):

    def test_registry_has_fundamental_key(self):
        """REGISTRY 必須含 'fundamental' 鍵。"""
        self.assertIn("fundamental", REGISTRY)

    def test_registry_value_is_fundamental_strategy_instance(self):
        """REGISTRY['fundamental'] 必須是 FundamentalStrategy 實例。"""
        self.assertIsInstance(REGISTRY["fundamental"], FundamentalStrategy)

    def test_strategy_name_attribute(self):
        self.assertEqual(REGISTRY["fundamental"].name, "fundamental")

    def test_strategy_has_signal_labels(self):
        """signal_labels 應包含五個基本面信號。"""
        strat = REGISTRY["fundamental"]
        for key in ("pe_reasonable", "eps_positive", "eps_growth",
                    "pb_reasonable", "revenue_growth"):
            self.assertIn(key, strat.signal_labels)


# ── min_bars & 必填條件 ───────────────────────────────────────────────────────

class TestFundamentalStrategyMinBars(unittest.TestCase):

    def setUp(self):
        self.strat = FundamentalStrategy()
        patch.object(FundamentalStrategy, "_load_params", _no_params).start()
        self.addCleanup(patch.stopall)

    def test_too_few_bars_returns_none(self):
        """資料少於 min_bars=20 → None。"""
        self.assertIsNone(self.strat.compute(_make_df(19), code="2330"))

    def test_empty_code_returns_none(self):
        """code='' 時不取得基本面資料 → None。"""
        self.assertIsNone(self.strat.compute(_make_df(30), code=""))

    def test_empty_fundamentals_returns_none(self):
        """_get_fundamentals 回傳空 dict → None。"""
        with patch("trading.strategies.fundamental._get_fundamentals", return_value={}):
            result = self.strat.compute(_make_df(30), code="2330")
        self.assertIsNone(result)


# ── 信號計算邏輯 ─────────────────────────────────────────────────────────────

def _fund(**kwargs):
    """建立基本面數據字典，填入預設值後覆蓋。"""
    base = {
        "trailingPE":    20.0,
        "trailingEps":   5.0,
        "forwardEps":    6.0,
        "priceToBook":   1.5,
        "revenueGrowth": 0.10,
        "currentPrice":  100.0,
    }
    base.update(kwargs)
    return base


class TestFundamentalStrategySignals(unittest.TestCase):

    def setUp(self):
        self.strat = FundamentalStrategy()
        patch.object(FundamentalStrategy, "_load_params", _no_params).start()
        self.addCleanup(patch.stopall)
        self.df = _make_df(30)

    def _compute(self, **fund_overrides):
        data = _fund(**fund_overrides)
        with patch("trading.strategies.fundamental._get_fundamentals", return_value=data):
            return self.strat.compute(self.df, code="2330")

    def test_pe_reasonable_true_when_pe_below_threshold(self):
        """PE = 20 < 閾值 30 → True。"""
        result = self._compute(trailingPE=20.0)
        self.assertTrue(result["signals"]["pe_reasonable"])

    def test_pe_reasonable_false_when_pe_exceeds_threshold(self):
        """PE = 50 > 閾值 30 → False。"""
        result = self._compute(trailingPE=50.0)
        self.assertFalse(result["signals"]["pe_reasonable"])

    def test_pe_reasonable_false_when_pe_none(self):
        """PE 為 None → False。"""
        result = self._compute(trailingPE=None)
        self.assertFalse(result["signals"]["pe_reasonable"])

    def test_eps_positive_true_when_eps_above_zero(self):
        """EPS = 5 > 0 → True。"""
        result = self._compute(trailingEps=5.0)
        self.assertTrue(result["signals"]["eps_positive"])

    def test_eps_positive_false_when_eps_negative(self):
        """EPS = -1 < 0 → False。"""
        result = self._compute(trailingEps=-1.0)
        self.assertFalse(result["signals"]["eps_positive"])

    def test_eps_growth_true_when_forward_eps_exceeds_trailing(self):
        """forwardEps(6) > trailingEps(5) → True。"""
        result = self._compute(trailingEps=5.0, forwardEps=6.0)
        self.assertTrue(result["signals"]["eps_growth"])

    def test_eps_growth_false_when_forward_eps_lower(self):
        """forwardEps(4) < trailingEps(5) → False。"""
        result = self._compute(trailingEps=5.0, forwardEps=4.0)
        self.assertFalse(result["signals"]["eps_growth"])

    def test_revenue_growth_true_when_positive(self):
        """revenueGrowth = 0.10 > 0 → True。"""
        result = self._compute(revenueGrowth=0.10)
        self.assertTrue(result["signals"]["revenue_growth"])

    def test_revenue_growth_false_when_negative(self):
        """revenueGrowth = -0.05 < 0 → False。"""
        result = self._compute(revenueGrowth=-0.05)
        self.assertFalse(result["signals"]["revenue_growth"])

    def test_all_signals_pass_gives_score_five(self):
        """所有 5 個信號通過 → score = 5。"""
        result = self._compute()
        self.assertEqual(result["score"], 5)
        self.assertEqual(result["total_enabled"], 5)

    def test_output_schema_has_required_keys(self):
        result = self._compute()
        for key in ("close", "pe", "eps", "forward_eps", "pb",
                    "revenue_growth", "signals", "score", "total_enabled"):
            self.assertIn(key, result, f"缺少欄位: {key}")


# ── calc_entry_params ────────────────────────────────────────────────────────

class TestFundamentalStrategyCalcEntryParams(unittest.TestCase):

    def setUp(self):
        self.strat = FundamentalStrategy()

    def _ind(self, close=100.0, swing_low=90.0):
        return {"close": close, "swing_low": swing_low}

    def test_entry_equals_close(self):
        params = self.strat.calc_entry_params(self._ind(), 100_000, 2.0)
        self.assertEqual(params["entry"], 100.0)

    def test_stop_is_below_entry(self):
        params = self.strat.calc_entry_params(self._ind(close=100, swing_low=90), 100_000, 2.0)
        self.assertLess(params["stop"], params["entry"])

    def test_stop_equals_swing_low_times_0_98(self):
        """停損 = swing_low × 0.98。"""
        params = self.strat.calc_entry_params(self._ind(close=100, swing_low=90), 100_000, 2.0)
        self.assertAlmostEqual(params["stop"], round(90 * 0.98, 2), places=2)

    def test_target_above_entry(self):
        params = self.strat.calc_entry_params(self._ind(), 100_000, 2.0)
        self.assertGreater(params["target"], params["entry"])


if __name__ == "__main__":
    unittest.main()
