"""
trading/optimizer.py — 策略參數掃描器

對給定股票與策略，枚舉所有參數組合，執行 BacktestEngine.run()，
回傳各組合的績效數據，支援 SSE 串流進度。
"""
from __future__ import annotations

import itertools
from typing import Generator, Optional

from trading.backtest import BacktestEngine
from trading.indicators import IndicatorEngine


class StrategyOptimizer:
    """枚舉 param_grid 所有組合，批次回測並回傳排名結果。"""

    def __init__(self, indicator_engine: Optional[IndicatorEngine] = None):
        self._ind    = indicator_engine or IndicatorEngine()
        self._engine = BacktestEngine(indicator_engine=self._ind)

    def sweep(
        self,
        code: str,
        strategy: str = "trend",
        param_grid: Optional[dict] = None,
        capital: float = 1_000_000,
        risk_pct: float = 2.0,
        period: str = "2y",
        commission_pct: float = 0.001425,
        slippage_pct: float = 0.0005,
    ) -> list[dict]:
        """
        對所有參數組合跑回測，回傳結果列表（依 total_return 降序）。

        Args:
            param_grid: 參數網格，例如
                {"min_score": [3, 4, 5], "adx_threshold": [20, 25, 30]}
                目前支援的參數鍵：min_score（直接傳入 BacktestEngine.run()）

        Returns:
            [{"params": {...}, "total_return": ..., "win_rate": ...,
              "max_drawdown": ..., "total_trades": ...}, ...]
        """
        if not param_grid:
            return []

        keys   = list(param_grid.keys())
        values = [param_grid[k] for k in keys]
        combos = list(itertools.product(*values))

        results: list[dict] = []
        for combo in combos:
            params = dict(zip(keys, combo))
            min_score = int(params.get("min_score", 4))
            r = self._engine.run(
                code,
                strategy=strategy,
                capital=capital,
                risk_pct=risk_pct,
                min_score=min_score,
                period=period,
                commission_pct=commission_pct,
                slippage_pct=slippage_pct,
            )
            if r.get("ok"):
                s = r["stats"]
                results.append({
                    "params":       params,
                    "total_return": s["total_return"],
                    "win_rate":     s["win_rate"],
                    "max_drawdown": s["max_drawdown"],
                    "total_trades": s["total_trades"],
                    "profit_factor":s["profit_factor"],
                })
            else:
                results.append({
                    "params": params,
                    "error":  r.get("error", "failed"),
                })

        results.sort(
            key=lambda x: x.get("total_return", -9999),
            reverse=True,
        )
        return results

    def sweep_stream(
        self,
        code: str,
        strategy: str = "trend",
        param_grid: Optional[dict] = None,
        capital: float = 1_000_000,
        risk_pct: float = 2.0,
        period: str = "2y",
        commission_pct: float = 0.001425,
        slippage_pct: float = 0.0005,
    ) -> Generator[dict, None, None]:
        """逐一 yield 每個參數組合的進度與結果（供 SSE 路由使用）。"""
        if not param_grid:
            yield {"type": "done", "results": [], "total": 0}
            return

        keys   = list(param_grid.keys())
        values = [param_grid[k] for k in keys]
        combos = list(itertools.product(*values))
        total  = len(combos)

        yield {"type": "start", "total": total}

        results: list[dict] = []
        for i, combo in enumerate(combos, 1):
            params = dict(zip(keys, combo))
            min_score = int(params.get("min_score", 4))
            r = self._engine.run(
                code,
                strategy=strategy,
                capital=capital,
                risk_pct=risk_pct,
                min_score=min_score,
                period=period,
                commission_pct=commission_pct,
                slippage_pct=slippage_pct,
            )
            if r.get("ok"):
                s = r["stats"]
                item = {
                    "params":       params,
                    "total_return": s["total_return"],
                    "win_rate":     s["win_rate"],
                    "max_drawdown": s["max_drawdown"],
                    "total_trades": s["total_trades"],
                    "profit_factor":s["profit_factor"],
                }
            else:
                item = {"params": params, "error": r.get("error", "failed")}

            results.append(item)
            yield {"type": "progress", "done": i, "total": total, "item": item}

        results.sort(key=lambda x: x.get("total_return", -9999), reverse=True)
        yield {"type": "done", "results": results, "total": total}
