"""
trading/market.py — 市場行情服務
快取台股、美股、匯率與大盤 EMA 資料，TTL 300 秒自動刷新。
"""
import threading
import time
from typing import Optional
from trading.constants import MARKET_CACHE_TTL
from trading.logger import get_logger

logger = get_logger("market")


class MarketService:
    """市場行情快取服務，背景非同步刷新，執行緒安全。"""

    TTL: int = MARKET_CACHE_TTL  # 快取有效秒數（預設 300 秒）

    SYMBOLS: dict = {
        "taiex":   "^TWII",
        "nasdaq":  "^IXIC",
        "sp500":   "^GSPC",
        "usd_twd": "TWD=X",
    }

    def __init__(self):
        self._cache:      dict  = {}
        self._cache_time: float = 0.0
        self._lock                = threading.Lock()
        self._fetching            = threading.Event()  # set = 正在抓取中

    # ── 公開介面 ───────────────────────────────────────────────

    def get_data(self) -> dict:
        """取得市場快取；若過期且未在刷新中，則觸發背景刷新。"""
        if time.time() - self._cache_time > self.TTL and not self._fetching.is_set():
            if not self._fetching.is_set():
                self._fetching.set()
                threading.Thread(target=self._fetch, daemon=True).start()
        with self._lock:
            return dict(self._cache)

    def refresh(self) -> None:
        """強制觸發同步刷新（阻塞直到完成）。"""
        self._fetch()

    # ── 內部抓取 ───────────────────────────────────────────────

    def _fetch(self) -> None:
        """抓取所有市場資料並更新快取。"""
        import concurrent.futures
        import yfinance as yf

        result: dict = {}

        def _sym(key: str, sym: str):
            try:
                df = yf.Ticker(sym).history(period="5d", interval="1d")
                if len(df) >= 2:
                    curr = float(df["Close"].iloc[-1])
                    prev = float(df["Close"].iloc[-2])
                    return key, {"price": round(curr, 2), "change_pct": round((curr - prev) / prev * 100, 2)}
            except Exception:
                pass
            return key, {"price": None, "change_pct": None}

        def _ema() -> dict:
            try:
                df = yf.Ticker("^TWII").history(period="3mo", interval="1d")
                if not df.empty and len(df) >= 20:
                    c = df["Close"]
                    e = c.ewm(span=20, adjust=False).mean()
                    return {
                        "market_above_ema20": bool(float(c.iloc[-1]) > float(e.iloc[-1])),
                        "ema20_tw":           round(float(e.iloc[-1]), 0),
                    }
            except Exception:
                pass
            return {"market_above_ema20": None, "ema20_tw": None}

        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
                futs  = {ex.submit(_sym, k, v): k for k, v in self.SYMBOLS.items()}
                ema_f = ex.submit(_ema)
                for f in concurrent.futures.as_completed(futs, timeout=30):
                    try:
                        k, d = f.result()
                        result[k] = d
                    except Exception:
                        pass
                try:
                    result.update(ema_f.result(timeout=30))
                except Exception:
                    result["market_above_ema20"] = None
        except Exception:
            pass

        if result:
            with self._lock:
                self._cache      = result
                self._cache_time = time.time()
            logger.info("快取更新完成")

        self._fetching.clear()
