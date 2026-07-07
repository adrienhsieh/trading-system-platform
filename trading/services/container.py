"""
trading/services/container.py — 依賴注入容器（多租戶版）
全系統服務單例由此統一管理，lazy-init，執行緒安全。

多人登入隔離策略（外掛式，不動既有業務邏輯／SQL／表結構）：
- pos_mgr（持倉 + 觀察名單）與 config_mgr（總資產／策略參數）依目前請求的
  JWT 登入身分（flask.g.current_user_id）動態切換到物理獨立的檔案：
      db/user_{username}/positions.db
      db/user_{username}/config.json
- 未登入（無 JWT，例如舊版 X-API-Key 呼叫、Telegram Bot、排程器、測試腳本）時
  維持原本行為，讀寫專案根目錄的 positions.db / config.json（單機預設租戶）。
- 全市場共用資源（ohlcv_cache.db、intelligence.db、股票代號表…）完全不受影響，
  所有人共用同一份，只讀不隔離。
"""
import os
import re
import threading
from pathlib import Path

_TENANT_RE = re.compile(r"^[A-Za-z0-9_.-]+$")


def _current_tenant():
    """回傳目前請求的租戶識別碼（登入使用者名稱），未登入或無請求上下文時回傳 None。"""
    try:
        from flask import g, has_request_context
    except Exception:
        return None
    if not has_request_context():
        return None
    username = getattr(g, "current_username", None)
    user_id = getattr(g, "current_user_id", None)
    if not user_id:
        return None
    tenant = str(username or user_id)
    if not _TENANT_RE.match(tenant):
        return None
    return tenant


