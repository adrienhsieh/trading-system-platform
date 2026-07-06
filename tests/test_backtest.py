"""tests/test_backtest.py — BacktestEngine 單元測試"""
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from trading.backtest import BacktestEngine


# ── 測試輔助 ──────────────────────────────────────────────────

def _make_df(n: int = 200, trend: bool = True, seed: int = 42) -> pd.DataFrame:
    """建立模擬 OHLCV 日線資料（DatetimeIndex）。"""
    np.random.seed(seed)
    if trend:
        close = np.linspace(100, 160, n) + np.random.normal(0, 2, n)
    else:
        close = 100 + np.random.normal(0, 3, n).cumsum()
    close = np.clip(close, 10, None)
    idx = pd.date_range("2022-01-03", periods=n, freq="B")
    return pd.DataFrame({
        "open":   close * 0.99,
        "high":   close * 1.015,
        "low":    close * 0.975,
        "close":  close,
        "volume": np.full(n, 50_000.0),
    }, index=idx)


# ── _calc_stats ───────────────────────────────────────────────

class TestCalcStats(unittest.TestCase):

    def test_empty_trades_returns_zeros(self):
        s = BacktestEngine._calc_stats([], 1_000_000, 1_000_000)
        self.assertEqual(s["total_trades"], 0)
        self.assertEqual(s["win_rate"], 0.0)
        self.assertEqual(s["total_return"], 0.0)

    def test_all_wins(self):
        trades = [
            {"pnl": 10_000, "pnl_pct": 5.0},
            {"pnl":  8_000, "pnl_pct": 4.0},
        ]
        s = BacktestEngine._calc_stats(trades, 1_000_000, 1_018_000)
        self.assertEqual(s["wins"],   2)
        self.assertEqual(s["losses"], 0)
        self.assertEqual(s["win_rate"], 100.0)
        self.assertEqual(s["profit_factor"], 999.0)

    def test_all_losses(self):
        trades = [{"pnl": -5_000, "pnl_pct": -2.5}]
        s = BacktestEngine._calc_stats(trades, 1_000_000, 995_000)
        self.assertEqual(s["wins"],   0)
        self.assertEqual(s["losses"], 1)
        self.assertEqual(s["win_rate"], 0.0)
        self.assertEqual(s["profit_factor"], 0.0)

    def test_mixed_profit_factor(self):
        trades = [
            {"pnl": 10_000, "pnl_pct":  5.0},
            {"pnl": -5_000, "pnl_pct": -2.5},
            {"pnl":  8_000, "pnl_pct":  4.0},
            {"pnl": -3_000, "pnl_pct": -1.5},
        ]
        s = BacktestEngine._calc_stats(trades, 1_000_000, 1_010_000)
        self.assertEqual(s["total_trades"], 4)
        self.assertEqual(s["wins"],   2)
        self.assertEqual(s["losses"], 2)
        self.assertAlmostEqual(s["profit_factor"], 2.25, places=2)

    def test_max_drawdown_positive(self):
        trades = [
            {"pnl":  5_000, "pnl_pct":  5.0},
            {"pnl": -8_000, "pnl_pct": -8.0},
        ]
        s = BacktestEngine._calc_stats(trades, 100_000, 97_000)
        self.assertGreater(s["max_drawdown"], 0)

    def test_total_return_calculation(self):
        trades = [{"pnl": 100_000, "pnl_pct": 10.0}]
        s = BacktestEngine._calc_stats(trades, 1_000_000, 1_100_000)
        self.assertAlmostEqual(s["total_return"], 10.0, places=1)


# ── BacktestEngine.run ────────────────────────────────────────

