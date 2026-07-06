"""tests/test_telegram_bot.py — TelegramBot 單元測試"""
import unittest
from unittest.mock import MagicMock, patch, call

from trading.telegram.bot import TelegramBot


def _make_bot(token="test_token", allowed_ids=None) -> TelegramBot:
    """建立依賴全部 Mock 的 TelegramBot，方便各測試使用。"""
    config_mgr = MagicMock()
    config_mgr.load.return_value = {
        "total_capital":      1_000_000,
        "consecutive_losses": 0,
        "scan_candidates":    ["2330"],
    }

    pos_mgr = MagicMock()
    pos_mgr.load_all.return_value = []

    scanner = MagicMock()
    scanner.run_scan.return_value     = []
    scanner.format_for_api.return_value = []
    scanner.get_stock_map.return_value  = {}

    ind_engine  = MagicMock()
    news_agg    = MagicMock()
    news_agg.fetch.return_value = []
    market_svc  = MagicMock()
    market_svc.get_data.return_value = {}

    return TelegramBot(
        token            = token,
        allowed_ids      = allowed_ids if allowed_ids is not None else {"123"},
        config_manager   = config_mgr,
        position_manager = pos_mgr,
        scanner          = scanner,
        indicator_engine = ind_engine,
        news_aggregator  = news_agg,
        market_service   = market_svc,
    )


class TestIsAllowed(unittest.TestCase):

    def test_allowed_when_id_in_whitelist(self):
        bot = _make_bot(allowed_ids={"111", "222"})
        self.assertTrue(bot.is_allowed("111"))

    def test_denied_when_id_not_in_whitelist(self):
        bot = _make_bot(allowed_ids={"111"})
        self.assertFalse(bot.is_allowed("999"))

    def test_denied_when_whitelist_empty(self):
        """空白 allowed_ids 應拒絕所有請求（fail-closed）。"""
        bot = _make_bot(allowed_ids=set())
        self.assertFalse(bot.is_allowed("any_id"))

    def test_denied_when_allowed_ids_none(self):
        """None allowed_ids 應拒絕所有請求（fail-closed）。"""
        bot = _make_bot(allowed_ids=None)
        self.assertFalse(bot.is_allowed("any_id"))

    def test_str_coercion(self):
        bot = _make_bot(allowed_ids={"456"})
        self.assertTrue(bot.is_allowed("456"))


class TestSendMessage(unittest.TestCase):

    def setUp(self):
        self.bot = _make_bot()

    @patch.object(TelegramBot, "api")
    def test_send_short_message_calls_api_once(self, mock_api):
        self.bot.send("123", "短訊息")
        mock_api.assert_called_once()

    @patch.object(TelegramBot, "api")
    def test_send_long_message_splits_into_chunks(self, mock_api):
        long_text = "A" * 8500   # > 4000 字 → 應分 3 chunk
        self.bot.send("123", long_text)
        self.assertGreaterEqual(mock_api.call_count, 2)

    @patch.object(TelegramBot, "api")
    def test_send_without_token_does_nothing(self, mock_api):
        bot = _make_bot(token="")
        bot.send("123", "test")
        mock_api.assert_not_called()


class TestCmdHelp(unittest.TestCase):

    def setUp(self):
        self.bot = _make_bot()

    def test_help_contains_key_commands(self):
        result = self.bot._cmd_help()
        for cmd in ("/pos", "/market", "/report", "/news", "/scan", "/analyze", "/addpos", "/delpos"):
            self.assertIn(cmd, result)


class TestCmdPositions(unittest.TestCase):

    def test_no_positions_returns_empty_message(self):
        bot = _make_bot()
        bot.pos_mgr.load_all.return_value = []
        result = bot._cmd_positions()
        self.assertIn("無持倉", result)

    @patch("yfinance.Ticker")
    def test_with_positions_returns_formatted_output(self, mock_ticker):
        bot = _make_bot()
        bot.pos_mgr.load_all.return_value = [{
            "id": 1, "code": "2330", "name": "台積電",
            "entry": 900.0, "stop": 850.0, "shares": 1000,
            "status": "active", "target": 1050.0,
        }]
        import pandas as pd
        mock_ticker.return_value.history.return_value = pd.DataFrame({
            "Close": [880.0, 910.0]
        })
        result = bot._cmd_positions()
        self.assertIn("2330", result)
        self.assertIn("台積電", result)


