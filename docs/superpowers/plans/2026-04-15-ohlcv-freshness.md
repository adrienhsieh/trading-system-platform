# OHLCV 資料新鮮度改善 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 確保台股掃描和回測使用的 OHLCV 數據包含最新收盤資料，以 14:00 為分界線判斷預期最新交易日。

**Architecture:** 在 `IndicatorEngine.fetch_ohlcv()` 的 DB 快取判斷中加入日期新鮮度檢查（新增 `_expected_latest_trade_date()` 模組級函式）。前端觀察名單快取從每日一次改為 5 分鐘 TTL。不動 DB schema、不動上層 API/掃描/回測邏輯。

**Tech Stack:** Python 3 (datetime, zoneinfo), pandas, unittest, JavaScript

**Spec:** `docs/superpowers/specs/2026-04-15-ohlcv-freshness-design.md`

---

## File Structure

| 檔案 | 動作 | 職責 |
|------|------|------|
| `trading/indicators.py` | Modify | 新增 `_expected_latest_trade_date()`，修改 `fetch_ohlcv()` 新鮮度判斷 |
| `index.html` | Modify | 觀察名單快取改為 5 分鐘 TTL |
| `tests/test_indicators.py` | Modify | 新增新鮮度函式和 fetch_ohlcv 新鮮度邏輯的測試 |

---

## Task 1: `_expected_latest_trade_date()` 函式 — 測試

**Files:**
- Modify: `tests/test_indicators.py`

- [ ] **Step 1: Write failing tests for `_expected_latest_trade_date()`**

在 `tests/test_indicators.py` 末尾新增測試類別：

```python
from unittest.mock import patch
from datetime import datetime, date
from zoneinfo import ZoneInfo

class TestExpectedLatestTradeDate(unittest.TestCase):
    """_expected_latest_trade_date() 單元測試"""

    def _call(self, fake_now: datetime) -> date:
        with patch("trading.indicators._now_taipei", return_value=fake_now):
            from trading.indicators import _expected_latest_trade_date
            return _expected_latest_trade_date()

    def test_weekday_after_14(self):
        """工作日 14:00 後 → 回傳當天"""
        # 2026-04-15 週三 15:00
        result = self._call(datetime(2026, 4, 15, 15, 0, tzinfo=ZoneInfo("Asia/Taipei")))
        self.assertEqual(result, date(2026, 4, 15))

    def test_weekday_before_14(self):
        """工作日 14:00 前 → 回傳前一個交易日"""
        # 2026-04-15 週三 09:00 → 前一交易日 = 4/14 週二
        result = self._call(datetime(2026, 4, 15, 9, 0, tzinfo=ZoneInfo("Asia/Taipei")))
        self.assertEqual(result, date(2026, 4, 14))

    def test_weekday_at_14(self):
        """工作日 14:00 整點 → 回傳當天（>= 14）"""
        result = self._call(datetime(2026, 4, 15, 14, 0, tzinfo=ZoneInfo("Asia/Taipei")))
        self.assertEqual(result, date(2026, 4, 15))

    def test_saturday(self):
        """週六 → 回傳週五"""
        # 2026-04-18 週六
        result = self._call(datetime(2026, 4, 18, 10, 0, tzinfo=ZoneInfo("Asia/Taipei")))
        self.assertEqual(result, date(2026, 4, 17))

    def test_sunday(self):
        """週日 → 回傳週五"""
        # 2026-04-19 週日
        result = self._call(datetime(2026, 4, 19, 10, 0, tzinfo=ZoneInfo("Asia/Taipei")))
        self.assertEqual(result, date(2026, 4, 17))

    def test_monday_before_14(self):
        """週一 09:00 → 回傳上週五"""
        # 2026-04-20 週一 09:00
        result = self._call(datetime(2026, 4, 20, 9, 0, tzinfo=ZoneInfo("Asia/Taipei")))
        self.assertEqual(result, date(2026, 4, 17))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m unittest tests.test_indicators.TestExpectedLatestTradeDate -v 2>&1 | grep -E "FAIL|ERROR|OK|Ran"`
Expected: ERROR — `_now_taipei` and `_expected_latest_trade_date` not found

---

## Task 2: `_expected_latest_trade_date()` 函式 — 實作

