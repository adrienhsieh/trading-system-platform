"""tests/test_strategy_trend.py — TrendStrategy 單元測試

涵蓋：min_bars 防衛、輸出 schema、各信號偵測邏輯、calc_entry_params 數學正確性。
"""
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from trading.strategies.trend import TrendStrategy
from trading.indicators import IndicatorEngine as IE


# ── 測試資料工廠 ─────────────────────────────────────────────────────────────

def _make_df(n: int, close_fn=None, high_offset=2.0, low_offset=-2.0,
             vol: float = 1000.0, last_vol_mult: float = 1.0) -> pd.DataFrame:
    """建立合成 OHLCV DataFrame。

    close_fn(i) → float；若為 None 則預設線性上升（100 + i）。
    last_vol_mult：最後一根成交量倍數。
    """
    if close_fn is None:
        close_vals = np.array([100.0 + i for i in range(n)])
    else:
        close_vals = np.array([float(close_fn(i)) for i in range(n)])
    high  = close_vals + high_offset
    low   = close_vals + low_offset
    open_ = close_vals * 0.999
    vol_arr = np.full(n, vol)
    vol_arr[-1] = vol * last_vol_mult
    return pd.DataFrame({
        "open": open_, "high": high, "low": low,
        "close": close_vals, "volume": vol_arr,
    })


def _no_params(self):
    """替換 _load_params，回傳空 dict（使用預設閾值）。"""
    return {}


# ── min_bars ─────────────────────────────────────────────────────────────────

class TestTrendStrategyMinBars(unittest.TestCase):

    def setUp(self):
        self.strat = TrendStrategy()
        patch.object(TrendStrategy, "_load_params", _no_params).start()
        self.addCleanup(patch.stopall)

    def test_too_few_bars_returns_none(self):
        """64 根 K 棒（< min_bars=65）應回傳 None。"""
        self.assertIsNone(self.strat.compute(_make_df(64)))

    def test_exactly_min_bars_returns_dict(self):
        """剛好 65 根應回傳 dict。"""
        result = self.strat.compute(_make_df(65))
        self.assertIsInstance(result, dict)

    def test_sufficient_bars_returns_dict(self):
        """充足資料（130 根）應正常計算。"""
        self.assertIsNotNone(self.strat.compute(_make_df(130)))


# ── 輸出 Schema ──────────────────────────────────────────────────────────────

class TestTrendStrategyOutputSchema(unittest.TestCase):

    def setUp(self):
        self.strat = TrendStrategy()
        patch.object(TrendStrategy, "_load_params", _no_params).start()
        self.addCleanup(patch.stopall)
        self.result = self.strat.compute(_make_df(130))

    def test_required_keys_present(self):
        for key in ("close", "ema5", "ema20", "ema60", "adx", "atr",
                    "macd_hist", "signals", "score", "total_enabled", "enabled"):
            self.assertIn(key, self.result, f"缺少欄位: {key}")

    def test_signals_has_all_six_keys(self):
        for key in TrendStrategy.signal_labels:
            self.assertIn(key, self.result["signals"], f"signals 缺少: {key}")

    def test_total_enabled_is_six_by_default(self):
        """預設所有 6 個信號均啟用。"""
        self.assertEqual(self.result["total_enabled"], 6)

    def test_score_is_non_negative_integer(self):
        self.assertIsInstance(self.result["score"], int)
        self.assertGreaterEqual(self.result["score"], 0)


# ── 信號偵測邏輯 ─────────────────────────────────────────────────────────────

