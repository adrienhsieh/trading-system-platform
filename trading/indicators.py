"""
trading/indicators.py — 技術指標計算引擎
資料來源：yfinance
指標計算：純 pandas 手寫（EMA / ADX / ATR / MACD / Volume SMA）
策略邏輯已移至 trading/strategies/，此模組僅保留原始數學輔助與資料抓取。
"""
from typing import Optional

import yfinance as yf
import pandas as pd

import io
import contextlib
import concurrent.futures
import datetime
import threading
import time as _time
from zoneinfo import ZoneInfo

from trading.constants import YFINANCE_RETRY_COUNT, YFINANCE_MIN_INTERVAL
from trading.logger import get_logger

logger = get_logger("indicators")

# ── period → 交易日天數對照 ──────────────────────────────────────
_PERIOD_DAYS = {
    "1mo": 22, "3mo": 66, "6mo": 130, "1y": 252,
    "2y": 504, "3y": 756, "5y": 1260, "max": 99999,
}


def _period_to_days(period: str) -> int:
    return _PERIOD_DAYS.get(period, 130)


_TZ_TAIPEI = ZoneInfo("Asia/Taipei")


def _now_taipei() -> datetime.datetime:
    """取得當前 Asia/Taipei 時間（獨立函式以利測試 mock）。"""
    return datetime.datetime.now(_TZ_TAIPEI)


def _expected_latest_trade_date() -> datetime.date:
    """根據台股收盤時間推算預期最新交易日。

    規則：14:00 後用當天，14:00 前用前一天；跳過週六日。
    國定假日不處理（yfinance 會自動跳過無資料日）。
    """
    now = _now_taipei()
    if now.hour >= 14:
        base = now.date()
    else:
        base = now.date() - datetime.timedelta(days=1)
    # 跳過週末
    while base.weekday() >= 5:  # 5=Sat, 6=Sun
        base -= datetime.timedelta(days=1)
    return base


# ── yfinance 全域速率節流 ──────────────────────────────────────
# 所有執行緒共用：兩次呼叫之間強制最短間隔，防止 rate limit。
_yf_throttle_lock  = threading.Lock()
_yf_last_call_time = 0.0


def _yf_throttle() -> None:
    """在呼叫 yfinance 前取得節流令牌；必要時阻塞等待。"""
    global _yf_last_call_time
    with _yf_throttle_lock:
        now  = _time.monotonic()
        wait = YFINANCE_MIN_INTERVAL - (now - _yf_last_call_time)
        if wait > 0:
            _time.sleep(wait)
        _yf_last_call_time = _time.monotonic()


def _fetch_with_retry(
    ticker: str,
    period: str = "6mo",
    interval: str = "1d",
    timeout: int = 8,
    retries: int = YFINANCE_RETRY_COUNT,
) -> Optional[pd.DataFrame]:
    """yfinance 資料抓取輔助：每次呼叫前節流，失敗時指數退避重試。

    回傳原始 yfinance DataFrame（欄位未重命名），失敗時回傳 None。
    """
    def _do_fetch() -> pd.DataFrame:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return yf.Ticker(ticker).history(period=period, interval=interval, auto_adjust=True)

    last_exc: Optional[Exception] = None
    for attempt in range(retries):
        if attempt > 0:
            _time.sleep(2 ** attempt)  # retry 退避：2s, 4s …
        _yf_throttle()  # 每次呼叫前強制最短間隔，防 rate limit
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                fut = ex.submit(_do_fetch)
                try:
                    raw = fut.result(timeout=timeout)
                except concurrent.futures.TimeoutError:
                    last_exc = TimeoutError(
                        f"yfinance fetch {ticker} timed out after {timeout}s"
                    )
                    continue
            if raw is None or raw.empty:
                return None
            return raw
        except Exception as e:
            last_exc = e
            msg = str(e)
            if "Too Many Requests" in msg or "Rate limit" in msg.lower():
                _time.sleep(5 * (2 ** attempt))  # rate limit 額外退避：5s, 10s …
                continue
    if last_exc:
        logger.warning("fetch %s 放棄（%d 次均失敗）: %s", ticker, retries, last_exc)
    return None


