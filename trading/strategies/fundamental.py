"""
trading/strategies/fundamental.py — 基本面策略
使用 yfinance 取得 PE/EPS/PB/營收成長率，共 5 個信號篩選估值合理且成長性佳的股票。
"""
from typing import Optional

import pandas as pd

import time as _time

from trading.strategies.base import BaseStrategy

# 基本面資料記憶體快取（TTL 30 分鐘，避免重複打 yfinance .info API）
_fund_cache: dict = {}
_fund_cache_time: dict = {}
_FUND_CACHE_TTL = 30 * 60  # 30 分鐘


def _get_fundamentals(code: str) -> dict:
    """從 yfinance 取得基本面數據。先試 .TW（上市），失敗再試 .TWO（上櫃）。
    結果快取 30 分鐘，避免掃描時重複請求。
    """
    now = _time.time()
    if code in _fund_cache and now - _fund_cache_time.get(code, 0) < _FUND_CACHE_TTL:
        return _fund_cache[code]
    try:
        import io
        import contextlib
        import yfinance as yf
        from trading.indicators import _yf_throttle
        for suffix in (".TW", ".TWO"):
            _yf_throttle()
            ticker = yf.Ticker(f"{code}{suffix}")
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                info = ticker.info
            # 若有取到任一基本面欄位即視為成功
            if info.get("trailingPE") is not None or info.get("trailingEps") is not None:
                result = {
                    "trailingPE":      info.get("trailingPE"),
                    "trailingEps":     info.get("trailingEps"),
                    "forwardEps":      info.get("forwardEps"),
                    "priceToBook":     info.get("priceToBook"),
                    "revenueGrowth":   info.get("revenueGrowth"),
                    "currentPrice":    info.get("currentPrice") or info.get("regularMarketPrice"),
                }
                _fund_cache[code] = result
                _fund_cache_time[code] = now
                return result
        # 不快取失敗結果，下次會重試
        return {}
    except Exception:
        return {}


class FundamentalStrategy(BaseStrategy):

    name     = "fundamental"
    label    = "基本面策略"
    min_bars = 20

    signal_labels = {
        "pe_reasonable":  "本益比合理",
        "eps_positive":   "EPS為正",
        "eps_growth":     "EPS成長",
        "pb_reasonable":  "PB合理",
        "revenue_growth": "營收成長",
    }

    _params_cache:      dict  = {}
    _params_cache_time: float = 0.0
    _PARAMS_TTL:        float = 60.0

    def _load_params(self) -> dict:
        import time
        if self._params_cache and time.time() - self._params_cache_time < self._PARAMS_TTL:
            return self._params_cache
        from trading.config import ConfigManager
        FundamentalStrategy._params_cache      = ConfigManager().load().get("strategy_params", {}).get("fundamental", {})
        FundamentalStrategy._params_cache_time = time.time()
        return self._params_cache

    def compute(self, df: pd.DataFrame, code: str = "") -> Optional[dict]:
        if len(df) < self.min_bars or not code:
            return None

        p = self._load_params()
        pe_threshold = float(p.get("pe_reasonable", {}).get("threshold", 30))
        pb_threshold = float(p.get("pb_reasonable", {}).get("threshold", 2.5))

        fund = _get_fundamentals(code)
        if not fund:
            return None

        close = float(df["close"].iloc[-1])
        high  = df["high"]
        low   = df["low"]

        pe  = fund.get("trailingPE")
        eps = fund.get("trailingEps")
        fwd = fund.get("forwardEps")
        pb  = fund.get("priceToBook")
        rev = fund.get("revenueGrowth")

        signals = {
            "pe_reasonable":  bool(pe is not None  and 0 < pe  < pe_threshold),
            "eps_positive":   bool(eps is not None and eps > 0),
            "eps_growth":     bool(eps is not None and fwd is not None and fwd > eps),
            "pb_reasonable":  bool(pb is not None  and 0 < pb  < pb_threshold),
            "revenue_growth": bool(rev is not None and rev > 0),
        }

        enabled       = {k: bool(p.get(k, {}).get("enabled", True)) for k in signals}
        score         = sum(v for k, v in signals.items() if enabled[k])
        total_enabled = sum(enabled.values())

        # 技術面 swing_low 用於停損計算
        n20 = min(len(low), 20)
        swing_low = float(low.iloc[-n20:].min())

        return {
            "close":          round(close, 2),
            "pe":             round(pe, 2)  if pe  is not None else None,
            "eps":            round(eps, 4) if eps is not None else None,
            "forward_eps":    round(fwd, 4) if fwd is not None else None,
            "pb":             round(pb, 2)  if pb  is not None else None,
            "revenue_growth": round(rev * 100, 2) if rev is not None else None,
            "pe_threshold":   pe_threshold,
            "pb_threshold":   pb_threshold,
            "swing_low":      round(swing_low, 2),
            "signals":        signals,
            "enabled":        enabled,
            "score":          score,
            "total_enabled":  total_enabled,
        }

    def calc_entry_params(self, ind: dict, capital: float, risk_pct: float = 2.0) -> dict:
        entry    = ind["close"]
        stop     = round(ind["swing_low"] * 0.98, 2)
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
