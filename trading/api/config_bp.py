"""
trading/api/config_bp.py — 設定、策略參數、Coverage 研究資料庫
"""
from flask import Blueprint, jsonify, request

from trading.api.auth import require_auth, validate_code
from trading.config import ConfigManager
from trading.services.container import container

config_bp = Blueprint("config", __name__)


# ── 設定 ───────────────────────────────────────────────────────

@config_bp.route("/api/config", methods=["GET"])
@require_auth
def get_config():
    return jsonify(container.config_mgr.load())


@config_bp.route("/api/config", methods=["POST"])
@require_auth
def update_config():
    cfg = container.config_mgr.update(request.get_json())
    return jsonify({"ok": True, "config": cfg})


# ── 策略參數 ───────────────────────────────────────────────────

@config_bp.route("/api/strategy_params", methods=["GET"])
@require_auth
def get_strategy_params():
    cfg = container.config_mgr.load()
    return jsonify({"ok": True, "params": cfg.get("strategy_params", ConfigManager.DEFAULTS["strategy_params"])})


@config_bp.route("/api/strategy_params", methods=["POST"])
@require_auth
def set_strategy_params():
    data = request.get_json() or {}
    cfg  = container.config_mgr.load()
    cfg["strategy_params"] = data.get("params", cfg.get("strategy_params", {}))
    container.config_mgr.save(cfg)
    return jsonify({"ok": True})


# ── Coverage API ───────────────────────────────────────────────

@config_bp.route("/api/coverage/keywords")
@require_auth
def get_coverage_keywords():
    limit = min(int(request.args.get("limit", 200)), 500)
    return jsonify({"ok": True, "keywords": container.coverage_reader.keywords(limit=limit)})


@config_bp.route("/api/coverage/search")
@require_auth
def search_coverage():
    keyword = request.args.get("q", "").strip()
    if not keyword:
        return jsonify({"ok": False, "error": "q parameter required"}), 400
    limit = min(int(request.args.get("limit", 20)), 50)
    results = container.coverage_reader.search(keyword, limit=limit)
    return jsonify({"ok": True, "keyword": keyword, "results": results})


@config_bp.route("/api/coverage/sync", methods=["POST"])
@require_auth
def sync_coverage():
    result = container.coverage_reader.sync()
    status = 200 if result.get("ok") else 500
    return jsonify(result), status


@config_bp.route("/api/coverage/<code>")
@require_auth
def get_coverage(code: str):
    code = code.strip()
    err = validate_code(code)
    if err:
        return err
    ov = container.coverage_reader.get_overview(code)
    #if ov is None:
    #    return jsonify({"ok": False, "error": "no coverage data"}), 404
    #return jsonify({"ok": True, "code": code, **ov})
    if ov is None:
        return jsonify({
            "ok": True,               # 改為 True，不讓 Flask 和前端噴紅字錯誤
            "has_data": False,        # 告訴前端此股沒有覆蓋資料
            "code": code,
            "error": "no coverage data"
        }), 200                       # 狀態碼改為 200 OK
    
    return jsonify({"ok": True, "has_data": True, "code": code, **ov})
