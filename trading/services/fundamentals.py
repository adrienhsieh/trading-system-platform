"""
trading/services/fundamentals.py — TWSE OpenAPI 基本面／籌碼資料服務

負責抓取並快取台灣證交所（TWSE）OpenAPI 公開資料集（全體共用，非個人化）：
  - BWIBBU_ALL   ：每日本益比、殖利率、股價淨值比（全上市股票）
  - MI_MARGN     ：每日融資融券餘額（全上市股票）
  - t187ap05_L   ：每月營業收入彙總表（上市公司，含 YoY/MoM）

資料每日僅需更新一次（TWSE 官方本身也是盤後才更新），採「讀取時檢查 TTL、
過期才重新抓取」的策略，不需要另開常駐執行緒；也提供 refresh_all() 供
啟動時或排程主動呼叫。

因為 TWSE OpenAPI 的 JSON 欄位命名在不同資料集間並不一致（有的用英文鍵，
有的用中文鍵），本模組對每個資料集的欄位讀取採「多鍵名嘗試」的防禦寫法，
單筆解析失敗只會跳過該筆，不會讓整個更新流程中斷。
"""
import sqlite3
import time
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import requests

from trading.logger import get_logger

logger = get_logger("fundamentals")

BASE_DIR = Path(__file__).parent.parent.parent
DB_PATH = BASE_DIR / "db" / "fundamentals.db"

TWSE_BWIBBU_URL  = "https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_ALL"
TWSE_MARGIN_URL  = "https://openapi.twse.com.tw/v1/exchangeReport/MI_MARGN"
TWSE_REVENUE_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap05_L"

REFRESH_TTL_SECONDS = 12 * 3600  # 12 小時內視為新鮮，不重複打 API


def _first(d: dict, *keys, cast=None):
    """依序嘗試多個可能的鍵名，回傳第一個存在且非空的值（可選型別轉換）。"""
    for k in keys:
        v = d.get(k)
        if v is not None and v != "":
            if cast is None:
                return v
            try:
                return cast(str(v).replace(",", ""))
            except (TypeError, ValueError):
                continue
    return None


