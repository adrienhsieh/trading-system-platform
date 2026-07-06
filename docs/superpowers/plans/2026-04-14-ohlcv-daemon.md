# OHLCV 全市場每日增量更新 實作計劃

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增 OHLCVDaemon 每日盤後自動增量更新全市場 ~2000 檔 K 線，並修改 fetch_ohlcv 改為 DB 優先讀取，大幅減少 yfinance 即時呼叫。

**Architecture:** 新增 `trading/ohlcv_daemon.py`（Thread-based daemon），遵循現有 `IntelligenceDaemon` 模式。修改 `IndicatorEngine.fetch_ohlcv()` 的讀取邏輯為 DB 優先 + fallback yfinance。不改動 DB schema。

**Tech Stack:** Python / yfinance / SQLite / threading

**Spec:** `docs/superpowers/specs/2026-04-14-ohlcv-daily-update.md`

---

## 檔案結構

| 檔案 | 動作 | 職責 |
|------|------|------|
| `trading/ohlcv_daemon.py` | 新建 | OHLCVDaemon（排程 + 回填 + 增量更新） |
| `trading/indicators.py` | 修改 | fetch_ohlcv 改為 DB 優先 |
| `trading/ohlcv_db.py` | 修改 | load() 預設天數加大 |
| `trading/services/container.py` | 修改 | 新增 ohlcv_daemon property |
| `run.py` | 修改 | 啟動 OHLCVDaemon |
| `tests/test_ohlcv_daemon.py` | 新建 | daemon 測試 |
| `tests/test_indicators.py` | 修改 | fetch_ohlcv 新邏輯測試 |

---

## Task 1: OHLCVDaemon（後端）

**Files:**
- Create: `trading/ohlcv_daemon.py`
- Test: `tests/test_ohlcv_daemon.py`

- [ ] **Step 1: 建立 `trading/ohlcv_daemon.py`**

```python
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
        # 首次：偵測 DB 是否需要回填
        stats = self.db.stats()
        if stats["total_rows"] < MIN_ROWS_FOR_BACKFILL:
            logger.info("DB 行數 %d < %d，開始全市場回填...", stats["total_rows"], MIN_ROWS_FOR_BACKFILL)
            try:
                self.backfill()
            except Exception as e:
                logger.error("回填失敗: %s", e)
        else:
            # 非首次：立即跑一次增量更新
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
        """從 scanner 取得全市場股票代號清單。"""
        try:
            stock_map = self.scanner.get_stock_map()
            return list(stock_map.keys())
        except Exception as e:
            logger.error("取得股票清單失敗: %s", e)
            return []

    def _fetch_one(self, code: str, period: str = "5d") -> bool:
        """抓取單檔 OHLCV 並寫入 DB。回傳是否成功。"""
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
        """全市場回填（period=max）。約 1-2 小時。"""
        codes = self._get_all_codes()
        total = len(codes)
        logger.info("回填 %d 檔...", total)
        done, failed = 0, 0
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
            logger.info("回填進度: %d/%d（失敗 %d）", done + failed, total, failed)
            time.sleep(BATCH_SLEEP)
        logger.info("回填完成: 成功 %d / 失敗 %d / 共 %d", done, failed, total)

    def incremental_update(self):
        """全市場增量更新（period=5d）。約 10-15 分鐘。"""
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
```

- [ ] **Step 2: 建立 `tests/test_ohlcv_daemon.py`**

