"""
trading/telegram/scheduler.py — 自動推播排程系統
功能：
  1. 盤前早報（08:30）— 大盤濾網 + 持倉摘要
  2. 收盤報告（13:30）— 持倉損益 + 技術警示
  3. 停損警示（盤中每 15 分鐘）— 價格接近停損自動推播
  4. 目標達成通知（盤中每 15 分鐘）— 股價到目標自動通知
"""
import datetime
import threading
import time
import concurrent.futures
from typing import TYPE_CHECKING

import yfinance as yf

from trading.indicators import IndicatorEngine
from trading.logger import get_logger
from trading.positions import PositionManager

logger = get_logger("telegram.scheduler")

if TYPE_CHECKING:
    from trading.telegram.bot import TelegramBot


class TradingScheduler:
    """交易排程器，定時推播早報、收盤報告與盤中警示。"""

    def __init__(
        self,
        telegram_bot: "TelegramBot",
        position_manager: PositionManager,
        indicator_engine: IndicatorEngine,
        coverage_reader=None,
    ):
        self.bot               = telegram_bot
        self.pos_mgr           = position_manager
        self.ind_eng           = indicator_engine
        self._coverage_reader  = coverage_reader

    # ── 啟動 ───────────────────────────────────────────────────

    def start(self) -> threading.Thread:
        """在背景執行緒啟動排程迴圈，回傳該執行緒。"""
        t = threading.Thread(target=self._loop, daemon=True)
        t.start()
        logger.info("排程系統啟動")
        return t

    # ── 主迴圈 ─────────────────────────────────────────────────

    def _loop(self) -> None:
        """每分鐘檢查一次，依時間觸發對應推播。"""
        sent_today:       set   = set()
        last_alert_check: float = 0.0
        last_date:        datetime.date = None

        while True:
            try:
                now  = datetime.datetime.now()
                date = now.date()
                hhmm = now.strftime("%H:%M")
                wday = now.weekday()  # 0=週一 ~ 4=週五

                # 跨日重置
                if date != last_date:
                    sent_today.clear()
                    last_date = date
                    logger.info("新的一天 %s，重置推播記錄", date)

                # 只在交易日（週一~週五）執行
                if wday <= 4:
                    now_hm = now.hour * 60 + now.minute

                    # 1. 盤前早報 >= 08:30（當天尚未發送）
                    if now_hm >= 8 * 60 + 30 and "morning" not in sent_today:
                        sent_today.add("morning")
                        logger.info("發送盤前早報")
                        threading.Thread(
                            target=lambda: self.bot.push_to_all(self.bot.build_morning_report()),
                            daemon=True,
                        ).start()

                    # 2. 收盤報告 >= 13:30（當天尚未發送）
                    if now_hm >= 13 * 60 + 30 and "close" not in sent_today:
                        sent_today.add("close")
                        logger.info("發送收盤報告")
                        threading.Thread(
                            target=lambda: self.bot.push_to_all(self.bot.build_close_report()),
                            daemon=True,
                        ).start()

                    # 3. 盤中警示：09:00~14:30 每 15 分鐘
                    now_ts = time.time()
                    is_trading = (
                        (now.hour == 9 and now.minute >= 0) or
                        (9 < now.hour < 14) or
                        (now.hour == 14 and now.minute <= 30)
                    )
                    if is_trading and (now_ts - last_alert_check) >= 900:
                        last_alert_check = now_ts
                        logger.debug("盤中警示檢查 %s", hhmm)
                        threading.Thread(target=self._check_alerts, daemon=True).start()

                # 4. Coverage sync：每日 02:00（不限交易日）
                if hhmm == "02:00" and "coverage_sync" not in sent_today:
                    if self._coverage_reader is not None:
                        sent_today.add("coverage_sync")
                        logger.info("執行 coverage sync")
                        threading.Thread(
                            target=self._coverage_reader.sync,
                            daemon=True,
                        ).start()

            except Exception as e:
                logger.error("排程錯誤: %s", e)

            time.sleep(60)

    # ── 盤中警示 ───────────────────────────────────────────────

    def _check_alerts(self) -> None:
        """檢查停損接近與目標達成，有觸發時推播給所有白名單使用者。"""
        positions = self.pos_mgr.load_all()
        if not positions:
            return
        active = [p for p in positions if p["status"] == "active"]
        if not active:
            return

        def fetch(p):
            try:
                sym = p["code"] if p["code"].endswith(".TW") else f"{p['code']}.TW"
                df  = yf.Ticker(sym).history(period="1d", interval="5m")
                if not df.empty:
                    return p["id"], round(float(df["Close"].iloc[-1]), 2)
            except Exception:
                pass
            return p["id"], None

        prices: dict = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
            for pid, curr in ex.map(fetch, active):
                if curr:
                    prices[pid] = curr

        stop_alerts:   list = []
        target_alerts: list = []

        for p in active:
            curr = prices.get(p["id"])
            if curr is None:
                continue

            # 停損警示：現價 <= 停損價 * 1.03
            if curr <= p["stop"] * 1.03:
                pct = round((curr - p["stop"]) / p["stop"] * 100, 2)
                s   = "+" if pct >= 0 else ""
                stop_alerts.append(
                    f"🚨 *{p['code']}* {p['name']}\n"
                    f"  現價 `{curr}` ｜ 停損 `{p['stop']}`\n"
                    f"  距停損 `{s}{pct}%`  ← 請確認是否執行停損"
                )

            # 目標達成通知：現價 >= 目標價 * 0.97
            if p.get("target") and curr >= p["target"] * 0.97:
                pct = round((p["target"] - curr) / p["target"] * 100, 2)
                target_alerts.append(
                    f"🎯 *{p['code']}* {p['name']}\n"
                    f"  現價 `{curr}` ｜ 目標 `{p['target']}`\n"
                    f"  距目標僅剩 `{pct}%`  ← 準備執行 50% 獲利了結"
                )

        if stop_alerts:
            msg = "🚨 *停損警示*\n━━━━━━━━━━━━━━━━━━━━\n" + "\n\n".join(stop_alerts)
            self.bot.push_to_all(msg)

        if target_alerts:
            msg = "🎯 *目標達成通知*\n━━━━━━━━━━━━━━━━━━━━\n" + "\n\n".join(target_alerts)
            self.bot.push_to_all(msg)
