# Unit Tests

## 執行方式

```bash
# 全部測試（從 trading_system/ 根目錄執行）
.venv\Scripts\python.exe -m unittest discover tests/

# 或
python -m unittest discover tests/ -v

# 單一測試檔
python -m unittest tests/test_config.py -v
```

## 測試覆蓋範圍

| 檔案 | 測試對象 | 測試數 |
|------|---------|-------|
| test_auth.py | API 認證（require_auth、Security Headers） | 7 |
| test_config.py | ConfigManager（含 api_key 自動產生） | 16 |
| test_indicators.py | IndicatorEngine | 37 |
| test_market.py | MarketService | 9 |
| test_news.py | NewsAggregator（含 XXE 拒絕） | 18 |
| test_positions.py | PositionManager | 22 |
| test_scanner.py | StockScanner | 27 |
| test_telegram_bot.py | TelegramBot（含 fail-closed 驗證） | 73 |
| test_scheduler.py | TradingScheduler | 9 |
| test_backtest.py | BacktestEngine | 35 |
| test_intelligence.py | IntelligenceDaemon + GroqClient | 28 |
| test_ohlcv_db.py | OHLCVDatabase | 15 |
| test_coverage.py | CoverageReader | 15 |

**合計：311 個測試案例**

## 設計原則

- **不依賴網路** — 所有外部呼叫（yfinance、requests）皆以 `unittest.mock` 替換
- **不依賴 .env** — Telegram Token 使用測試假值
- **隔離 DB** — PositionManager 使用 `tempfile.TemporaryDirectory()` 暫存資料庫
- **可重複** — 所有隨機資料使用固定 seed
- **資安測試** — test_auth.py 驗證 401 無 key、計時攻擊防護、Security Headers
