"""
trading/api/__init__.py — Blueprint 匯總與統一註冊
"""
from trading.api.positions import positions_bp
from trading.api.scan import scan_bp
from trading.api.config_bp import config_bp
from trading.api.backtest import backtest_bp
from trading.api.market import market_bp
from trading.api.intelligence import intelligence_bp
from trading.api.watchlist import watchlist_bp
from trading.api.predict import predict_bp
from trading.api.user_config import user_setting_bp
from trading.api.api_system import api_system          # ← 補上
from trading.api.auth import api_auth                  # ✨ 多人登入（註冊/登入/個人資料）
from trading.api.intraday import intraday_bp            # ✨ 即時監控
from trading.api.fundamentals import fundamentals_bp     # ✨ 基本面／籌碼資料
from trading.api.thsr import thsr_bp                      # ✨ 高鐵訂票（手動輸入驗證碼）


def register_blueprints(app) -> None:
    """將所有 Blueprint 掛載至 Flask app。"""
    app.register_blueprint(api_auth)
    app.register_blueprint(positions_bp)
    app.register_blueprint(scan_bp)
    app.register_blueprint(config_bp)
    app.register_blueprint(backtest_bp)
    app.register_blueprint(market_bp)
    app.register_blueprint(intelligence_bp)
    app.register_blueprint(watchlist_bp)
    app.register_blueprint(predict_bp)
    app.register_blueprint(user_setting_bp)
    app.register_blueprint(api_system)
    app.register_blueprint(intraday_bp)
    app.register_blueprint(fundamentals_bp)
    app.register_blueprint(thsr_bp)