class TestBacktestRun(unittest.TestCase):

    def setUp(self):
        self.engine = BacktestEngine()

    def test_returns_error_when_no_data(self):
        with patch.object(self.engine._ind, "fetch_ohlcv", return_value=None):
            r = self.engine.run("9999")
        self.assertFalse(r["ok"])
        self.assertIn("error", r)

    def test_returns_error_when_insufficient_data(self):
        tiny = _make_df(n=30)
        with patch.object(self.engine._ind, "fetch_ohlcv", return_value=tiny):
            r = self.engine.run("2330")
        self.assertFalse(r["ok"])

    def test_run_trend_returns_required_keys(self):
        with patch.object(self.engine._ind, "fetch_ohlcv", return_value=_make_df(200)):
            r = self.engine.run("2330", strategy="trend", capital=1_000_000)
        self.assertTrue(r["ok"])
        for key in ("trades", "equity_curve", "stats", "final_equity", "capital"):
            self.assertIn(key, r)

    def test_run_ict_strategy_executes(self):
        with patch.object(self.engine._ind, "fetch_ohlcv", return_value=_make_df(200)):
            r = self.engine.run("2330", strategy="ict", capital=1_000_000)
        self.assertTrue(r["ok"])
        self.assertIn("trades", r)

    def test_no_same_bar_exit(self):
        """進場後不可在同一根 K 棒出場（無未來偏差）。"""
        with patch.object(self.engine._ind, "fetch_ohlcv", return_value=_make_df(200)):
            r = self.engine.run("2330", strategy="trend", min_score=4)
        if r["ok"]:
            for t in r["trades"]:
                if t["reason"] != "未平倉":
                    self.assertNotEqual(t["entry_date"], t["exit_date"])

    def test_trades_have_required_keys(self):
        with patch.object(self.engine._ind, "fetch_ohlcv", return_value=_make_df(200)):
            r = self.engine.run("2330")
        if r["ok"] and r["trades"]:
            for t in r["trades"]:
                for key in ("entry_date", "exit_date", "entry", "exit",
                            "shares", "pnl", "pnl_pct", "reason"):
                    self.assertIn(key, t)

    def test_equity_curve_length_matches_bars(self):
        df = _make_df(200)
        with patch.object(self.engine._ind, "fetch_ohlcv", return_value=df):
            r = self.engine.run("2330", strategy="trend")
        if r["ok"]:
            from trading.strategies import get_strategy
            min_b = get_strategy("trend").min_bars
            self.assertEqual(len(r["equity_curve"]), len(df) - min_b)

    def test_final_equity_matches_last_equity_curve(self):
        with patch.object(self.engine._ind, "fetch_ohlcv", return_value=_make_df(200)):
            r = self.engine.run("2330")
        if r["ok"] and r["equity_curve"]:
            self.assertEqual(r["final_equity"], r["equity_curve"][-1]["equity"])

    def test_min_score_5_fewer_trades_than_min_score_3(self):
        """較高最低分數應產生較少（或等量）交易次數。"""
        df = _make_df(200)
        with patch.object(self.engine._ind, "fetch_ohlcv", return_value=df):
            r3 = self.engine.run("2330", min_score=3)
            r5 = self.engine.run("2330", min_score=5)
        if r3["ok"] and r5["ok"]:
            self.assertGreaterEqual(len(r3["trades"]), len(r5["trades"]))

    def test_stats_win_rate_between_0_and_100(self):
        with patch.object(self.engine._ind, "fetch_ohlcv", return_value=_make_df(200)):
            r = self.engine.run("2330")
        if r["ok"]:
            wr = r["stats"]["win_rate"]
            self.assertGreaterEqual(wr, 0.0)
            self.assertLessEqual(wr, 100.0)


# ── BacktestEngine.run_multi ───────────────────────────────────

