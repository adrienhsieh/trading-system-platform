"""
trading/strategies/ict.py — ICT 策略
Order Block / FVG / BOS / Liquidity Sweep / Discount / OTE / MSS，共 7 個信號。
"""
from typing import Optional

import pandas as pd

from trading.strategies.base import BaseStrategy


class ICTStrategy(BaseStrategy):

    name     = "ict"
    label    = "ICT 策略"
    min_bars = 30

    signal_labels = {
        "bullish_ob":       "多頭OB",
        "fvg_present":      "FVG不平衡",
        "bos":              "結構突破(BOS)",
        "liquidity_sweep":  "流動性掃除",
        "discount_zone":    "折扣區",
        "ote_zone":         "OTE回檔區",
        "mss":              "市場結構轉換(MSS)",
    }

    _params_cache:      dict  = {}
    _params_cache_time: float = 0.0
    _PARAMS_TTL:        float = 60.0

    def _load_params(self) -> dict:
        import time
        if self._params_cache and time.time() - self._params_cache_time < self._PARAMS_TTL:
            return self._params_cache
        from trading.config import ConfigManager
        ICTStrategy._params_cache      = ConfigManager().load().get("strategy_params", {}).get("ict", {})
        ICTStrategy._params_cache_time = time.time()
        return self._params_cache

    def compute(self, df: pd.DataFrame, code: str = "") -> Optional[dict]:
        if len(df) < self.min_bars:
            return None

        p = self._load_params()
        fib_low  = float(p.get("ote_zone", {}).get("fib_low",  0.618))
        fib_high = float(p.get("ote_zone", {}).get("fib_high", 0.786))

        close = df["close"].values
        high  = df["high"].values
        low   = df["low"].values
        open_ = df["open"].values
        c     = float(close[-1])

        # ── 1. Bullish Order Block ────────────────────────────
        bullish_ob = False
        ob_high = ob_low = None
        n = min(len(close), 30)
        for i in range(n - 3, 0, -1):
            idx = len(close) - n + i
            if close[idx] < open_[idx]:
                oh = float(high[idx])
                ol = float(low[idx])
                if (float(close[idx + 1]) > oh or
                        float(close[min(idx + 2, len(close) - 1)]) > oh):
                    if c > oh:
                        bullish_ob = True
                        ob_high    = round(oh, 2)
                        ob_low     = round(ol, 2)
                        break

        # ── 2. Fair Value Gap ─────────────────────────────────
        fvg_present = False
        fvg_top = fvg_bot = None
        n = min(len(close), 15)
        for i in range(len(close) - 1, len(close) - n + 1, -1):
            if i < 2:
                break
            gap_bot = float(high[i - 2])
            gap_top = float(low[i])
            if gap_top > gap_bot and c >= gap_bot:
                fvg_present = True
                fvg_top     = round(gap_top, 2)
                fvg_bot     = round(gap_bot, 2)
                break

        # ── 3. Break of Structure ─────────────────────────────
        bos            = False
        swing_high_ref = None
        lookback       = min(len(close) - 3, 25)
        if lookback >= 5:
            sh             = float(high[-(lookback + 2): -2].max())
            swing_high_ref = round(sh, 2)
            bos            = c > sh

        # ── 4. Liquidity Sweep ────────────────────────────────
        liquidity_sweep = False
        sweep_low       = None
        if len(low) >= 10:
            prior_lows = low[-20: -5]
            if len(prior_lows) > 0:
                sl              = float(prior_lows.min())
                sweep_low       = round(sl, 2)
                swept           = any(float(l) < sl for l in low[-5:])
                recovered       = float(close[-1]) > sl
                liquidity_sweep = swept and recovered

        # ── 5. Discount Zone ──────────────────────────────────
        n20           = min(len(close), 20)
        range_high    = float(high[-n20:].max())
        range_low     = float(low[-n20:].min())
        equilibrium   = (range_high + range_low) / 2
        discount_zone = c < equilibrium

        # ── 6. OTE Zone (61.8%–78.6% Fibonacci) ──────────────
        ote_zone = False
        ote_top  = ote_bot = None
        n40      = min(len(close), 40)
        sl_idx   = int(low[-n40:].argmin())
        sh_idx   = int(high[-n40:].argmax())
        if sl_idx < sh_idx:
            sl_val  = float(low[-n40:][sl_idx])
            sh_val  = float(high[-n40:][sh_idx])
            rng     = sh_val - sl_val
            if rng > 0:
                ote_top  = round(sh_val - rng * fib_low,  2)
                ote_bot  = round(sh_val - rng * fib_high, 2)
                ote_zone = ote_bot <= c <= ote_top

        # ── 7. Market Structure Shift (MSS) ───────────────────
        # 空頭結構（lower highs）被突破 → 多頭 MSS
        mss         = False
        mss_level   = None
        n_mss       = min(len(high), 40)
        h_arr       = high[-n_mss:]
        swing_highs = []
        for i in range(2, len(h_arr) - 2):
            if (h_arr[i] > h_arr[i - 1] and h_arr[i] > h_arr[i - 2] and
                    h_arr[i] > h_arr[i + 1] and h_arr[i] > h_arr[i + 2]):
                swing_highs.append(float(h_arr[i]))
        if len(swing_highs) >= 2:
            sh_prev = swing_highs[-2]
            sh_last = swing_highs[-1]
            if sh_last < sh_prev:          # 空頭結構：lower high
                mss       = c > sh_last    # 現價突破最近 lower high → MSS
                mss_level = round(sh_last, 2)

        signals = {
            "bullish_ob":       bullish_ob,
            "fvg_present":      fvg_present,
            "bos":              bos,
            "liquidity_sweep":  liquidity_sweep,
            "discount_zone":    discount_zone,
            "ote_zone":         ote_zone,
            "mss":              mss,
        }

        enabled       = {k: bool(p.get(k, {}).get("enabled", True)) for k in signals}
        score         = sum(v for k, v in signals.items() if enabled[k])
        total_enabled = sum(enabled.values())

        return {
            "close":          round(c, 2),
            "equilibrium":    round(equilibrium, 2),
            "range_high":     round(range_high, 2),
            "range_low":      round(range_low, 2),
            "ob_high":        ob_high,
            "ob_low":         ob_low,
            "fvg_top":        fvg_top,
            "fvg_bot":        fvg_bot,
            "swing_high_ref": swing_high_ref,
            "sweep_low":      sweep_low,
            "ote_top":        ote_top,
            "ote_bot":        ote_bot,
            "mss_level":      mss_level,
            "fib_low":        fib_low,
            "fib_high":       fib_high,
            "signals":        signals,
            "enabled":        enabled,
            "score":          score,
            "total_enabled":  total_enabled,
        }

    def calc_entry_params(self, ind: dict, capital: float, risk_pct: float = 2.0) -> dict:
        entry = ind["close"]
        if ind.get("ob_low"):
            stop = round(ind["ob_low"] * 0.99, 2)
        else:
            stop = round(ind["range_low"] * 0.99, 2)
        risk_per = max(entry - stop, 0.01)
        shares   = int((capital * risk_pct / 100) / risk_per)
        if ind.get("swing_high_ref") and ind["swing_high_ref"] > entry:
            target = round(ind["swing_high_ref"], 2)
        else:
            target = round(entry + risk_per * 2, 2)
        return {
            "entry":          entry,
            "stop":           stop,
            "target":         target,
            "shares":         shares,
            "risk_per_share": round(risk_per, 2),
            "total_risk":     int(risk_per * shares),
        }
