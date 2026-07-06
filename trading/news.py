"""
trading/news.py — 財經新聞聚合器
使用 RSS Feed 抓取；支援 Gemini AI 情緒分析。
來源：Yahoo 財經 / 自由時報 / Google News RSS（台股、財經、國際、地緣政治）
"""
import datetime
import defusedxml.ElementTree as ET
import concurrent.futures
from typing import Optional
from trading.logger import get_logger

logger = get_logger("news")


class NewsAggregator:
    """從多個 RSS Feed 並行抓取財經新聞並彙整排序。"""

    RSS_FEEDS: list = [
        # ── 台灣財經 ────────────────────────────────────────────
        {"url": "https://tw.stock.yahoo.com/rss",
         "tag": "tw",    "label": "Yahoo 財經"},
        {"url": "https://news.ltn.com.tw/rss/business.xml",
         "tag": "tw",    "label": "自由時報財經"},
        {"url": "https://news.google.com/rss/search?q=台股+股市&hl=zh-TW&gl=TW&ceid=TW:zh-Hant",
         "tag": "tw",    "label": "Google News 台股"},
        {"url": "https://news.google.com/rss/search?q=半導體+AI+台積電&hl=zh-TW&gl=TW&ceid=TW:zh-Hant",
         "tag": "tw",    "label": "Google News 半導體"},
        {"url": "https://news.google.com/rss/search?q=Fed+聯準會+利率&hl=zh-TW&gl=TW&ceid=TW:zh-Hant",
         "tag": "macro", "label": "Google News 總經"},
        {"url": "https://news.google.com/rss/search?q=美股+Nasdaq+S%26P500&hl=zh-TW&gl=TW&ceid=TW:zh-Hant",
         "tag": "intl",  "label": "Google News 美股"},
        # ── 國際新聞（中文） ────────────────────────────────────
        {"url": "https://news.ltn.com.tw/rss/world.xml",
         "tag": "intl",  "label": "自由時報國際"},
        {"url": "https://news.ltn.com.tw/rss/politics.xml",
         "tag": "macro", "label": "自由時報政治"},
        # ── 國際財經（英文，search-based，不用 topic ID） ─────────
        {"url": "https://news.google.com/rss/search?q=world+business+economy+when:1d&hl=en-US&gl=US&ceid=US:en",
         "tag": "intl",  "label": "Google World Business"},
        # ── 地緣政治 / 戰爭 ─────────────────────────────────────
        {"url": "https://news.google.com/rss/search?q=geopolitics+OR+war+OR+conflict+when:1d&hl=en-US&gl=US&ceid=US:en",
         "tag": "geo",   "label": "地緣政治"},
        # ── 亞洲局勢 ───────────────────────────────────────────
        {"url": "https://news.google.com/rss/search?q=Asia+economy+OR+China+trade+OR+Japan+economy+when:1d&hl=en-US&gl=US&ceid=US:en",
         "tag": "asia",  "label": "亞洲局勢"},
    ]

    HEADERS: dict = {
        "User-Agent": "Mozilla/5.0 (compatible; TradingDashboard/1.0)"
    }

    def __init__(self, max_per_feed: int = 3):
        self.max_per_feed = max_per_feed

    # ── 公開介面 ───────────────────────────────────────────────

    def fetch(self, limit: int = 20) -> list:
        """並行抓取所有 RSS Feed，合併後依時間降序排序。失敗時回傳靜態資料。"""
        all_news: list = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
            futures = [ex.submit(self._parse_feed, feed, self.max_per_feed) for feed in self.RSS_FEEDS]
            for f in concurrent.futures.as_completed(futures):
                all_news.extend(f.result())

        if not all_news:
            return self._get_fallback()

        # 去重（相同標題前 20 字）
        seen:   set  = set()
        unique: list = []
        for n in all_news:
            key = n["title"][:20]
            if key not in seen:
                seen.add(key)
                unique.append(n)

        unique.sort(key=lambda n: n.get("pub_iso") or "0000-01-01T00:00", reverse=True)
        return unique[:limit]

    # ── 內部方法 ───────────────────────────────────────────────

    def _parse_feed(self, feed_cfg: dict, max_items: int = 4) -> list:
        """解析單一 RSS Feed，回傳新聞列表。"""
        import requests
        items: list = []
        try:
            r    = requests.get(feed_cfg["url"], headers=self.HEADERS, timeout=8)
            root = ET.fromstring(r.content)

            for item in root.iter("item"):
                title_el = item.find("title")
                date_el  = item.find("pubDate")
                link_el  = item.find("link")
                if title_el is None:
                    continue

                title = (title_el.text or "").strip()
                if len(title) < 8:
                    continue

                time_str = "--:--"
                pub_iso  = ""
                try:
                    from email.utils import parsedate_to_datetime
                    pub_dt    = parsedate_to_datetime(date_el.text)
                    tw_offset = datetime.timezone(datetime.timedelta(hours=8))
                    pub_tw    = pub_dt.astimezone(tw_offset)
                    time_str  = pub_tw.strftime("%H:%M")
                    pub_iso   = pub_tw.isoformat()
                except Exception:
                    pass

                items.append({
                    "time":    time_str,
                    "pub_iso": pub_iso,
                    "tag":     feed_cfg["tag"],
                    "title":   title[:60],
                    "source":  feed_cfg["label"],
                    "link":    link_el.text if link_el is not None else "",
                })
                if len(items) >= max_items:
                    break
        except Exception as e:
            logger.warning("RSS 抓取失敗 %s: %s", feed_cfg['url'][:50], e)
        return items

    # ── 情緒分析 ──────────────────────────────────────────────

    # 利多／利空關鍵字
    BULLISH_WORDS: list = [
        "獲利", "盈餘", "創高", "突破", "大漲", "漲停", "強勁", "成長",
        "利多", "看多", "買超", "外資買", "投信買", "上調", "升評", "受惠",
        "拿單", "搶單", "訂單", "法說", "配息", "配股", "庫藏股",
    ]
    BEARISH_WORDS: list = [
        "虧損", "虧損擴大", "衰退", "大跌", "跌停", "下跌", "利空", "看空",
        "賣超", "外資賣", "下調", "降評", "警示", "訴訟", "罰款", "違約",
        "下修", "財報不佳", "獲利衰退", "虧損季", "停產",
    ]

    def analyze_sentiment(self, stock_map: dict, limit: int = 30) -> list:
        """
        抓取新聞並分析哪些股票被提及為利多 / 利空。

        Args:
            stock_map: {代號: 名稱} 字典（來自 StockScanner.get_stock_map）
            limit:     最多取幾則新聞

        Returns:
            list of {code, name, sentiment, reason, title, source, link}
            sentiment: "利多" | "利空" | "中性"
        """
        news = self.fetch(limit=limit)
        results: list = []

        # 建立反查表：名稱 / 代號 → code
        name_to_code: dict = {}
        for code, name in stock_map.items():
            name_to_code[name]  = code
            name_to_code[code]  = code

        for item in news:
            title = item["title"]

            # 找出標題中提到的股票
            mentioned_codes: list = []
            for keyword, code in name_to_code.items():
                if len(keyword) >= 2 and keyword in title:
                    if code not in mentioned_codes:
                        mentioned_codes.append(code)

            if not mentioned_codes:
                continue

            # 判斷情緒
            bull_hits = [w for w in self.BULLISH_WORDS if w in title]
            bear_hits = [w for w in self.BEARISH_WORDS if w in title]

            if bull_hits and not bear_hits:
                sentiment = "利多"
                reason    = "、".join(bull_hits[:3])
            elif bear_hits and not bull_hits:
                sentiment = "利空"
                reason    = "、".join(bear_hits[:3])
            elif bull_hits and bear_hits:
                sentiment = "中性"
                reason    = f"利多:{bull_hits[0]} 利空:{bear_hits[0]}"
            else:
                continue   # 無明確情緒則略過

            for code in mentioned_codes:
                results.append({
                    "code":      code,
                    "name":      stock_map.get(code, code),
                    "sentiment": sentiment,
                    "reason":    reason,
                    "title":     title,
                    "source":    item.get("source", ""),
                    "link":      item.get("link", ""),
                    "time":      item.get("time", "--:--"),
                })

        # 依利多優先、利空其次排序
        order = {"利多": 0, "利空": 1, "中性": 2}
        results.sort(key=lambda x: order.get(x["sentiment"], 3))
        return results

    # ── AI 情緒分析（Groq） ────────────────────────────────────

    def analyze_sentiment_ai(self, limit: int = 20) -> Optional[dict]:
        """
        使用 Groq API 分析最新新聞的整體市場情緒。
        若 Groq 不可用，則回傳 None（呼叫端應 fallback 至 keyword 分析）。

        Returns:
            {mood, confidence, themes, summary} 或 None
        """
        from trading.groq_client import GroqClient
        client = GroqClient()
        if not client.is_available():
            return None
        news = self.fetch(limit=limit)
        titles = [n["title"] for n in news if n.get("title")]
        if not titles:
            return None
        return client.analyze_news_batch(titles)

    def _get_fallback(self) -> list:
        """RSS 全部失敗時的靜態 fallback。"""
        return []
