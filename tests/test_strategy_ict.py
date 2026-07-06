"""tests/test_strategy_ict.py — ICTStrategy 單元測試

涵蓋：min_bars 防衛、輸出 schema、七個 ICT 信號偵測、calc_entry_params 數學正確性。
"""
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from trading.strategies.ict import ICTStrategy


# ── 測試資料工廠 ─────────────────────────────────────────────────────────────

def _make_df(n: int, close_vals=None, high_offset=2.0, low_offset=-2.0) -> pd.DataFrame:
    """建立 OHLCV DataFrame，close 預設為 [100, 101, ..., 100+n-1]。"""
    if close_vals is None:
        close_vals = [100.0 + i for i in range(n)]
    close = np.array(close_vals, dtype=float)
    high  = close + high_offset
    low   = close + low_offset
    open_ = close * 0.999
    vol   = np.full(n, 1000.0)
    return pd.DataFrame({
        "open": open_, "high": high, "low": low,
        "close": close, "volume": vol,
    })


def _no_params(self):
    return {}


# ── min_bars ─────────────────────────────────────────────────────────────────

class TestICTStrategyMinBars(unittest.TestCase):

    def setUp(self):
        self.strat = ICTStrategy()
        patch.object(ICTStrategy, "_load_params", _no_params).start()
        self.addCleanup(patch.stopall)

    def test_too_few_bars_returns_none(self):
        """29 根 K 棒（< min_bars=30）應回傳 None。"""
        self.assertIsNone(self.strat.compute(_make_df(29)))

    def test_exactly_min_bars_returns_dict(self):
        """剛好 30 根應回傳 dict。"""
        self.assertIsInstance(self.strat.compute(_make_df(30)), dict)

    def test_sufficient_bars_returns_dict(self):
        """充足資料應正常計算。"""
        self.assertIsNotNone(self.strat.compute(_make_df(80)))


# ── 輸出 Schema ──────────────────────────────────────────────────────────────

class TestICTStrategyOutputSchema(unittest.TestCase):

    def setUp(self):
        self.strat = ICTStrategy()
        patch.object(ICTStrategy, "_load_params", _no_params).start()
        self.addCleanup(patch.stopall)
        self.result = self.strat.compute(_make_df(80))

    def test_required_keys_present(self):
        for key in ("close", "equilibrium", "range_high", "range_low",
                    "signals", "score", "total_enabled", "enabled"):
            self.assertIn(key, self.result, f"缺少欄位: {key}")

    def test_signals_has_all_seven_keys(self):
        for key in ICTStrategy.signal_labels:
            self.assertIn(key, self.result["signals"], f"signals 缺少: {key}")

    def test_total_enabled_is_seven_by_default(self):
        """預設 7 個信號全部啟用。"""
        self.assertEqual(self.result["total_enabled"], 7)

    def test_score_between_zero_and_seven(self):
        self.assertGreaterEqual(self.result["score"], 0)
        self.assertLessEqual(self.result["score"], 7)


# ── 信號偵測邏輯 ─────────────────────────────────────────────────────────────

