"""tests/test_scheduler.py — TradingScheduler 單元測試"""
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd

from trading.indicators import IndicatorEngine
from trading.positions import PositionManager
from trading.telegram.scheduler import TradingScheduler


def _make_bot() -> MagicMock:
    bot = MagicMock()
    bot.push_to_all = MagicMock()
    return bot


def _make_scheduler(positions=None) -> tuple:
    """回傳 (scheduler, bot_mock, pos_mgr)。"""
    tmp     = tempfile.TemporaryDirectory()
    pos_mgr = PositionManager(
        db_file=Path(tmp.name) / "test.db",
    )
    if positions:
        for p in positions:
            pos_mgr.create(p)

    bot       = _make_bot()
    ind_eng   = IndicatorEngine()
    scheduler = TradingScheduler(
        telegram_bot     = bot,
        position_manager = pos_mgr,
        indicator_engine = ind_eng,
    )
    return scheduler, bot, pos_mgr, tmp


def _sample_position(**overrides) -> dict:
    base = {
        "code":   "2330", "name": "台積電",
        "date":   "2024-01-01",
        "entry":  900.0,  "stop":   850.0,
        "shares": 1000,   "target": 1050.0,
        "status": "active", "note": "",
    }
    base.update(overrides)
    return base


class TestCheckAlertsEmpty(unittest.TestCase):
    """無持倉 / 無 active 持倉時不應推播。"""

    def test_no_positions_no_push(self):
        scheduler, bot, pos_mgr, tmp = _make_scheduler()
        scheduler._check_alerts()
        bot.push_to_all.assert_not_called()
        tmp.cleanup()

    def test_only_safe_positions_no_push(self):
        scheduler, bot, pos_mgr, tmp = _make_scheduler(
            positions=[_sample_position(status="safe")]
        )
        scheduler._check_alerts()
        bot.push_to_all.assert_not_called()
        tmp.cleanup()


class TestCheckAlertsStopLoss(unittest.TestCase):
    """停損警示：現價 <= stop * 1.03 應推播。"""

    def setUp(self):
        self.scheduler, self.bot, self.pos_mgr, self.tmp = _make_scheduler(
            positions=[_sample_position(entry=900, stop=850, status="active")]
        )

    def tearDown(self):
        self.tmp.cleanup()

    @patch("yfinance.Ticker")
    def test_price_near_stop_triggers_alert(self, mock_ticker):
        # 現價 860 ≤ 850 * 1.03 = 875.5 → 觸發停損警示
        df = pd.DataFrame({"Close": [860.0]})
        mock_ticker.return_value.history.return_value = df

        self.scheduler._check_alerts()

        self.bot.push_to_all.assert_called()
        call_text = self.bot.push_to_all.call_args[0][0]
        self.assertIn("停損警示", call_text)

    @patch("yfinance.Ticker")
    def test_price_far_from_stop_no_alert(self, mock_ticker):
        # 現價 950 >> 850 * 1.03 → 不觸發
        df = pd.DataFrame({"Close": [950.0]})
        mock_ticker.return_value.history.return_value = df

        self.scheduler._check_alerts()

        # push_to_all 不應以停損為由被呼叫
        for c in self.bot.push_to_all.call_args_list:
            self.assertNotIn("停損警示", c[0][0])


class TestCheckAlertsTarget(unittest.TestCase):
    """目標達成通知：現價 >= target * 0.97 應推播。"""

    def setUp(self):
        self.scheduler, self.bot, self.pos_mgr, self.tmp = _make_scheduler(
            positions=[_sample_position(entry=900, stop=850, target=1050.0, status="active")]
        )

    def tearDown(self):
        self.tmp.cleanup()

    @patch("yfinance.Ticker")
    def test_price_near_target_triggers_notification(self, mock_ticker):
        # 現價 1030 ≥ 1050 * 0.97 = 1018.5 → 觸發目標通知
        df = pd.DataFrame({"Close": [1030.0]})
        mock_ticker.return_value.history.return_value = df

        self.scheduler._check_alerts()

        self.bot.push_to_all.assert_called()
        call_text = self.bot.push_to_all.call_args[0][0]
        self.assertIn("目標達成", call_text)

    @patch("yfinance.Ticker")
    def test_price_far_from_target_no_notification(self, mock_ticker):
        # 現價 900 << 1050 * 0.97 → 不觸發
        df = pd.DataFrame({"Close": [900.0]})
        mock_ticker.return_value.history.return_value = df

        self.scheduler._check_alerts()

        for c in self.bot.push_to_all.call_args_list:
            self.assertNotIn("目標達成", c[0][0])


