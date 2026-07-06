"""
trading/ohlcv_db.py — 本地 OHLCV SQLite 快取
減少 yfinance API 呼叫次數，加速分析速度。
"""
import sqlite3
import os
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd


DB_PATH = os.path.join(os.path.dirname(__file__), "..", "ohlcv_cache.db")


class OHLCVDatabase:
    """本地 OHLCV 快取資料庫（SQLite）。"""

    def __init__(self, db_path: str = None):
        self.db_path = db_path or DB_PATH
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        # timeout=60：多執行緒並行寫入時等待鎖釋放，而非立即拋出 database is locked
        conn = sqlite3.connect(self.db_path, timeout=60, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")  # WAL 模式下降低 sync 開銷
        return conn

    def _init_db(self):
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS ohlcv (
                    code    TEXT    NOT NULL,
                    date    TEXT    NOT NULL,
                    open    REAL    NOT NULL,
                    high    REAL    NOT NULL,
                    low     REAL    NOT NULL,
                    close   REAL    NOT NULL,
                    volume  REAL    NOT NULL,
                    PRIMARY KEY (code, date)
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_ohlcv_code ON ohlcv(code)")
            conn.commit()

    # ── 寫入 ────────────────────────────────────────────────────

    def upsert(self, code: str, df: pd.DataFrame) -> int:
        """
        將 DataFrame（含 open/high/low/close/volume，index 為日期）寫入快取。
        使用 INSERT OR REPLACE 保持冪等性。
        回傳寫入筆數。
        """
        if df is None or df.empty:
            return 0
        rows = []
        for dt, row in df.iterrows():
            date_str = str(dt)[:10]
            # 驗證日期格式（防止 RangeIndex 寫入如 "0", "21" 等壞資料）
            if len(date_str) < 8 or date_str[4:5] != '-':
                continue
            rows.append((
                code, date_str,
                float(row["open"]), float(row["high"]),
                float(row["low"]),  float(row["close"]),
                float(row["volume"]),
            ))
        with self._connect() as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO ohlcv(code,date,open,high,low,close,volume) VALUES(?,?,?,?,?,?,?)",
                rows,
            )
            conn.commit()
        return len(rows)

    # ── 讀取 ────────────────────────────────────────────────────

    def load(self, code: str, days: int = 600) -> Optional[pd.DataFrame]:
        """
        讀取指定代號最近 days 天的 OHLCV（日線）。
        若無資料回傳 None。
        """
        since = (datetime.today() - timedelta(days=days)).strftime("%Y-%m-%d")
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT date,open,high,low,close,volume FROM ohlcv "
                "WHERE code=? AND date>=? ORDER BY date ASC",
                (code, since),
            )
            rows = cur.fetchall()
        if not rows:
            return None
        df = pd.DataFrame(rows, columns=["date", "open", "high", "low", "close", "volume"])
        df["date"] = pd.to_datetime(df["date"], format="%Y-%m-%d")
        df.set_index("date", inplace=True)
        return df

    def latest_date(self, code: str) -> Optional[str]:
        """回傳該代號在快取中最新的日期（YYYY-MM-DD），無則 None。"""
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT MAX(date) FROM ohlcv WHERE code=?", (code,)
            )
            row = cur.fetchone()
        return row[0] if row and row[0] else None

    # ── 統計 ────────────────────────────────────────────────────

    def stats(self) -> dict:
        """回傳快取統計資訊。"""
        with self._connect() as conn:
            total_rows = conn.execute("SELECT COUNT(*) FROM ohlcv").fetchone()[0]
            total_codes = conn.execute("SELECT COUNT(DISTINCT code) FROM ohlcv").fetchone()[0]
            oldest = conn.execute("SELECT MIN(date) FROM ohlcv").fetchone()[0]
            newest = conn.execute("SELECT MAX(date) FROM ohlcv").fetchone()[0]
        return {
            "total_rows":  total_rows,
            "total_codes": total_codes,
            "oldest_date": oldest,
            "newest_date": newest,
        }

    def list_codes(self) -> list:
        """回傳所有已快取的代號清單。"""
        with self._connect() as conn:
            cur = conn.execute("SELECT DISTINCT code FROM ohlcv ORDER BY code")
            return [r[0] for r in cur.fetchall()]

    def delete_code(self, code: str) -> int:
        """刪除指定代號的所有快取資料，回傳刪除筆數。"""
        with self._connect() as conn:
            cur = conn.execute("DELETE FROM ohlcv WHERE code=?", (code,))
            conn.commit()
            return cur.rowcount
