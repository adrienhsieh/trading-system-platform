"""
trading/api/intraday.py — 即時監控 API

負責：
  - 使用者個人監控清單 CRUD（沿用 positions.db 的多人隔離機制，見 trading/positions.py）
  - 讀取 IntradayMonitorDaemon（獨立背景 Daemon，見 trading/services/intraday_monitor.py）
    維護的即時快照、K 線、預測 K 線、法人／外資買賣超
  - FETCH_INTERVAL 與策略權重為「系統目前作用中設定」（Daemon 是單一獨立服務，
    對所有使用者監控的股票統一套用同一組設定），可即時調整、立即套用、無需重啟。

本檔案只負責讀寫，實際抓取與運算完全由 intraday_monitor.py 的背景執行緒獨立完成。
"""
import json
from pathlib import Path

from flask import Blueprint, g, jsonify, request

from trading.api.auth import require_auth
from trading.services.container import container
from trading.services.intraday_monitor import DEFAULT_STRATEGY_WEIGHTS

intraday_bp = Blueprint("intraday", __name__)

BASE_DIR = Path(__file__).parent.parent.parent
SETTINGS_PATH = BASE_DIR / "db" / "intraday_settings.json"


# ── 系統設定持久化（FETCH_INTERVAL、策略權重；跨重啟保留） ────────────

def _load_settings() -> dict:
    if SETTINGS_PATH.exists():
        try:
            return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"interval": 5, "weights": dict(DEFAULT_STRATEGY_WEIGHTS)}


def _save_settings(settings: dict) -> None:
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")


def apply_saved_settings() -> None:
    """啟動時呼叫一次，把上次儲存的 FETCH_INTERVAL／策略權重套用到 Daemon。"""
    settings = _load_settings()
    daemon = container.intraday_monitor
    daemon.set_interval(int(settings.get("interval", 10)))
    daemon.set_default_weights(settings.get("weights", dict(DEFAULT_STRATEGY_WEIGHTS)))


# ── 監控清單聯集：彙整「所有使用者」個人監控清單，提供給 Daemon ─────────

def _all_tenant_pos_dbs() -> list:
    """列出所有租戶（含未登入單機預設租戶）的 positions.db 路徑。"""
    paths = []
    default_db = BASE_DIR / "positions.db"
    if default_db.exists():
        paths.append(default_db)
    users_dir = BASE_DIR / "db"
    if users_dir.exists():
        for sub in users_dir.iterdir():
            if sub.is_dir() and sub.name.startswith("user_"):
                db_file = sub / "positions.db"
                if db_file.exists():
                    paths.append(db_file)
    return paths


def _refresh_daemon_codes() -> None:
    """重新彙整所有使用者監控清單的聯集，同步給 Daemon（供任一使用者新增/刪除後呼叫）。"""
    import sqlite3
    from trading.positions import PositionManager

    codes_with_names: dict = {}
    for db_path in _all_tenant_pos_dbs():
        try:
            pm = PositionManager(db_file=db_path)
            for item in pm.intraday_watch_list():
                codes_with_names[item["code"]] = item.get("name") or item["code"]
        except Exception:
            continue
    container.intraday_monitor.set_codes(codes_with_names)


# ── 個人監控清單 CRUD ───────────────────────────────────────────────

@intraday_bp.route("/api/intraday/watchlist", methods=["GET"])
@require_auth
def list_intraday_watchlist():
    items = container.pos_mgr.intraday_watch_list()
    return jsonify({"ok": True, "items": items})


@intraday_bp.route("/api/intraday/watchlist", methods=["POST"])
@require_auth
def add_intraday_watchlist():
    data = request.get_json(silent=True) or {}
    code = str(data.get("code", "")).strip()
    if not code:
        return jsonify({"ok": False, "error": "缺少 code"}), 400
    name = container.scanner.get_stock_name(code)
    ok = container.pos_mgr.intraday_watch_add(code, name)
    if not ok:
        return jsonify({"ok": False, "error": f"{code} 已在監控清單中"}), 409
    _refresh_daemon_codes()
    return jsonify({"ok": True, "code": code, "name": name})


@intraday_bp.route("/api/intraday/watchlist/<code>", methods=["DELETE"])
@require_auth
def remove_intraday_watchlist(code: str):
    ok = container.pos_mgr.intraday_watch_remove(code)
    if not ok:
        return jsonify({"ok": False, "error": f"{code} 不在監控清單中"}), 404
    _refresh_daemon_codes()
    return jsonify({"ok": True})


# ── Daemon 狀態／設定（FETCH_INTERVAL、策略權重：系統層級，全體共用） ─────

@intraday_bp.route("/api/intraday/status", methods=["GET"])
@require_auth
def intraday_status():
    return jsonify({"ok": True, **container.intraday_monitor.get_status()})


