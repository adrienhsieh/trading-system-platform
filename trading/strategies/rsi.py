"""
trading/strategies/rsi.py — RSI 超買超賣策略
RSI(14) 判斷超賣反彈與健康多頭動能區間，共 4 個信號。
"""
import time
from typing import Optional

import pandas as pd

from trading.strategies.base import BaseStrategy


def _calc_rsi(close: pd.Series, length: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / length, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / length, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, 1e-9)
    return 100 - (100 / (1 + rs))


class RSIStrategy(BaseStrategy):

    name     = "rsi"
    label    = "RSI 策略"
    min_bars = 30

    signal_labels = {
        "oversold":       "RSI超賣(<30)",
        "cross_up_30":    "RSI脫離超賣",
        "healthy_zone":   "健康多頭區間",
        "rising":         "RSI走升",
    }

    _params_cache:      dict  = {}
    _params_cache_time: float = 0.0
    _PARAMS_TTL:        float = 60.0

    def _load_params(self) -> dict:
        if self._params_cache and time.time() - self._params_cache_time < self._PARAMS_TTL:
            return self._params_cache
        from trading.config import ConfigManager
        RSIStrategy._params_cache      = ConfigManager().load().get("strategy_params", {}).get("rsi", {})
        RSIStrategy._params_cache_time = time.time()
        return self._params_cache

    def compute(self, df: pd.DataFrame, code: str = "") -> Optional[dict]:
        if len(df) < self.min_bars:
            return None

        p = self._load_params()
        oversold_th  = float(p.get("oversold", {}).get("threshold", 30))
        overbought_th = float(p.get("healthy_zone", {}).get("threshold", 70))

        close = df["close"]
        rsi = _calc_rsi(close, 14)
        rsi_now = float(rsi.iloc[-1])
        c = float(close.iloc[-1])

        cross_up = False
        for i in range(1, min(4, len(rsi))):
            if rsi_now >= oversold_th and float(rsi.iloc[-(i + 1)]) < oversold_th:
                cross_up = True
                break

        signals = {
            "oversold":     rsi_now < oversold_th,
            "cross_up_30":  cross_up,
            "healthy_zone": 40 <= rsi_now <= overbought_th,
            "rising":       len(rsi) > 5 and rsi_now > float(rsi.iloc[-6]),
        }

        enabled       = {k: bool(p.get(k, {}).get("enabled", True)) for k in signals}
        score         = sum(v for k, v in signals.items() if enabled[k])
        total_enabled = sum(enabled.values())

        low = df["low"]
        n20 = min(len(low), 20)
        swing_low = float(low.iloc[-n20:].min())

        from trading.indicators import IndicatorEngine as IE
        atr_val = float(IE._atr(df["high"], df["low"], close, 14).iloc[-1])

        return {
            "close":     round(c, 2),
            "rsi":       round(rsi_now, 2),
            "atr":       round(atr_val, 2),
            "swing_low": round(swing_low, 2),
            "oversold_threshold": oversold_th,
            "signals":       signals,
            "enabled":       enabled,
            "score":         score,
            "total_enabled": total_enabled,
        }

    def calc_entry_params(self, ind: dict, capital: float, risk_pct: float = 2.0) -> dict:
        entry    = ind["close"]
        stop     = round(min(ind["swing_low"], entry - 1.2 * ind["atr"]), 2)
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