**Files:**
- Modify: `trading/indicators.py`

- [ ] **Step 1: Add `_now_taipei()` and `_expected_latest_trade_date()` to `trading/indicators.py`**

在 `_period_to_days` 函式之後、`_yf_throttle_lock` 之前（line 32 附近）插入：

```python
from zoneinfo import ZoneInfo

_TZ_TAIPEI = ZoneInfo("Asia/Taipei")


def _now_taipei() -> datetime.datetime:
    """取得當前 Asia/Taipei 時間（獨立函式以利測試 mock）。"""
    return datetime.datetime.now(_TZ_TAIPEI)


def _expected_latest_trade_date() -> datetime.date:
    """根據台股收盤時間推算預期最新交易日。

    規則：14:00 後用當天，14:00 前用前一天；跳過週六日。
    國定假日不處理（yfinance 會自動跳過無資料日）。
    """
    now = _now_taipei()
    if now.hour >= 14:
        base = now.date()
    else:
        base = now.date() - datetime.timedelta(days=1)
    # 跳過週末
    while base.weekday() >= 5:  # 5=Sat, 6=Sun
        base -= datetime.timedelta(days=1)
    return base
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `.venv\Scripts\python.exe -m unittest tests.test_indicators.TestExpectedLatestTradeDate -v 2>&1 | grep -E "FAIL|ERROR|OK|Ran|ok"`
Expected: `Ran 6 tests ... OK`

- [ ] **Step 3: Commit**

```bash
git add trading/indicators.py tests/test_indicators.py
git commit -m "feat: add _expected_latest_trade_date() for OHLCV freshness check

新增台股交易日判斷函式，14:00 為分界線，跳過週末。
含 6 個邊界情況測試。"
```

---

## Task 3: `fetch_ohlcv()` 新鮮度判斷 — 測試

**Files:**
- Modify: `tests/test_indicators.py`

- [ ] **Step 1: Write failing tests for `fetch_ohlcv()` freshness logic**

在 `tests/test_indicators.py` 末尾新增：

```python
from trading.ohlcv_db import OHLCVDatabase
import tempfile, shutil, os
import numpy as np


def _make_ohlcv_df(end_date: date, n: int = 100) -> pd.DataFrame:
    """產生以 end_date 為最後一天的 n 個工作日 OHLCV。"""
    close = 100.0 + np.arange(n, dtype=float)
    idx = pd.bdate_range(end=end_date, periods=n)
    return pd.DataFrame({
        "open": close * 0.99, "high": close * 1.01,
        "low": close * 0.98, "close": close,
        "volume": np.full(n, 10_000.0),
    }, index=idx)