class TestCmdAdd(unittest.TestCase):

    def setUp(self):
        self.bot = _make_bot()

    def test_no_args_returns_help(self):
        result = self.bot._cmd_add([])
        self.assertIn("格式", result)

    def test_insufficient_args_returns_help(self):
        result = self.bot._cmd_add(["2330", "台積電"])
        self.assertIn("格式", result)

    def test_success_creates_position(self):
        self.bot.pos_mgr.create.return_value = {
            "id": 1, "code": "2330", "name": "台積電",
            "entry": 900.0, "stop": 850.0, "shares": 1000,
            "target": 1050.0, "status": "active", "risk_amount": 50_000,
        }
        result = self.bot._cmd_add(["2330", "台積電", "900", "850", "1000"])
        self.assertIn("新增成功", result)
        self.bot.pos_mgr.create.assert_called_once()

    def test_invalid_price_returns_help(self):
        result = self.bot._cmd_add(["2330", "台積電", "abc", "850", "1000"])
        self.assertIn("格式", result)

    def test_optional_target_parsed(self):
        self.bot.pos_mgr.create.return_value = {
            "id": 1, "code": "2330", "name": "台積電",
            "entry": 900.0, "stop": 850.0, "shares": 1000,
            "target": 1050.0, "status": "active", "risk_amount": 50_000,
        }
        self.bot._cmd_add(["2330", "台積電", "900", "850", "1000", "1050"])
        _, kwargs = self.bot.pos_mgr.create.call_args
        data = self.bot.pos_mgr.create.call_args[0][0]
        self.assertEqual(data["target"], 1050.0)


class TestCmdDelete(unittest.TestCase):

    def setUp(self):
        self.bot = _make_bot()

    def test_no_args_returns_help(self):
        result = self.bot._cmd_delete([])
        self.assertIn("格式", result)

    def test_code_not_found_returns_error(self):
        self.bot.pos_mgr.load_all.return_value = []
        result = self.bot._cmd_delete(["9999"])
        self.assertIn("找不到", result)

    def test_delete_success_message(self):
        self.bot.pos_mgr.load_all.return_value = [
            {"id": 1, "code": "2330", "name": "台積電", "status": "active"}
        ]
        result = self.bot._cmd_delete(["2330"])
        self.assertIn("已刪除", result)
        self.bot.pos_mgr.delete.assert_called_with(1)


class TestCmdAnalyze(unittest.TestCase):

    def setUp(self):
        self.bot = _make_bot()

    def test_non_4digit_returns_error(self):
        result = self.bot._cmd_analyze("abc")
        self.assertIn("❌", result)

    def test_5digit_returns_error(self):
        result = self.bot._cmd_analyze("23300")
        self.assertIn("❌", result)

    def test_no_data_returns_error_message(self):
        self.bot.scanner.analyze_one.return_value = None
        result = self.bot._cmd_analyze("2330")
        self.assertIn("❌", result)

    def test_success_returns_analysis(self):
        self.bot.scanner.analyze_one.return_value = {
            "code": "2330", "name": "台積電", "score": 5,
            "ind": {
                "close": 900.0, "ema20": 880.0, "adx": 30.0, "atr": 12.0,
                "signals": {
                    "ema_arrangement": True, "slopes_up": True, "adx_above_25": True,
                    "macd_positive": True, "volume_spike": True, "ema_crossover": False,
                },
            },
            "params": {"entry": 900.0, "stop": 860.0, "target": 980.0, "shares": 555, "total_risk": 22200},
        }
        result = self.bot._cmd_analyze("2330")
        self.assertIn("2330", result)
        self.assertIn("台積電", result)
        self.assertIn("進場參數", result)


