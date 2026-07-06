"""tests/test_news.py — NewsAggregator 單元測試"""
import unittest
from unittest.mock import MagicMock, patch

from trading.news import NewsAggregator


def _make_rss_xml(items: list) -> bytes:
    """產生最小 RSS XML，items 為 (title, pubDate) tuple 列表。"""
    item_xml = ""
    for title, pub_date in items:
        item_xml += f"""
        <item>
            <title>{title}</title>
            <pubDate>{pub_date}</pubDate>
            <link>https://example.com/news</link>
        </item>"""
    return f"""<?xml version="1.0"?>
    <rss version="2.0"><channel>{item_xml}</channel></rss>""".encode("utf-8")


SAMPLE_PUBDATE = "Mon, 01 Jan 2024 08:00:00 +0800"
LATE_PUBDATE   = "Mon, 01 Jan 2024 14:30:00 +0800"
EARLY_PUBDATE  = "Mon, 01 Jan 2024 06:00:00 +0800"


class TestNewsAggregatorFetch(unittest.TestCase):
    """fetch() 整合行為。"""

    def setUp(self):
        self.agg = NewsAggregator(max_per_feed=3)

    @patch("requests.get")
    def test_fetch_returns_list(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.content = _make_rss_xml([
            ("台積電創新高，法人買超", SAMPLE_PUBDATE),
            ("聯準會維持利率不變",    SAMPLE_PUBDATE),
        ])
        mock_get.return_value = mock_resp
        result = self.agg.fetch()
        self.assertIsInstance(result, list)

    @patch("requests.get")
    def test_fetch_deduplicates_same_title(self, mock_get):
        # 同一則新聞出現在兩個 feed 中 → 只保留一筆
        same_title = "相同標題的財經新聞XYZ"
        xml = _make_rss_xml([(same_title, SAMPLE_PUBDATE)])
        mock_resp = MagicMock()
        mock_resp.content = xml
        mock_get.return_value = mock_resp

        # 兩個 feed 都回傳同一則新聞
        agg    = NewsAggregator(max_per_feed=5)
        result = agg.fetch(limit=100)
        titles = [n["title"] for n in result]
        # 前 20 字元相同的 title 應只出現一次
        prefix = same_title[:20]
        count  = sum(1 for t in titles if t[:20] == prefix)
        self.assertLessEqual(count, 1)

    @patch("requests.get")
    def test_fetch_sorted_by_time_descending(self, mock_get):
        def side_effect(url, **kwargs):
            resp = MagicMock()
            if "台股" in url:
                resp.content = _make_rss_xml([("台股新聞早盤（14:30）",    LATE_PUBDATE)])
            elif "半導體" in url:
                resp.content = _make_rss_xml([("半導體新聞早盤（06:00）", EARLY_PUBDATE)])
            else:
                resp.content = _make_rss_xml([])
            return resp
        mock_get.side_effect = side_effect

        result = self.agg.fetch()
        if len(result) >= 2:
            times = [n["time"] for n in result if n["time"] != "--:--"]
            self.assertEqual(times, sorted(times, reverse=True))

    @patch("requests.get")
    def test_fetch_returns_fallback_when_all_fail(self, mock_get):
        mock_get.side_effect = Exception("連線失敗")
        result = self.agg.fetch()
        # fallback 為空列表（_get_fallback 回傳 []）
        self.assertIsInstance(result, list)

    @patch("requests.get")
    def test_fetch_respects_limit(self, mock_get):
        xml = _make_rss_xml([(f"新聞標題第{i}則財金報導", SAMPLE_PUBDATE) for i in range(10)])
        mock_resp = MagicMock()
        mock_resp.content = xml
        mock_get.return_value = mock_resp

        result = self.agg.fetch(limit=5)
        self.assertLessEqual(len(result), 5)


class TestParseFeed(unittest.TestCase):
    """_parse_feed() 單一 feed 解析。"""

    def setUp(self):
        self.agg      = NewsAggregator()
        self.feed_cfg = {"url": "https://example.com/rss", "tag": "tw", "label": "測試來源"}

    @patch("requests.get")
    def test_parse_skips_titles_shorter_than_8_chars(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.content = _make_rss_xml([
            ("短標題", SAMPLE_PUBDATE),         # 4 字，應跳過
            ("這是一則超過八個字的正式新聞標題",  SAMPLE_PUBDATE),  # 合法
        ])
        mock_get.return_value = mock_resp
        result = self.agg._parse_feed(self.feed_cfg, max_items=5)
        self.assertEqual(len(result), 1)
        self.assertGreaterEqual(len(result[0]["title"]), 8)

    @patch("requests.get")
    def test_parse_respects_max_items(self, mock_get):
        items = [(f"合法的財金新聞標題第{i}則", SAMPLE_PUBDATE) for i in range(10)]
        mock_resp = MagicMock()
        mock_resp.content = _make_rss_xml(items)
        mock_get.return_value = mock_resp
        result = self.agg._parse_feed(self.feed_cfg, max_items=3)
        self.assertLessEqual(len(result), 3)

    @patch("requests.get")
    def test_parse_returns_empty_on_exception(self, mock_get):
        mock_get.side_effect = Exception("逾時")
        result = self.agg._parse_feed(self.feed_cfg)
        self.assertEqual(result, [])

    @patch("requests.get")
    def test_parse_item_has_required_keys(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.content = _make_rss_xml([("合法財金新聞標題夠長的一則", SAMPLE_PUBDATE)])
        mock_get.return_value = mock_resp
        result = self.agg._parse_feed(self.feed_cfg)
        if result:
            for key in ("time", "tag", "title", "source", "link"):
                self.assertIn(key, result[0])

    @patch("requests.get")
    def test_parse_tag_matches_feed_config(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.content = _make_rss_xml([("合法財金新聞標題夠長版本001", SAMPLE_PUBDATE)])
        mock_get.return_value = mock_resp
        result = self.agg._parse_feed(self.feed_cfg)
        if result:
            self.assertEqual(result[0]["tag"], "tw")

    def test_xxe_payload_rejected_by_defusedxml(self):
        """確認 defusedxml 拒絕 XXE payload（不會讀取系統檔案）。"""
        import defusedxml.ElementTree as dET
        xxe_payload = b"""<?xml version="1.0"?>
<!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>
<rss><channel><item><title>&xxe;</title></item></channel></rss>"""
        with self.assertRaises(Exception):
            dET.fromstring(xxe_payload)


class TestAnalyzeSentiment(unittest.TestCase):
    """analyze_sentiment() 情緒分析測試。"""

    def setUp(self):
        self.agg = NewsAggregator()
        self.stock_map = {"2330": "台積電", "2317": "鴻海", "2454": "聯發科"}

    def _mock_fetch(self, news_list):
        """回傳指定新聞列表的 mock patch。"""
        from unittest.mock import patch
        return patch.object(self.agg, "fetch", return_value=news_list)

    def test_returns_list(self):
        with self._mock_fetch([]):
            result = self.agg.analyze_sentiment(self.stock_map)
        self.assertIsInstance(result, list)

    def test_bullish_detection(self):
        news = [{"title": "台積電獲利大幅成長，法人看多", "source": "test", "link": "", "time": "10:00", "tag": "tw"}]
        with self._mock_fetch(news):
            result = self.agg.analyze_sentiment(self.stock_map)
        bullish = [r for r in result if r["code"] == "2330" and r["sentiment"] == "利多"]
        self.assertTrue(len(bullish) >= 1)

    def test_bearish_detection(self):
        news = [{"title": "鴻海遭外資賣超，業績衰退疑慮", "source": "test", "link": "", "time": "09:00", "tag": "tw"}]
        with self._mock_fetch(news):
            result = self.agg.analyze_sentiment(self.stock_map)
        bearish = [r for r in result if r["code"] == "2317" and r["sentiment"] == "利空"]
        self.assertTrue(len(bearish) >= 1)

    def test_no_match_if_no_keyword(self):
        news = [{"title": "今日天氣晴朗，出門記得帶傘", "source": "test", "link": "", "time": "08:00", "tag": "tw"}]
        with self._mock_fetch(news):
            result = self.agg.analyze_sentiment(self.stock_map)
        # 沒有股票名稱提到 → 應為空
        self.assertEqual(result, [])

    def test_result_has_required_keys(self):
        news = [{"title": "聯發科營收成長，法人買超", "source": "測試", "link": "https://example.com", "time": "11:00", "tag": "tw"}]
        with self._mock_fetch(news):
            result = self.agg.analyze_sentiment(self.stock_map)
        if result:
            for key in ("code", "name", "sentiment", "reason", "title", "source", "link"):
                self.assertIn(key, result[0])

    def test_bullish_sorted_before_bearish(self):
        news = [
            {"title": "鴻海虧損擴大，下調評等", "source": "test", "link": "", "time": "09:00", "tag": "tw"},
            {"title": "台積電獲利成長，外資買超", "source": "test", "link": "", "time": "10:00", "tag": "tw"},
        ]
        with self._mock_fetch(news):
            result = self.agg.analyze_sentiment(self.stock_map)
        if len(result) >= 2:
            sentiments = [r["sentiment"] for r in result]
            order = {"利多": 0, "利空": 1, "中性": 2}
            ordered = sorted(sentiments, key=lambda s: order.get(s, 3))
            self.assertEqual(sentiments, ordered)

    def test_empty_stock_map_returns_empty(self):
        news = [{"title": "台積電獲利成長，外資買超", "source": "test", "link": "", "time": "10:00", "tag": "tw"}]
        with self._mock_fetch(news):
            result = self.agg.analyze_sentiment({})
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
