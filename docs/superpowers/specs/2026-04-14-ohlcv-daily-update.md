# OHLCV 全市場每日增量更新

**日期：** 2026-04-14
**狀態：** 已核准
**範疇：** 後端新增 `OHLCVDaemon` + 修改 `fetch_ohlcv()` 讀取邏輯

---

## 1. 目標

將 OHLCV 快取從「按需抓取」改為「每日預先更新」。每日盤後 14:00 自動增量更新全市場 ~2000 檔股票的最新 K 線資料，使掃描和回測直接從本地 DB 讀取，大幅減少 yfinance API 呼叫與等待時間。

---

## 2. 設計決策

| 項目 | 選擇 |
|------|------|
| 更新觸發 | 每日自動（盤後 14:00） |
| 更新範圍 | 全市場（上市+上櫃 ~2000 檔） |
| 首次回填 | 啟動時自動（背景執行，不擋主程式） |
| 讀取邏輯 | DB 優先，不夠再 fallback yfinance 補齊 |

---

## 3. 新增模組

### 3-1. OHLCVDaemon（`trading/ohlcv_daemon.py`）

```python
class OHLCVDaemon:
    DAILY_HOUR = 14
    DAILY_MINUTE = 0
    BATCH_SIZE = 50
    BATCH_SLEEP = 2  # 秒

    def __init__(self, ohlcv_db: OHLCVDatabase, scanner: StockScanner): ...
    def start(self): ...
    def stop(self): ...
    def is_running(self) -> bool: ...
    def _loop(self): ...
    def backfill(self): ...
    def incremental_update(self): ...
```

**生命週期（`_loop`）：**
1. 首次啟動：偵測 DB 行數 < 1000 → 觸發 `backfill()`
2. 之後每日 14:00 → 觸發 `incremental_update()`
3. 迴圈每 60 秒 check 一次

**`backfill()`：**
- 從 `scanner.get_stock_map()` 取得全市場股票清單（~2000 檔）
- 每檔呼叫 `yfinance.Ticker(code).history(period="max")`
- 分批（50 檔/批），批間 sleep 2 秒
- 寫入 `ohlcv_db.upsert(code, df)`
- 預估 1-2 小時完成
- 背景執行，不擋主程式

**`incremental_update()`：**
- 同樣全市場清單
- 每檔呼叫 `yfinance.Ticker(code).history(period="5d")`（只抓最近 5 天）
- `INSERT OR REPLACE` 確保冪等
- 預估 10-15 分鐘完成

---

## 4. 修改 fetch_ohlcv()

### 改動前

```python
def fetch_ohlcv(self, code, period="6mo"):
    # 1. cache 有且 ≤ 3 天 → 回傳
    # 2. yfinance 抓 period → 寫 cache → 回傳
```

### 改動後

```python
def fetch_ohlcv(self, code, period="6mo"):
    need_days = _period_to_days(period)  # 6mo=130, 1y=252, 2y=504

    # 1. 從 DB 讀 need_days 天
    df = self._db.load(code, days=need_days)
    if df is not None and len(df) >= need_days * 0.8:
        return df

    # 2. 不夠 → yfinance 補齊 → 寫回 DB
    df_yf = self._fetch_yfinance(code, period)
    if df_yf is not None:
        self._db.upsert(code, df_yf)
        return df_yf

    # 3. DB 有部分資料也回傳
    return df
```

**`_period_to_days()` 對照表：**

| period | days |
|--------|------|
| `"1mo"` | 22 |
| `"3mo"` | 66 |
| `"6mo"` | 130 |
| `"1y"` | 252 |
| `"2y"` | 504 |
| `"3y"` | 756 |
| `"5y"` | 1260 |
| `"max"` | 99999 |

---

## 5. 修改 ohlcv_db.py

`OHLCVDatabase.load()` 目前硬編碼 300 天：

```python
def load(self, code, days=300):
```

改為支援自訂天數，由 `fetch_ohlcv()` 傳入。

---

## 6. 整合

| 整合點 | 改動 |
|--------|------|
| `trading/services/container.py` | 新增 `ohlcv_daemon` lazy property |
| `run.py` | 啟動 `OHLCVDaemon` |
| `trading/indicators.py` | 修改 `fetch_ohlcv()` 讀取邏輯 |
| `trading/ohlcv_db.py` | `load()` 支援自訂天數 |

---

## 7. 不改動

- `ohlcv_cache.db` schema 不變（per-row 儲存，已有 `INSERT OR REPLACE`）
- `/api/ohlcv/*` 端點保留
- 掃描/回測呼叫端不用改（`fetch_ohlcv` 介面不變）
- `YFINANCE_RETRY_COUNT`、`YFINANCE_MIN_INTERVAL` 常數不變

---

## 8. 效能預估

| 場景 | 改動前 | 改動後 |
|------|--------|--------|
| 全市場掃描（2000 檔） | 每檔 yfinance 抓 6mo，約 10-15 分鐘 | 直接讀 DB，約 30 秒 |
| 回測單檔 2y | yfinance 抓 2y，約 3-5 秒 | 讀 DB，< 0.1 秒 |
| 每日更新成本 | 無 | 14:00 背景跑 10-15 分鐘 |
| 首次回填 | 無 | 1-2 小時（一次性） |

---

## 9. 測試策略

| 測試檔 | 測試對象 |
|--------|---------|
| `tests/test_ohlcv_daemon.py` | OHLCVDaemon start/stop、backfill、incremental_update |
| `tests/test_indicators.py` | 修改後的 fetch_ohlcv 邏輯（DB 優先 + fallback） |
