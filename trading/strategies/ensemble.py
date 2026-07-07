"""
trading/strategies/ensemble.py — 組合投票策略（Ensemble）
彙整多個技術面策略（趨勢、ICT、RSI、MACD、布林、突破）的訊號密度，
每個策略訊號密度 ≥ 50% 視為一票「偏多」，統計總票數，共 N 個信號
（N = 成功運算的子策略數）。用於在多個策略「多數同意」時提高勝率。

刻意排除 fundamental / vix_panic / chip_washout：這三者依賴外部網路資料
（yfinance .info、TWSE OpenAPI），計算較慢，全市場掃描時容易拖慢整體速度；
如需要，可在策略清單另外單獨勾選使用。
"""
from typing import Optional

import pandas as pd

from trading.strategies.base import BaseStrategy
from trading.indicators import IndicatorEngine as IE

SUB_STRATEGY_NAMES = ["trend", "ict", "rsi", "macd", "bollinger", "breakout"]


class EnsembleStrategy(BaseStrategy):

    name     = "ensemble"
    label    = "組合投票策略"
    min_bars = 65

    signal_labels = {f"vote_{n}": f"{n} 偏多" for n in SUB_STRATEGY_NAMES}

    def compute(self, df: pd.DataFrame, code: str = "") -> Optional[dict]:
        if len(df) < self.min_bars:
            return None

        from trading.strategies import REGISTRY

        signals: dict = {}
        detail: dict = {}
        for sub_name in SUB_STRATEGY_NAMES:
            sub = REGISTRY.get(sub_name)
            if sub is None:
                continue
            try:
                res = sub.compute(df, code)
            except Exception:
                res = None
            if not res:
                continue
            total = res.get("total_enabled") or 1
            ratio = res.get("score", 0) / total
            signals[f"vote_{sub_name}"] = ratio >= 0.5
            detail[sub_name] = {"ratio": round(ratio, 3), "score": res.get("score"), "total": total}

        if not signals:
            return None

        score         = sum(1 for v in signals.values() if v)
        total_enabled = len(signals)

        close = df["close"]
        low   = df["low"]
        c = float(close.iloc[-1])
        n20 = min(len(low), 20)
        swing_low = float(low.iloc[-n20:].min())
        atr_val = float(IE._atr(df["high"], low, close, 14).iloc[-1])

        return {
            "close":      round(c, 2),
            "atr":        round(atr_val, 2),
            "swing_low":  round(swing_low, 2),
            "detail":        detail,
            "signals":       signals,
            "enabled":       {k: True for k in signals},
            "score":         score,
            "total_enabled": total_enabled,
        }

    def calc_entry_params(self, ind: dict, capital: float, risk_pct: float = 2.0) -> dict:
        entry    = ind["close"]
        stop     = round(min(ind["swing_low"], entry - 1.5 * ind["atr"]), 2)
        risk_per = max(entry - stop, 0.01)
        shares   = int((capital * risk_pct / 100) / risk_per)
        target   = round(entry + risk_per * 2, 2)
        return {
            "entry":          entry,
            "stop":           stop,
            "target":         target,
            "shares":         shares,
            "risk_per_share": round(risk_per, 2),
            "total_risk":     int(risk_per * shares),
        }