class ServiceContainer:
    """Lazy-init 服務容器。所有服務皆在首次存取時建立。"""

    def __init__(self):
        self._lock = threading.Lock()
        self._config_mgr     = None   # 單機預設租戶（未登入）
        self._pos_mgr        = None   # 單機預設租戶（未登入）
        self._pos_mgr_by_user    = {}  # {tenant: PositionManager}
        self._config_mgr_by_user = {}  # {tenant: ConfigManager}
        self._ind_engine     = None
        self._scanner        = None
        self._market_svc     = None
        self._news_agg       = None
        self._ohlcv_db       = None
        self._intel_daemon   = None
        self._ohlcv_daemon   = None
        self._coverage_reader = None
        self._intraday_monitor = None
        self._fundamentals = None

    # ── 多租戶專屬資料目錄 ─────────────────────────────────────

    @staticmethod
    def _user_dir(tenant: str) -> Path:
        base = Path(__file__).parent.parent.parent / "db" / f"user_{tenant}"
        base.mkdir(parents=True, exist_ok=True)
        return base

    # ── 服務屬性（雙重鎖定，確保執行緒安全） ──────────────────────

    @property
    def config_mgr(self):
        tenant = _current_tenant()
        if tenant is None:
            if self._config_mgr is None:
                with self._lock:
                    if self._config_mgr is None:
                        from trading.config import ConfigManager
                        self._config_mgr = ConfigManager()
            return self._config_mgr

        if tenant not in self._config_mgr_by_user:
            with self._lock:
                if tenant not in self._config_mgr_by_user:
                    from trading.config import ConfigManager
                    cfg_path = self._user_dir(tenant) / "config.json"
                    self._config_mgr_by_user[tenant] = ConfigManager(config_file=cfg_path)
        return self._config_mgr_by_user[tenant]

    @property
    def pos_mgr(self):
        tenant = _current_tenant()
        if tenant is None:
            if self._pos_mgr is None:
                with self._lock:
                    if self._pos_mgr is None:
                        from trading.positions import PositionManager
                        self._pos_mgr = PositionManager()
            return self._pos_mgr

        if tenant not in self._pos_mgr_by_user:
            with self._lock:
                if tenant not in self._pos_mgr_by_user:
                    from trading.positions import PositionManager
                    db_path = self._user_dir(tenant) / "positions.db"
                    self._pos_mgr_by_user[tenant] = PositionManager(db_file=db_path)
        return self._pos_mgr_by_user[tenant]

    @property
    def ind_engine(self):
        if self._ind_engine is None:
            with self._lock:
                if self._ind_engine is None:
                    from trading.indicators import IndicatorEngine
                    self._ind_engine = IndicatorEngine()
        return self._ind_engine

    @property
    def scanner(self):
        if self._scanner is None:
            with self._lock:
                if self._scanner is None:
                    from trading.scanner import StockScanner
                    self._scanner = StockScanner(self.ind_engine)
        return self._scanner

    @property
    def market_svc(self):
        if self._market_svc is None:
            with self._lock:
                if self._market_svc is None:
                    from trading.market import MarketService
                    self._market_svc = MarketService()
        return self._market_svc

    @property
    def news_agg(self):
        if self._news_agg is None:
            with self._lock:
                if self._news_agg is None:
                    from trading.news import NewsAggregator
                    self._news_agg = NewsAggregator()
        return self._news_agg

    @property
    def ohlcv_db(self):
        if self._ohlcv_db is None:
            with self._lock:
                if self._ohlcv_db is None:
                    from trading.ohlcv_db import OHLCVDatabase
                    self._ohlcv_db = OHLCVDatabase()
        return self._ohlcv_db

    @property
    def ohlcv_daemon(self):
        if self._ohlcv_daemon is None:
            # 在 lock 外取得依賴，避免 deadlock（Lock 不可重入）
            db = self.ohlcv_db
            sc = self.scanner
            with self._lock:
                if self._ohlcv_daemon is None:
                    from trading.ohlcv_daemon import OHLCVDaemon
                    self._ohlcv_daemon = OHLCVDaemon(
                        ohlcv_db=db,
                        scanner=sc,
                    )
        return self._ohlcv_daemon

    @property
    def intel_daemon(self):
        if self._intel_daemon is None:
            with self._lock:
                if self._intel_daemon is None:
                    from trading.intelligence import IntelligenceDaemon
                    self._intel_daemon = IntelligenceDaemon(
                        groq_key=os.environ.get("GROQ_API_KEY", ""),
                        xai_key=os.environ.get("XAI_API_KEY", ""),
                    )
        return self._intel_daemon

    @property
    def coverage_reader(self):
        if self._coverage_reader is None:
            with self._lock:
                if self._coverage_reader is None:
                    from trading.coverage import CoverageReader
                    import logging
                    reader = CoverageReader()
                    try:
                        reader.reload()
                    except Exception as e:
                        logging.getLogger("trading.container").warning(
                            "coverage_reader 載入失敗（忽略）: %s", e
                        )
                    self._coverage_reader = reader
        return self._coverage_reader

    @property
    def intraday_monitor(self):
        """盤中即時監控 Daemon（全體共用單例，獨立於 Flask request 週期背景運作）。"""
        if self._intraday_monitor is None:
            with self._lock:
                if self._intraday_monitor is None:
                    from trading.services.intraday_monitor import IntradayMonitorDaemon
                    self._intraday_monitor = IntradayMonitorDaemon(
                        ohlcv_db=self.ohlcv_db,
                        interval=int(os.environ.get("INTRADAY_FETCH_INTERVAL", 5)),
                        finmind_token=os.environ.get("FINMIND_TOKEN", ""),
                    )
        return self._intraday_monitor

    @property
    def fundamentals(self):
        """TWSE OpenAPI 基本面／籌碼資料服務（全體共用單例，每日快取）。"""
        if self._fundamentals is None:
            with self._lock:
                if self._fundamentals is None:
                    from trading.services.fundamentals import FundamentalsService
                    self._fundamentals = FundamentalsService()
        return self._fundamentals


# 全系統共用的唯一容器實例
container = ServiceContainer()
