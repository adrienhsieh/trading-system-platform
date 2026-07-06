"""trading/ohlcv_daemon.py — OHLCV 全市場每日增量更新 Daemon"""
import threading
import time
from datetime import datetime

import yfinance as yf

from trading.logger import get_logger
from trading.ohlcv_db import OHLCVDatabase

logger = get_logger("ohlcv_daemon")

DAILY_HOUR = 14
DAILY_MINUTE = 0
BATCH_SIZE = 50
BATCH_SLEEP = 2
MIN_ROWS_FOR_BACKFILL = 1000
YF_SLEEP = 0.3


class OHLCVDaemon:
    """每日盤後自動增量更新全市場 OHLCV。"""

    def __init__(self, ohlcv_db: OHLCVDatabase, scanner):
        self.db = ohlcv_db
        self.scanner = scanner
        self._stop = threading.Event()
        self._thread = None
        self._last_daily_date = ""

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="OHLCVDaemon")
        self._thread.start()
        logger.info("OHLCVDaemon 已啟動")

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("OHLCVDaemon 已停止")

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _loop(self):
        stats = self.db.stats()
        if stats["total_rows"] < MIN_ROWS_FOR_BACKFILL:
            logger.info("DB 行數 %d < %d，開始全市場回填（約 1-2 小時，背景執行）...", stats["total_rows"], MIN_ROWS_FOR_BACKFILL)
            print(f"   [OHLCV] 首次回填中（背景執行，約 1-2 小時）— 系統正常運作中")
            try:
                self.backfill()
                print(f"   [OHLCV] 回填完成！")
            except Exception as e:
                logger.error("回填失敗: %s", e)
        else:
            logger.info("DB 已有 %d 筆，執行增量更新...", stats["total_rows"])
            try:
                self.incremental_update()
            except Exception as e:
                logger.error("增量更新失敗: %s", e)

        while not self._stop.is_set():
            now = datetime.now()
            today = now.strftime("%Y-%m-%d")
            if (now.hour == DAILY_HOUR and now.minute >= DAILY_MINUTE
                    and today != self._last_daily_date):
                logger.info("每日增量更新開始...")
                try:
                    self.incremental_update()
                    self._last_daily_date = today
                    logger.info("每日增量更新完成")
                except Exception as e:
                    logger.error("增量更新失敗: %s", e)
            self._stop.wait(60)

    def _get_all_codes(self) -> list:
        try:
            stock_map = self.scanner.get_stock_map()
            return list(stock_map.keys())
        except Exception as e:
            logger.error("取得股票清單失敗: %s", e)
            return []

    def _fetch_one(self, code: str, period: str = "5d") -> bool:
        for suffix in (".TW", ".TWO"):
            try:
                df = yf.Ticker(f"{code}{suffix}").history(period=period, timeout=8)
                if df is not None and not df.empty:
                    df = df.rename(columns=str.lower)
                    if "close" in df.columns:
                        self.db.upsert(code, df[["open", "high", "low", "close", "volume"]])
                        return True
            except Exception:
                pass
            time.sleep(YF_SLEEP)
        return False

    def backfill(self):
        codes = self._get_all_codes()
        total = len(codes)
        if total == 0:
            logger.warning("無股票清單，跳過回填")
            return
        logger.info("回填 %d 檔...", total)
        done, failed = 0, 0
        t0 = time.time()
        for i in range(0, total, BATCH_SIZE):
            if self._stop.is_set():
                logger.info("回填中斷（收到停止信號）")
                return
            batch = codes[i:i + BATCH_SIZE]
            for code in batch:
                ok = self._fetch_one(code, period="max")
                if ok:
                    done += 1
                else:
                    failed += 1
            elapsed = int(time.time() - t0)
            pct = (done + failed) / total * 100
            logger.info("回填進度: %d/%d (%.0f%%) 成功 %d 失敗 %d [%dm%ds]",
                        done + failed, total, pct, done, failed, elapsed // 60, elapsed % 60)
            time.sleep(BATCH_SLEEP)
        logger.info("回填完成: 成功 %d / 失敗 %d / 共 %d", done, failed, total)

    def incremental_update(self):
        codes = self._get_all_codes()
        total = len(codes)
        logger.info("增量更新 %d 檔...", total)
        done, failed = 0, 0
        for i in range(0, total, BATCH_SIZE):
            if self._stop.is_set():
                return
            batch = codes[i:i + BATCH_SIZE]
            for code in batch:
                ok = self._fetch_one(code, period="5d")
                if ok:
                    done += 1
                else:
                    failed += 1
            time.sleep(BATCH_SLEEP)
        logger.info("增量更新完成: 成功 %d / 失敗 %d", done, failed)