class FundamentalsService:
    """TWSE OpenAPI 基本面／籌碼資料：抓取、快取、查詢。全體使用者共用同一份資料。"""

    def __init__(self, db_path: Path = None):
        self.db_path = db_path or DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._last_refresh: dict = {"valuation": 0.0, "margin": 0.0, "revenue": 0.0}
        self._init_db()

    @contextmanager
    def _conn(self):
        con = sqlite3.connect(str(self.db_path), check_same_thread=False, timeout=15.0)
        con.row_factory = sqlite3.Row
        try:
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    def _init_db(self) -> None:
        with self._conn() as con:
            con.execute("""
                CREATE TABLE IF NOT EXISTS valuation (
                    code TEXT PRIMARY KEY, name TEXT,
                    per REAL, pbr REAL, dividend_yield REAL,
                    updated_at TEXT
                )
            """)
            con.execute("""
                CREATE TABLE IF NOT EXISTS margin_trading (
                    code TEXT NOT NULL, trade_date TEXT NOT NULL,
                    margin_balance INTEGER, short_balance INTEGER,
                    PRIMARY KEY (code, trade_date)
                )
            """)
            con.execute("""
                CREATE TABLE IF NOT EXISTS monthly_revenue (
                    code TEXT NOT NULL, year INTEGER NOT NULL, month INTEGER NOT NULL,
                    revenue REAL, yoy_pct REAL, mom_pct REAL,
                    PRIMARY KEY (code, year, month)
                )
            """)

    # ── 對外查詢介面 ─────────────────────────────────────────────

    def get_valuation(self, code: str, auto_refresh: bool = True) -> Optional[dict]:
        if auto_refresh:
            self._refresh_if_stale("valuation", self.refresh_valuation)
        with self._conn() as con:
            row = con.execute("SELECT * FROM valuation WHERE code=?", (code,)).fetchone()
        return dict(row) if row else None

    def get_margin_series(self, code: str, days: int = 20, auto_refresh: bool = True) -> list:
        if auto_refresh:
            self._refresh_if_stale("margin", self.refresh_margin)
        with self._conn() as con:
            rows = con.execute(
                "SELECT trade_date, margin_balance, short_balance FROM margin_trading "
                "WHERE code=? ORDER BY trade_date DESC LIMIT ?", (code, days),
            ).fetchall()
        return [dict(r) for r in reversed(rows)]

    def get_revenue_series(self, code: str, months: int = 13, auto_refresh: bool = True) -> list:
        if auto_refresh:
            self._refresh_if_stale("revenue", self.refresh_revenue)
        with self._conn() as con:
            rows = con.execute(
                "SELECT year, month, revenue, yoy_pct, mom_pct FROM monthly_revenue "
                "WHERE code=? ORDER BY year DESC, month DESC LIMIT ?", (code, months),
            ).fetchall()
        return [dict(r) for r in reversed(rows)]

    def get_revenue_growth_streak(self, code: str) -> int:
        """回傳月營收 YoY 連續正成長的月數（由最新月份往前算，中斷即停止）。"""
        series = self.get_revenue_series(code, months=24)
        streak = 0
        for row in reversed(series):  # 由最新往前
            if row.get("yoy_pct") is not None and row["yoy_pct"] > 0:
                streak += 1
            else:
                break
        return streak

    def get_chip_washout_signal(self, code: str, lookback: int = 10) -> Optional[dict]:
        """
        籌碼洗淨訊號：融資餘額連續遞減 + 期間股價上漲，代表籌碼由散戶轉為大戶／法人承接。
        回傳 None 表示資料不足以判斷。
        """
        series = self.get_margin_series(code, days=lookback + 1)
        if len(series) < 2:
            return None
        balances = [r["margin_balance"] for r in series if r["margin_balance"] is not None]
        if len(balances) < 2:
            return None
        declining_days = sum(1 for i in range(1, len(balances)) if balances[i] < balances[i - 1])
        declining_ratio = declining_days / (len(balances) - 1)
        margin_change_pct = (balances[-1] - balances[0]) / balances[0] * 100 if balances[0] else 0
        return {
            "declining_ratio": round(declining_ratio, 3),
            "margin_change_pct": round(margin_change_pct, 2),
            "is_washout": declining_ratio >= 0.6 and margin_change_pct < -5,
        }

    def get_vix(self) -> Optional[float]:
        """取得最新 VIX 恐慌指數（yfinance ^VIX，20 分鐘快取）。"""
        now = time.time()
        cached = getattr(self, "_vix_cache", None)
        cached_time = getattr(self, "_vix_cache_time", 0)
        if cached is not None and now - cached_time < 20 * 60:
            return cached
        try:
            import yfinance as yf
            hist = yf.Ticker("^VIX").history(period="5d")
            if hist is not None and not hist.empty:
                vix = float(hist["Close"].iloc[-1])
                self._vix_cache = vix
                self._vix_cache_time = now
                return vix
        except Exception as e:
            logger.warning("VIX 抓取失敗: %s", e)
        return cached

    # ── 抓取（TWSE OpenAPI，每日一次即可） ──────────────────────────

    def _refresh_if_stale(self, key: str, fn) -> None:
        if time.time() - self._last_refresh.get(key, 0) > REFRESH_TTL_SECONDS:
            try:
                fn()
            except Exception as e:
                logger.warning("刷新 %s 失敗: %s", key, e)
            self._last_refresh[key] = time.time()

    def refresh_all(self) -> None:
        for fn in (self.refresh_valuation, self.refresh_margin, self.refresh_revenue):
            try:
                fn()
            except Exception as e:
                logger.warning("刷新失敗: %s", e)

    def refresh_valuation(self) -> int:
        """本益比／殖利率／股價淨值比（BWIBBU_ALL，全上市股票）。"""
        resp = requests.get(TWSE_BWIBBU_URL, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        records = resp.json()
        now = datetime.now().isoformat(timespec="seconds")
        n = 0
        with self._conn() as con:
            for r in records:
                code = _first(r, "Code", "code", "公司代號")
                if not code:
                    continue
                name = _first(r, "Name", "name", "公司簡稱") or ""
                per  = _first(r, "PEratio", "PERatio", "peRatio", cast=float)
                pbr  = _first(r, "PBratio", "PBRatio", "pbRatio", cast=float)
                dy   = _first(r, "DividendYield", "dividendYield", cast=float)
                con.execute("""
                    INSERT INTO valuation (code, name, per, pbr, dividend_yield, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(code) DO UPDATE SET
                        name=excluded.name, per=excluded.per, pbr=excluded.pbr,
                        dividend_yield=excluded.dividend_yield, updated_at=excluded.updated_at
                """, (code, name, per, pbr, dy, now))
                n += 1
        logger.info("本益比/殖利率 更新 %d 筆", n)
        self._last_refresh["valuation"] = time.time()
        return n

    def refresh_margin(self) -> int:
        """融資融券餘額（MI_MARGN，全上市股票）。"""
        resp = requests.get(TWSE_MARGIN_URL, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        records = resp.json()
        today = date.today().isoformat()
        n = 0
        with self._conn() as con:
            for r in records:
                code = _first(r, "Code", "code", "股票代號")
                if not code:
                    continue
                margin_bal = _first(r, "MarginPurchaseTodayBalance", "TodayBalance", cast=int)
                short_bal  = _first(r, "ShortSaleTodayBalance", cast=int)
                con.execute("""
                    INSERT INTO margin_trading (code, trade_date, margin_balance, short_balance)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(code, trade_date) DO UPDATE SET
                        margin_balance=excluded.margin_balance, short_balance=excluded.short_balance
                """, (code, today, margin_bal, short_bal))
                n += 1
        logger.info("融資融券 更新 %d 筆", n)
        self._last_refresh["margin"] = time.time()
        return n

    def refresh_revenue(self) -> int:
        """每月營業收入彙總表（t187ap05_L，上市公司，含 YoY/MoM）。"""
        resp = requests.get(TWSE_REVENUE_URL, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        records = resp.json()
        n = 0
        with self._conn() as con:
            for r in records:
                code = _first(r, "公司代號", "Code", "code")
                if not code:
                    continue
                period = _first(r, "資料年月", "出表日期", "年月")
                year, month = None, None
                if period:
                    period = str(period).strip()
                    try:
                        if len(period) == 5:      # 民國年+月，例如 11401 → 114年01月
                            year, month = int(period[:3]) + 1911, int(period[3:])
                        elif len(period) == 6:     # 西元年+月，例如 202501
                            year, month = int(period[:4]), int(period[4:])
                    except ValueError:
                        pass
                if year is None or month is None:
                    now = datetime.now()
                    year, month = now.year, now.month

                revenue = _first(r, "營業收入-當月營收", "當月營收", "revenue", cast=float)
                yoy     = _first(r, "營業收入-去年同月增減(%)", "去年同月增減(%)", cast=float)
                mom     = _first(r, "營業收入-上月比較增減(%)", "上月比較增減(%)", cast=float)

                con.execute("""
                    INSERT INTO monthly_revenue (code, year, month, revenue, yoy_pct, mom_pct)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(code, year, month) DO UPDATE SET
                        revenue=excluded.revenue, yoy_pct=excluded.yoy_pct, mom_pct=excluded.mom_pct
                """, (code, year, month, revenue, yoy, mom))
                n += 1
        logger.info("月營收 更新 %d 筆", n)
        self._last_refresh["revenue"] = time.time()
        return n