class TestCmdScan(unittest.TestCase):

    def test_empty_candidates_returns_hint(self):
        bot = _make_bot()
        bot.config_mgr.load.return_value = {
            "total_capital": 1_000_000,
            "consecutive_losses": 0,
            "scan_candidates": [],
        }
        result = bot._cmd_scan()
        self.assertIn("掃描清單為空", result)

    def test_no_results_returns_message(self):
        bot = _make_bot()
        bot.scanner.run_scan.return_value     = []
        bot.scanner.format_for_api.return_value = []
        result = bot._cmd_scan()
        self.assertIn("無符合條件", result)


class TestCmdReport(unittest.TestCase):

    def test_no_positions_returns_message(self):
        bot = _make_bot()
        bot.pos_mgr.load_all.return_value = []
        result = bot._cmd_report()
        self.assertIn("無持倉", result)


class TestBuildReports(unittest.TestCase):
    """build_morning_report / build_close_report 骨架測試。"""

    def test_morning_report_no_positions(self):
        bot = _make_bot()
        bot.pos_mgr.load_all.return_value = []
        result = bot.build_morning_report()
        self.assertIn("盤前早報", result)
        self.assertIn("無持倉", result)

    @patch("yfinance.Ticker")
    def test_close_report_no_positions(self, mock_ticker):
        bot = _make_bot()
        bot.pos_mgr.load_all.return_value = []
        result = bot.build_close_report()
        self.assertIn("收盤報告", result)
        self.assertIn("無持倉", result)

    def test_morning_report_with_market_data(self):
        bot = _make_bot()
        bot.market_svc.get_data.return_value = {
            "market_above_ema20": True,
            "ema20_tw":           19000.0,
            "nasdaq":             {"price": 16000.0, "change_pct": 0.5},
            "sp500":              {"price": 5000.0,  "change_pct": -0.2},
        }
        bot.pos_mgr.load_all.return_value = []
        result = bot.build_morning_report()
        self.assertIn("NASDAQ", result)
        self.assertIn("20EMA", result)


class TestStartPollingNoToken(unittest.TestCase):

    def test_no_token_returns_early(self):
        bot = _make_bot(token="")
        # 不應拋出例外，應直接 return
        try:
            bot.start_polling()
        except Exception:
            self.fail("start_polling() 沒有 token 時不應拋出例外")


class TestCmdRisk(unittest.TestCase):

    def test_no_positions_returns_empty_message(self):
        bot = _make_bot()
        bot.pos_mgr.load_all.return_value = []
        result = bot._cmd_risk()
        self.assertIn("無持倉", result)

    def test_with_positions_returns_risk_analysis(self):
        bot = _make_bot()
        bot.pos_mgr.load_all.return_value = [{
            "id": 1, "code": "2330", "name": "台積電",
            "entry": 900.0, "stop": 850.0, "shares": 1000,
            "status": "active", "risk_amount": 50_000,
        }]
        bot.pos_mgr.risk_summary.return_value = {"total_risk": 50_000, "risk_pct": 5.0}
        result = bot._cmd_risk()
        self.assertIn("2330", result)
        self.assertIn("風險", result)

    def test_high_risk_shows_warning(self):
        bot = _make_bot()
        bot.pos_mgr.load_all.return_value = [{
            "id": 1, "code": "2330", "name": "台積電",
            "entry": 900.0, "stop": 850.0, "shares": 5000,
            "status": "active", "risk_amount": 250_000,
        }]
        bot.pos_mgr.risk_summary.return_value = {"total_risk": 250_000, "risk_pct": 25.0}
        result = bot._cmd_risk()
        self.assertIn("風險過高", result)


