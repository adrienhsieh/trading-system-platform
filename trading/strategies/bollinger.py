"""
trading/strategies/bollinger.py — 布林通道策略
中軌趨勢 + 上軌突破 + 下軌反彈 + 通道擴張，共 4 個信號。
"""
import time
from typing import Optional

import pandas as pd

from trading.strategies.base import BaseStrategy
from trading.indicators import IndicatorEngine as IE


class BollingerStrategy(BaseStrategy):

    name     = "bollinger"
    label    = "布林通道策略"
    min_bars = 30

    signal_labels = {
        "above_mid":         "站上中軌",
        "upper_breakout":    "突破上軌",
        "lower_bounce":      "下軌反彈",
        "bandwidth_expand":  "通道擴張",
    }

    _params_cache:      dict  = {}
    _params_cache_time: float = 0.0
    _PARAMS_TTL:        float = 60.0

    def _load_params(self) -> dict:
        if self._params_cache and time.time() - self._params_cache_time < self._PARAMS_TTL:
            return self._params_cache
        from trading.config import ConfigManager
        BollingerStrategy._params_cache      = ConfigManager().load().get("strategy_params", {}).get("bollinger", {})
        BollingerStrategy._params_cache_time = time.time()
        return self._params_cache

    def compute(self, df: pd.DataFrame, code: str = "") -> Optional[dict]:
        if len(df) < self.min_bars:
            return None

        p = self._load_params()
        n_period = int(p.get("period", {}).get("threshold", 20))
        n_std    = float(p.get("std_mult", {}).get("threshold", 2))

        close = df["close"]
        mid = IE._sma(close, n_period)
        std = close.rolling(window=n_period).std()
        upper = mid + n_std * std
        lower = mid - n_std * std

        c        = float(close.iloc[-1])
        c_prev   = float(close.iloc[-2])
        mid_now  = float(mid.iloc[-1])
        up_now   = float(upper.iloc[-1])
        up_prev  = float(upper.iloc[-2])
        low_now  = float(lower.iloc[-1])
        low_prev = float(lower.iloc[-2])

        bandwidth_now  = (up_now - low_now) / mid_now if mid_now else 0
        n5 = min(5, len(mid) - 1)
        bandwidth_prev = (float(upper.iloc[-1 - n5]) - float(lower.iloc[-1 - n5])) / float(mid.iloc[-1 - n5]) \
            if float(mid.iloc[-1 - n5]) else 0

        signals = {
            "above_mid":        c > mid_now,
            "upper_breakout":   c > up_now and c_prev <= up_prev,
            "lower_bounce":     c > low_now and c_prev <= low_prev,
            "bandwidth_expand": bandwidth_now > bandwidth_prev,
        }

        enabled       = {k: bool(p.get(k, {}).get("enabled", True)) for k in signals}
        score         = sum(v for k, v in signals.items() if enabled[k])
        total_enabled = sum(enabled.values())

        low_col = df["low"]
        n20 = min(len(low_col), 20)
        swing_low = float(low_col.iloc[-n20:].min())
        atr_val = float(IE._atr(df["high"], df["low"], close, 14).iloc[-1])

        return {
            "close":      round(c, 2),
            "mid":        round(mid_now, 2),
            "upper":      round(up_now, 2),
            "lower":      round(low_now, 2),
            "bandwidth":  round(bandwidth_now, 4),
            "atr":        round(atr_val, 2),
            "swing_low":  round(swing_low, 2),
            "signals":       signals,
            "enabled":       enabled,
            "score":         score,
            "total_enabled": total_enabled,
        }

    def calc_entry_params(self, ind: dict, capital: float, risk_pct: float = 2.0) -> dict:
        entry    = ind["close"]
        stop     = round(min(ind["swing_low"], ind["mid"] - 1.0 * ind["atr"]), 2)
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