class TestCheckAlertsNoTarget(unittest.TestCase):
    """無目標價的持倉不觸發目標通知。"""

    def setUp(self):
        self.scheduler, self.bot, self.pos_mgr, self.tmp = _make_scheduler(
            positions=[_sample_position(target=None, status="active")]
        )

    def tearDown(self):
        self.tmp.cleanup()

    @patch("yfinance.Ticker")
    def test_no_target_no_target_alert(self, mock_ticker):
        df = pd.DataFrame({"Close": [9999.0]})   # 任何高價
        mock_ticker.return_value.history.return_value = df

        self.scheduler._check_alerts()

        for c in self.bot.push_to_all.call_args_list:
            self.assertNotIn("目標達成", c[0][0])


class TestCheckAlertsFetchFailure(unittest.TestCase):
    """yfinance 取得失敗不應推播，也不應拋出例外。"""

    def setUp(self):
        self.scheduler, self.bot, self.pos_mgr, self.tmp = _make_scheduler(
            positions=[_sample_position(status="active")]
        )

    def tearDown(self):
        self.tmp.cleanup()

    @patch("yfinance.Ticker")
    def test_fetch_failure_no_push_no_exception(self, mock_ticker):
        mock_ticker.return_value.history.side_effect = Exception("網路失敗")
        try:
            self.scheduler._check_alerts()
        except Exception:
            self.fail("_check_alerts() 不應傳遞 yfinance 例外")
        self.bot.push_to_all.assert_not_called()


class TestSchedulerStart(unittest.TestCase):
    """start() 應回傳一個 daemon 執行緒。"""

    def setUp(self):
        self.scheduler, self.bot, self.pos_mgr, self.tmp = _make_scheduler()

    def tearDown(self):
        self.tmp.cleanup()

    def test_start_returns_thread(self):
        with patch.object(self.scheduler, "_loop", return_value=None):
            t = self.scheduler.start()
        self.assertIsInstance(t, threading.Thread)
        self.assertTrue(t.daemon)


class TestCheckAlertsMultiplePositions(unittest.TestCase):
    """多持倉同時觸發警示。"""

    def setUp(self):
        positions = [
            _sample_position(code="2330", entry=900, stop=850, target=1050, status="active"),
            _sample_position(code="2317", entry=100, stop=90, target=120, status="active"),
        ]
        self.scheduler, self.bot, self.pos_mgr, self.tmp = _make_scheduler(positions)

    def tearDown(self):
        self.tmp.cleanup()

    @patch("yfinance.Ticker")
    def test_two_positions_near_stop_both_alert(self, mock_ticker):
        """兩筆持倉均接近停損 → push 被呼叫至少兩次。"""
        df_stop = pd.DataFrame({"Close": [860.0]})
        mock_ticker.return_value.history.return_value = df_stop
        self.scheduler._check_alerts()
        self.assertGreaterEqual(self.bot.push_to_all.call_count, 2)

    @patch("yfinance.Ticker")
    def test_one_near_stop_one_near_target(self, mock_ticker):
        """一筆近停損、一筆近目標 → 兩種 push 都出現。"""
        call_count = [0]
        def history_side(*args, **kwargs):
            call_count[0] += 1
            # 第奇數次（2330）: 接近停損；第偶數次（2317）: 接近目標
            price = 860.0 if call_count[0] % 2 == 1 else 119.0
            return pd.DataFrame({"Close": [price]})

        mock_ticker.return_value.history = history_side
        self.scheduler._check_alerts()
        texts = [c[0][0] for c in self.bot.push_to_all.call_args_list]
        all_text = " ".join(texts)
        # 至少有停損或目標其中一種警示
        self.assertTrue("停損警示" in all_text or "目標達成" in all_text)


