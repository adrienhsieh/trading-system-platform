"""
trading/api/fundamentals.py — 基本面／籌碼 API
本益比／殖利率／股價淨值比、月營收（含連續成長月數）、融資融券（含籌碼洗淨判斷）、
VIX 恐慌篩選。資料來源見 trading/services/fundamentals.py（TWSE OpenAPI，全體共用快取）。
"""
from flask import Blueprint, jsonify, request

from trading.api.auth import require_auth
from trading.services.container import container

fundamentals_bp = Blueprint("fundamentals", __name__)


@fundamentals_bp.route("/api/fundamentals/<code>", methods=["GET"])
@require_auth
def get_fundamentals(code: str):
    fs = container.fundamentals
    valuation = fs.get_valuation(code)
    revenue = fs.get_revenue_series(code, months=13)
    margin = fs.get_margin_series(code, days=20)
    streak = fs.get_revenue_growth_streak(code)
    washout = fs.get_chip_washout_signal(code)

    return jsonify({
        "ok": True,
        "code": code,
        "valuation": valuation,
        "revenue_series": revenue,
        "margin_series": margin,
        "revenue_growth_streak": streak,
        "chip_washout": washout,
    })


@fundamentals_bp.route("/api/fundamentals/refresh", methods=["POST"])
@require_auth
def refresh_fundamentals():
    """手動觸發重新抓取（TWSE OpenAPI 資料每日更新一次，一般不需頻繁呼叫）。"""
    fs = container.fundamentals
    fs.refresh_all()
    return jsonify({"ok": True, "message": "基本面／籌碼資料已重新整理"})


@fundamentals_bp.route("/api/fundamentals/vix-status", methods=["GET"])
@require_auth
def vix_status():
    fs = container.fundamentals
    vix = fs.get_vix()
    threshold = float(request.args.get("threshold", 30))
    return jsonify({
        "ok": True,
        "vix": vix,
        "threshold": threshold,
        "is_panic": bool(vix is not None and vix > threshold),
    })