class IndicatorEngine:
    """技術指標計算引擎：原始數學輔助、OHLCV 抓取、持倉分析。
    信號計算與進場邏輯請見 trading/strategies/。
    """

    def __init__(self):
        from trading.ohlcv_db import OHLCVDatabase
        self._db = OHLCVDatabase()

    # ── 向下相容的信號標籤（供舊程式碼參考） ─────────────────────
    SIGNAL_LABELS: dict = {
        "ema_arrangement": "均線排列",
        "slopes_up":       "三線齊揚",
        "adx_above_25":    "ADX>25",
        "macd_positive":   "MACD紅",
        "volume_spike":    "爆量",
        "ema_crossover":   "5穿20",
    }

    ICT_SIGNAL_LABELS: dict = {
        "bullish_ob":       "多頭OB",
        "fvg_present":      "FVG不平衡",
        "bos":              "結構突破(BOS)",
        "liquidity_sweep":  "流動性掃除",
        "discount_zone":    "折扣區",
        "ote_zone":         "OTE回檔區",
        "mss":              "市場結構轉換(MSS)",
    }

    # ── 私有指標計算（靜態輔助） ────────────────────────────────

    @staticmethod
    def _ema(series: pd.Series, length: int) -> pd.Series:
        return series.ewm(span=length, adjust=False).mean()

    @staticmethod
    def _sma(series: pd.Series, length: int) -> pd.Series:
        return series.rolling(window=length).mean()

    @staticmethod
    def _atr(high: pd.Series, low: pd.Series, close: pd.Series, length: int = 14) -> pd.Series:
        prev_close = close.shift(1)
        tr = pd.concat([
            high - low,
            (high - prev_close).abs(),
            (low  - prev_close).abs(),
        ], axis=1).max(axis=1)
        return tr.ewm(alpha=1 / length, adjust=False).mean()

    @staticmethod
    def _adx(high: pd.Series, low: pd.Series, close: pd.Series, length: int = 14) -> pd.Series:
        up       = high.diff()
        down     = -low.diff()
        plus_dm  = up.where((up > down) & (up > 0), 0.0)
        minus_dm = down.where((down > up) & (down > 0), 0.0)
        atr_s    = IndicatorEngine._atr(high, low, close, length)
        plus_di  = 100 * IndicatorEngine._ema(plus_dm,  length) / atr_s
        minus_di = 100 * IndicatorEngine._ema(minus_dm, length) / atr_s
        dx       = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, 1)
        return dx.ewm(alpha=1 / length, adjust=False).mean()

    @staticmethod
    def _macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
        macd_line   = IndicatorEngine._ema(close, fast) - IndicatorEngine._ema(close, slow)
        signal_line = IndicatorEngine._ema(macd_line, signal)
        return macd_line, signal_line, macd_line - signal_line

    # ── 資料抓取 ───────────────────────────────────────────────

    def fetch_ohlcv(self, ticker: str, period: str = "6mo") -> Optional[pd.DataFrame]:
        """
        抓取 OHLCV 日線資料。
        優先使用本地 SQLite 快取（ohlcv_cache.db）；
        若快取不存在或過期（今日未更新），再從 yfinance 補抓並回寫快取。
        上市股使用 {code}.TW，上櫃股使用 {code}.TWO（先試 .TW，失敗再試 .TWO）。
        """
        #code = ticker.replace(".TW", "").replace(".TWO", "")
        code = str(ticker).replace(".TW", "").replace(".TWO", "")
        cached = None

        # ── 1. DB 優先讀取 ───────────────────────────────────────
        need_days = _period_to_days(period)
        cal_days = int(need_days * 1.5)   # 交易日 → 日曆日（含假日）
        try:
            cached = self._db.load(code, days=cal_days)
            if cached is not None and len(cached) >= need_days * 0.8:
                # ── 新鮮度檢查：DB 最新日期 >= 預期最新交易日才回傳 ──
                expected = _expected_latest_trade_date()
                db_latest = cached.index[-1].date() if hasattr(cached.index[-1], 'date') else cached.index[-1]
                if db_latest >= expected:
                    return cached
        except Exception as e:
            logger.warning("DB 讀取失敗 (%s): %s", code, e)

        # ── 2. 從 yfinance 抓取：先試 .TW（上市），失敗再試 .TWO（上櫃）
        raw = _fetch_with_retry(f"{code}.TW", period=period, timeout=8)
        if raw is None or raw.empty:
            raw = _fetch_with_retry(f"{code}.TWO", period=period, timeout=8)
        if raw is None or raw.empty:
            # 3. DB 有部分資料也回傳（勝過 None）
            if cached is not None and not cached.empty:
                return cached
            return None

        try:
            raw.columns = [c.strip() for c in raw.columns]
            rename_map = {
                "Open": "open", "High": "high", "Low": "low",
                "Close": "close", "Volume": "volume",
            }
            df = raw.rename(columns=rename_map)

            needed = ["open", "high", "low", "close", "volume"]
            if not all(c in df.columns for c in needed):
                return None

            df = df[needed].copy()
            for col in needed:
                s = df[col]
                if isinstance(s, pd.DataFrame):
                    s = s.iloc[:, 0]
                df[col] = pd.to_numeric(s.squeeze(), errors="coerce")

            df = df.dropna()

            # 回寫快取
            if not df.empty:
                try:
                    self._db.upsert(code, df)
                except Exception as _e:
                    logger.warning("快取寫入失敗 %s: %s", code, _e)

            return df
        except Exception as e:
            logger.warning("fetch %s 處理失敗: %s", ticker, e)
            return None

    # ── 向下相容 wrapper（委派至策略類別） ──────────────────────

    @staticmethod
    def compute(df: pd.DataFrame) -> Optional[dict]:
        """趨勢策略指標計算（向下相容）。"""
        from trading.strategies import get_strategy
        return get_strategy("trend").compute(df)

    @staticmethod
    def calc_entry_params(ind: dict, capital: float, risk_pct: float = 2.0) -> dict:
        """趨勢策略進場參數計算（向下相容）。"""
        from trading.strategies import get_strategy
        return get_strategy("trend").calc_entry_params(ind, capital, risk_pct)

    @staticmethod
    def compute_ict(df: pd.DataFrame) -> Optional[dict]:
        """ICT 策略指標計算（向下相容）。"""
        from trading.strategies import get_strategy
        return get_strategy("ict").compute(df)

    @staticmethod
    def calc_entry_params_ict(ind: dict, capital: float, risk_pct: float = 2.0) -> dict:
        """ICT 進場參數計算（向下相容）。"""
        from trading.strategies import get_strategy
        return get_strategy("ict").calc_entry_params(ind, capital, risk_pct)

    # ── 持倉分析 ───────────────────────────────────────────────

    def analyze_position(self, pos: dict) -> dict:
        """分析單一持倉的技術狀態，產生警示與建議。"""
        df = self.fetch_ohlcv(pos["code"])
        if df is None or len(df) < 25:
            return {"code": pos["code"], "error": "無法取得報價"}

        close    = df["close"]
        ema20    = self._ema(close, 20)
        current  = float(close.iloc[-1])
        e20_now  = float(ema20.iloc[-1])
        e20_prev = float(ema20.iloc[-2])

        below_ema20   = current < e20_now
        ema20_turning = e20_now < e20_prev

        alerts     = []
        suggestion = ""

        if pos["status"] == "active":
            if current <= pos["stop"] * 1.02:
                alerts.append("🚨 接近停損！請確認是否執行停損")
            if below_ema20:
                alerts.append("⚠️ 收盤跌破 20EMA，依策略應出場")
            if pos.get("target") and current >= pos["target"] * 0.98:
                alerts.append("🎯 接近第一目標價，準備執行 50% 獲利了結")
            if ema20_turning:
                alerts.append("📉 20EMA 開始下彎，啟動扣抵警報防禦機制")
            suggestion = "持倉正常，日常防守看 20EMA。" if not alerts else "⚠️ 有警示項目，請優先處理。"

        elif pos["status"] == "safe":
            if below_ema20:
                alerts.append("⚠️ 跌破 20EMA，保本單也應考慮出場")
            suggestion = "保本單：收盤跌破 20EMA 即出場。" if not alerts else "⚠️ 注意出場時機。"

        pct_to_target = None
        if pos.get("target"):
            pct_to_target = round((pos["target"] - current) / current * 100, 2)

        return {
            "code":          pos["code"],
            "name":          pos["name"],
            "current":       round(current, 2),
            "ema20":         round(e20_now, 2),
            "below_ema20":   below_ema20,
            "ema20_turning": ema20_turning,
            "pct_to_target": pct_to_target,
            "alerts":        alerts,
            "suggestion":    suggestion,
        }
