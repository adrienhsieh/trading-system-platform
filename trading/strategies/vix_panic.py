"""
trading/strategies/vix_panic.py — VIX 恐慌篩選策略
當 VIX（美股波動率指數）處於恐慌區間時，篩選本益比低、殖利率高、
長期均線仍呈多頭的「危機入市」型標的，共 4 個信號。

VIX 與本益比/殖利率資料來自 trading/services/fundamentals.py（TWSE OpenAPI +
yfinance ^VIX，全體共用、每日快取），非本策略即時抓取。
"""
import time
from typing import Optional

import pandas as pd

from trading.strategies.base import BaseStrategy
from trading.indicators import IndicatorEngine as IE


class VixPanicStrategy(BaseStrategy):

    name     = "vix_panic"
    label    = "VIX恐慌篩選"
    min_bars = 60

    signal_labels = {
        "vix_elevated":     "VIX>恐慌閾值",
        "pe_low":           "本益比偏低",
        "dividend_high":    "殖利率偏高",
        "long_term_uptrend": "長期均線仍多頭",
    }

    _params_cache:      dict  = {}
    _params_cache_time: float = 0.0
    _PARAMS_TTL:        float = 60.0

    def _load_params(self) -> dict:
        if self._params_cache and time.time() - self._params_cache_time < self._PARAMS_TTL:
            return self._params_cache
        from trading.config import ConfigManager
        VixPanicStrategy._params_cache      = ConfigManager().load().get("strategy_params", {}).get("vix_panic", {})
        VixPanicStrategy._params_cache_time = time.time()
        return self._params_cache

    def compute(self, df: pd.DataFrame, code: str = "") -> Optional[dict]:
        if len(df) < self.min_bars or not code:
            return None

        p = self._load_params()
        vix_threshold = float(p.get("vix_elevated", {}).get("threshold", 30))
        pe_threshold  = float(p.get("pe_low", {}).get("threshold", 15))
        dy_threshold  = float(p.get("dividend_high", {}).get("threshold", 4))

        from trading.services.fundamentals import FundamentalsService
        fs = FundamentalsService()
        vix = fs.get_vix()
        valuation = fs.get_valuation(code)

        close = df["close"]
        c = float(close.iloc[-1])
        ma_len = min(200, len(close))
        ma200 = float(IE._sma(close, ma_len).iloc[-1])

        pe = valuation.get("per") if valuation else None
        dy = valuation.get("dividend_yield") if valuation else None

        signals = {
            "vix_elevated":      bool(vix is not None and vix > vix_threshold),
            "pe_low":            bool(pe is not None and 0 < pe < pe_threshold),
            "dividend_high":     bool(dy is not None and dy > dy_threshold),
            "long_term_uptrend": c > ma200,
        }

        enabled       = {k: bool(p.get(k, {}).get("enabled", True)) for k in signals}
        score         = sum(v for k, v in signals.items() if enabled[k])
        total_enabled = sum(enabled.values())

        low = df["low"]
        n20 = min(len(low), 20)
        swing_low = float(low.iloc[-n20:].min())
        atr_val = float(IE._atr(df["high"], low, close, 14).iloc[-1])

        return {
            "close":      round(c, 2),
            "vix":        round(vix, 2) if vix is not None else None,
            "pe":         round(pe, 2) if pe is not None else None,
            "dividend_yield": round(dy, 2) if dy is not None else None,
            "ma200":      round(ma200, 2),
            "atr":        round(atr_val, 2),
            "swing_low":  round(swing_low, 2),
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
        target   = round(entry + risk_per * 3, 2)   # 危機入市型，拉長獲利目標
        return {
            "entry":          entry,
            "stop":           stop,
            "target":         target,
            "shares":         shares,
            "risk_per_share": round(risk_per, 2),
            "total_risk":     int(risk_per * shares),
        }
