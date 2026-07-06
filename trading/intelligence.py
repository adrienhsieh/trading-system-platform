"""
trading/intelligence.py — 每日自動化情報 Daemon
背景執行緒：
  - 每 5 分鐘收集新聞（NewsAggregator）並以 Groq 分析情緒
  - 每 60 分鐘收集 X/Twitter 討論（XMonitor）
  - 每天 08:00 生成每日市場情報摘要（GroqClient）
資料存入 intelligence.db → news_intelligence, daily_summary
"""
import os
import sqlite3
import threading
import time
from datetime import datetime, timedelta
from typing import Optional

from trading.groq_client import GroqClient
from trading.news     import NewsAggregator
from trading.xmonitor import XMonitor
from trading.logger import get_logger

logger = get_logger("intelligence")


DB_PATH = os.path.join(os.path.dirname(__file__), "..", "intelligence.db")


class IntelligenceDaemon:
    """情報收集與分析背景 Daemon。"""

    NEWS_INTERVAL_SEC  =  5 * 60    # 5 分鐘
    X_INTERVAL_SEC     = 60 * 60    # 60 分鐘
    SUMMARY_HOUR       = 8          # 每天 08:00 生成摘要

    def __init__(
        self,
        groq_key: str = None,
        xai_key:  str = None,
        db_path:  str = None,
    ):
        self.db_path = db_path or DB_PATH
        self.groq    = GroqClient(api_key=groq_key)
        self.news_agg  = NewsAggregator()
        self.x_monitor = XMonitor(xai_api_key=xai_key, groq_client=self.groq)
        self._stop     = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_news_collect  = 0.0
        self._last_x_collect     = 0.0
        self._last_summary_date  = ""
        self._last_groq_batch    = 0.0   # 上次呼叫 analyze_news_batch 的時間
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self):
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS news_intelligence (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    title        TEXT    NOT NULL,
                    url          TEXT,
                    source       TEXT,
                    sentiment    TEXT,
                    confidence   INTEGER,
                    impact       TEXT,
                    reason       TEXT,
                    collected_at TEXT    NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS daily_summary (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    date         TEXT    NOT NULL UNIQUE,
                    summary      TEXT    NOT NULL,
                    mood         TEXT,
                    created_at   TEXT    NOT NULL
                )
            """)
            conn.commit()

    # ── 新聞收集 ────────────────────────────────────────────────

    def _collect_news(self):
        """
        抓取最新新聞並存入 DB。
        情緒判斷策略：
          - 使用 Groq 一次呼叫取得每則新聞各自的情緒（間隔 ≥ 30 分鐘）
          - Groq 不可用或超過間隔限制時，情緒預設為 "neutral"
        """
        try:
            articles = self.news_agg.fetch()
        except Exception as e:
            logger.warning("新聞抓取失敗: %s", e)
            return

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._connect() as conn:
            existing = {r[0] for r in conn.execute("SELECT title FROM news_intelligence").fetchall()}

        new_articles = []
        for art in articles:
            title = art.get("title", "").strip()
            if title and title not in existing:
                new_articles.append(art)

        if not new_articles:
            return

        # 單次 batch 呼叫取得每則新聞各自的情緒（限制：至少 30 分鐘呼叫一次）
        GROQ_BATCH_INTERVAL = 30 * 60   # 30 分鐘
        titles      = [a["title"] for a in new_articles]
        sentiments  = None
        if (self.groq.is_available() and
                time.time() - self._last_groq_batch >= GROQ_BATCH_INTERVAL):
            self._last_groq_batch = time.time()   # 無論成功與否都更新，避免連續觸發
            sentiments = self.groq.analyze_news_sentiments(titles)

        rows = []
        for i, art in enumerate(new_articles):
            title  = art.get("title", "").strip()
            url    = art.get("url", art.get("link", ""))
            source = art.get("source", "")
            # AI 逐則情緒；AI 不可用時預設 neutral
            if sentiments and i < len(sentiments) and sentiments[i] in ("bullish", "bearish", "neutral"):
                sentiment = sentiments[i]
            else:
                sentiment = "neutral"
            rows.append((title, url, source, sentiment, 5, "", "", now))

        if rows:
            with self._connect() as conn:
                conn.executemany(
                    "INSERT INTO news_intelligence"
                    "(title,url,source,sentiment,confidence,impact,reason,collected_at)"
                    " VALUES(?,?,?,?,?,?,?,?)",
                    rows,
                )
                conn.commit()
            logger.info("新增 %d 則新聞情報", len(rows))

    # ── X 收集 ──────────────────────────────────────────────────

    def _collect_x(self):
        """收集 X/Twitter 討論。"""
        try:
            added = self.x_monitor.collect()
            logger.info("X 收集 %d 則", added)
        except Exception as e:
            logger.warning("X 收集失敗: %s", e)

    # ── 每日摘要 ────────────────────────────────────────────────

    MIN_NEWS_FOR_SUMMARY = 5   # 至少需要幾則新聞才生成摘要

    def _generate_daily_summary(self, force: bool = False):
        """
        使用 Gemini 生成今日市場情報摘要。
        force=True 時忽略「已存在」檢查，強制重新生成。
        新聞少於 MIN_NEWS_FOR_SUMMARY 則跳過（避免生成空洞摘要）。
        """
        today = datetime.now().strftime("%Y-%m-%d")

        # 避免重複生成（非 force 模式）
        if not force:
            with self._connect() as conn:
                existing = conn.execute(
                    "SELECT summary FROM daily_summary WHERE date=?", (today,)
                ).fetchone()
            # 若已有摘要且非占位文字，跳過
            if existing and "無足夠資料" not in (existing[0] or ""):
                return

        # 取今日新聞（不限定今天，取最近 24 小時，讓剛啟動的情況也能生成）
        since = (datetime.now() - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT title, sentiment FROM news_intelligence "
                "WHERE collected_at>=? ORDER BY collected_at DESC LIMIT 20",
                (since,),
            ).fetchall()
        news_items = [{"title": r[0], "sentiment": r[1]} for r in rows]

        if len(news_items) < self.MIN_NEWS_FOR_SUMMARY:
            logger.info("新聞不足 %d 則（目前 %d 則），跳過摘要生成", self.MIN_NEWS_FOR_SUMMARY, len(news_items))
            return

        # 取近期 X 貼文
        x_posts = self.x_monitor.get_recent(hours=24, limit=10)

        summary_text = self.groq.generate_daily_summary(news_items, x_posts)
        if not summary_text:
            logger.warning("Groq 生成摘要失敗，略過儲存")
            return

        # 整體情緒
        sentiments = [r[1] for r in rows if r[1]]
        bullish    = sentiments.count("bullish")
        bearish    = sentiments.count("bearish")
        mood       = "bullish" if bullish > bearish else ("bearish" if bearish > bullish else "neutral")

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO daily_summary(date,summary,mood,created_at) VALUES(?,?,?,?)",
                (today, summary_text, mood, now),
            )
            conn.commit()
        logger.info("已生成 %s 每日摘要（情緒: %s）", today, mood)

    # ── 主迴圈 ──────────────────────────────────────────────────

    def _loop(self):
        while not self._stop.is_set():
            now = time.time()
            hour = datetime.now().hour
            today = datetime.now().strftime("%Y-%m-%d")

            # 每 5 分鐘收集新聞
            if now - self._last_news_collect >= self.NEWS_INTERVAL_SEC:
                self._collect_news()
                self._last_news_collect = now

            # 每 60 分鐘收集 X
            if now - self._last_x_collect >= self.X_INTERVAL_SEC:
                self._collect_x()
                self._last_x_collect = now

            # 每天 08:00 生成摘要
            if hour == self.SUMMARY_HOUR and today != self._last_summary_date:
                self._generate_daily_summary()
                self._last_summary_date = today

            time.sleep(30)

    # ── 控制介面 ────────────────────────────────────────────────

    def start(self):
        """啟動背景 Daemon 執行緒。"""
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="IntelligenceDaemon")
        self._thread.start()
        logger.info("已啟動")

    def stop(self):
        """停止 Daemon 執行緒。"""
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("已停止")

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ── 查詢 API ────────────────────────────────────────────────

    def get_recent_news(self, hours: int = 24, limit: int = 20) -> list[dict]:
        """取得最近 hours 小時內的新聞情報。"""
        since = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT title,url,source,sentiment,confidence,impact,collected_at "
                "FROM news_intelligence WHERE collected_at>=? "
                "ORDER BY collected_at DESC LIMIT ?",
                (since, limit),
            ).fetchall()
        return [
            {"title": r[0], "url": r[1], "source": r[2], "sentiment": r[3],
             "confidence": r[4], "impact": r[5], "collected_at": r[6]}
            for r in rows
        ]

    def get_latest_summary(self) -> Optional[dict]:
        """取得最新的每日摘要。"""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT date,summary,mood,created_at FROM daily_summary "
                "ORDER BY date DESC LIMIT 1"
            ).fetchone()
        if not row:
            return None
        return {"date": row[0], "summary": row[1], "mood": row[2], "created_at": row[3]}

    def get_news_sentiment_stats(self, hours: int = 24) -> dict:
        """統計最近 hours 小時內新聞情緒分佈。"""
        since = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT sentiment FROM news_intelligence WHERE collected_at>=?",
                (since,),
            ).fetchall()
        sentiments = [r[0] for r in rows if r[0]]
        total   = len(sentiments)
        bullish = sentiments.count("bullish")
        bearish = sentiments.count("bearish")
        neutral = total - bullish - bearish
        mood    = "bullish" if bullish > bearish else ("bearish" if bearish > bullish else "neutral")
        return {"total": total, "bullish": bullish, "bearish": bearish, "neutral": neutral, "mood": mood}

    def force_collect(self):
        """立即手動觸發一次新聞與 X 收集（供 API 呼叫）。"""
        self._collect_news()
        self._collect_x()

    def generate_summary_now(self) -> bool:
        """立即強制重新生成今日摘要（供 API 呼叫）。回傳是否成功儲存。"""
        today = datetime.now().strftime("%Y-%m-%d")
        with self._connect() as conn:
            before = conn.execute(
                "SELECT created_at FROM daily_summary WHERE date=?", (today,)
            ).fetchone()
        self._generate_daily_summary(force=True)
        with self._connect() as conn:
            after = conn.execute(
                "SELECT created_at FROM daily_summary WHERE date=?", (today,)
            ).fetchone()
        # 成功：新增了紀錄，或 created_at 有更新
        if after and (not before or after[0] != before[0]):
            return True
        return False
