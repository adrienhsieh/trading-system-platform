"""
trading/strategies/macd.py — MACD 交叉策略
MACD 黃金交叉 + 柱狀圖動能，共 4 個信號。
"""
import time
from typing import Optional

import pandas as pd

from trading.strategies.base import BaseStrategy
from trading.indicators import IndicatorEngine as IE


class MACDStrategy(BaseStrategy):

    name     = "macd"
    label    = "MACD 策略"
    min_bars = 40

    signal_labels = {
        "golden_cross":  "MACD黃金交叉",
        "hist_positive": "柱狀圖翻紅",
        "hist_rising":   "柱狀圖走升",
        "above_zero":    "MACD在零軸上",
    }

    _params_cache:      dict  = {}
    _params_cache_time: float = 0.0
    _PARAMS_TTL:        float = 60.0

    def _load_params(self) -> dict:
        if self._params_cache and time.time() - self._params_cache_time < self._PARAMS_TTL:
            return self._params_cache
        from trading.config import ConfigManager
        MACDStrategy._params_cache      = ConfigManager().load().get("strategy_params", {}).get("macd", {})
        MACDStrategy._params_cache_time = time.time()
        return self._params_cache

    def compute(self, df: pd.DataFrame, code: str = "") -> Optional[dict]:
        if len(df) < self.min_bars:
            return None

        self._load_params()
        close = df["close"]
        macd_line, signal_line, hist = IE._macd(close)

        c = float(close.iloc[-1])
        macd_now, sig_now, hist_now = float(macd_line.iloc[-1]), float(signal_line.iloc[-1]), float(hist.iloc[-1])

        golden_cross = False
        for i in range(1, min(4, len(hist))):
            if hist_now > 0 and float(hist.iloc[-(i + 1)]) <= 0:
                golden_cross = True
                break

        signals = {
            "golden_cross":  golden_cross,
            "hist_positive": hist_now > 0,
            "hist_rising":   len(hist) > 3 and hist_now > float(hist.iloc[-4]),
            "above_zero":    macd_now > 0,
        }

        p = self._params_cache
        enabled       = {k: bool(p.get(k, {}).get("enabled", True)) for k in signals}
        score         = sum(v for k, v in signals.items() if enabled[k])
        total_enabled = sum(enabled.values())

        low = df["low"]
        n20 = min(len(low), 20)
        swing_low = float(low.iloc[-n20:].min())
        atr_val = float(IE._atr(df["high"], df["low"], close, 14).iloc[-1])

        return {
            "close":      round(c, 2),
            "macd":       round(macd_now, 4),
            "signal":     round(sig_now, 4),
            "hist":       round(hist_now, 4),
            "atr":        round(atr_val, 2),
            "swing_low":  round(swing_low, 2),
            "signals":       signals,
            "enabled":       enabled,
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
