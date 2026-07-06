"""
run.py — 戰情指揮中心啟動入口
用法：python run.py [--port 8787]
"""
import os
import sys
import sqlite3
import threading
import time
import webbrowser
from pathlib import Path
from trading.api.api_system import api_system  

BASE_DIR = Path(__file__).parent


# ── 1. 載入 .env ───────────────────────────────────────────────

def _load_env() -> None:
    env_file = BASE_DIR / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


_load_env()

from trading.logger import setup_root_level
setup_root_level()

TG_TOKEN       = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TG_ALLOWED_IDS = set(os.environ.get("TELEGRAM_ALLOWED_IDS", "").split(",")) - {""}


# ── 2. 自動安裝缺少的套件 ──────────────────────────────────────

def _install(pkg: str) -> None:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", pkg, "-q"])


for _mod, _pkg in {
    "flask":      "flask",
    "flask_cors": "flask-cors",
    "yfinance":   "yfinance",
    "pandas":     "pandas",
    "requests":   "requests",
    "certifi":    "certifi",
}.items():
    try:
        __import__(_mod)
    except ImportError:
        print(f"[run] 安裝 {_pkg}...")
        _install(_pkg)


# ── 3. 匯入服務層與 Flask app ──────────────────────────────────

from app import app  # noqa: E402
from trading.services.container import container as _svc
config_mgr      = _svc.config_mgr
pos_mgr         = _svc.pos_mgr
ind_engine      = _svc.ind_engine
scanner         = _svc.scanner
market_svc      = _svc.market_svc
news_agg        = _svc.news_agg
intel_daemon    = _svc.intel_daemon
coverage_reader = _svc.coverage_reader
from trading.telegram.bot import TelegramBot
from trading.telegram.scheduler import TradingScheduler


def main() -> None:
    port = int(os.environ.get("PORT", 8787))

    # 強制載入設定檔以確保首次啟動時自動生成 API Key 與 config.json
    config_mgr.load()

    # 啟動狀態摘要
    db_path = BASE_DIR / "positions.db"
    print(f"\n[Trading] 戰情指揮中心啟動  http://localhost:{port}")
    print(f"   工作目錄 : {BASE_DIR}")
    print(f"   DB  路徑 : {db_path}  {'✅ 存在' if db_path.exists() else '❌ 不存在'}")
    if db_path.exists():
        c = sqlite3.connect(str(db_path))
        n = c.execute("SELECT COUNT(*) FROM positions").fetchone()[0]
        print(f"   DB 持倉  : {n} 筆")
        c.close()
    print(f"   Telegram : {'✅ Token 已設定' if TG_TOKEN else '❌ 未設定（請建立 .env）'}")
    print()

    # ── 建立 Telegram Bot 與排程器 ─────────────────────────────
    bot = TelegramBot(
        token            = TG_TOKEN,
        allowed_ids      = TG_ALLOWED_IDS,
        config_manager   = config_mgr,
        position_manager = pos_mgr,
        scanner          = scanner,
        indicator_engine = ind_engine,
        news_aggregator  = news_agg,
        market_service   = market_svc,
        intel_daemon     = intel_daemon,
        coverage_reader  = coverage_reader,
    )

    scheduler = TradingScheduler(
        telegram_bot     = bot,
        position_manager = pos_mgr,
        indicator_engine = ind_engine,
        coverage_reader  = coverage_reader,
    )

    # ── 情報 Daemon ────────────────────────────────────────────
    intel_daemon.start()
    groq_ok = bool(os.environ.get("GROQ_API_KEY", ""))
    xai_ok  = bool(os.environ.get("XAI_API_KEY", ""))
    print(f"   情報Daemon: ✅ 已啟動（Groq={'✅' if groq_ok else '❌'} / XAI={'✅' if xai_ok else '❌'}）")

    # ── OHLCV Daemon ───────────────────────────────────────────
    ohlcv_daemon = _svc.ohlcv_daemon
    ohlcv_daemon.start()
    print(f"   OHLCV更新:  ✅ 已啟動（每日 14:00 全市場增量更新）")

    # ── 即時監控 Daemon（獨立背景作業，09:00-13:30 盤中自動抓取） ──
    from trading.api.intraday import apply_saved_settings, _refresh_daemon_codes
    intraday_monitor = _svc.intraday_monitor
    apply_saved_settings()   # 還原上次儲存的 FETCH_INTERVAL / 策略權重
    _refresh_daemon_codes()  # 彙整所有使用者目前的監控清單
    intraday_monitor.start()
    print(f"   即時監控:  ✅ 已啟動（盤中 09:00-13:30，每 {intraday_monitor.get_interval()} 秒自動抓取，可於頁面即時調整）")

    # ── 背景任務 ───────────────────────────────────────────────

    # 自動開啟瀏覽器（僅本機，Docker/Render 環境跳過）
    if not os.environ.get("RENDER") and not os.environ.get("DOCKER"):
        def _open_browser():
            time.sleep(1.2)
            webbrowser.open(f"http://localhost:{port}")
        threading.Thread(target=_open_browser, daemon=True).start()

    # 預熱：抓取大盤資料 + 股票代號表
    def _preload():
        time.sleep(1)
        market_svc.refresh()
        try:
            m = scanner.get_stock_map()
            print(f"[run] 股票代號表 {len(m)} 檔")
        except Exception as e:
            print(f"[run] 代號表失敗: {e}")
    threading.Thread(target=_preload, daemon=True).start()

    # Telegram Bot polling
    def _start_bot():
        time.sleep(2)
        bot.start_polling()
    threading.Thread(target=_start_bot, daemon=True).start()

    # 自動推播排程
    def _start_scheduler():
        time.sleep(5)
        scheduler.start()
    threading.Thread(target=_start_scheduler, daemon=True).start()

    # ── 啟動 Flask ─────────────────────────────────────────────
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