class TestFetchOhlcvFreshness(unittest.TestCase):
    """fetch_ohlcv() 新鮮度判斷測試"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "test.db")

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    @patch("trading.indicators._expected_latest_trade_date")
    @patch("trading.indicators._fetch_with_retry")
    def test_fresh_db_skips_yfinance(self, mock_fetch, mock_expected):
        """DB 有最新資料 → 不打 yfinance"""
        mock_expected.return_value = date(2026, 4, 15)
        db = OHLCVDatabase(db_path=self.db_path)
        df = _make_ohlcv_df(date(2026, 4, 15), n=130)
        db.upsert("2330", df)

        eng = IndicatorEngine.__new__(IndicatorEngine)
        eng._db = db
        result = eng.fetch_ohlcv("2330", period="6mo")

        self.assertIsNotNone(result)
        mock_fetch.assert_not_called()

    @patch("trading.indicators._expected_latest_trade_date")
    @patch("trading.indicators._fetch_with_retry")
    def test_stale_db_calls_yfinance(self, mock_fetch, mock_expected):
        """DB 資料過期 → 打 yfinance 補抓"""
        mock_expected.return_value = date(2026, 4, 15)
        db = OHLCVDatabase(db_path=self.db_path)
        df = _make_ohlcv_df(date(2026, 4, 10), n=130)
        db.upsert("2330", df)

        fresh_df = _make_ohlcv_df(date(2026, 4, 15), n=130)
        fresh_df.columns = ["Open", "High", "Low", "Close", "Volume"]
        mock_fetch.return_value = fresh_df

        eng = IndicatorEngine.__new__(IndicatorEngine)
        eng._db = db
        result = eng.fetch_ohlcv("2330", period="6mo")

        self.assertIsNotNone(result)
        mock_fetch.assert_called()

    @patch("trading.indicators._expected_latest_trade_date")
    @patch("trading.indicators._fetch_with_retry")
    def test_stale_db_yfinance_fails_falls_back(self, mock_fetch, mock_expected):
        """DB 資料過期但 yfinance 失敗 → fallback DB"""
        mock_expected.return_value = date(2026, 4, 15)
        db = OHLCVDatabase(db_path=self.db_path)
        df = _make_ohlcv_df(date(2026, 4, 10), n=130)
        db.upsert("2330", df)

        mock_fetch.return_value = None

        eng = IndicatorEngine.__new__(IndicatorEngine)
        eng._db = db
        result = eng.fetch_ohlcv("2330", period="6mo")

        self.assertIsNotNone(result)
        self.assertEqual(len(result), 130)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv\Scripts\python.exe -m unittest tests.test_indicators.TestFetchOhlcvFreshness -v 2>&1 | grep -E "FAIL|ERROR|OK|Ran"`
Expected: FAIL — `test_fresh_db_skips_yfinance` fails because current code doesn't check freshness, `test_stale_db_yfinance_fails_falls_back` may pass (existing fallback logic)

---

## Task 4: `fetch_ohlcv()` 新鮮度判斷 — 實作

**Files:**
- Modify: `trading/indicators.py:164-192`

- [ ] **Step 1: Modify `fetch_ohlcv()` to add freshness check**

Replace the DB cache section (lines 164-192) with:

```python
    def fetch_ohlcv(self, ticker: str, period: str = "6mo") -> Optional[pd.DataFrame]:
        """
        抓取 OHLCV 日線資料。
        優先使用本地 SQLite 快取（ohlcv_cache.db）；
        若快取不存在或資料不夠新，再從 yfinance 補抓並回寫快取。
        上市股使用 {code}.TW，上櫃股使用 {code}.TWO（先試 .TW，失敗再試 .TWO）。
        """
        code = ticker.replace(".TW", "").replace(".TWO", "")
        cached = None

        # ── 1. DB 優先讀取 ───────────────────────────────────────
        need_days = _period_to_days(period)
        cal_days = int(need_days * 1.5)   # 交易日 → 日曆日（含假日）
        try:
            cached = self._db.load(code, days=cal_days)
            if cached is not None and len(cached) >= need_days * 0.8:
                # ── 新鮮度檢查：DB 最新日期 >= 預期最新交易日才回傳 ──
                expected = _expected_latest_trade_date()
                db_latest = cached.index[-1].date() if hasattr(cached.index[-1], 'date') else cached.index[-1]
                if db_latest >= expected:
                    return cached
        except Exception as e:
            logger.warning("DB 讀取失敗 (%s): %s", code, e)

        # ── 2. 從 yfinance 抓取：先試 .TW（上市），失敗再試 .TWO（上櫃）
        raw = _fetch_with_retry(f"{code}.TW", period=period, timeout=8)
        if raw is None or raw.empty:
            raw = _fetch_with_retry(f"{code}.TWO", period=period, timeout=8)
        if raw is None or raw.empty:
            # 3. DB 有部分資料也回傳（勝過 None）
            if cached is not None and not cached.empty:
                return cached
            return None

        try:
            raw.columns = [c.strip() for c in raw.columns]
            rename_map = {
                "Open": "open", "High": "high", "Low": "low",
                "Close": "close", "Volume": "volume",
            }
            df = raw.rename(columns=rename_map)

            needed = ["open", "high", "low", "close", "volume"]
            if not all(c in df.columns for c in needed):
                return None

            df = df[needed].copy()
            for col in needed:
                s = df[col]
                if isinstance(s, pd.DataFrame):
                    s = s.iloc[:, 0]
                df[col] = pd.to_numeric(s.squeeze(), errors="coerce")

            df = df.dropna()

            # 回寫快取
            if not df.empty:
                try:
                    self._db.upsert(code, df)
                except Exception as _e:
                    logger.warning("快取寫入失敗 %s: %s", code, _e)

            return df
        except Exception as e:
            logger.warning("fetch %s 處理失敗: %s", ticker, e)
            return None
```

Key change: lines after `len(cached) >= need_days * 0.8` now also check `db_latest >= expected` before returning cached data.

- [ ] **Step 2: Run freshness tests to verify they pass**

Run: `.venv\Scripts\python.exe -m unittest tests.test_indicators.TestFetchOhlcvFreshness -v 2>&1 | grep -E "FAIL|ERROR|OK|Ran|ok"`
Expected: `Ran 3 tests ... OK`

- [ ] **Step 3: Run ALL tests to check for regressions**

Run: `.venv\Scripts\python.exe -m unittest discover tests/ 2>&1 | grep -E "^(Ran|OK|FAIL|ERROR)"`
Expected: `Ran 4xx tests ... OK`

- [ ] **Step 4: Commit**

```bash
git add trading/indicators.py tests/test_indicators.py
git commit -m "feat: fetch_ohlcv() 加入 2PM 分界線新鮮度檢查

DB 快取除了筆數 >= 80% 外，還檢查最新日期是否 >= 預期最新交易日。
14:00 後用當天、14:00 前用前一個交易日。過期則走 yfinance 補抓。"
```

---

## Task 5: 前端觀察名單快取 — 改為 5 分鐘 TTL

**Files:**
- Modify: `index.html:1307-1308, 1360-1376`

- [ ] **Step 1: Change cache variables from date-based to timestamp-based**

In `index.html`, replace lines 1307-1308:

```javascript
let _wlAnalysisCache = null;
let _wlAnalysisDate = '';
```

with:

```javascript
let _wlAnalysisCache = null;
let _wlAnalysisTime = 0;
const _WL_CACHE_TTL = 5 * 60_000;  // 5 分鐘
```

- [ ] **Step 2: Update `loadWatchlistAnalysis()` to use TTL-based cache**

In `index.html`, replace the cache check in `loadWatchlistAnalysis()` (lines 1360-1376):

```javascript
async function loadWatchlistAnalysis() {
  const today = new Date().toISOString().slice(0, 10);
  if (_wlAnalysisCache && _wlAnalysisDate === today) {
    renderWatchlistAnalysis(_wlAnalysisCache);
    return;
  }
```

with:

```javascript
async function loadWatchlistAnalysis() {
  if (_wlAnalysisCache && (Date.now() - _wlAnalysisTime < _WL_CACHE_TTL)) {
    renderWatchlistAnalysis(_wlAnalysisCache);
    return;
  }
```

And replace the cache update line:

```javascript
    _wlAnalysisCache = r.results || [];
    _wlAnalysisDate = today;
```

with:

```javascript
    _wlAnalysisCache = r.results || [];
    _wlAnalysisTime = Date.now();
```

- [ ] **Step 3: Verify `saveWlAdd()` and `removeWl()` still invalidate cache correctly**

Check that `_wlAnalysisCache = null;` in `saveWlAdd()` (line 1324) and `removeWl()` (line 1332) still works — setting `_wlAnalysisCache = null` will cause the TTL check `_wlAnalysisCache && ...` to be falsy, so no changes needed.

- [ ] **Step 4: Run all tests to verify no regressions**

Run: `.venv\Scripts\python.exe -m unittest discover tests/ 2>&1 | grep -E "^(Ran|OK|FAIL|ERROR)"`
Expected: `Ran 4xx tests ... OK`

- [ ] **Step 5: Commit**

```bash
git add index.html
git commit -m "feat: 觀察名單快取從每日一次改為 5 分鐘 TTL

避免整天看到同一份分析結果，5 分鐘內重複切換仍用快取避免多餘請求。"
```

---

## Task 6: 最終驗證

- [ ] **Step 1: Run full test suite**

Run: `.venv\Scripts\python.exe -m unittest discover tests/ 2>&1 | grep -E "^(Ran|OK|FAIL|ERROR)"`
Expected: All tests pass, 0 failures

- [ ] **Step 2: Update spec status**

In `docs/superpowers/specs/2026-04-15-ohlcv-freshness-design.md`, change:

```
> 狀態：待實作
```

to:

```
> 狀態：已完成
```

- [ ] **Step 3: Final commit**

```bash
git add docs/superpowers/specs/2026-04-15-ohlcv-freshness-design.md
git commit -m "docs: mark OHLCV freshness spec as complete"
```