```python
"""tests/test_ohlcv_daemon.py — OHLCVDaemon 單元測試"""
import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd


def _mock_yf_history(n=20):
    dates = pd.date_range("2026-04-01", periods=n, freq="B")
    close = np.linspace(100, 110, n)
    return pd.DataFrame({
        "Open": close - 0.5, "High": close + 1, "Low": close - 1,
        "Close": close, "Volume": np.full(n, 1e6),
    }, index=dates)


class TestOHLCVDaemon(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = str(Path(self.tmpdir) / "test_ohlcv.db")
        from trading.ohlcv_db import OHLCVDatabase
        self.db = OHLCVDatabase(db_path=self.db_path)
        self.mock_scanner = MagicMock()
        self.mock_scanner.get_stock_map.return_value = {"2330": "台積電", "2317": "鴻海"}

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_daemon(self):
        from trading.ohlcv_daemon import OHLCVDaemon
        return OHLCVDaemon(ohlcv_db=self.db, scanner=self.mock_scanner)

    def test_not_running_initially(self):
        d = self._make_daemon()
        self.assertFalse(d.is_running())

    def test_start_and_stop(self):
        d = self._make_daemon()
        started = threading.Event()
        original_loop = d._loop
        def patched_loop():
            started.set()
        d._loop = patched_loop
        d.start()
        self.assertTrue(started.wait(timeout=2.0))
        d.stop()

    @patch("yfinance.Ticker")
    def test_fetch_one_success(self, mock_ticker):
        mock_ticker.return_value.history.return_value = _mock_yf_history()
        d = self._make_daemon()
        ok = d._fetch_one("2330", period="5d")
        self.assertTrue(ok)
        # 確認 DB 有資料
        df = self.db.load("2330", days=30)
        self.assertIsNotNone(df)
        self.assertGreater(len(df), 0)

    @patch("yfinance.Ticker")
    def test_fetch_one_failure(self, mock_ticker):
        mock_ticker.return_value.history.return_value = pd.DataFrame()
        d = self._make_daemon()
        ok = d._fetch_one("9999", period="5d")
        self.assertFalse(ok)

    @patch("yfinance.Ticker")
    def test_incremental_update(self, mock_ticker):
        mock_ticker.return_value.history.return_value = _mock_yf_history()
        d = self._make_daemon()
        d.incremental_update()
        # 兩檔都應該有資料
        self.assertIsNotNone(self.db.load("2330", days=30))
        self.assertIsNotNone(self.db.load("2317", days=30))

    @patch("yfinance.Ticker")
    def test_backfill(self, mock_ticker):
        mock_ticker.return_value.history.return_value = _mock_yf_history(100)
        d = self._make_daemon()
        d.backfill()
        stats = self.db.stats()
        self.assertGreater(stats["total_rows"], 0)

    def test_get_all_codes(self):
        d = self._make_daemon()
        codes = d._get_all_codes()
        self.assertEqual(len(codes), 2)
        self.assertIn("2330", codes)

    def test_get_all_codes_failure(self):
        self.mock_scanner.get_stock_map.side_effect = Exception("network error")
        d = self._make_daemon()
        codes = d._get_all_codes()
        self.assertEqual(codes, [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: 跑測試**

```bash
.venv/Scripts/python.exe -m unittest tests/test_ohlcv_daemon.py -v
```

Expected: 8 tests, all PASS

- [ ] **Step 4: 跑全部測試**

```bash
.venv/Scripts/python.exe -m unittest discover tests/ 2>&1 | tail -5
```

Expected: 425+ tests OK

- [ ] **Step 5: Commit**

```bash
git add trading/ohlcv_daemon.py tests/test_ohlcv_daemon.py
git commit -m "feat: OHLCVDaemon 全市場每日增量更新

每日 14:00 增量更新 ~2000 檔（period=5d，約 10-15 分鐘）。
首次啟動自動回填（period=max，約 1-2 小時）。8 個測試通過。"
```

---

## Task 2: 修改 fetch_ohlcv — DB 優先讀取

**Files:**
- Modify: `trading/indicators.py`
- Modify: `trading/ohlcv_db.py`
- Modify: `tests/test_indicators.py`

- [ ] **Step 1: 在 `trading/indicators.py` 頂部新增 `_period_to_days` 輔助函式**

在 import 區塊之後、class 定義之前加入：

```python
_PERIOD_DAYS = {
    "1mo": 22, "3mo": 66, "6mo": 130, "1y": 252,
    "2y": 504, "3y": 756, "5y": 1260, "max": 99999,
}

def _period_to_days(period: str) -> int:
    return _PERIOD_DAYS.get(period, 130)
```

- [ ] **Step 2: 替換 `fetch_ohlcv()` 方法的快取邏輯**

找到 `fetch_ohlcv` 方法（line ~154）。將整個方法中的快取讀取段落（目前是 load 300 天 + 檢查 latest_date >= yesterday-3）替換為 DB 優先邏輯：

找到這段：
```python
        # ── 1. 本地快取 ──────────────────────────────────────────
```
到
```python
        # ── 2. yfinance fallback ─────────────────────────────────
```
之間的快取邏輯，替換為：

```python
        # ── 1. DB 優先讀取 ───────────────────────────────────────
        need_days = _period_to_days(period)
        try:
            cached = self._db.load(code, days=need_days)
            if cached is not None and len(cached) >= need_days * 0.8:
                return cached
        except Exception as e:
            logger.warning("DB 讀取失敗 (%s): %s", code, e)