@intraday_bp.route("/api/intraday/interval", methods=["GET"])
@require_auth
def get_interval():
    return jsonify({"ok": True, "interval": container.intraday_monitor.get_interval()})


@intraday_bp.route("/api/intraday/interval", methods=["POST"])
@require_auth
def set_interval():
    data = request.get_json(silent=True) or {}
    try:
        seconds = int(data.get("seconds", 10))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "seconds 需為整數"}), 400
    if seconds < 3:
        return jsonify({"ok": False, "error": "FETCH_INTERVAL 最短需 3 秒，避免過度呼叫官方 API"}), 400

    applied = container.intraday_monitor.set_interval(seconds)
    settings = _load_settings()
    settings["interval"] = applied
    _save_settings(settings)
    return jsonify({"ok": True, "interval": applied})


@intraday_bp.route("/api/intraday/strategies", methods=["GET"])
@require_auth
def list_strategies():
    from trading.strategies import REGISTRY
    return jsonify({
        "ok": True,
        "strategies": [{"name": k, "label": v.label} for k, v in REGISTRY.items()],
    })


@intraday_bp.route("/api/intraday/weights", methods=["GET"])
@require_auth
def get_weights():
    settings = _load_settings()
    return jsonify({"ok": True, "weights": settings.get("weights", dict(DEFAULT_STRATEGY_WEIGHTS))})


@intraday_bp.route("/api/intraday/weights", methods=["POST"])
@require_auth
def set_weights():
    from trading.strategies import REGISTRY

    data = request.get_json(silent=True) or {}
    weights = data.get("weights", {})
    if not isinstance(weights, dict) or not weights:
        return jsonify({"ok": False, "error": "weights 格式錯誤"}), 400

    cleaned = {}
    for name, w in weights.items():
        if name not in REGISTRY:
            continue
        try:
            cleaned[name] = max(0, min(100, int(w)))
        except (TypeError, ValueError):
            continue
    if not cleaned:
        return jsonify({"ok": False, "error": "沒有合法的策略權重"}), 400

    container.intraday_monitor.set_default_weights(cleaned)
    settings = _load_settings()
    settings["weights"] = cleaned
    _save_settings(settings)
    return jsonify({"ok": True, "weights": cleaned})


# ── 即時快照／五檔／法人外資 ────────────────────────────────────────

@intraday_bp.route("/api/intraday/snapshot", methods=["GET"])
@require_auth
def snapshot():
    codes_param = request.args.get("codes", "")
    if codes_param:
        codes = [c.strip() for c in codes_param.split(",") if c.strip()]
    else:
        codes = [item["code"] for item in container.pos_mgr.intraday_watch_list()]

    if not codes:
        return jsonify({"ok": True, "items": {}})

    daemon = container.intraday_monitor
    snap = daemon.get_snapshot(codes)
    result = {}
    for code in codes:
        row = dict(snap.get(code, {}))
        row.setdefault("code", code)
        row.setdefault("name", container.scanner.get_stock_name(code))
        inst = daemon.get_institutional(code)
        row["institutional"] = inst
        result[code] = row

    return jsonify({
        "ok": True,
        "items": result,
        "market_open": daemon.get_status()["market_open"],
        "channel": daemon.get_status()["channel"],
    })


# ── K 線（實際 + 預測，供前端繪圖比對） ───────────────────────────────

@intraday_bp.route("/api/intraday/kline", methods=["GET"])
@require_auth
def kline():
    code = request.args.get("code", "").strip()
    if not code:
        return jsonify({"ok": False, "error": "缺少 code"}), 400
    trade_date = request.args.get("date") or None

    daemon = container.intraday_monitor
    actual = daemon.get_bars(code, trade_date=trade_date)
    predicted = daemon.get_predicted_bars(code, trade_date=trade_date)
    institutional = daemon.get_institutional(code)

    return jsonify({
        "ok": True,
        "code": code,
        "name": container.scanner.get_stock_name(code),
        "actual": actual,
        "predicted": predicted,
        "institutional": institutional,
    })


# ── 即時相關新聞（依股票名稱/代號比對既有情報庫，非結構化個股標記） ──────

@intraday_bp.route("/api/intraday/news", methods=["GET"])
@require_auth
def intraday_news():
    code = request.args.get("code", "").strip()
    if not code:
        return jsonify({"ok": False, "error": "缺少 code"}), 400
    name = container.scanner.get_stock_name(code) or ""

    hours = int(request.args.get("hours", 48))
    all_items = container.intel_daemon.get_recent_news(hours=hours, limit=100)

    keywords = [k for k in {code, name} if k]
    related = [
        item for item in all_items
        if any(k in (item.get("title") or "") for k in keywords)
    ]
    return jsonify({"ok": True, "code": code, "name": name, "items": related[:20]})
