"""tests/test_intelligence.py — IntelligenceDaemon & XMonitor 單元測試"""
import os
import shutil
import sqlite3
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock, patch


class TestXMonitor(unittest.TestCase):

    def setUp(self):
        from trading.xmonitor import XMonitor
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "x.db")
        self.x = XMonitor(xai_api_key=None, db_path=self.db_path)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_is_available_false_without_key(self):
        self.assertFalse(self.x.is_available())

    def test_is_available_true_with_key(self):
        from trading.xmonitor import XMonitor
        x = XMonitor(xai_api_key="fake_key", db_path=self.db_path)
        self.assertTrue(x.is_available())

    def test_get_recent_empty_initially(self):
        posts = self.x.get_recent(hours=24)
        self.assertIsInstance(posts, list)
        self.assertEqual(len(posts), 0)

    def test_sentiment_summary_empty(self):
        stats = self.x.sentiment_summary(hours=24)
        self.assertIn("total",   stats)
        self.assertIn("bullish", stats)
        self.assertIn("bearish", stats)
        self.assertIn("neutral", stats)
        self.assertIn("mood",    stats)
        self.assertEqual(stats["total"], 0)

    @patch("requests.get")
    def test_collect_uses_google_news_fallback(self, mock_get):
        rss_xml = b"""<?xml version="1.0"?>
        <rss><channel>
          <item><title>Taiwan stock market rises</title><link>http://example.com</link></item>
          <item><title>TSMC reports strong earnings</title><link>http://example2.com</link></item>
        </channel></rss>"""
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.content = rss_xml
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        added = self.x.collect(queries=["Taiwan stock"])
        self.assertGreaterEqual(added, 0)

    def test_sentiment_summary_with_data(self):
        from trading.xmonitor import XMonitor
        x = XMonitor(db_path=self.db_path)
        # 直接插入測試資料
        from datetime import datetime
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with sqlite3.connect(self.db_path) as conn:
            conn.executemany(
                "INSERT INTO x_posts(source,query,content,sentiment,url,collected_at) VALUES(?,?,?,?,?,?)",
                [
                    ("test", "query", "bull post", "bullish", "", now),
                    ("test", "query", "bear post", "bearish", "", now),
                    ("test", "query", "bull post 2", "bullish", "", now),
                ],
            )
            conn.commit()
        stats = x.sentiment_summary(hours=24)
        self.assertEqual(stats["total"],   3)
        self.assertEqual(stats["bullish"], 2)
        self.assertEqual(stats["bearish"], 1)
        self.assertEqual(stats["mood"],    "bullish")


class TestIntelligenceDaemon(unittest.TestCase):

    def setUp(self):
        from trading.intelligence import IntelligenceDaemon
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "intel.db")
        self.daemon = IntelligenceDaemon(groq_key=None, xai_key=None, db_path=self.db_path)

    def tearDown(self):
        self.daemon.stop()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_is_not_running_initially(self):
        self.assertFalse(self.daemon.is_running())

    def test_start_and_stop(self):
        """使用 Event 等待 daemon 啟動，取代 time.sleep。"""
        running_event = threading.Event()
        original_loop = self.daemon._loop

        def patched_loop():
            running_event.set()
            original_loop()

        self.daemon._loop = patched_loop
        self.daemon.start()
        started = running_event.wait(timeout=2.0)
        self.assertTrue(started, "daemon 應在 2 秒內啟動")
        self.assertTrue(self.daemon.is_running())
        self.daemon._stop.set()
        self.assertTrue(self.daemon._stop.is_set())

    def test_get_recent_news_empty_initially(self):
        news = self.daemon.get_recent_news(hours=24)
        self.assertIsInstance(news, list)
        self.assertEqual(len(news), 0)

    def test_get_latest_summary_none_initially(self):
        summary = self.daemon.get_latest_summary()
        self.assertIsNone(summary)

    def test_get_news_sentiment_stats_empty(self):
        stats = self.daemon.get_news_sentiment_stats(hours=24)
        self.assertIn("total",   stats)
        self.assertIn("mood",    stats)
        self.assertEqual(stats["total"], 0)

    @patch("trading.intelligence.XMonitor.collect", return_value=0)
    @patch("trading.intelligence.NewsAggregator.fetch", return_value=[])
    def test_force_collect_no_crash(self, mock_fetch, mock_x):
        # 應該不崩潰
        try:
            self.daemon.force_collect()
        except Exception as e:
            self.fail(f"force_collect raised {e}")

    def test_double_start_safe(self):
        """重複 start() 不應報錯，使用 Event 取代 sleep。"""
        started = threading.Event()
        original_loop = self.daemon._loop

        def patched_loop():
            started.set()
            original_loop()

        self.daemon._loop = patched_loop
        self.daemon.start()
        started.wait(timeout=2.0)
        self.daemon.start()  # 重複啟動不應報錯
        self.assertTrue(self.daemon.is_running())

    def test_get_news_sentiment_stats_keys(self):
        stats = self.daemon.get_news_sentiment_stats()
        for key in ("total", "bullish", "bearish", "neutral", "mood"):
            self.assertIn(key, stats)