```

保留 yfinance fallback 段落不動（它會在 DB 不夠時觸發）。

- [ ] **Step 3: 修改 `ohlcv_db.py` 的 `load()` 預設天數**

找到 `load` 方法簽名（line 76）：
```python
def load(self, code: str, days: int = 300) -> Optional[pd.DataFrame]:
```

改為：
```python
def load(self, code: str, days: int = 600) -> Optional[pd.DataFrame]:
```

（預設值加大到 600，掃描和回測都夠用）

- [ ] **Step 4: 在 `tests/test_indicators.py` 新增 DB 優先讀取測試**

在 `TestFetchOhlcv` class 末尾新增：

```python
    @patch("yfinance.Ticker")
    def test_returns_cached_data_when_sufficient(self, mock_ticker):
        """DB 有足夠資料時不呼叫 yfinance。"""
        # 先寫入 200 天快取
        dates = pd.date_range("2025-06-01", periods=200, freq="B")
        df = pd.DataFrame({
            "open": range(200), "high": range(200), "low": range(200),
            "close": range(200), "volume": [1000] * 200,
        }, index=dates)
        self.engine._db.upsert("9999", df)

        result = self.engine.fetch_ohlcv("9999", period="6mo")
        self.assertIsNotNone(result)
        self.assertGreater(len(result), 0)
        # yfinance 不應被呼叫
        mock_ticker.assert_not_called()

    @patch("yfinance.Ticker")
    def test_falls_back_to_yfinance_when_insufficient(self, mock_ticker):
        """DB 資料不足時 fallback 到 yfinance。"""
        # 只寫入 10 天快取（不夠 6mo=130 天的 80%）
        dates = pd.date_range("2026-04-01", periods=10, freq="B")
        df = pd.DataFrame({
            "open": range(10), "high": range(10), "low": range(10),
            "close": range(10), "volume": [1000] * 10,
        }, index=dates)
        self.engine._db.upsert("8888", df)

        mock_ticker.return_value.history.return_value = self._make_yf_df()
        result = self.engine.fetch_ohlcv("8888", period="6mo")
        self.assertIsNotNone(result)
        # yfinance 應被呼叫
        mock_ticker.assert_called()
```

- [ ] **Step 5: 跑全部測試**

```bash
.venv/Scripts/python.exe -m unittest discover tests/ 2>&1 | tail -5
```

Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add trading/indicators.py trading/ohlcv_db.py tests/test_indicators.py
git commit -m "refactor: fetch_ohlcv 改為 DB 優先讀取

DB 有足夠歷史 → 直接用；不夠 → yfinance 補齊 → 寫回 DB。
load() 預設天數 300→600。新增 _period_to_days 對照。"
```

---

## Task 3: 系統整合

**Files:**
- Modify: `trading/services/container.py`
- Modify: `run.py`

- [ ] **Step 1: 在 `container.py` 新增 `ohlcv_daemon` property**

在 `__init__` 中加入 `self._ohlcv_daemon = None`。

新增 property（在 `ohlcv_db` property 之後）：

```python
    @property
    def ohlcv_daemon(self):
        if self._ohlcv_daemon is None:
            with self._lock:
                if self._ohlcv_daemon is None:
                    from trading.ohlcv_daemon import OHLCVDaemon
                    self._ohlcv_daemon = OHLCVDaemon(
                        ohlcv_db=self.ohlcv_db,
                        scanner=self.scanner,
                    )
        return self._ohlcv_daemon
```

- [ ] **Step 2: 在 `run.py` 啟動 OHLCVDaemon**

在 `intel_daemon.start()` 區塊之後加入：

```python
    ohlcv_daemon = _svc.ohlcv_daemon
    ohlcv_daemon.start()
    print(f"   OHLCV更新:  ✅ 已啟動（每日 14:00 全市場增量更新）")
```

- [ ] **Step 3: 跑全部測試**

```bash
.venv/Scripts/python.exe -m unittest discover tests/ 2>&1 | tail -5
```

- [ ] **Step 4: Commit & Push**

```bash
git add trading/services/container.py run.py
git commit -m "feat: OHLCVDaemon 系統整合

container.py 新增 ohlcv_daemon property，run.py 啟動時自動啟動。"
git push
```

---

## Spec 覆蓋對照

| Spec 區塊 | Task |
|-----------|------|
| 3-1 OHLCVDaemon | Task 1 |
| 4 修改 fetch_ohlcv | Task 2 |
| 5 修改 ohlcv_db.load | Task 2 |
| 6 整合 container + run.py | Task 3 |
| 7 不改動項目 | 未觸碰 |