class TestBacktestRunMulti(unittest.TestCase):

    def setUp(self):
        self.engine = BacktestEngine()

    def _patch_multi(self, codes: list, df):
        """回傳一個 patch context：對所有 codes 都回傳同一份 df。"""
        return patch.object(self.engine._ind, "fetch_ohlcv", return_value=df)

    def test_run_multi_returns_ok(self):
        df = _make_df(200)
        with self._patch_multi(["2330", "2454"], df):
            r = self.engine.run_multi(["2330", "2454"])
        self.assertTrue(r["ok"])

    def test_run_multi_has_results_and_summary(self):
        df = _make_df(200)
        with self._patch_multi(["2330", "2454"], df):
            r = self.engine.run_multi(["2330", "2454"])
        self.assertIn("results",  r)
        self.assertIn("summary",  r)
        self.assertEqual(len(r["results"]),  2)
        self.assertEqual(len(r["summary"]),  2)

    def test_run_multi_single_code_still_works(self):
        df = _make_df(200)
        with self._patch_multi(["2330"], df):
            r = self.engine.run_multi(["2330"])
        self.assertTrue(r["ok"])
        self.assertEqual(len(r["results"]), 1)

    def test_run_multi_failed_code_in_summary(self):
        """資料不足的代號應出現在 summary 且含 error 欄位。"""
        tiny = _make_df(n=10)
        with self._patch_multi(["2330"], tiny):
            r = self.engine.run_multi(["2330"])
        self.assertTrue(r["ok"])
        self.assertIn("error", r["summary"][0])

    def test_run_multi_summary_sorted_by_return(self):
        """summary 應依 total_return 降冪排列（成功的排在失敗之前）。"""
        df = _make_df(200, trend=True)
        with self._patch_multi(["A", "B", "C"], df):
            r = self.engine.run_multi(["A", "B", "C"])
        ok_rows = [s for s in r["summary"] if "total_return" in s]
        returns = [s["total_return"] for s in ok_rows]
        self.assertEqual(returns, sorted(returns, reverse=True))

    def test_run_multi_summary_contains_required_keys(self):
        df = _make_df(200)
        with self._patch_multi(["2330"], df):
            r = self.engine.run_multi(["2330"])
        row = r["summary"][0]
        if "error" not in row:
            for key in ("code", "total_return", "total_trades",
                        "win_rate", "profit_factor", "max_drawdown", "final_equity"):
                self.assertIn(key, row)


class TestFundamentalStrategyRegistered(unittest.TestCase):
    """FundamentalStrategy 已正確登錄且介面符合 BaseStrategy。"""

    def test_fundamental_in_registry(self):
        from trading.strategies import REGISTRY
        self.assertIn("fundamental", REGISTRY)

    def test_fundamental_strategy_has_required_attrs(self):
        from trading.strategies import REGISTRY
        strat = REGISTRY["fundamental"]
        self.assertEqual(strat.name, "fundamental")
        self.assertGreater(strat.min_bars, 0)
        self.assertIsInstance(strat.signal_labels, dict)
        self.assertGreater(len(strat.signal_labels), 0)

    def test_fundamental_returns_none_without_code(self):
        from trading.strategies import REGISTRY
        import pandas as pd
        import numpy as np
        strat = REGISTRY["fundamental"]
        n     = strat.min_bars + 5
        df    = pd.DataFrame({
            "open":   np.random.uniform(90, 110, n),
            "high":   np.random.uniform(100, 120, n),
            "low":    np.random.uniform(80, 100, n),
            "close":  np.random.uniform(95, 115, n),
            "volume": np.random.randint(1000, 10000, n),
        })
        # code="" → should return None (no code to fetch fundamentals for)
        result = strat.compute(df, code="")
        self.assertIsNone(result)

    def test_fundamental_returns_none_for_insufficient_data(self):
        from trading.strategies import REGISTRY
        import pandas as pd
        import numpy as np
        strat = REGISTRY["fundamental"]
        df    = pd.DataFrame({
            "open":   np.random.uniform(90, 110, 5),
            "high":   np.random.uniform(100, 120, 5),
            "low":    np.random.uniform(80, 100, 5),
            "close":  np.random.uniform(95, 115, 5),
            "volume": np.random.randint(1000, 10000, 5),
        })
        result = strat.compute(df, code="2330")
        self.assertIsNone(result)

    def test_fundamental_calc_entry_params(self):
        from trading.strategies import REGISTRY
        strat = REGISTRY["fundamental"]
        ind   = {
            "close": 100.0, "swing_low": 90.0,
            "signals": {k: True for k in strat.signal_labels},
            "score": 5,
            "pe": 15.0, "eps": 5.0, "forward_eps": 6.0, "pb": 1.5, "revenue_growth": 10.0,
        }
        params = strat.calc_entry_params(ind, 1_000_000, risk_pct=2.0)
        self.assertIn("entry",      params)
        self.assertIn("stop",       params)
        self.assertIn("target",     params)
        self.assertIn("shares",     params)
        self.assertIn("total_risk", params)
        self.assertGreater(params["shares"], 0)
        self.assertLess(params["stop"], params["entry"])
        self.assertGreater(params["target"], params["entry"])


