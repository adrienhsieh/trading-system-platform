"""
trading/services/container.py — 依賴注入容器
全系統服務單例由此統一管理，lazy-init，執行緒安全。
"""
import os
import threading


class ServiceContainer:
    """Lazy-init 服務容器。所有服務皆在首次存取時建立。"""

    def __init__(self):
        self._lock = threading.Lock()
        self._config_mgr     = None
        self._pos_mgr        = None
        self._ind_engine     = None
        self._scanner        = None
        self._market_svc     = None
        self._news_agg       = None
        self._ohlcv_db       = None
        self._intel_daemon   = None
        self._ohlcv_daemon   = None
        self._coverage_reader = None
        self._predict_svc    = None  # 🚀 確保在這裡，且維持 8 個空格的縮排

    # ── 服務屬性（雙重鎖定，確保執行緒安全） ──────────────────────

    @property
    def config_mgr(self):
        if self._config_mgr is None:
            with self._lock:
                if self._config_mgr is None:
                    from trading.config import ConfigManager
                    self._config_mgr = ConfigManager()
        return self._config_mgr

    @property
    def pos_mgr(self):
        if self._pos_mgr is None:
            with self._lock:
                if self._pos_mgr is None:
                    from trading.positions import PositionManager
                    self._pos_mgr = PositionManager()
        return self._pos_mgr

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
        
    def get_user_db(self, explicit_user_id=None):
        """
        【雙軌多租戶路由】
        1. 優先採用顯式傳入的 explicit_user_id (供 Telegram / 定時排程使用)
        2. 次之採用 Flask 全域變數 g.current_user_id (供網頁 API 使用)
        """
        user_id = explicit_user_id
        
        # 如果沒有顯式指定，且目前處於 Flask Request 上下文中，則降級從 g 取得
        if not user_id and has_request_context():
            user_id = getattr(g, 'current_user_id', None)
            
        if not user_id:
            raise PermissionError("沒有合法的用戶 Context，拒絕建立私有連線")
            
        # 物理隔離目錄：db/user_[id]/userdata.db
        user_folder = os.path.join(self.base_dir, f"user_{user_id}")
        os.makedirs(user_folder, exist_ok=True)
        
        db_path = os.path.join(user_folder, "userdata.db")
        is_new = not os.path.exists(db_path)
        
        conn = sqlite3.connect(db_path, timeout=30.0)
        conn.execute("PRAGMA journal_mode=WAL;") # 啟用 WAL 模式確保個人讀寫效能
        conn.row_factory = sqlite3.Row
        
        if is_new:
            self._init_user_schema(conn) # 新用戶登入時自動初始化他個人原汁原味的持倉與觀察表
        return conn


# 全系統共用的唯一容器實例
container = ServiceContainer()