class TestICTStrategySignals(unittest.TestCase):

    def setUp(self):
        self.strat = ICTStrategy()
        patch.object(ICTStrategy, "_load_params", _no_params).start()
        self.addCleanup(patch.stopall)

    # ── Discount Zone ─────────────────────────────────────────────────────────
    # discount_zone = close[-1] < (high[-20:].max() + low[-20:].min()) / 2

    def test_discount_zone_true_when_close_below_equilibrium(self):
        """收盤 < 近 20 根區間中點（均衡價）→ True。"""
        # 最後 20 根：從 200 跌到 90 → high_max=202, low_min=88, eq=145, close[-1]=90
        close_vals = [100.0] * 60 + list(np.linspace(200.0, 90.0, 20))
        df = _make_df(80, close_vals=close_vals)
        result = self.strat.compute(df)
        self.assertTrue(result["signals"]["discount_zone"])
        self.assertLess(result["close"], result["equilibrium"])

    def test_discount_zone_false_when_close_above_equilibrium(self):
        """收盤 > 均衡價 → False。"""
        # 最後 20 根：從 90 漲到 200 → close[-1]=200 > eq
        close_vals = [100.0] * 60 + list(np.linspace(90.0, 200.0, 20))
        df = _make_df(80, close_vals=close_vals)
        result = self.strat.compute(df)
        self.assertFalse(result["signals"]["discount_zone"])

    # ── Break of Structure ────────────────────────────────────────────────────
    # bos = close[-1] > max(high[-(lookback+2):-2])，lookback = min(n-3, 25)

    def test_bos_true_when_close_breaks_recent_swing_high(self):
        """收盤突破近期擺動高點 → True。"""
        # 前 78 根緩漲至 147（high 最高 149），最後兩根急漲至 200
        close_vals = list(np.linspace(100.0, 147.0, 78)) + [200.0, 200.0]
        df = _make_df(80, close_vals=close_vals)
        result = self.strat.compute(df)
        self.assertTrue(result["signals"]["bos"])
        self.assertIsNotNone(result["swing_high_ref"])

    def test_bos_false_when_close_below_recent_high(self):
        """收盤低於近期擺動高點 → False。"""
        close_vals = [150.0] * 40 + [80.0] * 40
        df = _make_df(80, close_vals=close_vals)
        result = self.strat.compute(df)
        self.assertFalse(result["signals"]["bos"])

    # ── Liquidity Sweep ───────────────────────────────────────────────────────
    # swept = any(low[-5:] < min(low[-20:-5]))  AND  recovered = close[-1] > that min

    def test_liquidity_sweep_detected_dip_and_recovery(self):
        """近 5 根某根刺破前段低點，且最新收盤已收回 → True。"""
        # 前段（low[-20:-5] = bars 60..74）: close=100, low=98 → sl=98
        # bar 76（low[-4]）: 手動設 low=94 < sl=98 → swept=True
        # close[-1] = 100 > sl=98 → recovered=True
        close_vals = [100.0] * 80
        df = _make_df(80, close_vals=close_vals)
        df.loc[df.index[76], "low"] = 94.0   # bar 76 = index -4
        result = self.strat.compute(df)
        self.assertTrue(result["signals"]["liquidity_sweep"])

    def test_no_liquidity_sweep_when_no_dip(self):
        """最後 5 根沒有刺破前段低點 → False。"""
        close_vals = [100.0] * 80
        df = _make_df(80, close_vals=close_vals)
        result = self.strat.compute(df)
        self.assertFalse(result["signals"]["liquidity_sweep"])

    # ── OTE Zone ─────────────────────────────────────────────────────────────
    # 需要：近40根出現 swing_low → swing_high，close[-1] 在 61.8%-78.6% 回撤區間

    def test_ote_zone_when_close_in_fibonacci_retracement(self):
        """收盤在近期擺動 61.8%–78.6% 回撤區間 → True。"""
        # 後 60 根：先漲（swing_low=58）再急漲（swing_high=162）再回撤到 90（OTE 區間）
        # Last 40 bars:
        #   bars 40..59: linspace(60, 160, 20) → sl at 58, sh at 162
        #   bars 60..79: linspace(160, 90, 20)  → retrace to close[-1]=90
        # ote_top = 162 - 0.618*(162-58) = 97.7
        # ote_bot = 162 - 0.786*(162-58) = 80.3
        # close[-1] = 90 → 80.3 ≤ 90 ≤ 97.7 ✓
        close_vals = (
            [100.0] * 20 +
            list(np.linspace(100.0, 60.0, 20)) +
            list(np.linspace(60.0, 160.0, 20)) +
            list(np.linspace(160.0, 90.0, 20))
        )
        df = _make_df(80, close_vals=close_vals)
        result = self.strat.compute(df)
        self.assertTrue(result["signals"]["ote_zone"])
        self.assertIsNotNone(result["ote_top"])
        self.assertIsNotNone(result["ote_bot"])

    # ── FVG ──────────────────────────────────────────────────────────────────
    # gap_top=low[i] > gap_bot=high[i-2]（3棒不平衡）且 c >= gap_bot

    def test_fvg_detected_with_upward_gap(self):
        """最後幾根存在向上跳空（未填補）→ True。"""
        # candle[77]: high=102, candle[79]: low=103 → gap 102..103 ✓
        close_vals = [100.0] * 77 + [100.0, 102.0, 105.0]
        df = _make_df(80, close_vals=close_vals)
        result = self.strat.compute(df)
        self.assertTrue(result["signals"]["fvg_present"])
        self.assertIsNotNone(result["fvg_top"])

    # ── Bullish Order Block ────────────────────────────────────────────────────

    def test_bullish_ob_detected_with_bearish_candle_and_break(self):
        """近 30 根中跌棒後立即突破，且現價站上 OB 高點 → True。"""
        # bar 65: 跌棒（close=98 < open=101），high=100
        # bar 66: close=104 > high[65]=100（突破）
        # close[-1]=105 > high[65]=100 ✓
        close_vals = [100.0] * 65 + [98.0, 104.0] + [105.0] * 13
        df = _make_df(80, close_vals=close_vals)
        # 設定 bar 65 為跌棒
        df.loc[df.index[65], "open"] = 101.0
        result = self.strat.compute(df)
        self.assertTrue(result["signals"]["bullish_ob"])