class TestCommissionSlippage(unittest.TestCase):
    """手續費與滑價模型驗證。"""

    def setUp(self):
        self.engine = BacktestEngine()

    def test_with_commission_lower_return_than_without(self):
        """有手續費/滑價的報酬率應低於無手續費版本（合理降幅）。"""
        df = _make_df(200, trend=True)
        with patch.object(self.engine._ind, "fetch_ohlcv", return_value=df):
            r_no_cost = self.engine.run(
                "2330", commission_pct=0.0, slippage_pct=0.0
            )
            r_with_cost = self.engine.run(
                "2330", commission_pct=0.001425, slippage_pct=0.0005
            )
        if r_no_cost.get("ok") and r_with_cost.get("ok") and r_no_cost["stats"]["total_trades"] > 0:
            self.assertLessEqual(
                r_with_cost["stats"]["total_return"],
                r_no_cost["stats"]["total_return"],
            )

    def test_zero_commission_zero_slippage_equals_original_logic(self):
        """commission=0 且 slippage=0 時 final_equity 應等於 capital + sum(pnl)（近似）。"""
        df = _make_df(200, trend=True)
        with patch.object(self.engine._ind, "fetch_ohlcv", return_value=df):
            r = self.engine.run("2330", commission_pct=0.0, slippage_pct=0.0)
        if r.get("ok"):
            expected = 1_000_000 + sum(t["pnl"] for t in r["trades"])
            self.assertAlmostEqual(r["final_equity"], expected, delta=5)

    def test_trades_have_code_field(self):
        """每筆交易記錄應含 code 欄位（用於 CSV 匯出）。"""
        df = _make_df(200, trend=True)
        with patch.object(self.engine._ind, "fetch_ohlcv", return_value=df):
            r = self.engine.run("2330")
        if r.get("ok") and r["trades"]:
            for t in r["trades"]:
                self.assertIn("code", t)
                self.assertEqual(t["code"], "2330")


class TestMonteCarlo(unittest.TestCase):
    """BacktestEngine.monte_carlo() 信心區間。"""

    def test_empty_trades_returns_empty_lists(self):
        result = BacktestEngine.monte_carlo([], capital=1_000_000)
        self.assertEqual(result["p5"],  [])
        self.assertEqual(result["p50"], [])
        self.assertEqual(result["p95"], [])

    def test_returns_three_percentile_lists(self):
        trades = [{"pnl": 10_000} for _ in range(10)]
        result = BacktestEngine.monte_carlo(trades, capital=1_000_000, n=100)
        self.assertIn("p5",  result)
        self.assertIn("p50", result)
        self.assertIn("p95", result)

    def test_curve_length_equals_trades_plus_one(self):
        trades = [{"pnl": 5_000} for _ in range(8)]
        result = BacktestEngine.monte_carlo(trades, capital=1_000_000, n=50)
        self.assertEqual(len(result["p5"]),  9)  # len(trades) + 1
        self.assertEqual(len(result["p50"]), 9)
        self.assertEqual(len(result["p95"]), 9)

    def test_p5_leq_p50_leq_p95(self):
        """p5 ≤ p50 ≤ p95 在每個時間點均成立。"""
        trades = [{"pnl": 5_000 if i % 3 != 0 else -8_000} for i in range(20)]
        result = BacktestEngine.monte_carlo(trades, capital=1_000_000, n=200)
        for p5, p50, p95 in zip(result["p5"], result["p50"], result["p95"]):
            self.assertLessEqual(p5, p50)
            self.assertLessEqual(p50, p95)

    def test_all_positive_pnl_p5_above_capital(self):
        """所有交易為正損益時，p5 最終值應 ≥ 初始資金。"""
        trades = [{"pnl": 10_000} for _ in range(5)]
        result = BacktestEngine.monte_carlo(trades, capital=1_000_000, n=100)
        self.assertGreaterEqual(result["p5"][-1], 1_000_000)


if __name__ == "__main__":
    unittest.main()
