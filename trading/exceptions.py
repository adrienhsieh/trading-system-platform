"""
trading/exceptions.py — 系統統一例外層級定義
三層錯誤策略：
  - 可重試（DataFetchError）→ caller 實作 retry with backoff
  - 不可重試（ValidationError）→ log.warning + return None/空結果
  - 系統錯誤（ConfigError / DBError）→ log.error + raise
"""


class TradingSystemError(Exception):
    """所有交易系統錯誤的基底類別。"""


class DataFetchError(TradingSystemError):
    """外部資料抓取失敗（yfinance、RSS、API）。可重試。"""


class CacheError(TradingSystemError):
    """快取讀寫失敗（SQLite OHLCV 快取）。"""


class StrategyError(TradingSystemError):
    """策略計算錯誤（資料不足、指標計算失敗）。"""


class ValidationError(TradingSystemError):
    """輸入驗證失敗（無效代號、格式錯誤）。不可重試。"""


class ConfigError(TradingSystemError):
    """設定檔讀寫失敗（config.json 損毀或權限問題）。"""


class DBError(TradingSystemError):
    """資料庫操作失敗（positions.db、intelligence.db）。"""
