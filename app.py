"""
app.py — Flask 應用程式進入點
路由分散於 trading/api/ Blueprint 模組；服務單例統一由 trading/services/container.py 管理。
啟動方式：python run.py
"""
import logging
import os
import threading  # 🟢 確保導入多執行緒套件
from pathlib import Path

from flask import Flask, send_from_directory, jsonify
from flask_cors import CORS

from trading.api import register_blueprints
from trading.api.extensions import limiter
from trading.api.auth import ensure_users_db
from trading.exceptions import TradingSystemError
from trading.services.config_db import init_db
from trading.api.admin_ui import init_admin_web_ui
from trading.services.container import container as _container

# ── backward-compat：讓 run.py 可以繼續 from app import config_mgr, ... ──
config_mgr = _container.config_mgr
pos_mgr = _container.pos_mgr
ind_engine = _container.ind_engine
scanner = _container.scanner
market_svc = _container.market_svc
news_agg = _container.news_agg
intel_daemon = _container.intel_daemon
coverage_reader = _container.coverage_reader

BASE_DIR = Path(__file__).parent
_logger = logging.getLogger("trading.app")

# ── 啟動前自動建立 SQLite 資料表 ──────────────────────────────────────
try:
    init_db()
    _logger.info("SQLite 初始化成功。")
except Exception as e:
    _logger.error("SQLite 初始化失敗: %s", e, exc_info=True)

try:
    ensure_users_db()
    _logger.info("多人登入帳密庫（db/users.db）初始化成功。")
except Exception as e:
    _logger.error("多人登入帳密庫初始化失敗: %s", e, exc_info=True)

# ── Flask 應用 ────────────────────────────────────────────────────────
app = Flask(__name__, static_folder=str(BASE_DIR), static_url_path="")
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "trading_system_opus_secure_key_2026")

_allowed_origin = os.environ.get("CORS_ORIGIN", "http://localhost:8787")
CORS(app, resources={r"/api/*": {"origins": [_allowed_origin]}})
limiter.init_app(app)

register_blueprints(app)
init_admin_web_ui(app)   # ← 只呼叫一次


# ── 🟢 ✨ 台股即時自動監控背景安全非同步啟動核心（精準驅動版） ─────────────────────
_monitor_lock = threading.Lock()
_monitor_started = False

def _start_intraday_monitor_daemon():
    """在完全隔離的獨立背景執行緒中安全初始化並執行台股監控迴圈"""
    try:
        _logger.info("🚀 [Monitor Thread] 正在獨立背景執行緒中載入台股常駐監控程序...")
        
        # 真正讀取屬性，觸發 container 的延遲載入 (Lazy-init)
        monitor = _container.intraday_monitor
        
        # ⚠️ 這裡做出核心精準修正：
        # 繞過可能與高鐵訂票或其他模組混淆的 'start' 或 'run' 屬性判斷，直接鎖定台股的核心無窮迴圈 `run_loop`。
        if hasattr(monitor, 'run_loop'):
            _logger.info("🤖 [Monitor Thread] 偵測到台股核心 run_loop 方法，背景輪詢已正式啟動！")
            monitor.run_loop()
        else:
            # 安全防禦 Fallback：若您的 intraday_monitor.py 將主入口命名為 run
            _logger.info("🤖 [Monitor Thread] 執行標準台股監控入口...")
            if hasattr(monitor, '_fetch_all_candidates_loop'):
                monitor._fetch_all_candidates_loop()
            elif hasattr(monitor, 'run'):
                monitor.run()
            
        _logger.info("✅ [Monitor Thread] 台股即時自動監控程序已成功進入監聽迴圈。")
    except Exception as ex:
        _logger.error("❌ [Monitor Thread] 背景自動監控常駐程式發生嚴重崩潰: %s", ex, exc_info=True)


@app.before_request
def _init_background_tasks_on_first_request():
    """利用首次前端請求安全觸發背景執行緒，確保 Flask 已完全就緒且絕不卡死主執行緒"""
    global _monitor_started
    if not _monitor_started:
        with _monitor_lock:
            if not _monitor_started:
                # 扔進完全獨立且常駐的背景 Daemon 執行緒中跑
                t = threading.Thread(target=_start_intraday_monitor_daemon, daemon=True)
                t.start()
                _monitor_started = True
                _logger.info("⚙️ [System] 已成功指派獨立背景 Daemon 執行緒接管盤中自動化監控。")


# ── 靜態頁面 ──────────────────────────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory(str(BASE_DIR), "index.html")


# 明確指定 login 路由，確保前端載入安全
@app.route("/login")
def login_page():
    return send_from_directory(str(BASE_DIR), "login.html")


@app.route("/mockup")
def mockup():
    return send_from_directory(str(BASE_DIR / "docs"), "mockup-recorder.html")


# ── Security headers ──────────────────────────────────────────────────
@app.after_request
def set_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    return response


# ── 全域 error handler ────────────────────────────────────────────────
@app.errorhandler(TradingSystemError)
def handle_trading_error(e: TradingSystemError):
    _logger.error("TradingSystemError: %s", e, exc_info=True)
    return jsonify({"ok": False, "error": f"系統發生錯誤: {str(e)}"}), 500


# 優化：修改 500 攔截器，直接在回傳中暴露錯誤原因
@app.errorhandler(500)
def handle_500(e):
    _logger.error("Unhandled 500: %s", e, exc_info=True)
    
    # 擷取最底層的原始錯誤訊息
    original_err = str(e.original_exception) if hasattr(e, "original_exception") and e.original_exception else str(e)
    
    return jsonify({
        "ok": False, 
        "error": f"內部伺服器錯誤: {original_err}。請檢查後端終端機日誌。"
    }), 500


# ── 直接執行（開發用） ────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=True, threaded=True)