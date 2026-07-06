# 系統架構說明

## 目錄

- [整體架構](#整體架構)
- [安全層](#安全層)
- [模組職責](#模組職責)
- [資料層](#資料層)
- [執行緒模型](#執行緒模型)
- [資料流](#資料流)
- [跨模組依賴關係](#跨模組依賴關係)

---

## 整體架構

```
┌─────────────────────────────────────────────────────────────┐
│  啟動層                                                       │
│  run.py  → 載入 .env → import app → 取得 container 服務單例  │
│            → 建立 Bot/Scheduler → intel_daemon.start()        │
│            → Flask.run()                                      │
└────────────────────────┬────────────────────────────────────┘
                         │
          ┌──────────────┼──────────────┐
          ▼              ▼              ▼
┌─────────────┐  ┌──────────────┐  ┌──────────────────────┐
│  Web 層      │  │  Bot 層       │  │  情報 Daemon 層       │
│  app.py（76行）│  │  telegram/   │  │  intelligence.py      │
│  + trading/  │  │  bot.py      │  │  背景執行緒            │
│    api/      │  │  scheduler.py│  └──────────────────────┘
│  index.html  │  └──────┬───────┘
│  ─────────── │         │
│  auth.py     │         │
│  rate limit  │         │
└──────┬──────┘          │
       │                 │
       └─────────┬───────┘
                 ▼
┌───────────────────────────────────────────────────────────┐
│  服務容器（trading/services/container.py）                   │
│  ServiceContainer — lazy-init 單例，執行緒安全雙重鎖定       │
└───────────────────────────┬───────────────────────────────┘
                            ▼
┌───────────────────────────────────────────────────────────┐
│  服務層（trading/）                                         │
│  scanner.py  indicators.py  positions.py  market.py        │
│  news.py     backtest.py    strategies/   config.py        │
│  groq_client.py  xmonitor.py   ohlcv_db.py                 │
│  ──────────────────────────────────────────────────────── │
│  logger.py   exceptions.py  constants.py  streaming.py     │
└───────────────────────────────────────────────────────────┘
                         │
┌───────────────────────────────────────────────────────────┐
│  資料層                                                     │
│  positions.db       intelligence.db       ohlcv_cache.db   │
│  (SQLite)           (SQLite)              (SQLite)          │
└───────────────────────────────────────────────────────────┘
```

---

## 安全層

所有 `/api/*` 路由均受以下機制保護（Phase 1 資安強化，2026-04-08）：

### API 認證（`require_auth` decorator）

- 每個請求必須帶 `X-API-Key` header（或 SSE 的 `?key=` query 參數）
- Key 儲存於 `config.json`（`api_key` 欄位），首次啟動自動以 `secrets.token_hex(32)` 產生
- 比對使用 `hmac.compare_digest()`，防止 timing attack
- 無 key 或 key 錯誤 → `401 {"ok": false, "error": "Unauthorized"}`

**首次使用設定：**
1. 啟動後從 `config.json` 讀取 `api_key`
2. 在瀏覽器 Console 執行：`localStorage.setItem('trading_api_key', '<key>')`
3. 重新整理頁面

**SSE 端點（EventSource 不支援自訂 header）需在 URL 帶 key：**
```
/api/scan/full?strategy=trend&key=<api_key>
/api/backtest/full?strategy=trend&key=<api_key>
/api/backtest/optimize?code=2330&key=<api_key>
```
前端的 `api()` 函式與所有 `EventSource` 建立時已自動從 `localStorage` 讀取 key。

### Rate Limiting（Flask-Limiter）

| 端點 | 限制 |
|------|------|
| 全域（所有 /api/*） | 200 req/min per IP |
| `/api/scan/full` | 2 req/min |
| `/api/backtest/full` | 2 req/min |
| `/api/backtest/optimize` | 1 req/5min |
| `/api/intelligence/*` | 10 req/min |
| `/api/ohlcv/update` | 5 req/min |

### CORS

限縮至 `CORS_ORIGIN` env var（預設 `http://localhost:8787`）。

### Security Headers

所有回應自動附加：
- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`

### XXE 防護

`trading/news.py` RSS 解析改用 `defusedxml.ElementTree`，拒絕含外部實體的 XML。

### Telegram Fail-Closed

`TELEGRAM_ALLOWED_IDS` 未設定時，`is_allowed()` 回傳 `False`（拒絕所有人），而非放行所有人。

---

## 模組職責

### 啟動層

| 檔案 | 職責 |
|------|------|
| `run.py` | 唯一啟動入口。載入 `.env`、自動安裝套件、建立 TelegramBot / TradingScheduler，啟動 IntelligenceDaemon，最後啟動 Flask。 |

### API 層

| 檔案 | 職責 |
|------|------|
| `app.py` | Flask 應用程式（76 行）。設定 CORS、掛載 Flask-Limiter、呼叫 `register_blueprints()` 掛載所有路由，定義全域 error handler 與 security headers。不再包含任何路由邏輯。 |
| `trading/api/__init__.py` | `register_blueprints(app)` — 統一掛載 7 個 Blueprint 模組。 |
| `trading/api/auth.py` | `require_auth` decorator（`X-API-Key` + `hmac.compare_digest`）、`validate_code()`、`validate_number()`。 |
| `trading/api/extensions.py` | `Flask-Limiter` 以 `init_app` 模式初始化，避免與 Blueprint 之間的循環 import。 |
| `trading/api/positions.py` | Blueprint：持倉 CRUD（`/api/positions/*`）、即時報價（`/api/prices`）、持倉報告（`/api/report`）。 |
| `trading/api/scan.py` | Blueprint：股票資訊（`/api/stock_info/*`）、個股分析（`/api/analyze/*`）、候選掃描（`/api/scan`）、全市場 SSE 串流（`/api/scan/full`）。 |
| `trading/api/config_bp.py` | Blueprint：設定讀寫（`/api/config`）、策略參數（`/api/strategy_params`）、Coverage API（`/api/coverage/*`）。 |
| `trading/api/backtest.py` | Blueprint：單/多檔回測（`/api/backtest`）、策略參數最佳化（`/api/backtest/optimize`）、全市場回測（`/api/backtest/full`）。 |
| `trading/api/market.py` | Blueprint：大盤行情（`/api/market`）、新聞（`/api/news/*`）。 |
| `trading/api/intelligence.py` | Blueprint：AI 情報（`/api/intelligence/*`）、OHLCV 快取管理（`/api/ohlcv/*`）。 |
| `trading/api/watchlist.py` | Blueprint：觀察名單 CRUD（`/api/watchlist/*`）、觀察名單分析（`/api/watchlist/analyze`）。 |
| `index.html` | 單頁前端應用。使用 Tabler UI 框架，以原生 JavaScript 呼叫後端 API，包含持倉、掃描、回測、財經情報、設定等 Tab。 |

### 服務容器（`trading/services/`）

| 檔案 | 職責 |
|------|------|
| `services/container.py` | `ServiceContainer`：所有服務單例的唯一建立點。每個服務以 `@property` + 雙重鎖定（`threading.Lock`）實作 lazy-init。模組層級 `container = ServiceContainer()` 全系統共用。路由與 `run.py` 均透過 `container.xxx` 取得服務，確保同一份實例。 |

### 服務層（`trading/`）

| 檔案 | 職責 |
|------|------|
| `config.py` | 讀寫 `config.json`。`ConfigManager.load()` 使用深度合併（`_deep_merge`）確保巢狀預設值不被覆蓋。`risk_pct` 屬性依連續虧損次數自動切換 1%/2%。 |
| `constants.py` | 全系統魔法數字集中管理（Phase 2）。`SCAN_WORKERS`、`FULL_SCAN_WORKERS`、`YFINANCE_MIN_INTERVAL`、`MARKET_CACHE_TTL` 等，修改數值只需改此檔。 |
| `exceptions.py` | 自訂例外層級（Phase 2）：`TradingSystemError` → `DataFetchError` / `CacheError` / `StrategyError` / `ConfigError`。Flask 全域 error handler 捕捉並回傳 500 + JSON。 |
| `logger.py` | `get_logger(name)` + `setup_root_level()` — 統一結構化日誌（`LOG_LEVEL` 環境變數控制）。全系統 `print()` 均已替換。 |
| `streaming.py` | `SSEStream`：SSE 事件序列化工具類（Phase 3）。`start()`、`progress()`、`result()`、`done()`、`scan_start()`、`bt_result()` 等，統一 SSE payload 格式。 |
| `positions.py` | `PositionManager`：管理持倉的 CRUD，讀寫 `positions.db`。支援 `risk_summary()` 計算各持倉的曝險金額。 |
| `indicators.py` | `IndicatorEngine`：純數學輔助（EMA/SMA/ATR/ADX/MACD）與 OHLCV 資料抓取。`_yf_throttle()` 全域節流（`YFINANCE_MIN_INTERVAL=0.3s`）防止 rate limit；`fetch_ohlcv()` 優先讀取本地快取，`analyze_position()` 用於持倉技術警示。 |
| `ohlcv_db.py` | `OHLCVDatabase`：SQLite 本地 OHLCV 快取（`ohlcv_cache.db`）。`save()`/`load()` 以 Parquet 格式儲存 DataFrame，降低重複網路請求。 |
| `strategies/` | 策略套件，詳見 [strategies.md](strategies.md)。REGISTRY 登錄表供 scanner 和 backtest 使用。 |
| `scanner.py` | `StockScanner`：呼叫 TWSE/TPEX API 取得全市場股票清單（12 小時 TTL 快取），對每支股票執行策略 `compute()` + `calc_entry_params()`，支援趨勢/ICT/基本面策略掃描。全市場 SSE 掃描使用 `ThreadPoolExecutor(max_workers=FULL_SCAN_WORKERS=2)` 搭配 `_yf_throttle` 避免 rate limit。 |
| `backtest.py` | `BacktestEngine`：Walk-forward 回測引擎。逐根 K 棒前向推進，停損優先（用當日最低價），目標其次（用當日最高價）。支援單標的 `run()` 與多標的平行 `run_multi()`。 |
| `market.py` | `MarketService`：以 yfinance 抓取台股加權指數、NASDAQ、S&P500、USD/TWD 匯率，5 分鐘 TTL 快取，以 `threading.Event` 防止重複觸發背景抓取。 |
| `news.py` | `NewsAggregator`：並行抓取多個財經 RSS feed（鉅亨、Yahoo、工商、中央社），回傳去重後的新聞列表。使用 `defusedxml.ElementTree` 防止 XXE 攻擊。 |
| `groq_client.py` | `GroqClient`：封裝 Groq API（Llama 3.3，OpenAI 相容格式），用於新聞逐則情緒分析與每日市場摘要生成。 |
| `xmonitor.py` | `XMonitor`：以 Grok API（xAI）為主、Google News RSS 為備援，收集 X/Twitter 市場討論。以 `content_hash`（MD5）+ `INSERT OR IGNORE` 避免重複。 |
| `intelligence.py` | `IntelligenceDaemon`：背景執行緒 Daemon。每 5 分鐘收集新聞並以 Groq 逐則分析情緒，每 60 分鐘收集 X 討論，每天 08:00 生成每日摘要。資料存入 `intelligence.db`。 |

### Telegram 層（`trading/telegram/`）

| 檔案 | 職責 |
|------|------|
| `bot.py` | `TelegramBot`：透過 constructor injection 取得所有服務實例。實作所有指令處理（`_cmd_*`）。`start_polling()` 使用 `threading.Event` 支援優雅停止。`send()` 自動在換行處切割超過 4000 字元的訊息。 |
| `scheduler.py` | `TradingScheduler`：以閾值比較（`now_hm >= target_hm`）取代精確時間比對，避免 60 秒輪詢粒度導致錯過觸發時間。08:30 推播盤前早報，13:30 推播收盤報告。 |

---

## 資料層

| 資料庫 | 用途 | 主要資料表 |
|--------|------|-----------|
| `positions.db` | 持倉管理 | `positions`（持倉記錄） |
| `intelligence.db` | 情報收集 | `news_intelligence`（新聞與情緒）、`x_posts`（X 討論）、`daily_summary`（每日摘要） |
| `ohlcv_cache.db` | K 線快取 | `ohlcv_cache`（以 Parquet 格式儲存的 OHLCV DataFrame） |

---

## 執行緒模型

`run.py` 主執行緒啟動 Flask，其餘功能均以 daemon thread 執行：

| 執行緒 | 觸發時間 | 職責 |
|--------|---------|------|
| `_open_browser` | 啟動後 1.2 秒 | 自動開啟瀏覽器 |
| `_preload` | 啟動後 1 秒 | 預熱大盤資料 + 股票代號表 |
| `_start_bot` | 啟動後 2 秒 | 啟動 Telegram Bot long-polling |
| `_start_scheduler` | 啟動後 5 秒 | 啟動自動推播排程（08:30 / 13:30） |
| `MarketService._fetch` | 按需觸發（TTL=5min） | 背景更新大盤資料 |
| `IntelligenceDaemon._loop` | 持續運行 | 新聞收集、X 討論收集、每日摘要生成 |

`MarketService` 以 `threading.Lock` 保護 `_fetching` 旗標，確保同時只有一個背景抓取任務執行。

---

## 資料流

### 個股分析流程

```
使用者 /分析 2330
  └─ TelegramBot._cmd_analyze()
       └─ StockScanner.analyze_one("2330", capital, risk_pct)
            ├─ IndicatorEngine.fetch_ohlcv("2330.TW")
            │    ├─ OHLCVDatabase.load()     # 嘗試本地快取
            │    ├─ (快取失效) yfinance.Ticker.history()
            │    └─ OHLCVDatabase.save()     # 存入快取
            ├─ TrendStrategy.compute(df)
            └─ TrendStrategy.calc_entry_params(ind, capital, risk_pct)
```

### 情報 Daemon 流程

```
IntelligenceDaemon._loop()（背景執行緒）
  ├─ 每 5 分鐘：
  │    ├─ NewsAggregator.fetch()         # 抓取 RSS 新聞
  │    └─ GroqClient.analyze_news_sentiments()  # 逐則情緒分析，存入 intelligence.db
  ├─ 每 60 分鐘：
  │    └─ XMonitor.collect()                   # Grok API / Google News，存入 x_posts
  └─ 每天 08:00：
       └─ GroqClient.generate_daily_summary()  # 生成每日摘要，存入 daily_summary
```

### 服務單例共用關係

```
trading/services/container.py（模組層級單例）
  ServiceContainer（lazy-init，雙重鎖定）
    ├─ .config_mgr     → ConfigManager()
    ├─ .pos_mgr        → PositionManager()
    ├─ .ind_engine     → IndicatorEngine()
    ├─ .scanner        → StockScanner(ind_engine)
    ├─ .market_svc     → MarketService()
    ├─ .news_agg       → NewsAggregator()
    ├─ .ohlcv_db       → OHLCVDatabase()
    ├─ .intel_daemon   → IntelligenceDaemon(groq_key, xai_key)
    └─ .coverage_reader → CoverageReader()

app.py（import container，向 run.py 向下相容再匯出）
  ├─ register_blueprints(app)
  │    └─ 各 Blueprint 函式呼叫 container.xxx 取服務
  └─ config_mgr = container.config_mgr  ← run.py backward compat

run.py（從 container 直接取得服務）
  ├─ from trading.services.container import container
  ├─ intel_daemon = container.intel_daemon → .start()
  └─ TelegramBot(config_manager=container.config_mgr,
                 position_manager=container.pos_mgr, ...)
```

所有服務均由 `ServiceContainer` 統一建立（lazy-init），Flask Blueprint 路由、`run.py` 和 Telegram Bot 存取同一份實例，確保狀態一致性。
