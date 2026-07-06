# -*- coding: utf-8 -*-
"""
trading/services/__init__.py — 服務容器 Lazy-init 單例中樞
專案路徑: D:\SourceCode\TypeScript\trading-system-main\trading\services\__init__.py
"""

from trading.logger import get_logger

logger = get_logger("service_container")

class ServiceContainer:
    """
    Lazy-init 服務容器 (單例模式)
    避免模組循環導入 (Circular Imports)，並在首次調用時才初始化核心服務
    """
    def __init__(self):
        self._market_svc = None
        self._predict_svc = None
        # 這裡可以保留您原本系統中原有的其他管理器初始化宣告，例如：
        # self._pos_mgr = None
        # self._scanner = None
        # self._config_mgr = None

    @property
    def market_svc(self):
        """行情服務單例門戶"""
        if self._market_svc is None:
            print("market_svc 是空的") 
            from trading.market import MarketService
            self._market_svc = MarketService()
            print("market_svc 已建立") 
            logger.info("🚀 [Container] MarketService (智慧三級防線版) 初始化成功。")
        return self._market_svc

    @property
    def predict_svc(self):
        """多因子預測引擎服務單例門戶"""
        if self._predict_svc is None:
            print("predict_svc 是空的") 
            from trading.services.predict_service import TaiwanStockPredictService
            self._predict_svc = TaiwanStockPredictService()
            print("predict_svc 已建立")
            logger.info("🚀 [Container] TaiwanStockPredictService (15因子預測引擎) 初始化成功。")
        return self._predict_svc

    # ─────────────────────────────────────────────────────────────────
    # 💡 提示：如果您的系統原本還有其他 Property (如 pos_mgr, scanner 等)，
    # 請保持原樣留在下方即可。以下為標準相容性範例：
    # ─────────────────────────────────────────────────────────────────
    @property
    def pos_mgr(self):
        if not hasattr(self, '_pos_mgr') or self._pos_mgr is None:
            from trading.services.position_manager import PositionManager
            self._pos_mgr = PositionManager()
            print("PositionManager 已啟動")
        return self._pos_mgr

    @property
    def scanner(self):
        if not hasattr(self, '_scanner') or self._scanner is None:
            from trading.services.stock_scanner import StockScanner
            self._scanner = StockScanner()
            print("StockScanner 已啟動")
        return self._scanner

    @property
    def config_mgr(self):
        if not hasattr(self, '_config_mgr') or self._config_mgr is None:
            from trading.config import ConfigManager
            self._config_mgr = ConfigManager()
            print("ConfigManager 已啟動")
        return self._config_mgr


# 🟢 導出全局唯一的容器實例，供所有 API 路由 (Blueprint) 共享
container = ServiceContainer()