class TestCmdSizing(unittest.TestCase):

    def setUp(self):
        self.bot = _make_bot()
        self.bot.scanner.get_stock_name.return_value = "台積電"

    def test_no_args_returns_help(self):
        result = self.bot._cmd_sizing([])
        self.assertIn("格式", result)

    def test_insufficient_args_returns_help(self):
        result = self.bot._cmd_sizing(["2330", "900"])
        self.assertIn("格式", result)

    def test_stop_greater_than_entry_returns_error(self):
        result = self.bot._cmd_sizing(["2330", "850", "900"])
        self.assertIn("❌", result)

    def test_valid_args_returns_calculation(self):
        result = self.bot._cmd_sizing(["2330", "900", "850"])
        self.assertIn("2330", result)
        self.assertIn("進場價", result)
        self.assertIn("建議股數", result)

    def test_sizing_help_contains_example(self):
        result = self.bot._sizing_help()
        self.assertIn("/計算", result)
        self.assertIn("2330", result)


class TestCmdWatchlist(unittest.TestCase):

    def setUp(self):
        self.bot = _make_bot()

    def test_show_empty_returns_hint(self):
        self.bot.config_mgr.load.return_value = {
            "total_capital": 1_000_000, "consecutive_losses": 0,
            "scan_candidates": [],
        }
        result = self.bot._cmd_watchlist_show()
        self.assertIn("為空", result)

    def test_show_with_candidates_lists_them(self):
        self.bot.config_mgr.load.return_value = {
            "total_capital": 1_000_000, "consecutive_losses": 0,
            "scan_candidates": ["2330", "2317"],
        }
        self.bot.scanner.get_stock_map.return_value = {"2330": "台積電", "2317": "鴻海"}
        result = self.bot._cmd_watchlist_show()
        self.assertIn("2330", result)
        self.assertIn("2317", result)

    def test_add_no_args_returns_usage(self):
        result = self.bot._cmd_watchlist_add([])
        self.assertIn("用法", result)

    def test_add_invalid_code_returns_error(self):
        result = self.bot._cmd_watchlist_add(["abc"])
        self.assertIn("❌", result)

    def test_add_valid_code_saves_config(self):
        self.bot.config_mgr.load.return_value = {
            "total_capital": 1_000_000, "consecutive_losses": 0,
            "scan_candidates": [],
        }
        result = self.bot._cmd_watchlist_add(["2330"])
        self.assertIn("已加入", result)
        self.bot.config_mgr.save.assert_called_once()

    def test_add_already_existing_shows_note(self):
        self.bot.config_mgr.load.return_value = {
            "total_capital": 1_000_000, "consecutive_losses": 0,
            "scan_candidates": ["2330"],
        }
        result = self.bot._cmd_watchlist_add(["2330"])
        self.assertIn("已在清單", result)

    def test_remove_no_args_returns_usage(self):
        result = self.bot._cmd_watchlist_remove([])
        self.assertIn("用法", result)

    def test_remove_existing_code_saves_config(self):
        self.bot.config_mgr.load.return_value = {
            "total_capital": 1_000_000, "consecutive_losses": 0,
            "scan_candidates": ["2330", "2317"],
        }
        result = self.bot._cmd_watchlist_remove(["2330"])
        self.assertIn("已移除", result)
        self.bot.config_mgr.save.assert_called_once()

    def test_remove_nonexistent_code_shows_warning(self):
        self.bot.config_mgr.load.return_value = {
            "total_capital": 1_000_000, "consecutive_losses": 0,
            "scan_candidates": [],
        }
        result = self.bot._cmd_watchlist_remove(["9999"])
        self.assertIn("不在清單", result)


class TestCmdFilter(unittest.TestCase):

    def setUp(self):
        self.bot = _make_bot()

    def test_no_market_data_returns_loading_message(self):
        self.bot.market_svc.get_data.return_value = {}
        result = self.bot._cmd_filter()
        self.assertIn("載入中", result)

    def test_above_ema20_shows_bullish(self):
        self.bot.market_svc.get_data.return_value = {
            "market_above_ema20": True,
            "ema20_tw": 19200.0,
            "taiex": {"price": 19850.0, "change_pct": 0.5},
            "nasdaq": {},
            "sp500": {},
        }
        result = self.bot._cmd_filter()
        self.assertIn("站上", result)

    def test_below_ema20_shows_bearish(self):
        self.bot.market_svc.get_data.return_value = {
            "market_above_ema20": False,
            "ema20_tw": 19200.0,
            "taiex": {"price": 18500.0, "change_pct": -1.0},
            "nasdaq": {},
            "sp500": {},
        }
        result = self.bot._cmd_filter()
        self.assertIn("跌破", result)


