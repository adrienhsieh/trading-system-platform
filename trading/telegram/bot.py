"""
trading/telegram/bot.py — Telegram Bot（Polling 模式）
不需公開 URL，所有指令處理集中於 TelegramBot 類別。
"""
import datetime
import threading
import concurrent.futures
from typing import Optional

import yfinance as yf

from trading.config import ConfigManager
from trading.indicators import IndicatorEngine
from trading.logger import get_logger
from trading.market import MarketService
from trading.news import NewsAggregator
from trading.positions import PositionManager
from trading.scanner import StockScanner

logger = get_logger("telegram.bot")


class TelegramBot:
    """Telegram Bot — Polling 模式，管理指令路由與訊息推播。"""

    def __init__(
        self,
        token: str,
        allowed_ids: set,
        config_manager: ConfigManager,
        position_manager: PositionManager,
        scanner: StockScanner,
        indicator_engine: IndicatorEngine,
        news_aggregator: NewsAggregator,
        market_service: MarketService,
        intel_daemon=None,
        coverage_reader=None,
    ):
        self.token            = token
        self.allowed_ids      = allowed_ids
        self.config_mgr       = config_manager
        self.pos_mgr          = position_manager
        self.scanner          = scanner
        self.ind_engine       = indicator_engine
        self.news_agg         = news_aggregator
        self.market_svc       = market_service
        self.intel_daemon     = intel_daemon
        self.coverage_reader  = coverage_reader
        self._offset:    int  = 0
        self._stop_event      = threading.Event()

    # ── Telegram API ───────────────────────────────────────────

    def api(self, method: str, **kwargs) -> dict:
        """呼叫 Telegram Bot API。"""
        if not self.token:
            return {}
        import requests
        r = requests.post(
            f"https://api.telegram.org/bot{self.token}/{method}",
            json=kwargs, timeout=15,
        )
        return r.json() if r.ok else {}

    def send(self, chat_id: str, text: str, parse_mode: str = "Markdown") -> None:
        """傳送訊息，超過 4000 字時優先在換行處分割以保護 Markdown 格式。"""
        if not self.token:
            return

        def _send_chunk(chunk: str) -> None:
            kw = {"chat_id": chat_id, "text": chunk}
            if parse_mode:
                kw["parse_mode"] = parse_mode
            self.api("sendMessage", **kw)

        if len(text) <= 4000:
            _send_chunk(text)
            return

        remaining = text
        while remaining:
            if len(remaining) <= 4000:
                _send_chunk(remaining)
                break
            split_at = remaining.rfind("\n", 2000, 4000)
            if split_at == -1:
                split_at = 4000
            _send_chunk(remaining[:split_at])
            remaining = remaining[split_at:].lstrip("\n")

    def push_to_all(self, text: str, parse_mode: str = "Markdown") -> None:
        """推播給所有白名單使用者。"""
        if not self.token:
            return
        for chat_id in (self.allowed_ids or set()):
            try:
                self.send(chat_id, text, parse_mode=parse_mode)
            except Exception as e:
                logger.warning("推播失敗 chat_id=%s: %s", chat_id, e)

    def is_allowed(self, chat_id: str) -> bool:
        """檢查 chat_id 是否在白名單中。未設定白名單時拒絕所有人（fail-closed）。"""
        if not self.allowed_ids:
            return False
        return str(chat_id) in self.allowed_ids

    def get_updates(self, offset: int = 0) -> list:
        data = self.api("getUpdates", offset=offset, timeout=30, allowed_updates=["message"])
        return data.get("result", [])

    # ── Polling 主循環 ─────────────────────────────────────────

    def setup_commands(self) -> None:
        """設定 Bot 指令選單。"""
        self.api("setMyCommands", commands=[
            {"command": "pos",         "description": "持股現價與損益"},
            {"command": "report",      "description": "每日持倉技術指標警示"},
            {"command": "risk",        "description": "持倉風險曝露分析"},
            {"command": "stats",       "description": "持倉績效統計（浮動損益）"},
            {"command": "addpos",      "description": "新增持倉"},
            {"command": "delpos",      "description": "刪除持倉"},
            {"command": "market",      "description": "台股、美股、匯率即時報價"},
            {"command": "filter",      "description": "大盤濾網快查（台股是否站上 20EMA）"},
            {"command": "news",        "description": "最新 10 則財經新聞"},
            {"command": "analyze",     "description": "個股進場條件（例：/analyze 2330）"},
            {"command": "size",        "description": "部位計算（例：/size 2330 900 850）"},
            {"command": "scan",        "description": "掃描自訂候選清單（趨勢策略）"},
            {"command": "scanall",     "description": "掃描全台上市股票（需 5-15 分鐘）"},
            {"command": "scanict",     "description": "ICT 策略掃描候選清單"},
            {"command": "watchlist",   "description": "查看候選掃描清單"},
            {"command": "wadd",        "description": "加入候選清單（例：/wadd 2330 2317）"},
            {"command": "wdel",        "description": "移除候選清單（例：/wdel 2330）"},
            {"command": "ict",         "description": "ICT 策略分析個股（例：/ict 2330）"},
            {"command": "backtest",    "description": "回測策略（例：/backtest 2330 ict 1y）"},
            {"command": "backtestall", "description": "全市場批次回測（取掃描前 30 名）"},
            {"command": "fund",        "description": "基本面分析個股（例：/fund 2330）"},
            {"command": "strategy",    "description": "三大策略指標門檻與啟用狀態"},
            {"command": "ai",          "description": "AI 分析今日新聞整體市場情緒（Groq）"},
            {"command": "x",           "description": "X/Twitter 市場討論情緒統計"},
            {"command": "summary",     "description": "每日 AI 市場情報摘要"},
            {"command": "schedule",    "description": "查看自動推播排程設定"},
            {"command": "testam",      "description": "立即預覽盤前早報"},
            {"command": "testpm",      "description": "立即預覽收盤報告"},
            {"command": "wlist",       "description": "查看觀察名單"},
            {"command": "wladd",       "description": "新增觀察股票（例：/wladd 2330）"},
            {"command": "wldel",       "description": "刪除觀察股票（例：/wldel 2330）"},
            {"command": "wlscan",      "description": "分析觀察名單（趨勢+基本面）"},
            {"command": "myid",        "description": "取得 Chat ID"},
            {"command": "help",        "description": "查看所有指令說明"},
        ])

    def start_polling(self) -> None:
        """啟動 Polling 迴圈（阻塞）。"""
        if not self.token:
            logger.warning("未設定 TELEGRAM_BOT_TOKEN，Bot 未啟動")
            return
        self.setup_commands()
        me = self.api("getMe")
        logger.info("Bot 啟動：@%s", me.get('result', {}).get('username', '?'))

        import time
        self._stop_event.clear()
        while not self._stop_event.is_set():
            try:
                updates = self.get_updates(self._offset)
                for u in updates:
                    self._offset = u["update_id"] + 1
                    msg = u.get("message", {})
                    if not msg:
                        continue
                    chat_id = str(msg.get("chat", {}).get("id", ""))
                    text    = msg.get("text", "")
                    if not chat_id or not text:
                        continue
                    if not self.is_allowed(chat_id):
                        self.send(chat_id, "⛔ 你沒有使用此 Bot 的權限")
                        continue
                    threading.Thread(
                        target=self._handle_message,
                        args=(chat_id, text),
                        daemon=True,
                    ).start()
            except Exception as e:
                logger.error("Polling 錯誤: %s", e)
                time.sleep(5)

    def stop(self) -> None:
        """通知 Polling 迴圈停止。"""
        self._stop_event.set()

    # ── 訊息路由 ───────────────────────────────────────────────

    def _handle_message(self, chat_id: str, text: str) -> None:
        text    = text.strip()
        parts   = text.split()
        raw_cmd = parts[0] if parts else ""
        cmd     = raw_cmd.split("@")[0].lower()
        args    = parts[1:]
        logger.debug("chat=%s cmd=%r", chat_id, cmd)

        if cmd in ("/持倉", "/pos"):
            self.send(chat_id, self._cmd_positions())
        elif cmd in ("/大盤", "/market"):
            self.send(chat_id, self._cmd_market())
        elif cmd in ("/報告", "/report"):
            self.send(chat_id, self._cmd_report())
        elif cmd in ("/新聞", "/news"):
            self.send(chat_id, self._cmd_news())
        elif cmd in ("/掃描", "/scan"):
            strat = args[0].lower() if args and args[0].lower() in ("trend", "ict") else "trend"
            self.send(chat_id, "🔍 掃描中，請稍候...")
            if strat == "ict":
                threading.Thread(
                    target=lambda: self.send(chat_id, self._cmd_scan(strategy="ict")),
                    daemon=True,
                ).start()
            else:
                self.send(chat_id, self._cmd_scan())
        elif cmd in ("/掃描全市場", "/scanall"):
            threading.Thread(target=self._cmd_scan_full, args=(chat_id,), daemon=True).start()
        elif cmd in ("/掃描ict", "/scanict"):
            self.send(chat_id, "🔍 ICT 掃描中，請稍候...")
            threading.Thread(
                target=lambda: self.send(chat_id, self._cmd_scan(strategy="ict")),
                daemon=True,
            ).start()
        elif cmd == "/ict":
            if not args:
                self.send(chat_id, "用法：`/ict 代號`\n範例：`/ict 2330`")
            else:
                self.send(chat_id, "⏳ ICT 分析中...")
                threading.Thread(
                    target=lambda: self.send(chat_id, self._cmd_analyze(args[0], strategy="ict")),
                    daemon=True,
                ).start()
        elif cmd in ("/新增", "/addpos"):
            self.send(chat_id, self._cmd_add(args) if args else self._add_help())
        elif cmd in ("/刪除", "/delpos"):
            self.send(chat_id, self._cmd_delete(args) if args else self._delete_help())
        elif cmd in ("/分析", "/analyze"):
            if not args:
                self.send(chat_id, "用法：`/analyze 代號`\n範例：`/analyze 2330`")
            else:
                self.send(chat_id, "🔍 分析中，請稍候...")
                threading.Thread(
                    target=lambda: self.send(chat_id, self._cmd_analyze(args[0], strategy="trend")),
                    daemon=True,
                ).start()
        elif cmd in ("/風險", "/risk"):
            self.send(chat_id, self._cmd_risk())
        elif cmd in ("/計算", "/size"):
            self.send(chat_id, self._cmd_sizing(args) if args else self._sizing_help())
        elif cmd in ("/清單", "/watchlist"):
            self.send(chat_id, self._cmd_watchlist_show())
        elif cmd in ("/加入", "/wadd"):
            self.send(chat_id, self._cmd_watchlist_add(args) if args else "用法：`/wadd 代號 [代號2 ...]`\n範例：`/wadd 2330 2317`")
        elif cmd in ("/移除", "/wdel"):
            self.send(chat_id, self._cmd_watchlist_remove(args) if args else "用法：`/wdel 代號 [代號2 ...]`\n範例：`/wdel 2330`")
        elif cmd in ("/觀察", "/wlist"):
            self.send(chat_id, self._cmd_observe_list())
        elif cmd in ("/觀察新增", "/wladd"):
            self.send(chat_id, self._cmd_observe_add(args) if args else "用法：`/wladd 代號`\n範例：`/wladd 2330`")
        elif cmd in ("/觀察刪除", "/wldel"):
            self.send(chat_id, self._cmd_observe_remove(args) if args else "用法：`/wldel 代號`\n範例：`/wldel 2330`")
        elif cmd in ("/觀察分析", "/wlscan"):
            self.send(chat_id, "⏳ 觀察名單分析中（趨勢+基本面），請稍候...")
            threading.Thread(
                target=lambda: self.send(chat_id, self._cmd_observe_analyze()),
                daemon=True,
            ).start()
        elif cmd in ("/濾網", "/filter"):
            self.send(chat_id, self._cmd_filter())
        elif cmd in ("/績效", "/stats"):
            self.send(chat_id, "⏳ 抓取報價中，請稍候...")
            threading.Thread(
                target=lambda: self.send(chat_id, self._cmd_stats()),
                daemon=True,
            ).start()
        elif cmd in ("/回測", "/backtest"):
            if not args:
                self.send(chat_id, (
                    "用法：`/backtest 代號 [策略] [週期]`\n"
                    "範例：\n"
                    "  `/backtest 2330`\n"
                    "  `/backtest 2330 ict 1y`\n"
                    "  `/backtest 2330,2454 trend 2y`\n\n"
                    "策略：`trend`（預設）/ `ict` / `fundamental`\n"
                    "週期：`6mo` `1y` `2y`（預設）`3y` `5y`"
                ))
            else:
                self.send(chat_id, "⏳ 回測中，請稍候（約 10–30 秒）...")
                threading.Thread(
                    target=lambda: self.send(chat_id, self._cmd_backtest(args)),
                    daemon=True,
                ).start()
        elif cmd == "/新聞分析":
            self.send(chat_id, "🔍 分析新聞情緒中，請稍候...")
            threading.Thread(
                target=lambda: self.send(chat_id, self._cmd_news_sentiment()),
                daemon=True,
            ).start()
        elif cmd in ("/基本面", "/fund"):
            if not args:
                self.send(chat_id, "用法：`/fund 代號`\n範例：`/fund 2330`")
            else:
                self.send(chat_id, "⏳ 基本面分析中...")
                threading.Thread(
                    target=lambda: self.send(chat_id, self._cmd_analyze(args[0], strategy="fundamental")),
                    daemon=True,
                ).start()
        elif cmd in ("/策略設定", "/strategy"):
            self.send(chat_id, self._cmd_strategy_settings())
        elif cmd in ("/ai情報", "/ai"):
            self.send(chat_id, "⏳ AI 分析新聞情緒中...")
            threading.Thread(
                target=lambda: self.send(chat_id, self._cmd_ai_sentiment()),
                daemon=True,
            ).start()
        elif cmd in ("/x情報", "/x"):
            self.send(chat_id, self._cmd_x_sentiment())
        elif cmd in ("/情報摘要", "/summary"):
            self.send(chat_id, "⏳ 取得每日情報摘要中...")
            threading.Thread(
                target=lambda: self.send(chat_id, self._cmd_daily_summary()),
                daemon=True,
            ).start()
        elif cmd in ("/全市場回測", "/backtestall"):
            strat  = args[0].lower() if args and args[0].lower() in ("trend", "ict", "fundamental") else "trend"
            period = args[1].lower() if len(args) > 1 and args[1].lower() in ("6mo", "1y", "2y", "3y", "5y") else "2y"
            self.send(chat_id, f"⏳ 全市場回測啟動（{strat} · {period}），掃描全台後取前 30 名回測，約需 10-20 分鐘...")
            threading.Thread(target=self._cmd_backtest_full, args=(chat_id, strat, period), daemon=True).start()
        elif cmd in ("/我的id", "/myid"):
            self.send(chat_id, f"你的 Chat ID：`{chat_id}`")
        elif cmd in ("/排程", "/schedule"):
            self.send(chat_id, self._cmd_schedule_info())
        elif cmd in ("/測試早報", "/testam"):
            self.send(chat_id, "⏳ 產生盤前早報中...")
            threading.Thread(
                target=lambda: self.send(chat_id, self.build_morning_report()),
                daemon=True,
            ).start()
        elif cmd in ("/測試收盤", "/testpm"):
            self.send(chat_id, "⏳ 產生收盤報告中（需抓取報價，請稍候）...")
            threading.Thread(
                target=lambda: self.send(chat_id, self.build_close_report()),
                daemon=True,
            ).start()
        elif cmd in ("/start", "/help", "/說明", "/指令"):
            self.send(chat_id, self._cmd_help())
        else:
            self.send(chat_id, self._unknown_cmd_reply())

    # ── 指令實作 ───────────────────────────────────────────────

    def _cmd_help(self) -> str:
        return (
            "⚔️ *戰情指揮中心 指令說明*\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "📋 *持倉管理*\n"
            "/pos　　持股現價與損益\n"
            "/report　每日技術指標警示\n"
            "/risk　　持倉風險曝露分析\n"
            "/stats　　浮動損益統計\n"
            "/addpos　新增持倉\n"
            "/delpos　刪除持倉\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "🔍 *市場分析*\n"
            "/market　台股、美股、匯率\n"
            "/filter　大盤 20EMA 快查\n"
            "/news　　最新 10 則財經新聞\n"
            "/analyze [代號] 個股進場條件\n"
            "/size [代號 進場價 停損價] 部位計算\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "📡 *掃描候選*\n"
            "/scan　　掃描自訂清單（趨勢策略）\n"
            "/scanall　掃描全台上市股票\n"
            "/scanict　ICT 策略掃描候選清單\n"
            "/watchlist 查看候選清單\n"
            "/wadd [代號...] 加入候選清單\n"
            "/wdel [代號...] 移除候選清單\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "👀 *觀察名單*\n"
            "/wlist　　查看觀察名單\n"
            "/wladd [代號] 新增觀察股票\n"
            "/wldel [代號] 刪除觀察股票\n"
            "/wlscan　分析觀察名單（趨勢+基本面）\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "🧠 *ICT 策略*\n"
            "/ict [代號] 個股 ICT 分析\n"
            "/scanict　用 ICT 條件掃描候選清單\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "🔬 *回測*\n"
            "/backtest [代號] 單檔回測（預設趨勢策略 2 年）\n"
            "/backtest [代號,代號] 多檔比較\n"
            "/backtest [代號 ict 1y] 指定策略與週期\n"
            "/backtestall [策略 週期] 全市場批次回測前 30 名\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "📊 *基本面分析*\n"
            "/fund [代號] 查看 PE/EPS/PB/營收成長\n"
            "/strategy　三大策略的指標門檻與啟用狀態\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "🤖 *AI 情報*\n"
            "/ai　　今日新聞整體市場情緒（Groq）\n"
            "/x　　X/Twitter 市場討論情緒統計\n"
            "/summary 每日 AI 市場情報摘要\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "⚙️ *系統*\n"
            "/schedule 查看自動推播設定\n"
            "/testam　立即預覽盤前早報\n"
            "/testpm　立即預覽收盤報告\n"
            "/myid　　取得 Chat ID\n"
            "━━━━━━━━━━━━━━━━━━━━"
        )

    def _unknown_cmd_reply(self) -> str:
        return "❓ 未知指令\n\n" + self._cmd_help()

    def _cmd_positions(self) -> str:
        positions = self.pos_mgr.load_all()
        if not positions:
            return "📭 目前無持倉"

        def fetch(p):
            try:
                sym = p["code"] if p["code"].endswith(".TW") else f"{p['code']}.TW"
                df  = yf.Ticker(sym).history(period="2d", interval="1d")
                if len(df) >= 1:
                    curr    = round(float(df["Close"].iloc[-1]), 2)
                    prev    = round(float(df["Close"].iloc[-2]), 2) if len(df) >= 2 else curr
                    chg     = round((curr - prev) / prev * 100, 2) if prev else 0
                    pnl     = int(round((curr - p["entry"]) * p["shares"], 0))
                    pnl_pct = round((curr - p["entry"]) / p["entry"] * 100, 2)
                    return p["id"], curr, chg, pnl, pnl_pct
            except Exception:
                pass
            return p["id"], None, None, None, None

        prices = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
            for pid, curr, chg, pnl, pnl_pct in ex.map(fetch, positions):
                prices[pid] = (curr, chg, pnl, pnl_pct)

        lines     = ["📊 *持倉損益*", "━━━━━━━━━━━━━━━━━━━━"]
        total_pnl = 0
        for p in positions:
            curr, chg, pnl, pnl_pct = prices.get(p["id"], (None, None, None, None))
            icon = {"safe": "✅", "active": "🔥", "alert": "⚠️"}.get(p["status"], "▪️")
            if curr is not None:
                total_pnl += pnl
                cs = "+" if chg >= 0 else ""
                ps = "+" if pnl >= 0 else ""
                pe = "📈" if pnl >= 0 else "📉"
                lines.append(
                    f"{icon} *{p['code']}* {p['name']}\n"
                    f"  💰 現價 `{curr}`  ({cs}{chg}%)\n"
                    f"  {pe} 損益 `{ps}{pnl:,}` 元  ({ps}{pnl_pct}%)\n"
                    f"  進場 `{p['entry']}` ｜ 停損 `{p['stop']}`"
                )
            else:
                lines.append(f"{icon} *{p['code']}* {p['name']}\n  ⏳ 報價取得失敗")

        ps = "+" if total_pnl >= 0 else ""
        pe = "📈" if total_pnl >= 0 else "📉"
        lines += ["━━━━━━━━━━━━━━━━━━━━", f"{pe} *合計損益：`{ps}{total_pnl:,}` 元*"]
        return "\n".join(lines)

    def _cmd_market(self) -> str:
        symbols = {"台灣加權": "^TWII", "NASDAQ": "^IXIC", "S&P 500": "^GSPC", "USD/TWD": "TWD=X"}

        def fetch_sym(key, sym):
            try:
                df = yf.Ticker(sym).history(period="5d", interval="1d")
                if len(df) >= 2:
                    curr = float(df["Close"].iloc[-1])
                    prev = float(df["Close"].iloc[-2])
                    chg  = round((curr - prev) / prev * 100, 2)
                    return key, curr, chg
            except Exception:
                pass
            return key, None, None

        results = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
            futs = {ex.submit(fetch_sym, k, v): k for k, v in symbols.items()}
            for f in concurrent.futures.as_completed(futs, timeout=20):
                try:
                    k, curr, chg = f.result()
                    results[k] = (curr, chg)
                except Exception:
                    pass

        lines = ["📈 *即時市場報價*", "━━━━━━━━━━━━━━━━━━━━"]
        for name in symbols:
            curr, chg = results.get(name, (None, None))
            if curr is not None:
                if name == "USD/TWD":
                    lines.append(f"💱 *{name}*：`{curr:.2f}`")
                else:
                    s    = "+" if chg >= 0 else ""
                    icon = "📗" if chg >= 0 else "📕"
                    lines.append(f"{icon} *{name}*：`{curr:,.2f}`  ({s}{chg}%)")
            else:
                lines.append(f"⬜ *{name}*：--")

        m = self.market_svc.get_data()
        if m.get("market_above_ema20") is not None:
            above = m["market_above_ema20"]
            ema   = m.get("ema20_tw", "--")
            lines.append("━━━━━━━━━━━━━━━━━━━━")
            lines.append(f"大盤濾網：{'✅ 站上 20EMA' if above else '❌ 跌破 20EMA'}")
            lines.append(f"台股 20EMA：`{ema}`")
        return "\n".join(lines)

    def _cmd_report(self) -> str:
        positions = self.pos_mgr.load_all()
        if not positions:
            return "📭 目前無持倉，無法產生報告"

        lines         = [f"📋 *每日持倉報告*  {datetime.date.today()}", "━━━━━━━━━━━━━━━━━━━━"]
        alerts_total  = 0
        for p in positions:
            try:
                a      = self.ind_engine.analyze_position(p)
                if a.get("error"):
                    lines.append(f"❓ *{p['code']}* {p['name']}：{a['error']}")
                    continue
                alerts = a.get("alerts", [])
                alerts_total += len(alerts)
                ema_dir = "▼ 跌破" if a["below_ema20"] else "▲ 站上"
                icon    = "🔥" if p["status"] == "active" else "✅"
                lines.append(f"{icon} *{p['code']}* {p['name']}")
                lines.append(f"  現價 `{a['current']}` ｜ 20EMA `{a['ema20']}` {ema_dir}")
                if alerts:
                    for alert in alerts:
                        lines.append(f"  {alert}")
                else:
                    lines.append("  ✅ 持倉正常")
            except Exception as e:
                lines.append(f"❓ *{p['code']}*：{e}")

        lines.append("━━━━━━━━━━━━━━━━━━━━")
        summary = f"⚠️ 共 {alerts_total} 項警示，請優先處理" if alerts_total else "✅ 所有持倉正常"
        lines.append(summary)
        return "\n".join(lines)

    def _cmd_news(self) -> str:
        news = self.news_agg.fetch(limit=10)
        if not news:
            return "📰 目前無法取得新聞"
        tag_icon = {"tw": "🇹🇼", "intl": "🌏", "macro": "🏦"}
        lines    = ["📰 *最新財經新聞*", "━━━━━━━━━━━━━━━━━━━━"]
        for i, n in enumerate(news, 1):
            icon  = tag_icon.get(n.get("tag", ""), "📌")
            t     = n.get("time", "--:--")
            title = n["title"].replace("*", "").replace("`", "").replace("_", "").replace("[", "").replace("]", "")
            link  = n.get("link", "").strip()
            if link:
                lines.append(f"{i}. {icon} `{t}` [{title}]({link})")
            else:
                lines.append(f"{i}. {icon} `{t}` {title}")
        pages = self._paginate("\n".join(lines))
        return pages[0] if len(pages) == 1 else "\n".join(pages)

    def _cmd_news_sentiment(self) -> str:
        sm      = self.scanner.get_stock_map()
        results = self.news_agg.analyze_sentiment(sm, limit=30)
        if not results:
            return "📰 目前新聞中未偵測到明確個股情緒"
        icon_map = {"利多": "🟢", "利空": "🔴", "中性": "🟡"}
        lines    = ["📰 *新聞情緒分析*", "━━━━━━━━━━━━━━━━━━━━"]
        for r in results[:15]:
            icon  = icon_map.get(r["sentiment"], "▪️")
            title = r["title"].replace("*", "").replace("`", "").replace("_", "")
            lines.append(
                f"{icon} *{r['sentiment']}* `{r['code']}` {r['name']}\n"
                f"  [{r['reason']}] {title[:50]}"
            )
        return "\n".join(lines)

    def _cmd_scan(self, strategy: str = "trend") -> str:
        cfg        = self.config_mgr.load()
        capital    = cfg["total_capital"]
        risk_pct   = 1.0 if cfg.get("consecutive_losses", 0) >= 3 else 2.0
        candidates = cfg.get("scan_candidates", [])
        if not candidates:
            return (
                "🔍 *掃描清單為空*\n\n"
                "使用 `/加入 代號` 新增候選股，例：`/加入 2330 2317`\n\n"
                "或使用 /掃描全市場 掃描全台上市股票"
            )
        results = self.scanner.run_scan(candidates, capital, risk_pct, strategy=strategy)
        if strategy == "ict":
            return self._fmt_scan_ict(results, len(candidates))
        if not results:
            return "🔍 掃描完成，無符合條件股票"
        return self._fmt_scan_results(self.scanner.format_for_api(results), len(candidates), risk_pct)

    def _cmd_scan_full(self, chat_id: str) -> None:
        cfg      = self.config_mgr.load()
        capital  = cfg["total_capital"]
        risk_pct = 1.0 if cfg.get("consecutive_losses", 0) >= 3 else 2.0
        sm       = self.scanner.get_stock_map()
        total    = len(sm)
        self.send(chat_id, f"🌐 *全台股掃描啟動*\n共 {total} 檔，預計 5-15 分鐘\n每完成 200 檔回報一次進度")

        import time
        results: list = []
        codes  = list(sm.keys())
        batch  = 100   # 縮小批次，降低瞬間並發
        for start in range(0, total, batch):
            chunk = codes[start:start + batch]
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
                futs = {ex.submit(self.scanner.analyze_one, c, capital, risk_pct, "trend", sm.get(c, "")): c
                        for c in chunk}
                for f in concurrent.futures.as_completed(futs):
                    r = f.result()
                    if r:
                        results.append(r)
            done = min(start + batch, total)
            pct  = round(done / total * 100)
            self.send(chat_id, f"⏳ 進度：{done}/{total}（{pct}%）  目前找到 {len(results)} 檔符合")
            time.sleep(2)   # 批次間稍作停頓，避免 rate limit

        results.sort(key=lambda x: x["score"], reverse=True)
        if not results:
            self.send(chat_id, "🔍 全台股掃描完成，無符合條件股票")
            return
        self.send(chat_id, self._fmt_scan_results(self.scanner.format_for_api(results), total, risk_pct))

    def _paginate(self, text: str, max_chars: int = 3500) -> list:
        """將長文本在換行處切分為多頁，每頁末尾附頁碼。"""
        if len(text) <= max_chars:
            return [text]
        pages = []
        remaining = text
        while remaining:
            if len(remaining) <= max_chars:
                pages.append(remaining)
                break
            split_at = remaining.rfind("\n", 0, max_chars)
            if split_at == -1:
                split_at = max_chars
            pages.append(remaining[:split_at])
            remaining = remaining[split_at:].lstrip("\n")
        total = len(pages)
        return [f"{p}\n（第 {i+1}/{total} 頁）" for i, p in enumerate(pages)]

    def _cmd_analyze(self, code: str, strategy: str = "trend") -> str:
        code = code.strip().upper()
        if not code.isdigit() or len(code) != 4:
            return "❌ 請輸入正確的台股代號（4 位數字）\n範例：`/分析 2330`"
        try:
            cfg      = self.config_mgr.load()
            capital  = cfg["total_capital"]
            risk_pct = 1.0 if cfg.get("consecutive_losses", 0) >= 3 else 2.0
            result   = self.scanner.analyze_one(code, capital, risk_pct, strategy=strategy)
            if result is None:
                return f"❌ `{code}` 無法分析：資料不足或代號錯誤"
            if strategy == "ict":
                main_text = self._fmt_analyze_ict(result, capital, risk_pct)
            elif strategy == "fundamental":
                main_text = self._fmt_analyze_fundamental(result, capital, risk_pct)
            else:
                main_text = self._fmt_analyze_trend(result, capital, risk_pct)
            # Append coverage summary if available
            if self.coverage_reader:
                try:
                    ov = self.coverage_reader.get_overview(code)
                    if ov:
                        biz = (ov.get("business", "") or "")[:60]
                        sc  = (ov.get("supply_chain", "") or "")[:40]
                        cov_block = "━━━━━━━━━━━━━━━━━━━━\n📚 研究摘要（My-TW-Coverage）"
                        if biz:
                            cov_block += f"\n  {biz}"
                        if sc:
                            cov_block += f"\n  供應鏈：{sc}"
                        main_text = main_text + "\n" + cov_block
                except Exception:
                    pass
            return main_text
        except Exception as e:
            return f"⏳ 分析失敗，請稍後再試（{e}）"

    def _cmd_backtest(self, args: list) -> str:
        from trading.backtest import BacktestEngine
        from trading.strategies import REGISTRY

        raw_code = args[0].replace("，", ",")
        strategy = args[1].lower() if len(args) > 1 else "trend"
        period   = args[2].lower() if len(args) > 2 else "2y"

        if strategy not in REGISTRY:
            return f"❌ 未知策略：`{strategy}`\n可用：`trend` / `ict` / `fundamental`"
        if period not in ("6mo", "1y", "2y", "3y", "5y"):
            return f"❌ 未知週期：`{period}`\n可用：`6mo` `1y` `2y` `3y` `5y`"

        cfg     = self.config_mgr.load()
        capital = float(cfg.get("total_capital", 1_000_000))
        codes   = [c.strip() for c in raw_code.split(",") if c.strip()]

        engine = BacktestEngine()
        try:
            if len(codes) == 1:
                r = engine.run(codes[0], strategy=strategy, capital=capital, period=period)
                return self._fmt_backtest_single(r, strategy, period)
            else:
                r = engine.run_multi(codes, strategy=strategy, capital=capital, period=period)
                return self._fmt_backtest_multi(r, strategy, period)
        except Exception as e:
            return f"❌ 回測失敗：{e}"

    def _fmt_backtest_single(self, r: dict, strategy: str, period: str) -> str:
        if not r.get("ok"):
            return f"❌ {r.get('error', '回測失敗')}"
        s    = r["stats"]
        strat_label = {"ict": "ICT 策略", "fundamental": "基本面策略"}.get(strategy, "趨勢策略")
        pf   = "∞" if s["profit_factor"] >= 999 else s["profit_factor"]
        sign = "+" if s["total_return"] >= 0 else ""
        net  = r["final_equity"] - r["capital"]
        net_sign = "+" if net >= 0 else ""
        trades_preview = ""
        if r["trades"]:
            recent = r["trades"][-3:]
            lines = []
            for t in reversed(recent):
                icon = "✅" if t["pnl"] >= 0 else "❌"
                sgn  = "+" if t["pnl_pct"] >= 0 else ""
                lines.append(f"  {icon} {t['entry_date']} 進 {t['entry']} → 出 {t['exit']}（{sgn}{t['pnl_pct']}%）[{t['reason']}]")
            trades_preview = "\n最近 3 筆交易：\n" + "\n".join(lines) + "\n"
        return (
            f"🔬 *回測結果 · {r['code']} · {strat_label} · {period}*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"交易次數：{s['total_trades']} 筆（{s['wins']}W / {s['losses']}L）\n"
            f"勝　　率：{s['win_rate']}%\n"
            f"盈虧　比：{pf}\n"
            f"最大回撤：{s['max_drawdown']}%\n"
            f"總　報酬：{sign}{s['total_return']}%（{net_sign}{net:,.0f} 元）\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"{trades_preview}"
            f"⚠️ 回測結果不代表未來績效"
        )

    def _fmt_backtest_multi(self, r: dict, strategy: str, period: str) -> str:
        if not r.get("ok"):
            return f"❌ {r.get('error', '回測失敗')}"
        strat_label = {"ict": "ICT 策略", "fundamental": "基本面策略"}.get(strategy, "趨勢策略")
        rows = []
        for row in r["summary"]:
            if "error" in row:
                rows.append(f"  {row['code']}  ❌ {row['error']}")
            else:
                sign = "+" if row["total_return"] >= 0 else ""
                pf   = "∞" if row["profit_factor"] >= 999 else row["profit_factor"]
                rows.append(
                    f"  `{row['code']}`  {sign}{row['total_return']}%  "
                    f"勝{row['win_rate']}%  PF {pf}  回撤 {row['max_drawdown']}%"
                )
        table = "\n".join(rows)
        full_text = (
            f"🔬 *多檔回測比較 · {strat_label} · {period}*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"代號  總報酬  勝率  盈虧比  回撤\n"
            f"{table}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"⚠️ 回測結果不代表未來績效"
        )
        pages = self._paginate(full_text)
        return pages[0] if len(pages) == 1 else "\n".join(pages)

    def _cmd_strategy_settings(self) -> str:
        """顯示三大策略目前的指標設定（啟用狀態與門檻）。"""
        from trading.config import ConfigManager
        cfg    = ConfigManager().load()
        params = cfg.get("strategy_params", ConfigManager.DEFAULTS["strategy_params"])

        LABELS = {
            "trend": {
                "ema_arrangement": "均線多頭排列",
                "slopes_up":       "三線齊揚",
                "adx_above_25":    "ADX 門檻",
                "macd_positive":   "MACD 紅柱",
                "volume_spike":    "成交量爆量倍數",
                "ema_crossover":   "EMA5 穿越 EMA20",
            },
            "ict": {
                "bullish_ob":      "多頭 Order Block",
                "fvg_present":     "Fair Value Gap",
                "bos":             "結構突破(BOS)",
                "liquidity_sweep": "流動性掃除",
                "discount_zone":   "折扣區",
                "ote_zone":        "OTE 回檔區(Fib)",
                "mss":             "市場結構轉換(MSS)",
            },
            "fundamental": {
                "pe_reasonable":  "本益比合理(PE <)",
                "eps_positive":   "EPS 為正",
                "eps_growth":     "EPS 成長",
                "pb_reasonable":  "PB 合理(PB <)",
                "revenue_growth": "營收成長",
            },
        }
        HEADERS = {"trend": "🛡️ 趨勢策略", "ict": "🏹 ICT 策略", "fundamental": "📊 基本面策略"}

        lines = ["⚙️ *策略指標設定*\n━━━━━━━━━━━━━━━━━━━━"]
        for strat, labels in LABELS.items():
            lines.append(f"\n{HEADERS[strat]}")
            sp = params.get(strat, {})
            for key, label in labels.items():
                p = sp.get(key, {})
                en = p.get("enabled", True)
                icon = "✅" if en else "☐"
                extra = ""
                if key == "adx_above_25"    and "threshold" in p: extra = f" ( >{p['threshold']} )"
                elif key == "volume_spike"  and "threshold" in p: extra = f" ( {p['threshold']}x )"
                elif key == "pe_reasonable" and "threshold" in p: extra = f" ( <{p['threshold']} )"
                elif key == "pb_reasonable" and "threshold" in p: extra = f" ( <{p['threshold']} )"
                elif key == "ote_zone":
                    fl = p.get("fib_low", 0.618); fh = p.get("fib_high", 0.786)
                    extra = f" ( {fl}–{fh} )"
                lines.append(f"  {icon} {label}{extra}")
        lines.append("\n━━━━━━━━━━━━━━━━━━━━")
        lines.append("調整設定請至 Web 介面 → 台股掃描 → ⚙ 設定")
        return "\n".join(lines)

    def _cmd_backtest_full(self, chat_id: str, strategy: str = "trend", period: str = "2y") -> None:
        """掃描全市場高分股，取前 30 名批次回測，並推播排行榜。"""
        from trading.backtest import BacktestEngine
        try:
            cfg      = self.config_mgr.load()
            capital  = float(cfg.get("total_capital", 1_000_000))
            risk_pct = 1.0 if cfg.get("consecutive_losses", 0) >= 3 else 2.0
            min_score = 4

            sm    = self.scanner.get_stock_map()
            cands = list(sm.keys())
            strat_label = {"ict": "ICT 策略", "fundamental": "基本面策略"}.get(strategy, "趨勢策略")

            # 掃描取得高分候選
            pass_scored = []
            for i, code in enumerate(cands, 1):
                r = self.scanner.analyze_one(code, capital, risk_pct, strategy=strategy, name=sm.get(code, ""))
                if r and r["score"] >= min_score:
                    pass_scored.append((r["score"], code))
                if i % 200 == 0:
                    self.send(chat_id, f"⏳ 掃描進度 {i}/{len(cands)}，已找到 {len(pass_scored)} 檔...")

            pass_scored.sort(key=lambda x: x[0], reverse=True)
            top_codes = [code for _, code in pass_scored[:30]]

            if not top_codes:
                self.send(chat_id, f"❌ 全市場掃描完成，無符合條件（得分≥{min_score}）的股票")
                return

            self.send(chat_id, f"📊 掃描完成，共 {len(pass_scored)} 檔通過，開始回測前 {len(top_codes)} 名...")

            # 批次回測
            engine = BacktestEngine()
            bt_results = []
            for code in top_codes:
                r = engine.run(code, strategy=strategy, capital=capital,
                               risk_pct=risk_pct, min_score=min_score, period=period)
                r["code"]  = code
                r["name"]  = sm.get(code, code)
                if r.get("ok"):
                    bt_results.append(r)

            bt_results.sort(key=lambda x: x["stats"]["total_return"], reverse=True)

            if not bt_results:
                self.send(chat_id, "❌ 回測完成，無有效結果")
                return

            rows = []
            for i, r in enumerate(bt_results[:20], 1):
                s    = r["stats"]
                sign = "+" if s["total_return"] >= 0 else ""
                pf   = "∞" if s["profit_factor"] >= 999 else s["profit_factor"]
                rows.append(
                    f"{i:2}. `{r['code']}` {r['name'][:5]}  "
                    f"{sign}{s['total_return']}%  勝{s['win_rate']}%  PF {pf}"
                )
            table = "\n".join(rows)
            self.send(chat_id, (
                f"🌐 *全市場回測排行 · {strat_label} · {period}*\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"（掃描 {len(cands)} 檔 → {len(pass_scored)} 通過 → 回測前 {len(top_codes)} 名）\n\n"
                f"{table}\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"⚠️ 回測結果不代表未來績效"
            ))
        except Exception as e:
            self.send(chat_id, f"❌ 全市場回測失敗：{e}")

    def _fmt_analyze_trend(self, result: dict, capital: float, risk_pct: float) -> str:
        ind, params = result["ind"], result["params"]
        code, name, score = result["code"], result.get("name", ""), result["score"]

        label_map = {
            "ema_arrangement": "均線多頭排列",
            "slopes_up":       "三線齊揚",
            "adx_above_25":    "ADX > 25",
            "macd_positive":   "MACD 紅柱",
            "volume_spike":    "成交量爆量",
            "ema_crossover":   "EMA5 穿越 EMA20",
        }
        total      = len(ind["signals"])
        passed_str = "\n".join(f"  ✓ {label_map[k]}" for k, v in ind["signals"].items() if v) or "  （無）"
        failed_str = "\n".join(f"  ✗ {label_map[k]}" for k, v in ind["signals"].items() if not v) or "  （無）"

        if score >= 5:
            verdict = "✅ *強烈符合進場條件，可考慮進場*"
        elif score >= 3:
            verdict = "🟡 *部分符合，建議等待更多確認再進場*"
        else:
            verdict = "❌ *條件不足，暫不建議進場*"

        extra = ""
        if not ind["signals"].get("ema_arrangement"):
            extra += "\n⚠️ 均線尚未多頭排列，為進場基本條件"
        if ind.get("adx", 99) < 20:
            extra += "\n⚠️ ADX < 20，趨勢偏弱"

        return (
            f"🔍 *個股分析：{code} {name}*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 *技術指標*\n"
            f"  收盤價  `{ind['close']}`\n"
            f"  20EMA  `{ind['ema20']}`\n"
            f"  ADX    `{ind['adx']}`   ATR `{ind['atr']}`\n\n"
            f"✅ *通過信號（{score}/{total}）*\n{passed_str}\n\n"
            f"❌ *未通過*\n{failed_str}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📋 *進場參數*（資金 `{capital:,}` 元 ｜ 風險 `{risk_pct}%`）\n"
            f"  進場價   `{params['entry']}`\n"
            f"  停損價   `{params['stop']}`\n"
            f"  目標價   `{params['target']}`\n"
            f"  建議股數  `{params['shares']:,}` 股（`{params['shares']/1000:.1f}` 張）\n"
            f"  曝險金額  `{params['total_risk']:,}` 元\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"{verdict}{extra}\n"
            f"⚠️ 技術指標僅供參考，非投資建議"
        )

    def _fmt_analyze_ict(self, result: dict, capital: float, risk_pct: float) -> str:
        ind, params = result["ind"], result["params"]
        code, name, score = result["code"], result.get("name", ""), result["score"]
        sigs  = ind["signals"]
        total = len(sigs)

        LABELS = {
            "bullish_ob":       "多頭 Order Block",
            "fvg_present":      "Fair Value Gap（不平衡）",
            "bos":              "Break of Structure",
            "liquidity_sweep":  "流動性掃除後反轉",
            "discount_zone":    "折扣區（低於均衡價）",
            "ote_zone":         "OTE 回檔區（61.8–78.6%）",
            "mss":              "Market Structure Shift",
        }

        passed = [f"  ✓ {LABELS.get(k, k)}" for k, v in sigs.items() if v]
        failed = [f"  ✗ {LABELS.get(k, k)}" for k, v in sigs.items() if not v]

        if score >= 5:
            conclusion = "✅ *ICT 強烈信號，可考慮進場*"
        elif score >= 3:
            conclusion = "🟡 *ICT 部分符合，等待確認*"
        else:
            conclusion = "❌ *ICT 條件不足，暫不進場*"

        lines = [
            f"🧠 *ICT 分析：{code} {name}*",
            "━━━━━━━━━━━━━━━━━━━━",
            "📊 *價格結構*",
            f"  收盤價    `{ind['close']}`",
            f"  區間高點  `{ind['range_high']}`",
            f"  區間低點  `{ind['range_low']}`",
            f"  均衡價    `{ind['equilibrium']}`",
        ]
        if ind.get("ob_high"):
            lines.append(f"  OB 區間   `{ind['ob_low']}` – `{ind['ob_high']}`")
        if ind.get("fvg_bot"):
            lines.append(f"  FVG 區間  `{ind['fvg_bot']}` – `{ind['fvg_top']}`")
        if ind.get("ote_bot"):
            lines.append(f"  OTE 區間  `{ind['ote_bot']}` – `{ind['ote_top']}`")
        if ind.get("mss_level"):
            lines.append(f"  MSS 水位  `{ind['mss_level']}`")
        if ind.get("swing_high_ref"):
            lines.append(f"  結構高點  `{ind['swing_high_ref']}`")

        lines += [
            "━━━━━━━━━━━━━━━━━━━━",
            f"✅ 通過信號（{score}/{total}）",
        ] + (passed or ["  （無）"]) + [
            "❌ 未通過",
        ] + (failed or ["  （無）"]) + [
            "━━━━━━━━━━━━━━━━━━━━",
            f"📋 *進場參數*（資金 {capital:,} 元 ｜ 風險 {risk_pct}%）",
            f"  進場價  `{params['entry']}`",
            f"  停損價  `{params['stop']}`",
            f"  目標價  `{params['target']}`",
            f"  建議股數 `{params['shares']:,}` 股",
            f"  曝險金額 `{params['total_risk']:,}` 元",
            "━━━━━━━━━━━━━━━━━━━━",
            conclusion,
            "⚠️ 技術指標僅供參考，非投資建議",
        ]
        return "\n".join(lines)

    def _fmt_analyze_fundamental(self, result: dict, capital: float, risk_pct: float) -> str:
        ind, params = result["ind"], result["params"]
        code, name, score = result["code"], result.get("name", ""), result["score"]
        sigs  = ind["signals"]
        total = len(sigs)

        LABELS = {
            "pe_reasonable":  "本益比合理 (PE<30)",
            "eps_positive":   "EPS 為正",
            "eps_growth":     "EPS 成長（預測>當期）",
            "pb_reasonable":  "PB 合理 (PB<2.5)",
            "revenue_growth": "營收成長",
        }
        passed = [f"  ✓ {LABELS.get(k, k)}" for k, v in sigs.items() if v]
        failed = [f"  ✗ {LABELS.get(k, k)}" for k, v in sigs.items() if not v]

        if score >= 4:
            conclusion = "✅ *基本面優良，可考慮進場*"
        elif score >= 2:
            conclusion = "🟡 *基本面尚可，建議搭配技術面確認*"
        else:
            conclusion = "❌ *基本面條件不足，暫不建議進場*"

        lines = [
            f"📊 *基本面分析：{code} {name}*",
            "━━━━━━━━━━━━━━━━━━━━",
        ]
        if ind.get("pe") is not None:
            lines.append(f"  本益比 (PE)    `{ind['pe']}`")
        if ind.get("eps") is not None:
            lines.append(f"  EPS（近期）   `{ind['eps']}`")
        if ind.get("forward_eps") is not None:
            lines.append(f"  EPS（預測）   `{ind['forward_eps']}`")
        if ind.get("pb") is not None:
            lines.append(f"  股價淨值比 PB `{ind['pb']}`")
        if ind.get("revenue_growth") is not None:
            lines.append(f"  營收成長率    `{ind['revenue_growth']}%`")
        lines += [
            "━━━━━━━━━━━━━━━━━━━━",
            f"✅ 通過信號（{score}/{total}）",
        ] + (passed or ["  （無）"]) + [
            "❌ 未通過",
        ] + (failed or ["  （無）"]) + [
            "━━━━━━━━━━━━━━━━━━━━",
            f"📋 *進場參數*（資金 {capital:,} 元 ｜ 風險 {risk_pct}%）",
            f"  進場價  `{params['entry']}`",
            f"  停損價  `{params['stop']}`",
            f"  目標價  `{params['target']}`",
            f"  建議股數 `{params['shares']:,}` 股",
            f"  曝險金額 `{params['total_risk']:,}` 元",
            "━━━━━━━━━━━━━━━━━━━━",
            conclusion,
            "⚠️ 基本面資料來自 yfinance，可能有延遲，非投資建議",
        ]
        return "\n".join(lines)

    def _fmt_scan_ict(self, results: list, total_candidates: int) -> str:
        qualified = [r for r in results if r["score"] >= 3]
        strat     = total_candidates

        if not qualified:
            return (
                f"🧠 *ICT 掃描完成*（共 {strat} 檔）\n\n"
                "❌ 無符合 ICT 條件的個股（score < 3）"
            )

        LABELS = {
            "bullish_ob":       "多頭OB",
            "fvg_present":      "FVG",
            "bos":              "BOS",
            "liquidity_sweep":  "流動掃除",
            "discount_zone":    "折扣區",
            "ote_zone":         "OTE",
            "mss":              "MSS",
        }
        total_sigs = len(next(iter(qualified))["ind"]["signals"])

        lines = [f"🧠 *ICT 掃描結果*（{len(qualified)}/{strat} 符合）",
                 "━━━━━━━━━━━━━━━━━━━━"]
        for r in qualified:
            ind    = r["ind"]
            params = r["params"]
            score  = r["score"]
            passed = [LABELS.get(k, k) for k, v in ind["signals"].items() if v]
            star   = "⭐" * min(score, 5)
            lines.append(
                f"{star} *{r['code']}* {r['name']}  `{score}/{total_sigs}`\n"
                f"  進場 `{params['entry']}` ｜ 停損 `{params['stop']}` ｜ 目標 `{params['target']}`\n"
                f"  ✓ {'  '.join(passed)}"
            )
        lines.append("━━━━━━━━━━━━━━━━━━━━")
        lines.append("⚠️ ICT 信號篩選，非投資建議")
        return "\n".join(lines)

    def _add_help(self) -> str:
        return (
            "➕ *新增持倉格式：*\n\n"
            "`/新增 代號 名稱 進場價 停損價 持股數 [目標價] [狀態]`\n\n"
            "*範例：*\n"
            "`/新增 2330 台積電 900 850 1000`\n"
            "`/新增 3583 辛耘 372 307 1000 502 active`\n\n"
            "*狀態可選：*\n"
            "  `active`（預設）= 持倉中\n"
            "  `safe` = 已保本無風險\n\n"
            "目標價可省略（波段抱單）"
        )

    def _cmd_add(self, args: list) -> str:
        if len(args) < 5:
            return self._add_help()
        try:
            code   = args[0].strip()
            name   = args[1].strip()
            entry  = float(args[2])
            stop   = float(args[3])
            shares = int(args[4])
            target = float(args[5]) if len(args) >= 6 and args[5].replace(".", "").isdigit() else None
            status = (args[6] if len(args) >= 7 and args[6] in ("active", "safe", "alert") else
                      (args[5] if len(args) >= 6 and args[5] in ("active", "safe", "alert") else "active"))
            pos = self.pos_mgr.create({
                "code": code, "name": name,
                "date": str(datetime.date.today()),
                "entry": entry, "stop": stop, "shares": shares,
                "target": target, "status": status, "note": "",
            })
            risk_str = f"`{pos['risk_amount']:,}` 元" if pos["risk_amount"] else "無風險（保本）"
            tgt_str  = f"`{pos['target']}` 元" if pos["target"] else "波段抱單（不設目標）"
            return (
                f"✅ *新增成功*\n\n"
                f"代號：*{pos['code']}* {pos['name']}\n"
                f"進場：`{pos['entry']}` 元 × `{pos['shares']:,}` 股\n"
                f"停損：`{pos['stop']}` 元\n"
                f"目標：{tgt_str}\n"
                f"曝險：{risk_str}"
            )
        except (ValueError, IndexError):
            return self._add_help()
        except Exception as e:
            return f"❌ 新增失敗：{e}"

    def _delete_help(self) -> str:
        return (
            "🗑 *刪除持倉格式：*\n\n"
            "`/刪除 代號`\n\n"
            "*範例：*\n"
            "`/刪除 2330`\n\n"
            "⚠️ 刪除後無法復原"
        )

    def _cmd_delete(self, args: list) -> str:
        if not args:
            return self._delete_help()
        code      = args[0].strip()
        positions = self.pos_mgr.load_all()
        targets   = [p for p in positions if p["code"] == code]
        if not targets:
            return f"❌ 找不到代號 `{code}` 的持倉"
        for p in targets:
            self.pos_mgr.delete(p["id"])
        names = "、".join(p["name"] for p in targets)
        return f"✅ 已刪除 *{code}* {names}（共 {len(targets)} 筆）"

    def _cmd_schedule_info(self) -> str:
        now = datetime.datetime.now()
        return (
            "⏰ *自動推播排程*\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            "🌅 *08:30*  盤前早報\n"
            "   大盤濾網 + 美股昨收 + 持倉清單\n\n"
            "📊 *13:30*  收盤報告\n"
            "   持倉損益 + 技術警示\n\n"
            "🚨 *盤中每15分鐘*  即時警示\n"
            "   停損接近（3%以內）自動推播\n"
            "   目標達成（3%以內）自動推播\n\n"
            "━━━━━━━━━━━━━━━━━━━━\n"
            f"現在時間：`{now.strftime('%H:%M')}`\n"
            "輸入 /測試早報 或 /測試收盤 可立即預覽"
        )

    def _fmt_scan_results(self, formatted: list, total: int, risk_pct: float) -> str:
        sc_icon = lambda s: "🟢" if s >= 5 else ("🟡" if s >= 3 else "🔴")
        lines   = [f"🔍 *掃描結果*  共掃 {total} 檔  前 {min(10, len(formatted))} 名", "━━━━━━━━━━━━━━━━━━━━"]
        for s in formatted[:10]:
            sigs    = [v["label"] for v in s["signals"].values() if v["pass"]]
            sig_str = "  ".join(sigs) if sigs else "無訊號"
            lines.append(
                f"{sc_icon(s['score'])} *{s['code']}* {s.get('name', '')}  `{s['score']}/6`\n"
                f"  收 `{s['close']}` ｜ 停損 `{s['stop']}` ｜ 目標 `{s['target']}`\n"
                f"  ✓ {sig_str}"
            )
        lines.append("━━━━━━━━━━━━━━━━━━━━")
        lines.append(f"⚠️ 技術指標篩選，非投資建議  風險模式：{risk_pct}%")
        return "\n".join(lines)

    # ── 新增指令：風險 / 計算 / 清單 / 加入 / 移除 / 濾網 / 績效 ─

    def _cmd_risk(self) -> str:
        """顯示所有持倉的風險曝露分析。"""
        cfg       = self.config_mgr.load()
        capital   = cfg["total_capital"]
        positions = self.pos_mgr.load_all()
        if not positions:
            return "📭 目前無持倉"

        summary = self.pos_mgr.risk_summary(positions, capital)
        lines   = ["🛡 *風險曝露分析*", "━━━━━━━━━━━━━━━━━━━━"]
        lines.append(f"總資金：`{capital:,}` 元")
        lines.append(f"總曝險：`{summary['total_risk']:,}` 元（`{summary['risk_pct']}%`）")
        lines.append("━━━━━━━━━━━━━━━━━━━━")

        for p in positions:
            icon     = {"safe": "✅", "active": "🔥"}.get(p["status"], "▪️")
            risk     = p.get("risk_amount", 0)
            risk_pct = round(risk / capital * 100, 2) if capital else 0
            if p["status"] == "safe":
                lines.append(f"{icon} *{p['code']}* {p['name']}  保本（無風險）")
            else:
                lines.append(f"{icon} *{p['code']}* {p['name']}  `{risk:,}` 元（{risk_pct}%）")

        lines.append("━━━━━━━━━━━━━━━━━━━━")
        pct = summary["risk_pct"]
        if pct > 10:
            lines.append("🚨 風險過高（> 10%），建議減碼")
        elif pct > 6:
            lines.append("⚠️ 風險偏高（> 6%），請注意")
        else:
            lines.append("✅ 風險在合理範圍內")
        return "\n".join(lines)

    def _sizing_help(self) -> str:
        return (
            "📐 *部位計算格式：*\n\n"
            "`/計算 代號 進場價 停損價`\n\n"
            "*範例：*\n"
            "`/計算 2330 900 850`\n\n"
            "系統會依資金與風險模式計算建議股數與曝險金額。"
        )

    def _cmd_sizing(self, args: list) -> str:
        """依手動輸入的進場價與停損價計算建議部位。"""
        if len(args) < 3:
            return self._sizing_help()
        try:
            code   = args[0].strip()
            entry  = float(args[1])
            stop   = float(args[2])
            if entry <= stop:
                return "❌ 進場價必須大於停損價"

            cfg      = self.config_mgr.load()
            capital  = cfg["total_capital"]
            risk_pct = 1.0 if cfg.get("consecutive_losses", 0) >= 3 else 2.0
            name     = self.scanner.get_stock_name(code)

            risk_per     = round(entry - stop, 2)
            shares       = int((capital * risk_pct / 100) / risk_per)
            target       = round(entry + risk_per * 2, 2)
            total_risk   = int(risk_per * shares)
            risk_amt_pct = round(total_risk / capital * 100, 2) if capital else 0

            return (
                f"📐 *部位計算：{code} {name}*\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"進場價：`{entry}` 元\n"
                f"停損價：`{stop}` 元\n"
                f"目標價：`{target}` 元（1:2 報酬比）\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"建議股數：`{shares:,}` 股（`{shares/1000:.1f}` 張）\n"
                f"每股風險：`{risk_per}` 元\n"
                f"曝險金額：`{total_risk:,}` 元（佔資金 `{risk_amt_pct}%`）\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"風險模式：`{risk_pct}%`\n"
                f"⚠️ 以上僅供計算參考，非投資建議"
            )
        except (ValueError, IndexError):
            return self._sizing_help()
        except Exception as e:
            return f"❌ 計算失敗：{e}"

    def _cmd_watchlist_show(self) -> str:
        """列出目前的候選掃描清單。"""
        cfg        = self.config_mgr.load()
        candidates = cfg.get("scan_candidates", [])
        if not candidates:
            return "📋 候選清單目前為空\n\n使用 `/加入 代號` 新增，例：`/加入 2330 2317`"

        sm    = self.scanner.get_stock_map()
        lines = [f"📋 *候選清單*（共 {len(candidates)} 檔）", "━━━━━━━━━━━━━━━━━━━━"]
        for i, code in enumerate(candidates, 1):
            name = sm.get(code, code)
            lines.append(f"{i}. `{code}` {name}")
        lines.append("━━━━━━━━━━━━━━━━━━━━")
        lines.append("使用 `/掃描` 對此清單執行技術分析")
        return "\n".join(lines)

    def _cmd_watchlist_add(self, args: list) -> str:
        """將代號加入候選掃描清單。"""
        if not args:
            return "用法：`/加入 代號 [代號2 ...]`\n範例：`/加入 2330 2317`"

        valid    = [a.strip() for a in args if a.strip().isdigit() and len(a.strip()) == 4]
        invalid  = [a.strip() for a in args if not (a.strip().isdigit() and len(a.strip()) == 4)]
        if not valid:
            return "❌ 請輸入正確的台股代號（4 位數字）"

        cfg       = self.config_mgr.load()
        existing  = set(cfg.get("scan_candidates", []))
        already   = [c for c in valid if c in existing]
        new_codes = [c for c in valid if c not in existing]
        existing.update(new_codes)
        cfg["scan_candidates"] = sorted(existing)
        self.config_mgr.save(cfg)

        total = len(cfg["scan_candidates"])
        lines = [f"✅ 已加入 {len(new_codes)} 個代號，清單共 {total} 檔"]
        if new_codes:
            lines.append("新增：" + "、".join(new_codes))
        if already:
            lines.append("已在清單：" + "、".join(already))
        if invalid:
            lines.append("忽略（格式錯誤）：" + "、".join(invalid))
        return "\n".join(lines)

    def _cmd_watchlist_remove(self, args: list) -> str:
        """從候選掃描清單移除代號。"""
        if not args:
            return "用法：`/移除 代號 [代號2 ...]`\n範例：`/移除 2330`"

        codes     = [a.strip() for a in args]
        cfg       = self.config_mgr.load()
        existing  = set(cfg.get("scan_candidates", []))
        removed   = [c for c in codes if c in existing]
        not_found = [c for c in codes if c not in existing]

        for c in removed:
            existing.discard(c)
        cfg["scan_candidates"] = sorted(existing)
        self.config_mgr.save(cfg)

        lines = []
        if removed:
            lines.append(f"✅ 已移除：" + "、".join(removed))
        if not_found:
            lines.append(f"⚠️ 不在清單：" + "、".join(not_found))
        lines.append(f"清單剩餘 {len(cfg['scan_candidates'])} 檔")
        return "\n".join(lines)

    # ── 觀察名單（positions.db watchlist table）──────────────

    def _cmd_observe_list(self) -> str:
        """列出觀察名單。"""
        items = self.pos_mgr.watchlist_list()
        if not items:
            return "👀 觀察名單為空\n\n使用 `/wladd 代號` 新增，例：`/wladd 2330`"
        lines = [f"👀 *觀察名單*（共 {len(items)} 檔）", "━━━━━━━━━━━━━━━━━━━━"]
        for i, item in enumerate(items, 1):
            lines.append(f"{i}. `{item['code']}` {item['name']}　（{item['added_at']}）")
        lines.append("━━━━━━━━━━━━━━━━━━━━")
        lines.append("使用 `/wlscan` 執行趨勢+基本面分析")
        return "\n".join(lines)

    def _cmd_observe_add(self, args: list) -> str:
        """新增觀察股票。"""
        code = args[0].strip()
        if not code.isdigit() or len(code) != 4:
            return "❌ 請輸入正確的台股代號（4 位數字）"
        name = self.scanner.get_stock_name(code)
        ok = self.pos_mgr.watchlist_add(code, name)
        if not ok:
            return f"⚠️ `{code}` 已在觀察名單中"
        return f"✅ 已新增 `{code}` {name} 到觀察名單"

    def _cmd_observe_remove(self, args: list) -> str:
        """刪除觀察股票。"""
        code = args[0].strip()
        ok = self.pos_mgr.watchlist_remove(code)
        if not ok:
            return f"⚠️ `{code}` 不在觀察名單中"
        return f"✅ 已從觀察名單移除 `{code}`"

    def _cmd_observe_analyze(self) -> str:
        """分析觀察名單所有股票（趨勢+基本面）。"""
        items = self.pos_mgr.watchlist_list()
        if not items:
            return "👀 觀察名單為空，請先用 `/wladd 代號` 新增"

        cfg = self.config_mgr.load()
        capital = cfg.get("total_capital", 3000000)
        risk_pct = 1.0 if cfg.get("consecutive_losses", 0) >= 3 else 2.0

        lines = [f"🔍 *觀察名單分析*（{len(items)} 檔）", "━━━━━━━━━━━━━━━━━━━━"]
        for item in items:
            code, name = item["code"], item["name"]
            lines.append(f"\n*{code} {name}*")

            # 趨勢
            trend = self.scanner.analyze_one(code, capital, risk_pct, strategy="trend")
            if trend:
                fmt = self.scanner.format_for_api([trend], strategy="trend")
                if fmt:
                    sigs = fmt[0].get("signals", {})
                    passed = sum(1 for s in sigs.values() if s.get("pass"))
                    total = len(sigs)
                    sig_str = " ".join(
                        f"{'✓' if s.get('pass') else '✗'}{s.get('label','')}"
                        for s in sigs.values()
                    )
                    adx = fmt[0].get("adx")
                    adx_str = f"（ADX {adx:.1f}）" if adx else ""
                    lines.append(f"🛡️ 趨勢 {passed}/{total}{adx_str}")
                    lines.append(f"  {sig_str}")

            # 基本面
            fund = self.scanner.analyze_one(code, capital, risk_pct, strategy="fundamental")
            if fund:
                fmt = self.scanner.format_for_api([fund], strategy="fundamental")
                if fmt:
                    sigs = fmt[0].get("signals", {})
                    passed = sum(1 for s in sigs.values() if s.get("pass"))
                    total = len(sigs)
                    sig_str = " ".join(
                        f"{'✓' if s.get('pass') else '✗'}{s.get('label','')}"
                        for s in sigs.values()
                    )
                    pe = fmt[0].get("pe")
                    eps = fmt[0].get("eps")
                    pe_str = f"（PE {pe:.1f}" if pe else ""
                    eps_str = f" EPS {eps:.2f}）" if eps else "）" if pe_str else ""
                    lines.append(f"📊 基本面 {passed}/{total}{pe_str}{eps_str}")
                    lines.append(f"  {sig_str}")

            lines.append("")

        lines.append("\n━━━━━━━━━━━━━━━━━━━━")
        return "\n".join(lines)

    def _cmd_filter(self) -> str:
        """大盤濾網快查：台股是否站上 20EMA。"""
        m = self.market_svc.get_data()
        if not m:
            return "⏳ 大盤資料載入中，請稍後再試 `/濾網`"

        above  = m.get("market_above_ema20")
        ema    = m.get("ema20_tw", "--")
        taiex  = m.get("taiex", {})
        nasdaq = m.get("nasdaq", {})
        sp500  = m.get("sp500", {})

        lines = ["🔭 *大盤濾網*", "━━━━━━━━━━━━━━━━━━━━"]
        if taiex.get("price"):
            s = "+" if taiex.get("change_pct", 0) >= 0 else ""
            lines.append(f"台股加權：`{taiex['price']:,.0f}`  ({s}{taiex['change_pct']}%)")
        lines.append(f"台股 20EMA：`{ema}`")
        lines.append("━━━━━━━━━━━━━━━━━━━━")

        if above is True:
            lines.append("✅ *站上 20EMA — 多方格局*")
            lines.append("依系統信號可積極進場")
        elif above is False:
            lines.append("❌ *跌破 20EMA — 謹慎操作*")
            lines.append("避免新建多單，現有持倉注意停損")
        else:
            lines.append("⏳ 濾網資料更新中...")

        if nasdaq.get("price") or sp500.get("price"):
            lines.append("━━━━━━━━━━━━━━━━━━━━")
        if nasdaq.get("price"):
            s    = "+" if nasdaq.get("change_pct", 0) >= 0 else ""
            icon = "📗" if nasdaq.get("change_pct", 0) >= 0 else "📕"
            lines.append(f"{icon} NASDAQ `{nasdaq['price']:,.2f}`  ({s}{nasdaq['change_pct']}%)")
        if sp500.get("price"):
            s    = "+" if sp500.get("change_pct", 0) >= 0 else ""
            icon = "📗" if sp500.get("change_pct", 0) >= 0 else "📕"
            lines.append(f"{icon} S&P500  `{sp500['price']:,.2f}`  ({s}{sp500['change_pct']}%)")
        return "\n".join(lines)

    def _cmd_stats(self) -> str:
        """持倉績效統計：浮動損益、最佳/最差持倉、風險概況。"""
        positions = self.pos_mgr.load_all()
        if not positions:
            return "📭 目前無持倉"

        cfg     = self.config_mgr.load()
        capital = cfg["total_capital"]

        def fetch(p):
            try:
                sym = p["code"] if p["code"].endswith(".TW") else f"{p['code']}.TW"
                df  = yf.Ticker(sym).history(period="2d", interval="1d")
                if len(df) >= 1:
                    curr    = round(float(df["Close"].iloc[-1]), 2)
                    pnl     = int(round((curr - p["entry"]) * p["shares"], 0))
                    pnl_pct = round((curr - p["entry"]) / p["entry"] * 100, 2)
                    return p["id"], curr, pnl, pnl_pct
            except Exception:
                pass
            return p["id"], None, None, None

        prices = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
            for pid, curr, pnl, pnl_pct in ex.map(fetch, positions):
                prices[pid] = (curr, pnl, pnl_pct)

        summary    = self.pos_mgr.risk_summary(positions, capital)
        active_cnt = sum(1 for p in positions if p["status"] == "active")
        safe_cnt   = sum(1 for p in positions if p["status"] == "safe")

        pnl_data   = [(p, *prices[p["id"]]) for p in positions
                      if prices.get(p["id"]) and prices[p["id"]][1] is not None]
        profitable = [x for x in pnl_data if x[2] > 0]
        losing     = [x for x in pnl_data if x[2] < 0]
        total_pnl  = sum(x[2] for x in pnl_data)

        ps = "+" if total_pnl >= 0 else ""
        pe = "📈" if total_pnl >= 0 else "📉"

        lines = ["📊 *持倉績效統計*", "━━━━━━━━━━━━━━━━━━━━"]
        lines.append(f"持倉數：{len(positions)} 筆（🔥 active {active_cnt} / ✅ safe {safe_cnt}）")
        lines.append(f"總資金：`{capital:,}` 元")
        lines.append(f"總曝險：`{summary['total_risk']:,}` 元（`{summary['risk_pct']}%`）")
        lines.append("━━━━━━━━━━━━━━━━━━━━")
        lines.append("*浮動損益*")
        lines.append(f"  📈 獲利：{len(profitable)} 筆")
        lines.append(f"  📉 虧損：{len(losing)} 筆")
        lines.append(f"  {pe} 合計：`{ps}{total_pnl:,}` 元")

        if pnl_data:
            best  = max(pnl_data, key=lambda x: x[2])
            worst = min(pnl_data, key=lambda x: x[2])
            lines.append("━━━━━━━━━━━━━━━━━━━━")
            bp, bpp = best[0], best[3]
            wp, wpp = worst[0], worst[3]
            bs = "+" if best[2] >= 0 else ""
            ws = "+" if worst[2] >= 0 else ""
            lines.append(f"🏆 最佳：*{bp['code']}* {bp['name']}  `{bs}{best[2]:,}` 元（{bs}{bpp}%）")
            lines.append(f"⚠️ 最差：*{wp['code']}* {wp['name']}  `{ws}{worst[2]:,}` 元（{ws}{wpp}%）")

        return "\n".join(lines)

    # ── ICT 策略指令 ───────────────────────────────────────────

    # ── 排程共用報告（供 TradingScheduler 呼叫） ──────────────

    def build_morning_report(self) -> str:
        """08:30 盤前早報內容。"""
        today   = datetime.date.today().strftime("%m/%d")
        weekday = ["一", "二", "三", "四", "五", "六", "日"][datetime.date.today().weekday()]
        lines   = [f"🌅 *盤前早報*  {today}（週{weekday}）", "━━━━━━━━━━━━━━━━━━━━"]

        m = self.market_svc.get_data()
        if m:
            above   = m.get("market_above_ema20")
            ema     = m.get("ema20_tw", "--")
            nasdaq  = m.get("nasdaq", {})
            sp500   = m.get("sp500", {})
            if nasdaq.get("price"):
                ns = "+" if nasdaq["change_pct"] >= 0 else ""
                lines.append(f"🌏 NASDAQ `{nasdaq['price']:,.2f}`  ({ns}{nasdaq['change_pct']}%)")
            if sp500.get("price"):
                ss = "+" if sp500["change_pct"] >= 0 else ""
                lines.append(f"🌏 S&P500  `{sp500['price']:,.2f}`  ({ss}{sp500['change_pct']}%)")
            lines.append("━━━━━━━━━━━━━━━━━━━━")
            if above is not None:
                lines.append(f"大盤濾網：{'✅ 站上 20EMA，多方格局' if above else '❌ 跌破 20EMA，謹慎操作'}")
                lines.append(f"台股 20EMA：`{ema}`")
        else:
            lines.append("⏳ 大盤資料更新中...")

        positions = self.pos_mgr.load_all()
        lines.append("━━━━━━━━━━━━━━━━━━━━")
        if positions:
            lines.append(f"📋 持倉 {len(positions)} 筆，今日注意：")
            for p in positions:
                icon = "🔥" if p["status"] == "active" else "✅"
                tgt  = f" → 目標 `{p['target']}`" if p.get("target") else ""
                lines.append(f"  {icon} *{p['code']}* {p['name']}  停損 `{p['stop']}`{tgt}")
        else:
            lines.append("📭 目前無持倉")

        lines.append("━━━━━━━━━━━━━━━━━━━━")
        lines.append("祝交易順利 ⚔️")
        return "\n".join(lines)

    def build_close_report(self) -> str:
        """13:30 收盤報告內容。"""
        today     = datetime.date.today().strftime("%m/%d")
        positions = self.pos_mgr.load_all()
        lines     = [f"📊 *收盤報告*  {today}", "━━━━━━━━━━━━━━━━━━━━"]

        if not positions:
            lines.append("📭 目前無持倉")
            return "\n".join(lines)

        def fetch(p):
            try:
                sym = p["code"] if p["code"].endswith(".TW") else f"{p['code']}.TW"
                df  = yf.Ticker(sym).history(period="2d", interval="1d")
                if len(df) >= 1:
                    curr    = round(float(df["Close"].iloc[-1]), 2)
                    prev    = round(float(df["Close"].iloc[-2]), 2) if len(df) >= 2 else curr
                    chg     = round((curr - prev) / prev * 100, 2) if prev else 0
                    pnl     = int(round((curr - p["entry"]) * p["shares"], 0))
                    pnl_pct = round((curr - p["entry"]) / p["entry"] * 100, 2)
                    return p["id"], curr, chg, pnl, pnl_pct
            except Exception:
                pass
            return p["id"], None, None, None, None

        prices = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
            for pid, curr, chg, pnl, pnl_pct in ex.map(fetch, positions):
                prices[pid] = (curr, chg, pnl, pnl_pct)

        total_pnl = 0
        for p in positions:
            curr, chg, pnl, pnl_pct = prices.get(p["id"], (None, None, None, None))
            icon = {"safe": "✅", "active": "🔥", "alert": "⚠️"}.get(p["status"], "▪️")
            if curr is not None:
                total_pnl += pnl
                cs = "+" if chg >= 0 else ""
                ps = "+" if pnl >= 0 else ""
                pe = "📈" if pnl >= 0 else "📉"
                lines.append(
                    f"{icon} *{p['code']}* {p['name']}\n"
                    f"  收盤 `{curr}`  ({cs}{chg}%)\n"
                    f"  {pe} 損益 `{ps}{pnl:,}` 元  ({ps}{pnl_pct}%)"
                )
            else:
                lines.append(f"{icon} *{p['code']}* {p['name']}  ⏳ 報價取得失敗")

        ps = "+" if total_pnl >= 0 else ""
        pe = "📈" if total_pnl >= 0 else "📉"
        lines.append("━━━━━━━━━━━━━━━━━━━━")
        lines.append(f"{pe} *今日合計損益：`{ps}{total_pnl:,}` 元*")

        alerts_found = []
        for p in positions:
            try:
                a = self.ind_engine.analyze_position(p)
                if a.get("alerts"):
                    for alert in a["alerts"]:
                        alerts_found.append(f"  *{p['code']}* {p['name']}：{alert}")
            except Exception:
                pass

        if alerts_found:
            lines.append("━━━━━━━━━━━━━━━━━━━━")
            lines.append("⚠️ *技術警示*")
            lines.extend(alerts_found)

        return "\n".join(lines)

    # ── AI 情報指令 ─────────────────────────────────────────────

    def _cmd_ai_sentiment(self) -> str:
        """使用 Groq 分析今日新聞整體市場情緒。"""
        result = self.news_agg.analyze_sentiment_ai(limit=20)
        if result is None:
            return "❌ AI 情緒分析不可用（請設定 GROQ_API_KEY）"
        mood_icon = {"bullish": "📈", "bearish": "📉", "neutral": "➡️"}.get(result.get("mood", ""), "❓")
        mood_tw   = {"bullish": "多頭", "bearish": "空頭", "neutral": "中性"}.get(result.get("mood", ""), "?")
        themes    = result.get("themes", [])
        themes_str = "\n".join(f"  • {t}" for t in themes) if themes else "  （無）"
        lines = [
            "🤖 *AI 新聞情緒分析（Groq）*",
            "━━━━━━━━━━━━━━━━━━━━",
            f"整體情緒：{mood_icon} *{mood_tw}*（信心 {result.get('confidence', '?')}/10）",
            "",
            "📌 主要主題",
            themes_str,
            "",
            "📝 摘要",
            result.get("summary", "（無）"),
            "━━━━━━━━━━━━━━━━━━━━",
            "⚠️ 僅供參考，非投資建議",
        ]
        return "\n".join(lines)

    def _cmd_x_sentiment(self) -> str:
        """查看 X/Twitter 市場討論情緒統計。"""
        from trading.xmonitor import XMonitor
        x_mon = XMonitor()
        stats = x_mon.sentiment_summary(hours=24)
        posts = x_mon.get_recent(hours=24, limit=5)

        source = "Grok API" if x_mon.is_available() else "Google News RSS"
        mood_icon = {"bullish": "📈", "bearish": "📉", "neutral": "➡️"}.get(stats.get("mood", ""), "❓")
        mood_tw   = {"bullish": "多頭", "bearish": "空頭", "neutral": "中性"}.get(stats.get("mood", ""), "?")

        lines = [
            f"🐦 *X/Twitter 市場情緒（來源：{source}）*",
            "━━━━━━━━━━━━━━━━━━━━",
            f"過去 24 小時共 {stats['total']} 則",
            f"整體情緒：{mood_icon} *{mood_tw}*",
            f"  多頭 {stats['bullish']} | 空頭 {stats['bearish']} | 中性 {stats['neutral']}",
        ]
        if posts:
            lines += ["", "最近討論："]
            for p in posts[:5]:
                sent_icon = {"bullish": "📈", "bearish": "📉", "neutral": "➡️"}.get(p.get("sentiment", ""), "")
                lines.append(f"  {sent_icon} {p['content'][:60]}")
        if stats["total"] == 0:
            lines.append("\n（尚無資料，請先等 Daemon 收集或手動觸發）")
        lines.append("━━━━━━━━━━━━━━━━━━━━")
        return "\n".join(lines)

    def _cmd_daily_summary(self) -> str:
        """取得每日 AI 市場情報摘要。"""
        daemon  = self.intel_daemon
        if daemon is None:
            from trading.intelligence import IntelligenceDaemon
            daemon = IntelligenceDaemon()
        summary = daemon.get_latest_summary()
        stats   = daemon.get_news_sentiment_stats(hours=24)

        if not summary:
            return "📭 尚無每日摘要（每天 08:00 自動生成，或等 Daemon 啟動後收集足夠新聞）"

        mood_icon = {"bullish": "📈", "bearish": "📉", "neutral": "➡️"}.get(summary.get("mood", ""), "❓")
        mood_tw   = {"bullish": "多頭", "bearish": "空頭", "neutral": "中性"}.get(summary.get("mood", ""), "?")

        lines = [
            f"📋 *每日市場情報摘要 · {summary['date']}*",
            "━━━━━━━━━━━━━━━━━━━━",
            f"整體情緒：{mood_icon} *{mood_tw}*",
            f"新聞分析：{stats['total']} 則（多 {stats['bullish']} | 空 {stats['bearish']} | 中 {stats['neutral']}）",
            "",
            summary.get("summary", "（無內容）"),
            "━━━━━━━━━━━━━━━━━━━━",
            f"⏱ 生成時間：{summary.get('created_at', '?')}",
        ]
        return "\n".join(lines)