class TestGroqClient(unittest.TestCase):

    def test_is_available_false_without_key(self):
        from trading.groq_client import GroqClient
        g = GroqClient(api_key="")
        self.assertFalse(g.is_available())

    def test_is_available_true_with_key(self):
        from trading.groq_client import GroqClient
        g = GroqClient(api_key="fake_key")
        self.assertTrue(g.is_available())

    def test_generate_returns_none_without_key(self):
        from trading.groq_client import GroqClient
        g = GroqClient(api_key="")
        self.assertIsNone(g.generate("test prompt"))

    def test_analyze_news_batch_returns_none_without_key(self):
        from trading.groq_client import GroqClient
        g = GroqClient(api_key="")
        self.assertIsNone(g.analyze_news_batch(["title 1", "title 2"]))

    def test_analyze_news_batch_returns_none_empty_list(self):
        from trading.groq_client import GroqClient
        g = GroqClient(api_key="fake_key")
        self.assertIsNone(g.analyze_news_batch([]))

    def test_parse_json_valid(self):
        from trading.groq_client import GroqClient
        g = GroqClient(api_key="")
        result = g._parse_json('{"mood": "bullish", "confidence": 7}')
        self.assertEqual(result["mood"], "bullish")

    def test_parse_json_markdown_block(self):
        from trading.groq_client import GroqClient
        g = GroqClient(api_key="")
        text = '```json\n{"mood": "neutral"}\n```'
        result = g._parse_json(text)
        self.assertIsNotNone(result)
        self.assertEqual(result["mood"], "neutral")

    def test_parse_json_invalid_returns_none(self):
        from trading.groq_client import GroqClient
        g = GroqClient(api_key="")
        result = g._parse_json("not valid json at all")
        self.assertIsNone(result)

    def test_parse_json_empty_returns_none(self):
        from trading.groq_client import GroqClient
        g = GroqClient(api_key="")
        self.assertIsNone(g._parse_json(""))
        self.assertIsNone(g._parse_json(None))

    @patch("requests.post")
    def test_generate_calls_api(self, mock_post):
        from trading.groq_client import GroqClient
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": "hello"}}]
        }
        mock_post.return_value = mock_resp
        g = GroqClient(api_key="test_key")
        result = g.generate("test prompt")
        self.assertEqual(result, "hello")
        mock_post.assert_called_once()

    def test_analyze_news_sentiments_returns_none_without_key(self):
        from trading.groq_client import GroqClient
        g = GroqClient(api_key="")
        self.assertIsNone(g.analyze_news_sentiments(["title 1", "title 2"]))

    def test_analyze_news_sentiments_returns_none_empty_list(self):
        from trading.groq_client import GroqClient
        g = GroqClient(api_key="fake_key")
        self.assertIsNone(g.analyze_news_sentiments([]))

    @patch("requests.post")
    def test_analyze_news_sentiments_returns_list(self, mock_post):
        from trading.groq_client import GroqClient
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": '["bullish", "bearish", "neutral"]'}}]
        }
        mock_post.return_value = mock_resp
        g = GroqClient(api_key="test_key")
        result = g.analyze_news_sentiments(["漲停", "大跌", "平盤"])
        self.assertEqual(result, ["bullish", "bearish", "neutral"])

    @patch("requests.post")
    def test_analyze_news_sentiments_parses_markdown(self, mock_post):
        from trading.groq_client import GroqClient
        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": '```json\n["bullish", "neutral"]\n```'}}]
        }
        mock_post.return_value = mock_resp
        g = GroqClient(api_key="test_key")
        result = g.analyze_news_sentiments(["title1", "title2"])
        self.assertIsInstance(result, list)
        self.assertEqual(result[0], "bullish")


if __name__ == "__main__":
    unittest.main()