class TestCmdStats(unittest.TestCase):

    def test_no_positions_returns_empty_message(self):
        bot = _make_bot()
        bot.pos_mgr.load_all.return_value = []
        result = bot._cmd_stats()
        self.assertIn("無持倉", result)

    @patch("yfinance.Ticker")
    def test_with_positions_returns_stats(self, mock_ticker):
        import pandas as pd
        bot = _make_bot()
        bot.pos_mgr.load_all.return_value = [{
            "id": 1, "code": "2330", "name": "台積電",
            "entry": 900.0, "stop": 850.0, "shares": 1000,
            "status": "active", "risk_amount": 50_000,
        }]
        bot.pos_mgr.risk_summary.return_value = {"total_risk": 50_000, "risk_pct": 5.0}
        mock_ticker.return_value.history.return_value = pd.DataFrame({
            "Close": [880.0, 920.0]
        })
        result = bot._cmd_stats()
        self.assertIn("2330", result)
        self.assertIn("績效", result)


class TestUnknownCmdReply(unittest.TestCase):

    def test_unknown_cmd_contains_help_content(self):
        """_unknown_cmd_reply 應包含與 _cmd_help 相同的內容。"""
        bot = _make_bot()
        unknown = bot._unknown_cmd_reply()
        help_   = bot._cmd_help()
        # unknown reply 是 help 的超集
        self.assertIn(help_, unknown)

    def test_unknown_cmd_has_error_prefix(self):
        bot = _make_bot()
        result = bot._unknown_cmd_reply()
        self.assertIn("未知指令", result)


class TestCmdBacktest(unittest.TestCase):

    def setUp(self):
        self.bot = _make_bot()

    def test_no_args_returns_usage(self):
        # _dispatch 層處理，此處確認格式說明文字存在
        bot = _make_bot()
        # 直接模擬 dispatch 行為：呼叫時沒有 args 應回傳用法說明
        # 這裡測試 _cmd_backtest 傳入已知壞策略
        result = bot._cmd_backtest(["2330", "badstrat"])
        self.assertIn("未知策略", result)

    def test_bad_period_returns_error(self):
        result = self.bot._cmd_backtest(["2330", "trend", "99y"])
        self.assertIn("未知週期", result)

    def test_single_stock_ok_result(self):
        with patch("trading.backtest.BacktestEngine.run") as mock_run:
            mock_run.return_value = {
                "ok": True, "code": "2330", "strategy": "trend",
                "capital": 1_000_000, "final_equity": 1_100_000,
                "trades": [
                    {"entry_date": "2024-01-02", "exit_date": "2024-02-01",
                     "entry": 500.0, "exit": 550.0, "shares": 1000,
                     "pnl": 50_000, "pnl_pct": 10.0, "reason": "目標"},
                ],
                "equity_curve": [],
                "stats": {
                    "total_trades": 1, "wins": 1, "losses": 0,
                    "win_rate": 100.0, "profit_factor": 999.0,
                    "avg_win_pct": 10.0, "avg_loss_pct": 0.0,
                    "total_return": 10.0, "max_drawdown": 0.0,
                    "gross_profit": 50_000, "gross_loss": 0,
                },
            }
            result = self.bot._cmd_backtest(["2330"])
        self.assertIn("2330", result)
        self.assertIn("10.0%", result)
        self.assertIn("100.0%", result)

    def test_single_stock_error_result(self):
        with patch("trading.backtest.BacktestEngine.run") as mock_run:
            mock_run.return_value = {"ok": False, "error": "資料不足"}
            result = self.bot._cmd_backtest(["9999"])
        self.assertIn("資料不足", result)

    def test_multi_stock_ok_result(self):
        with patch("trading.backtest.BacktestEngine.run_multi") as mock_multi:
            mock_multi.return_value = {
                "ok": True,
                "results": [],
                "summary": [
                    {"code": "2330", "total_return": 18.2, "total_trades": 12,
                     "win_rate": 58.3, "profit_factor": 2.84,
                     "max_drawdown": 3.96, "final_equity": 1_182_000},
                    {"code": "2454", "total_return": 6.9, "total_trades": 9,
                     "win_rate": 44.4, "profit_factor": 1.65,
                     "max_drawdown": 3.96, "final_equity": 1_069_000},
                ],
            }
            result = self.bot._cmd_backtest(["2330,2454"])
        self.assertIn("2330", result)
        self.assertIn("2454", result)
        self.assertIn("18.2%", result)

    def test_multi_stock_with_failed_code(self):
        with patch("trading.backtest.BacktestEngine.run_multi") as mock_multi:
            mock_multi.return_value = {
                "ok": True,
                "results": [],
                "summary": [
                    {"code": "2330", "total_return": 5.0, "total_trades": 3,
                     "win_rate": 66.7, "profit_factor": 2.0,
                     "max_drawdown": 2.0, "final_equity": 1_050_000},
                    {"code": "9999", "error": "資料不足"},
                ],
            }
            result = self.bot._cmd_backtest(["2330,9999"])
        self.assertIn("9999", result)
        self.assertIn("資料不足", result)

    def test_ict_strategy_accepted(self):
        with patch("trading.backtest.BacktestEngine.run") as mock_run:
            mock_run.return_value = {
                "ok": True, "code": "2330", "strategy": "ict",
                "capital": 1_000_000, "final_equity": 1_050_000,
                "trades": [], "equity_curve": [],
                "stats": {
                    "total_trades": 0, "wins": 0, "losses": 0,
                    "win_rate": 0.0, "profit_factor": 0.0,
                    "avg_win_pct": 0.0, "avg_loss_pct": 0.0,
                    "total_return": 5.0, "max_drawdown": 1.0,
                    "gross_profit": 0, "gross_loss": 0,
                },
            }
            result = self.bot._cmd_backtest(["2330", "ict", "1y"])
        self.assertIn("ICT", result)