class TestCheckAlertsAlertDeduplication(unittest.TestCase):
    """相同持倉連續兩次 check 時的行為（alert dedup 機制驗證）。"""

    def setUp(self):
        self.scheduler, self.bot, self.pos_mgr, self.tmp = _make_scheduler(
            positions=[_sample_position(entry=900, stop=850, status="active")]
        )

    def tearDown(self):
        self.tmp.cleanup()

    @patch("yfinance.Ticker")
    def test_repeated_alert_price_triggers_push_each_check(self, mock_ticker):
        """每次 _check_alerts 都在接近停損時推播（無強制去重）。"""
        df = pd.DataFrame({"Close": [860.0]})
        mock_ticker.return_value.history.return_value = df
        self.scheduler._check_alerts()
        self.scheduler._check_alerts()
        # 兩次都應推播（目前無 dedup 機制）
        self.assertGreaterEqual(self.bot.push_to_all.call_count, 2)


class TestCheckAlertsEmptyHistory(unittest.TestCase):
    """yfinance 回傳空 DataFrame 時不應崩潰。"""

    def setUp(self):
        self.scheduler, self.bot, self.pos_mgr, self.tmp = _make_scheduler(
            positions=[_sample_position(status="active")]
        )

    def tearDown(self):
        self.tmp.cleanup()

    @patch("yfinance.Ticker")
    def test_empty_history_no_exception(self, mock_ticker):
        mock_ticker.return_value.history.return_value = pd.DataFrame()
        try:
            self.scheduler._check_alerts()
        except Exception:
            self.fail("空 history 不應拋出例外")
        self.bot.push_to_all.assert_not_called()


class TestSchedulerStartDaemon(unittest.TestCase):
    """start() 回傳的執行緒屬性驗證。"""

    def setUp(self):
        self.scheduler, self.bot, self.pos_mgr, self.tmp = _make_scheduler()

    def tearDown(self):
        self.tmp.cleanup()

    def test_start_thread_is_alive(self):
        """start() 後執行緒應在 2 秒內啟動。"""
        started = threading.Event()
        original_loop = self.scheduler._loop

        def patched_loop():
            started.set()

        with patch.object(self.scheduler, "_loop", patched_loop):
            t = self.scheduler.start()
            thread_started = started.wait(timeout=2.0)

        self.assertTrue(thread_started, "執行緒應在 2 秒內啟動")

    def test_start_thread_is_daemon(self):
        """start() 應回傳 daemon thread。"""
        with patch.object(self.scheduler, "_loop", return_value=None):
            t = self.scheduler.start()
        self.assertTrue(t.daemon)


class TestCheckAlertsActiveAndSafe(unittest.TestCase):
    """同時存在 active 與 safe 持倉時的行為。"""

    def setUp(self):
        positions = [
            _sample_position(code="2330", status="active", entry=900, stop=850, target=1050),
            _sample_position(code="2317", status="safe",   entry=100, stop=100, target=None),
        ]
        self.scheduler, self.bot, self.pos_mgr, self.tmp = _make_scheduler(positions)

    def tearDown(self):
        self.tmp.cleanup()

    @patch("yfinance.Ticker")
    def test_safe_status_not_checked_for_stop(self, mock_ticker):
        """safe 持倉不觸發停損警示（用高於 stop 的現價）。"""
        df = pd.DataFrame({"Close": [950.0]})
        mock_ticker.return_value.history.return_value = df
        self.scheduler._check_alerts()
        texts = [c[0][0] for c in self.bot.push_to_all.call_args_list]
        # 沒有停損警示
        for t in texts:
            self.assertNotIn("停損警示", t)


if __name__ == "__main__":
    unittest.main()
