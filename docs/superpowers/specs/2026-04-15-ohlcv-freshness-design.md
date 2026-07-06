# OHLCV 資料新鮮度改善設計

> 日期：2026-04-15
> 狀態：已完成

## 問題

台股掃描和回測使用的 OHLCV 數據可能是數天前的舊資料。根因是 `fetch_ohlcv()` 只檢查 DB 中的筆數是否足夠（≥80%），不檢查資料是否為最新。DB 中有足夠筆數的舊資料時，直接回傳而不去 yfinance 補抓最新收盤價。

## 目標

1. 掃描和回測使用的 OHLCV 數據必須包含最新可用的收盤資料
2. 下午 14:00 前使用前一個交易日的資料，14:00 後使用當天資料
3. 前端觀察名單快取從每日一次改為 5 分鐘 TTL
4. 不改變 DB schema，不改變上層 API/掃描/回測邏輯

## 設計

### 1. 預期最新交易日函式

新增 `_expected_latest_trade_date()` 於 `trading/indicators.py`：

```
輸入：無（使用系統時間，Asia/Taipei 時區）
輸出：datetime.date — 預期 DB 中應有的最新交易日

邏輯：
  now = 當前 Asia/Taipei 時間
  if now.hour >= 14:
      base = now.date()        # 今天
  else:
      base = now.date() - 1天  # 昨天

  while base 是週六或週日:
      base -= 1天

  return base
```

國定假日暫不處理。yfinance 在假日不會有資料，此時 DB 的最新日期會是假日前一個交易日，fetch_ohlcv 會嘗試 yfinance 補抓但拿不到新資料，fallback 回 DB 現有資料。這個行為是正確的 — 假日本來就沒有新的收盤價。

### 2. fetch_ohlcv() 新鮮度檢查

修改 `trading/indicators.py` 的 `fetch_ohlcv()` 方法：

```
現有流程：
  1. 從 DB load
  2. 筆數 >= 80% → 直接回傳
  3. 否則 → yfinance 抓取 → upsert DB → 回傳

改為：
  1. 從 DB load
  2. expected = _expected_latest_trade_date()
  3. db_latest = DB 中該 code 最新日期（從 cached DataFrame 的 index 取）
  4. if cached 筆數 >= 80% AND db_latest >= expected:
       回傳 cached          ← 資料夠新且筆數足夠
  5. 否則 → yfinance 抓取 → upsert DB → 回傳
  6. yfinance 失敗 → fallback 回 cached（現有邏輯不變）
```

db_latest 直接從已載入的 cached DataFrame 的最後一筆 index 取得，不額外查 DB。

### 3. 前端觀察名單快取

修改 `index.html` 中的觀察名單分析快取：

```
現有：
  _wlAnalysisCache = null     // 分析結果
  _wlAnalysisDate = ''        // 日期字串，整天只 fetch 一次

改為：
  _wlAnalysisCache = null     // 分析結果
  _wlAnalysisTime = 0         // Unix timestamp（毫秒）
  WL_CACHE_TTL = 300000       // 5 分鐘

判斷邏輯：
  if (_wlAnalysisCache && (Date.now() - _wlAnalysisTime < WL_CACHE_TTL)):
      使用快取
  else:
      fetch API → 更新 _wlAnalysisCache 和 _wlAnalysisTime
```

## 影響範圍

### 會改的檔案

| 檔案 | 改動 |
|------|------|
| `trading/indicators.py` | `fetch_ohlcv()` 加新鮮度判斷；新增 `_expected_latest_trade_date()` |
| `index.html` | 觀察名單快取改為 5 分鐘 TTL |
| `tests/` | 新增新鮮度判斷的單元測試 |

### 不動的檔案

| 項目 | 原因 |
|------|------|
| `trading/ohlcv_db.py` | DB 層不需要改，新鮮度判斷在 fetch 層 |
| `ohlcv_cache.db` schema | 不變 |
| `trading/scanner.py` | 股票/產業清單 12hr TTL 不在此次範圍 |
| `trading/market.py` | 大盤 5min TTL 不在此次範圍 |
| `trading/api/*` | 所有掃描/回測 API 都經過 fetch_ohlcv()，上游修好下游自動受益 |
| `trading/telegram/bot.py` | 同上 |

## 邊界情況

| 情況 | 預期行為 |
|------|---------|
| 週六日呼叫 | expected = 週五，DB 有週五 → 直接回傳 |
| 週一 14:00 前 | expected = 上週五 |
| 國定假日 | expected = 假日當天（非週末），yfinance 無資料，fallback DB → 回傳假日前最後交易日資料 |
| yfinance rate limit | fallback 回 DB 舊資料（現有行為不變） |
| 新股無歷史 | DB 無資料 → yfinance 抓取 → 正常流程 |
| 14:00 整點 | >= 14 判斷包含 14:00，使用當天資料 |

## 測試計畫

1. `_expected_latest_trade_date()` 單元測試：
   - 工作日 14:00 後 → 回傳當天
   - 工作日 14:00 前 → 回傳前一個交易日
   - 週六 → 回傳週五
   - 週日 → 回傳週五
   - 週一 09:00 → 回傳上週五

2. `fetch_ohlcv()` 新鮮度整合測試：
   - DB 有最新資料 → 不打 yfinance
   - DB 資料過期 → 打 yfinance 補抓
   - DB 資料過期但 yfinance 失敗 → fallback DB

3. 前端觀察名單快取：
   - 5 分鐘內重複切換 → 不重新 fetch
   - 超過 5 分鐘 → 重新 fetch
