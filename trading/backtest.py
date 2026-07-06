"""trading/backtest.py — Walk-forward 回測引擎

設計原則：
- 嚴格逐根 K 棒前向推進，bar i 的訊號只能用 df[:i+1] 的資料
- 進場後不在同一根 K 棒出場
- 停損優先（使用當日最低價判斷），目標其次（使用當日最高價）
- 未平倉部位以最後一根 K 棒收盤價強制平倉
- 支援滑價與手續費（commission_pct / slippage_pct）
"""
from __future__ import annotations

import concurrent.futures
import random
from typing import Optional

from trading.indicators import IndicatorEngine
from trading.strategies import get_strategy
from trading.logger import get_logger

logger = get_logger("backtest")


class BacktestEngine:
    """Walk-forward backtester，支援趨勢策略（trend）與 ict 策略。"""

    def __init__(self, indicator_engine: IndicatorEngine = None):
        self._ind = indicator_engine or IndicatorEngine()

    # ── 主要回測入口 ───────────────────────────────────────────

    def run(
        self,
        code: str,
        strategy: str = "trend",
        capital: float = 1_000_000,
        risk_pct: float = 2.0,
        min_score: int = 4,
        period: str = "2y",
        commission_pct: float = 0.001425,
        slippage_pct: float = 0.0005,
    ) -> dict:
        """
        對單一標的執行回測。

        Args:
            commission_pct: 單邊手續費比例（預設 0.1425%，台股標準）
            slippage_pct:   單邊滑價比例（預設 0.05%）

        Returns dict with keys:
            ok, code, strategy, capital, final_equity,
            trades, equity_curve, stats
        """
        strat = get_strategy(strategy)
        df    = self._ind.fetch_ohlcv(code, period=period)

        if df is None or len(df) < strat.min_bars + 20:
            return {"ok": False, "error": "資料不足，請換較長週期或確認代號"}

        trades: list       = []
        equity_curve: list = []
        equity             = float(capital)
        open_trade: Optional[dict] = None
        entry_bar          = -1

        for i in range(strat.min_bars, len(df)):
            date  = str(df.index[i].date())
            close = float(df["close"].iloc[i])
            low   = float(df["low"].iloc[i])
            high  = float(df["high"].iloc[i])

            # ── 出場判斷（不在進場同根 K 棒出場） ──────────────
            if open_trade and i > entry_bar:
                exit_price: Optional[float] = None
                reason = ""

                # 停損優先（用當日最低）
                if low <= open_trade["stop"]:
                    exit_price = open_trade["stop"]
                    reason     = "停損"
                # 目標（用當日最高）
                elif open_trade.get("target") and high >= open_trade["target"]:
                    exit_price = open_trade["target"]
                    reason     = "目標"

                if exit_price is not None:
                    actual_exit = exit_price * (1 - slippage_pct)
                    comm_sell   = actual_exit * open_trade["shares"] * commission_pct
                    pnl = (
                        (actual_exit - open_trade["actual_entry"]) * open_trade["shares"]
                        - open_trade["comm_buy"] - comm_sell
                    )
                    equity += pnl
                    trades.append({
                        "entry_date": open_trade["entry_date"],
                        "exit_date":  date,
                        "code":       code,
                        "entry":      open_trade["entry"],
                        "exit":       round(exit_price, 2),
                        "shares":     open_trade["shares"],
                        "pnl":        int(round(pnl)),
                        "pnl_pct":    round(
                            (actual_exit - open_trade["actual_entry"])
                            / open_trade["actual_entry"] * 100, 2
                        ),
                        "reason":     reason,
                    })
                    open_trade = None

            # ── 進場判斷 ─────────────────────────────────────
            if open_trade is None:
                try:
                    sub_df = df.iloc[: i + 1]
                    ind    = strat.compute(sub_df, code=code)
                    if ind and ind["score"] >= min_score:
                        params = strat.calc_entry_params(ind, equity, risk_pct)
                        if params.get("shares", 0) > 0:
                            actual_entry = params["entry"] * (1 + slippage_pct)
                            comm_buy     = actual_entry * params["shares"] * commission_pct
                            equity      -= comm_buy
                            open_trade = {
                                "entry":        params["entry"],
                                "actual_entry": actual_entry,
                                "stop":         params["stop"],
                                "target":       params.get("target"),
                                "shares":       params["shares"],
                                "entry_date":   date,
                                "comm_buy":     comm_buy,
                            }
                            entry_bar = i
                except Exception as e:
                    logger.warning("bar 計算例外 code=%s bar=%d: %s", code, i, e)

            equity_curve.append({"date": date, "equity": round(equity)})

        # ── 強制平倉未平倉部位 ───────────────────────────────
        if open_trade:
            last_close  = float(df["close"].iloc[-1])
            actual_exit = last_close * (1 - slippage_pct)
            comm_sell   = actual_exit * open_trade["shares"] * commission_pct
            pnl         = (
                (actual_exit - open_trade["actual_entry"]) * open_trade["shares"]
                - open_trade["comm_buy"] - comm_sell
            )
            equity += pnl
            trades.append({
                "entry_date": open_trade["entry_date"],
                "exit_date":  str(df.index[-1].date()),
                "code":       code,
                "entry":      open_trade["entry"],
                "exit":       round(last_close, 2),
                "shares":     open_trade["shares"],
                "pnl":        int(round(pnl)),
                "pnl_pct":    round(
                    (actual_exit - open_trade["actual_entry"])
                    / open_trade["actual_entry"] * 100, 2
                ),
                "reason": "未平倉",
            })
            if equity_curve:
                equity_curve[-1]["equity"] = round(equity)

        return {
            "ok":           True,
            "code":         code,
            "strategy":     strategy,
            "capital":      capital,
            "final_equity": round(equity),
            "trades":       trades,
            "equity_curve": equity_curve,
            "stats":        self._calc_stats(trades, capital, equity),
        }

    # ── 多標的回測 ────────────────────────────────────────────

    def run_multi(
        self,
        codes: list[str],
        strategy: str = "trend",
        capital: float = 1_000_000,
        risk_pct: float = 2.0,
        min_score: int = 4,
        period: str = "2y",
        max_workers: int = 4,
        commission_pct: float = 0.001425,
        slippage_pct: float = 0.0005,
    ) -> dict:
        """
        對多個標的平行執行回測，每個標的獨立使用相同初始資金。

        Returns dict with keys:
            ok, results (list of per-stock run() outputs),
            summary (comparison table rows)
        """
        def _run_one(code: str) -> dict:
            r = self.run(code, strategy=strategy, capital=capital,
                         risk_pct=risk_pct, min_score=min_score, period=period,
                         commission_pct=commission_pct, slippage_pct=slippage_pct)
            r["code"] = code
            return r

        results = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
            futs = {ex.submit(_run_one, c): c for c in codes}
            for f in concurrent.futures.as_completed(futs):
                results.append(f.result())

        # 依 total_return 降冪排序（失敗的排最後）
        results.sort(
            key=lambda r: r.get("stats", {}).get("total_return", -999) if r.get("ok") else -9999,
            reverse=True,
        )

        summary = []
        for r in results:
            if r.get("ok"):
                s = r["stats"]
                summary.append({
                    "code":         r["code"],
                    "total_return": s["total_return"],
                    "total_trades": s["total_trades"],
                    "win_rate":     s["win_rate"],
                    "profit_factor":s["profit_factor"],
                    "max_drawdown": s["max_drawdown"],
                    "final_equity": r["final_equity"],
                })
            else:
                summary.append({
                    "code":  r["code"],
                    "error": r.get("error", "unknown"),
                })

        return {"ok": True, "results": results, "summary": summary}

    # ── Monte Carlo 信心區間 ────────────────────────────────────

    @staticmethod
    def monte_carlo(
        trades: list,
        capital: float = 1_000_000,
        n: int = 500,
    ) -> dict:
        """Bootstrap 重抽樣，計算累積報酬曲線的 p5 / p50 / p95 信心帶。

        Args:
            trades:  BacktestEngine.run() 回傳的交易列表
            capital: 初始資金（用於計算累積報酬率曲線）
            n:       重抽樣次數

        Returns:
            {"p5": [...], "p50": [...], "p95": [...]}
            每個列表長度等於 len(trades) + 1（含起始點 0）
        """
        if not trades:
            return {"p5": [], "p50": [], "p95": []}

        pnls = [t["pnl"] for t in trades]
        k    = len(pnls)
        rng  = random.Random(42)

        all_curves: list[list[float]] = []
        for _ in range(n):
            sample    = [rng.choice(pnls) for _ in range(k)]
            eq        = capital
            curve     = [eq]
            for pnl in sample:
                eq += pnl
                curve.append(eq)
            all_curves.append(curve)

        # 每個時間點取分位數
        p5, p50, p95 = [], [], []
        for step in range(k + 1):
            vals = sorted(c[step] for c in all_curves)
            idx5  = max(0, int(n * 0.05) - 1)
            idx50 = max(0, int(n * 0.50) - 1)
            idx95 = max(0, int(n * 0.95) - 1)
            p5.append(round(vals[idx5]))
            p50.append(round(vals[idx50]))
            p95.append(round(vals[idx95]))

        return {"p5": p5, "p50": p50, "p95": p95}

    # ── 績效統計 ──────────────────────────────────────────────

    @staticmethod
    def _calc_stats(trades: list, initial: float, final: float) -> dict:
        _zero = {
            "total_trades": 0, "wins": 0, "losses": 0,
            "win_rate": 0.0, "profit_factor": 0.0,
            "avg_win_pct": 0.0, "avg_loss_pct": 0.0,
            "total_return": 0.0, "max_drawdown": 0.0,
            "gross_profit": 0, "gross_loss": 0,
        }
        if not trades:
            return _zero

        wins   = [t for t in trades if t["pnl"] > 0]
        losses = [t for t in trades if t["pnl"] <= 0]

        gross_profit  = sum(t["pnl"] for t in wins)
        gross_loss    = abs(sum(t["pnl"] for t in losses))
        profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else 999.0

        avg_win  = round(sum(t["pnl_pct"] for t in wins)   / len(wins),   2) if wins   else 0.0
        avg_loss = round(sum(t["pnl_pct"] for t in losses) / len(losses), 2) if losses else 0.0

        # 最大回撤（交易間計算）
        peak, max_dd, running = initial, 0.0, initial
        for t in trades:
            running += t["pnl"]
            peak     = max(peak, running)
            dd       = (peak - running) / peak * 100 if peak > 0 else 0.0
            max_dd   = max(max_dd, dd)

        return {
            "total_trades": len(trades),
            "wins":         len(wins),
            "losses":       len(losses),
            "win_rate":     round(len(wins) / len(trades) * 100, 1),
            "profit_factor":profit_factor,
            "avg_win_pct":  avg_win,
            "avg_loss_pct": avg_loss,
            "total_return": round((final - initial) / initial * 100, 2),
            "max_drawdown": round(max_dd, 2),
            "gross_profit": int(gross_profit),
            "gross_loss":   int(gross_loss),
        }