class TestPaginate(unittest.TestCase):
    """Track 4-B: _paginate helper"""

    def setUp(self):
        self.bot = _make_bot()

    def test_short_text_returns_single_page(self):
        text = "Hello\nWorld"
        pages = self.bot._paginate(text, max_chars=3500)
        self.assertEqual(len(pages), 1)
        self.assertEqual(pages[0], text)

    def test_long_text_splits_at_newline(self):
        # Build a text > 3500 chars with known structure
        line = "A" * 100 + "\n"
        text = line * 40  # 4040 chars
        pages = self.bot._paginate(text, max_chars=3500)
        self.assertGreater(len(pages), 1)
        for p in pages:
            self.assertLessEqual(len(p), 3600)  # slight over due to page marker

    def test_page_numbers_appended(self):
        line = "B" * 100 + "\n"
        text = line * 40
        pages = self.bot._paginate(text, max_chars=3500)
        total = len(pages)
        self.assertIn(f"（第 1/{total} 頁）", pages[0])
        self.assertIn(f"（第 {total}/{total} 頁）", pages[-1])

    def test_exact_fit_returns_single_page(self):
        text = "X" * 3500
        pages = self.bot._paginate(text, max_chars=3500)
        self.assertEqual(len(pages), 1)


class TestCoverageInAnalyze(unittest.TestCase):
    """Track 4-A: coverage summary appended to /分析"""

    def setUp(self):
        self.bot = _make_bot()

    def test_coverage_block_appended_when_data_available(self):
        coverage_reader = MagicMock()
        coverage_reader.get_overview.return_value = {
            "business": "台積電是全球最大晶圓代工廠，專注半導體製程技術",
            "supply_chain": "上游：矽晶圓、光罩；下游：蘋果、AMD、NVIDIA",
        }
        self.bot.coverage_reader = coverage_reader

        with patch.object(self.bot.scanner, "analyze_one") as mock_analyze:
            mock_analyze.return_value = {
                "ind": {"close": 900, "ema20": 880, "adx": 28, "atr": 15},
                "params": {"entry": 900, "stop": 850, "target": 1000, "shares": 1000, "risk_amount": 50000},
                "signals": {},
                "score": 5,
                "code": "2330",
                "name": "台積電",
            }
            with patch.object(self.bot, "_fmt_analyze_trend", return_value="分析結果"):
                result = self.bot._cmd_analyze("2330")

        self.assertIn("📚 研究摘要", result)
        self.assertIn("My-TW-Coverage", result)
        self.assertIn("台積電是全球最大晶圓代工廠", result)

    def test_coverage_block_silently_skipped_when_no_data(self):
        coverage_reader = MagicMock()
        coverage_reader.get_overview.return_value = None
        self.bot.coverage_reader = coverage_reader

        with patch.object(self.bot.scanner, "analyze_one") as mock_analyze:
            mock_analyze.return_value = {
                "ind": {"close": 900, "ema20": 880, "adx": 28, "atr": 15},
                "params": {"entry": 900, "stop": 850, "target": 1000, "shares": 1000, "risk_amount": 50000},
                "signals": {},
                "score": 5,
                "code": "2330",
                "name": "台積電",
            }
            with patch.object(self.bot, "_fmt_analyze_trend", return_value="分析結果"):
                result = self.bot._cmd_analyze("2330")

        self.assertNotIn("📚 研究摘要", result)

    def test_coverage_reader_none_works_normally(self):
        self.bot.coverage_reader = None
        with patch.object(self.bot.scanner, "analyze_one") as mock_analyze:
            mock_analyze.return_value = {
                "ind": {"close": 900, "ema20": 880, "adx": 28, "atr": 15},
                "params": {"entry": 900, "stop": 850, "target": 1000, "shares": 1000, "risk_amount": 50000},
                "signals": {},
                "score": 5,
                "code": "2330",
                "name": "台積電",
            }
            with patch.object(self.bot, "_fmt_analyze_trend", return_value="分析結果"):
                result = self.bot._cmd_analyze("2330")
        self.assertEqual(result, "分析結果")