class TestTrendStrategySignals(unittest.TestCase):

    def setUp(self):
        self.strat = TrendStrategy()
        patch.object(TrendStrategy, "_load_params", _no_params).start()
        self.addCleanup(patch.stopall)

    # ── EMA 排列 ──────────────────────────────────────────────────────────────

    def test_ema_arrangement_true_for_uptrend(self):
        """強勢上漲趨勢：收 > EMA5 > EMA20 > EMA60 → True。"""
        df = _make_df(130, close_fn=lambda i: 100.0 + i * 2)
        result = self.strat.compute(df)
        self.assertTrue(result["signals"]["ema_arrangement"])

    def test_ema_arrangement_false_for_downtrend(self):
        """下跌趨勢：均線死亡排列 → False。"""
        df = _make_df(130, close_fn=lambda i: 500.0 - i * 2)
        result = self.strat.compute(df)
        self.assertFalse(result["signals"]["ema_arrangement"])

    # ── ADX ───────────────────────────────────────────────────────────────────

    def test_adx_above_25_for_linear_trend(self):
        """線性上升趨勢 ADX 應 > 25。"""
        df = _make_df(130, close_fn=lambda i: 100.0 + i)
        result = self.strat.compute(df)
        self.assertTrue(result["signals"]["adx_above_25"])
        self.assertGreater(result["adx"], 25)

    def test_adx_below_25_for_choppy_market(self):
        """鋸齒震盪（無方向性）ADX 應不觸發。"""
        df = _make_df(130, close_fn=lambda i: 100.0 + (1.0 if i % 2 == 0 else -1.0))
        result = self.strat.compute(df)
        self.assertFalse(result["signals"]["adx_above_25"])

    # ── MACD ─────────────────────────────────────────────────────────────────

    def test_macd_positive_when_histogram_positive(self):
        """MACD 柱狀圖 > 0 → macd_positive = True。"""
        df = _make_df(130)
        n = len(df)
        with patch.object(IE, "_macd", return_value=(
            pd.Series([2.0] * n, dtype=float),
            pd.Series([1.5] * n, dtype=float),
            pd.Series([0.5] * n, dtype=float),   # 正柱
        )):
            result = self.strat.compute(df)
        self.assertTrue(result["signals"]["macd_positive"])
        self.assertAlmostEqual(result["macd_hist"], 0.5, places=2)

    def test_macd_negative_when_histogram_negative(self):
        """MACD 柱狀圖 < 0 → macd_positive = False。"""
        df = _make_df(130)
        n = len(df)
        with patch.object(IE, "_macd", return_value=(
            pd.Series([-2.0] * n, dtype=float),
            pd.Series([-1.5] * n, dtype=float),
            pd.Series([-0.5] * n, dtype=float),  # 負柱
        )):
            result = self.strat.compute(df)
        self.assertFalse(result["signals"]["macd_positive"])

    # ── 爆量 ─────────────────────────────────────────────────────────────────

    def test_volume_spike_true_when_last_vol_exceeds_threshold(self):
        """最後一根成交量 = 2× 均量 (> 1.5×) → True。"""
        df = _make_df(130, vol=1000.0, last_vol_mult=2.0)
        result = self.strat.compute(df)
        self.assertTrue(result["signals"]["volume_spike"])

    def test_volume_spike_false_when_vol_normal(self):
        """最後一根成交量 = 1× 均量 → False。"""
        df = _make_df(130, vol=1000.0, last_vol_mult=1.0)
        result = self.strat.compute(df)
        self.assertFalse(result["signals"]["volume_spike"])

    # ── EMA 黃金交叉 ──────────────────────────────────────────────────────────

    def test_ema_crossover_detected_when_ema5_just_crossed_above(self):
        """EMA5 剛穿越 EMA20（近 3 根內）→ ema_crossover = True。"""
        df = _make_df(130)
        n = len(df)
        # ema5 在最後一根才站上 ema20（之前在下方）
        ema5_vals  = [8.0] * n;  ema5_vals[-1]  = 10.0
        ema20_vals = [9.0] * n

        def _ema_side(series, length):
            if length == 5:
                return pd.Series(ema5_vals, dtype=float)
            elif length == 20:
                return pd.Series(ema20_vals, dtype=float)
            elif length == 60:
                return pd.Series([5.0] * n, dtype=float)
            # 其他長度（_adx / _macd 內部使用）→ 正常計算
            return series.ewm(span=length, adjust=False).mean()

        with patch.object(IE, "_ema", side_effect=_ema_side):
            result = self.strat.compute(df)

        self.assertTrue(result["signals"]["ema_crossover"])
        self.assertIsNotNone(result["cross_days"])

    def test_no_ema_crossover_when_ema5_always_above(self):
        """EMA5 始終高於 EMA20（無近期交叉）→ False。"""
        df = _make_df(130)
        n = len(df)
        # ema5 在整段歷史都 > ema20 → 找不到之前在下方的時間點
        ema5_vals  = [10.0] * n
        ema20_vals = [8.0]  * n

        def _ema_side(series, length):
            if length == 5:
                return pd.Series(ema5_vals, dtype=float)
            elif length == 20:
                return pd.Series(ema20_vals, dtype=float)
            elif length == 60:
                return pd.Series([5.0] * n, dtype=float)
            return series.ewm(span=length, adjust=False).mean()

        with patch.object(IE, "_ema", side_effect=_ema_side):
            result = self.strat.compute(df)

        self.assertFalse(result["signals"]["ema_crossover"])
        self.assertIsNone(result["cross_days"])


