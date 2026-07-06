"""
trading/strategies/trend.py — 趨勢策略
均線多頭排列 + ADX 趨勢強度 + MACD 動能 + 爆量 + 黃金交叉，共 6 個信號。
"""
import time
from typing import Optional

import pandas as pd

from trading.strategies.base import BaseStrategy
from trading.indicators import IndicatorEngine as IE


class TrendStrategy(BaseStrategy):

    name     = "trend"
    label    = "趨勢策略"
    min_bars = 65

    signal_labels = {
        "ema_arrangement": "均線排列",
        "slopes_up":       "三線齊揚",
        "adx_above_25":    "ADX>25",
        "macd_positive":   "MACD紅",
        "volume_spike":    "爆量",
        "ema_crossover":   "5穿20",
    }

    _params_cache:      dict  = {}
    _params_cache_time: float = 0.0
    _PARAMS_TTL:        float = 60.0

    def _load_params(self) -> dict:
        if self._params_cache and time.time() - self._params_cache_time < self._PARAMS_TTL:
            return self._params_cache
        from trading.config import ConfigManager
        TrendStrategy._params_cache      = ConfigManager().load().get("strategy_params", {}).get("trend", {})
        TrendStrategy._params_cache_time = time.time()
        return self._params_cache

    def compute(self, df: pd.DataFrame, code: str = "") -> Optional[dict]:
        if len(df) < self.min_bars:
            return None

        p = self._load_params()
        adx_threshold = float(p.get("adx_above_25", {}).get("threshold", 25))
        vol_mult      = float(p.get("volume_spike",  {}).get("threshold", 1.5))

        close = df["close"]
        high  = df["high"]
        low   = df["low"]
        vol   = df["volume"]

        ema5  = IE._ema(close, 5)
        ema20 = IE._ema(close, 20)
        ema60 = IE._ema(close, 60)
        e5, e20, e60 = float(ema5.iloc[-1]), float(ema20.iloc[-1]), float(ema60.iloc[-1])
        c = float(close.iloc[-1])

        adx_val   = float(IE._adx(high, low, close, 14).iloc[-1])
        atr_val   = float(IE._atr(high, low, close, 14).iloc[-1])
        _, _, h_s = IE._macd(close)
        macd_hist = float(h_s.iloc[-1])

        vol_sma = IE._sma(vol, 20)
        vol_avg = float(vol_sma.iloc[-1])
        vol_now = float(vol.iloc[-1])

        slopes_up = (
            float(ema5.iloc[-1])  > float(ema5.iloc[-3])  and
            float(ema20.iloc[-1]) > float(ema20.iloc[-3]) and
            float(ema60.iloc[-1]) > float(ema60.iloc[-3])
        )

        cross_days = None
        e5_now = float(ema5.iloc[-1])
        e20_now_val = float(ema20.iloc[-1])
        for i in range(1, 4):
            if (len(ema5) > i + 1
                    and e5_now >= e20_now_val                              # 現在 EMA5 已站上 EMA20
                    and float(ema5.iloc[-(i+1)]) < float(ema20.iloc[-(i+1)])):  # 之前在下方
                cross_days = i
                break

        swing_low = float(low.iloc[-20:].min())
        w52_high  = float(close.iloc[-252:].max()) if len(close) >= 252 else float(close.max())
        w52_low   = float(close.iloc[-252:].min()) if len(close) >= 252 else float(close.min())

        signals = {
            "ema_arrangement": c > e5 > e20 > e60,
            "slopes_up":       slopes_up,
            "adx_above_25":    adx_val > adx_threshold,
            "macd_positive":   macd_hist > 0,
            "volume_spike":    vol_now > vol_avg * vol_mult,
            "ema_crossover":   cross_days is not None,
        }

        enabled       = {k: bool(p.get(k, {}).get("enabled", True)) for k in signals}
        score         = sum(v for k, v in signals.items() if enabled[k])
        total_enabled = sum(enabled.values())

        return {
            "close":         round(c, 2),
            "ema5":          round(e5, 2),
            "ema20":         round(e20, 2),
            "ema60":         round(e60, 2),
            "adx":           round(adx_val, 2),
            "atr":           round(atr_val, 2),
            "macd_hist":     round(macd_hist, 4),
            "volume":        int(vol_now),
            "vol_avg":       int(vol_avg),
            "swing_low":     round(swing_low, 2),
            "w52_high":      round(w52_high, 2),
            "w52_low":       round(w52_low, 2),
            "cross_days":    cross_days,
            "adx_threshold": adx_threshold,
            "vol_mult":      vol_mult,
            "signals":       signals,
            "enabled":       enabled,
            "score":         score,
            "total_enabled": total_enabled,
        }

    def calc_entry_params(self, ind: dict, capital: float, risk_pct: float = 2.0) -> dict:
        entry    = ind["close"]
        stop     = round(ind["swing_low"] - 1.5 * ind["atr"], 2)
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
