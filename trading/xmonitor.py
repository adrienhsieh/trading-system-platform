"""
trading/xmonitor.py — X/Twitter 市場情緒監控
主要：Grok API（xAI）
備援：Google News RSS + Groq 情緒分析
最後：Google News RSS（無情緒分析）
資料存入 intelligence.db → x_posts
"""
import hashlib
import json
import os
import sqlite3
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import quote_plus
from trading.logger import get_logger

logger = get_logger("xmonitor")

import requests


DB_PATH = os.path.join(os.path.dirname(__file__), "..", "intelligence.db")

GROK_API_URL  = "https://api.x.ai/v1/chat/completions"
GROK_MODEL    = "grok-4.3"  # xAI 目前建議的一般對話/分析預設模型（舊版 grok-2-latest 已停用，會回 400）

GOOGLE_NEWS_RSS = "https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"

# 監控關鍵字（英文 for Grok / Google News）
SEARCH_QUERIES = [
    "Taiwan stock market",
    "TSMC semiconductor",
    "Fed interest rate",
    "Taiwan dollar TWD",
    "TWSE TAIEX",
]


class XMonitor:
    """X/Twitter 市場討論監控，以 Grok API 為主、Google News RSS 為備援。"""

    def __init__(self, xai_api_key: str = None, db_path: str = None, groq_client=None):
        self.xai_api_key = xai_api_key or os.environ.get("XAI_API_KEY", "")
        self.db_path     = db_path or DB_PATH
        self.groq        = groq_client
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self):
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS x_posts (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    source       TEXT    NOT NULL,
                    query        TEXT    NOT NULL,
                    content      TEXT    NOT NULL,
                    sentiment    TEXT,
                    url          TEXT,
                    collected_at TEXT    NOT NULL,
                    content_hash TEXT    UNIQUE
                )
            """)
            # 相容舊資料庫：若 content_hash 欄位不存在則補加
            try:
                conn.execute("ALTER TABLE x_posts ADD COLUMN content_hash TEXT UNIQUE")
            except Exception:
                pass
            conn.commit()

    # ── Grok API ────────────────────────────────────────────────

    def _fetch_grok(self, query: str) -> list[dict]:
        """透過 Grok API 取得關於 query 的最新 X 討論摘要。"""
        if not self.xai_api_key:
            return []
        prompt = (
            f"Summarize the top 5 recent X/Twitter discussions about '{query}' "
            "related to financial markets, stocks, or economic trends. "
            "For each discussion, provide: content (1-2 sentences), and sentiment (bullish/bearish/neutral). "
            "Return as a JSON array: [{\"content\": \"...\", \"sentiment\": \"...\"}]"
        )
        body = {
            "model":    GROK_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 1024,
            "temperature": 0.3,
        }
        try:
            r = requests.post(
                GROK_API_URL,
                headers={
                    "Authorization": f"Bearer {self.xai_api_key}",
                    "Content-Type":  "application/json",
                },
                json=body,
                timeout=30,
            )
            r.raise_for_status()
            text = r.json()["choices"][0]["message"]["content"]
            # 解析 JSON
            text = text.strip()
            if "```" in text:
                for part in text.split("```"):
                    part = part.strip()
                    if part.startswith("json"):
                        part = part[4:].strip()
                    try:
                        data = json.loads(part)
                        if isinstance(data, list):
                            return data
                    except Exception:
                        continue
            data = json.loads(text)
            return data if isinstance(data, list) else []
        except Exception as e:
            logger.warning("Grok API 失敗: %s", e)
            return []

    # ── Google News RSS 備援 ────────────────────────────────────

    def _fetch_google_news(self, query: str) -> list[dict]:
        """從 Google News RSS 取得相關英文新聞作為備援。"""
        url = GOOGLE_NEWS_RSS.format(query=quote_plus(query))
        try:
            r = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
            r.raise_for_status()
            root = ET.fromstring(r.content)
            items = root.findall(".//item")
            results = []
            for item in items[:5]:
                title = item.findtext("title", "")
                link  = item.findtext("link", "")
                if title:
                    results.append({"content": title, "sentiment": "neutral", "url": link})
            return results
        except Exception as e:
            logger.warning("Google News RSS 失敗: %s", e)
            return []

    # ── Google News + Groq 情緒分析 ──────────────────────────────

    def _fetch_google_news_with_groq(self, query: str) -> list[dict]:
        """Google News RSS 抓新聞，再用 Groq 分析情緒。"""
        news = self._fetch_google_news(query)
        if not news or not self.groq or not self.groq.is_available():
            return news  # fallback 到無情緒版本

        titles = [n["content"] for n in news if n.get("content")]
        if not titles:
            return news

        prompt = (
            "Analyze the sentiment of each financial news headline below.\n"
            "Return ONLY a JSON array of sentiments: [\"bullish\", \"bearish\", \"neutral\", ...]\n"
            "One sentiment per headline, same order.\n\n"
            + "\n".join(f"{i+1}. {t}" for i, t in enumerate(titles))
        )
        try:
            raw = self.groq.generate(prompt)
            if raw:
                text = raw.strip()
                if "```" in text:
                    for part in text.split("```"):
                        part = part.strip()
                        if part.startswith("json"):
                            part = part[4:].strip()
                        try:
                            data = json.loads(part)
                            if isinstance(data, list):
                                sentiments = data
                                break
                        except Exception:
                            continue
                    else:
                        sentiments = json.loads(text)
                else:
                    sentiments = json.loads(text)

                if isinstance(sentiments, list):
                    for i, s in enumerate(sentiments):
                        if i < len(news) and s in ("bullish", "bearish", "neutral"):
                            news[i]["sentiment"] = s
                    logger.info("Groq 情緒分析完成: %d 則", len(sentiments))
        except Exception as e:
            logger.warning("Groq 情緒分析失敗: %s", e)

        return news

    # ── 主要收集入口 ────────────────────────────────────────────

    def collect(self, queries: list[str] = None) -> int:
        """
        收集 X/Twitter 討論資料並存入資料庫。
        若 Grok 可用則用 Grok，否則改用 Google News RSS。
        回傳新增筆數。
        """
        queries     = queries or SEARCH_QUERIES
        total_added = 0
        # 三層 fallback: Grok → Google News + Groq 情緒 → Google News 純新聞
        if self.xai_api_key:
            source = "grok"
        elif self.groq and self.groq.is_available():
            source = "groq_news"
        else:
            source = "google_news"
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        for query in queries:
            if source == "grok":
                posts = self._fetch_grok(query)
            elif source == "groq_news":
                posts = self._fetch_google_news_with_groq(query)
            else:
                posts = self._fetch_google_news(query)

            rows = []
            for p in posts:
                content   = p.get("content", "").strip()
                sentiment = p.get("sentiment", "neutral")
                url       = p.get("url", "")
                if content:
                    content_hash = hashlib.md5(content.encode("utf-8")).hexdigest()
                    rows.append((source, query, content, sentiment, url, now, content_hash))

            if rows:
                with self._connect() as conn:
                    conn.executemany(
                        "INSERT OR IGNORE INTO x_posts"
                        "(source,query,content,sentiment,url,collected_at,content_hash) "
                        "VALUES(?,?,?,?,?,?,?)",
                        rows,
                    )
                    total_added += conn.execute("SELECT changes()").fetchone()[0]
                    conn.commit()

        return total_added

    # ── 查詢 ────────────────────────────────────────────────────

    def get_recent(self, hours: int = 24, limit: int = 20) -> list[dict]:
        """取得最近 hours 小時內的貼文，依 collected_at 降序。"""
        since = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT source,query,content,sentiment,url,collected_at FROM x_posts "
                "WHERE collected_at>=? ORDER BY collected_at DESC LIMIT ?",
                (since, limit),
            )
            rows = cur.fetchall()
        return [
            {"source": r[0], "query": r[1], "content": r[2],
             "sentiment": r[3], "url": r[4], "collected_at": r[5]}
            for r in rows
        ]

    def sentiment_summary(self, hours: int = 24) -> dict:
        """統計最近 hours 小時內各情緒占比。"""
        posts = self.get_recent(hours=hours, limit=200)
        total    = len(posts)
        bullish  = sum(1 for p in posts if p["sentiment"] == "bullish")
        bearish  = sum(1 for p in posts if p["sentiment"] == "bearish")
        neutral  = total - bullish - bearish
        mood     = "bullish" if bullish > bearish else ("bearish" if bearish > bullish else "neutral")
        return {
            "total":   total,
            "bullish": bullish,
            "bearish": bearish,
            "neutral": neutral,
            "mood":    mood,
        }

    def is_available(self) -> bool:
        return bool(self.xai_api_key)
