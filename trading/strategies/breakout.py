"""
trading/strategies/breakout.py — Donchian 突破策略
N 日高點突破 + 量能確認 + 趨勢濾網，共 4 個信號。
"""
import time
from typing import Optional

import pandas as pd

from trading.strategies.base import BaseStrategy
from trading.indicators import IndicatorEngine as IE


class BreakoutStrategy(BaseStrategy):

    name     = "breakout"
    label    = "突破策略"
    min_bars = 30

    signal_labels = {
        "donchian_break":  "N日高點突破",
        "volume_confirm":  "量能確認",
        "near_high":       "貼近高點(未假突破)",
        "above_ema20":     "站上EMA20",
    }

    _params_cache:      dict  = {}
    _params_cache_time: float = 0.0
    _PARAMS_TTL:        float = 60.0

    def _load_params(self) -> dict:
        if self._params_cache and time.time() - self._params_cache_time < self._PARAMS_TTL:
            return self._params_cache
        from trading.config import ConfigManager
        BreakoutStrategy._params_cache      = ConfigManager().load().get("strategy_params", {}).get("breakout", {})
        BreakoutStrategy._params_cache_time = time.time()
        return self._params_cache

    def compute(self, df: pd.DataFrame, code: str = "") -> Optional[dict]:
        if len(df) < self.min_bars:
            return None

        p = self._load_params()
        n_period = int(p.get("donchian_break", {}).get("threshold", 20))
        vol_mult = float(p.get("volume_confirm", {}).get("threshold", 1.5))

        close = df["close"]
        high  = df["high"]
        vol   = df["volume"]

        n_period = min(n_period, len(high) - 1)
        prior_high = float(high.iloc[-n_period - 1:-1].max())
        c = float(close.iloc[-1])

        vol_sma = IE._sma(vol, 20)
        vol_avg = float(vol_sma.iloc[-1])
        vol_now = float(vol.iloc[-1])

        ema20 = IE._ema(close, 20)
        e20_now = float(ema20.iloc[-1])

        signals = {
            "donchian_break": c > prior_high,
            "volume_confirm": vol_now > vol_avg * vol_mult,
            "near_high":      c >= prior_high * 0.98,
            "above_ema20":    c > e20_now,
        }

        enabled       = {k: bool(p.get(k, {}).get("enabled", True)) for k in signals}
        score         = sum(v for k, v in signals.items() if enabled[k])
        total_enabled = sum(enabled.values())

        low_col = df["low"]
        n20 = min(len(low_col), 20)
        swing_low = float(low_col.iloc[-n20:].min())
        atr_val = float(IE._atr(high, low_col, close, 14).iloc[-1])

        return {
            "close":       round(c, 2),
            "prior_high":  round(prior_high, 2),
            "ema20":       round(e20_now, 2),
            "volume":      int(vol_now),
            "vol_avg":     int(vol_avg),
            "atr":         round(atr_val, 2),
            "swing_low":   round(swing_low, 2),
            "signals":       signals,
            "enabled":       enabled,
            "score":         score,
            "total_enabled": total_enabled,
        }

    def calc_entry_params(self, ind: dict, capital: float, risk_pct: float = 2.0) -> dict:
        entry    = ind["close"]
        stop     = round(min(ind["swing_low"], entry - 2.0 * ind["atr"]), 2)
        risk_per = max(entry - stop, 0.01)
        shares   = int((capital * risk_pct / 100) / risk_per)
        target   = round(entry + risk_per * 2.5, 2)
        return {
            "entry":          entry,
            "stop":           stop,
            "target":         target,
            "shares":         shares,
            "risk_per_share": round(risk_per, 2),
            "total_risk":     int(risk_per * shares),
        }