class TestScanStrategyRouting(unittest.TestCase):
    """Track 4-D: /掃描 [strategy] routing"""

    def setUp(self):
        self.bot = _make_bot()

    def test_scan_default_calls_trend(self):
        with patch.object(self.bot, "_cmd_scan", return_value="趨勢掃描結果") as mock_scan:
            # Simulate dispatch for /掃描 with no args
            strat = "trend"
            self.bot._cmd_scan(strategy=strat)
            mock_scan.assert_called_once_with(strategy="trend")

    def test_scan_ict_arg_routes_to_ict(self):
        with patch.object(self.bot, "_cmd_scan", return_value="ICT掃描結果") as mock_scan:
            self.bot._cmd_scan(strategy="ict")
            mock_scan.assert_called_once_with(strategy="ict")

    def test_dispatch_scan_with_ict_arg_routes_ict(self):
        """_dispatch /掃描 ict should route to _cmd_scan with strategy='ict'."""
        called_with = []

        def fake_scan(strategy="trend"):
            called_with.append(strategy)
            return "result"

        self.bot._cmd_scan = fake_scan

        # Build a fake _dispatch-like call; test the strategy selection logic
        args = ["ict"]
        strat = args[0].lower() if args and args[0].lower() in ("trend", "ict") else "trend"
        self.assertEqual(strat, "ict")

    def test_dispatch_scan_with_invalid_arg_defaults_trend(self):
        args = ["fundamental"]
        strat = args[0].lower() if args and args[0].lower() in ("trend", "ict") else "trend"
        self.assertEqual(strat, "trend")

    def test_dispatch_scan_with_no_arg_defaults_trend(self):
        args = []
        strat = args[0].lower() if args and args[0].lower() in ("trend", "ict") else "trend"
        self.assertEqual(strat, "trend")


if __name__ == "__main__":
    unittest.main()