# ── Score 驗算 ───────────────────────────────────────────────────────────────

class TestTrendStrategyScore(unittest.TestCase):

    def setUp(self):
        self.strat = TrendStrategy()
        patch.object(TrendStrategy, "_load_params", _no_params).start()
        self.addCleanup(patch.stopall)

    def test_score_zero_when_all_signals_false(self):
        """全部信號強制返回 False → score = 0。"""
        df = _make_df(130, vol=1000.0)
        n = len(df)
        flat = pd.Series([100.0] * n, dtype=float)

        with patch.object(IE, "_ema",  return_value=flat), \
             patch.object(IE, "_adx",  return_value=pd.Series([10.0] * n, dtype=float)), \
             patch.object(IE, "_atr",  return_value=pd.Series([1.0]  * n, dtype=float)), \
             patch.object(IE, "_macd", return_value=(flat, flat, pd.Series([-1.0] * n, dtype=float))), \
             patch.object(IE, "_sma",  return_value=pd.Series([9999.0] * n, dtype=float)):
            result = self.strat.compute(df)

        # 驗算每個信號
        # ema_arrangement: c(229) > e5(100) > e20(100) > e60(100) → 100>100 = False
        # slopes_up: flat[-1]=flat[-3]=100 → False
        # adx_above_25: 10 < 25 → False
        # macd_positive: -1 < 0 → False
        # volume_spike: 1000 > 9999*1.5 → False
        # ema_crossover: e5_now(100) >= e20(100) but ema5.iloc[-2]=100 not < 100 → False
        self.assertEqual(result["score"], 0)


# ── calc_entry_params ────────────────────────────────────────────────────────

class TestTrendStrategyCalcEntryParams(unittest.TestCase):

    def setUp(self):
        self.strat = TrendStrategy()

    def _ind(self, close=100.0, swing_low=90.0, atr=0.0):
        return {"close": close, "swing_low": swing_low, "atr": atr}

    def test_entry_equals_close(self):
        params = self.strat.calc_entry_params(self._ind(), 100_000, 2.0)
        self.assertEqual(params["entry"], 100.0)

    def test_stop_is_below_entry(self):
        params = self.strat.calc_entry_params(self._ind(close=100, swing_low=90, atr=0), 100_000, 2.0)
        self.assertLess(params["stop"], params["entry"])

    def test_target_is_above_entry(self):
        params = self.strat.calc_entry_params(self._ind(), 100_000, 2.0)
        self.assertGreater(params["target"], params["entry"])

    def test_risk_reward_ratio_is_2_to_1(self):
        """目標 = entry + 2 × risk → 風報比 2:1。"""
        params = self.strat.calc_entry_params(self._ind(close=100, swing_low=90, atr=0), 100_000, 2.0)
        risk   = params["entry"] - params["stop"]
        reward = params["target"] - params["entry"]
        self.assertAlmostEqual(reward / risk, 2.0, places=5)

    def test_shares_based_on_capital_and_risk_pct(self):
        """shares = floor((capital × risk% / 100) / risk_per)。"""
        # stop = 90 - 0 = 90, risk_per = 10, budget = 100000*0.02 = 2000
        # shares = int(2000 / 10) = 200
        params = self.strat.calc_entry_params(self._ind(close=100, swing_low=90, atr=0), 100_000, 2.0)
        self.assertEqual(params["shares"], 200)

    def test_total_risk_equals_risk_per_times_shares(self):
        params = self.strat.calc_entry_params(self._ind(close=100, swing_low=90, atr=0), 100_000, 2.0)
        expected = int(params["risk_per_share"] * params["shares"])
        self.assertEqual(params["total_risk"], expected)

    def test_zero_atr_and_equal_stop_does_not_crash(self):
        """stop ≥ entry 時 risk_per = max(..., 0.01) 保護不崩潰。"""
        ind = {"close": 100.0, "swing_low": 100.0, "atr": 0.0}
        try:
            params = self.strat.calc_entry_params(ind, 100_000, 2.0)
            self.assertIsInstance(params, dict)
        except Exception as exc:
            self.fail(f"calc_entry_params 不應拋出例外: {exc}")


if __name__ == "__main__":
    unittest.main()
