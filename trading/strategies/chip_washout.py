"""
trading/strategies/chip_washout.py — 籌碼洗淨策略
融資餘額連續遞減 + 股價逆勢上漲，代表籌碼由散戶轉為大戶／法人承接，共 4 個信號。

融資餘額資料來自 trading/services/fundamentals.py（TWSE OpenAPI MI_MARGN，
全體共用、每日快取），非本策略即時抓取。
"""
import time
from typing import Optional

import pandas as pd

from trading.strategies.base import BaseStrategy
from trading.indicators import IndicatorEngine as IE


class ChipWashoutStrategy(BaseStrategy):

    name     = "chip_washout"
    label    = "籌碼洗淨策略"
    min_bars = 30

    signal_labels = {
        "margin_declining":  "融資連續遞減",
        "margin_drop_big":   "融資減幅顯著",
        "price_rising":      "股價逆勢上漲",
        "volume_healthy":    "量能未萎縮",
    }

    _params_cache:      dict  = {}
    _params_cache_time: float = 0.0
    _PARAMS_TTL:        float = 60.0

    def _load_params(self) -> dict:
        if self._params_cache and time.time() - self._params_cache_time < self._PARAMS_TTL:
            return self._params_cache
        from trading.config import ConfigManager
        ChipWashoutStrategy._params_cache      = ConfigManager().load().get("strategy_params", {}).get("chip_washout", {})
        ChipWashoutStrategy._params_cache_time = time.time()
        return self._params_cache

    def compute(self, df: pd.DataFrame, code: str = "") -> Optional[dict]:
        if len(df) < self.min_bars or not code:
            return None

        p = self._load_params()
        drop_threshold = float(p.get("margin_drop_big", {}).get("threshold", -5))

        from trading.services.fundamentals import FundamentalsService
        fs = FundamentalsService()
        washout = fs.get_chip_washout_signal(code, lookback=10)

        close = df["close"]
        vol   = df["volume"]
        c = float(close.iloc[-1])
        lookback = min(10, len(close) - 1)
        price_change_pct = (c - float(close.iloc[-1 - lookback])) / float(close.iloc[-1 - lookback]) * 100

        vol_sma = IE._sma(vol, 20)
        vol_avg = float(vol_sma.iloc[-1])
        vol_now = float(vol.iloc[-1])

        declining_ratio = washout.get("declining_ratio") if washout else None
        margin_change   = washout.get("margin_change_pct") if washout else None

        signals = {
            "margin_declining": bool(declining_ratio is not None and declining_ratio >= 0.6),
            "margin_drop_big":  bool(margin_change is not None and margin_change < drop_threshold),
            "price_rising":     price_change_pct > 0,
            "volume_healthy":   vol_now > vol_avg * 0.7,
        }

        enabled       = {k: bool(p.get(k, {}).get("enabled", True)) for k in signals}
        score         = sum(v for k, v in signals.items() if enabled[k])
        total_enabled = sum(enabled.values())

        low = df["low"]
        n20 = min(len(low), 20)
        swing_low = float(low.iloc[-n20:].min())
        atr_val = float(IE._atr(df["high"], low, close, 14).iloc[-1])

        return {
            "close":              round(c, 2),
            "margin_declining_ratio": declining_ratio,
            "margin_change_pct":  margin_change,
            "price_change_pct":   round(price_change_pct, 2),
            "atr":                round(atr_val, 2),
            "swing_low":          round(swing_low, 2),
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