# ── calc_entry_params ────────────────────────────────────────────────────────

class TestICTStrategyCalcEntryParams(unittest.TestCase):

    def setUp(self):
        self.strat = ICTStrategy()

    def _ind_with_ob(self, close=100.0, ob_low=85.0, range_low=80.0, swing_high=120.0):
        return {
            "close": close, "ob_low": ob_low, "ob_high": ob_low + 5,
            "range_low": range_low, "swing_high_ref": swing_high,
        }

    def _ind_no_ob(self, close=100.0, range_low=80.0):
        return {
            "close": close, "ob_low": None, "ob_high": None,
            "range_low": range_low, "swing_high_ref": None,
        }

    def test_stop_based_on_ob_low_when_ob_available(self):
        """有 OB 時停損 = ob_low × 0.99。"""
        ind = self._ind_with_ob(close=100, ob_low=85)
        params = self.strat.calc_entry_params(ind, 100_000, 2.0)
        self.assertAlmostEqual(params["stop"], round(85.0 * 0.99, 2), places=2)

    def test_stop_based_on_range_low_when_no_ob(self):
        """無 OB 時停損 = range_low × 0.99。"""
        ind = self._ind_no_ob(close=100, range_low=80)
        params = self.strat.calc_entry_params(ind, 100_000, 2.0)
        self.assertAlmostEqual(params["stop"], round(80.0 * 0.99, 2), places=2)

    def test_target_uses_swing_high_when_available(self):
        """有 swing_high_ref > entry 時目標取 swing_high_ref。"""
        ind = self._ind_with_ob(close=100, swing_high=130)
        params = self.strat.calc_entry_params(ind, 100_000, 2.0)
        self.assertAlmostEqual(params["target"], 130.0, places=2)

    def test_target_uses_2x_risk_when_no_swing_high(self):
        """無 swing_high_ref 時目標 = entry + risk_per × 2。"""
        ind = self._ind_no_ob(close=100, range_low=80)
        params = self.strat.calc_entry_params(ind, 100_000, 2.0)
        risk   = params["entry"] - params["stop"]
        reward = params["target"] - params["entry"]
        self.assertAlmostEqual(reward / risk, 2.0, places=5)

    def test_entry_equals_close(self):
        ind = self._ind_with_ob()
        params = self.strat.calc_entry_params(ind, 100_000, 2.0)
        self.assertEqual(params["entry"], ind["close"])

    def test_stop_below_entry(self):
        ind = self._ind_with_ob()
        params = self.strat.calc_entry_params(ind, 100_000, 2.0)
        self.assertLess(params["stop"], params["entry"])

    def test_shares_is_non_negative_integer(self):
        ind = self._ind_with_ob()
        params = self.strat.calc_entry_params(ind, 100_000, 2.0)
        self.assertIsInstance(params["shares"], int)
        self.assertGreaterEqual(params["shares"], 0)


if __name__ == "__main__":
    unittest.main()
