"""
trading/api/positions.py — 持倉 CRUD、即時報價、持倉分析報告
"""
import concurrent.futures
import datetime

from flask import Blueprint, jsonify, request

from trading.api.auth import require_auth
from trading.constants import POSITION_FETCH_WORKERS
from trading.services.container import container

positions_bp = Blueprint("positions", __name__)


# ── 持倉 CRUD ──────────────────────────────────────────────────

@positions_bp.route("/api/positions", methods=["GET"])
@require_auth
def get_positions():
    cfg       = container.config_mgr.load()
    positions = container.pos_mgr.load_all()
    summary   = container.pos_mgr.risk_summary(positions, cfg["total_capital"])
    return jsonify({"positions": positions, "summary": summary, "config": cfg})


@positions_bp.route("/api/positions", methods=["POST"])
@require_auth
def create_position():
    try:
        return jsonify({"ok": True, "position": container.pos_mgr.create(request.get_json())}), 201
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400


@positions_bp.route("/api/positions/<int:pid>", methods=["PUT"])
@require_auth
def update_position(pid: int):
    updated = container.pos_mgr.update(pid, request.get_json())
    if updated:
        return jsonify({"ok": True, "position": updated})
    return jsonify({"ok": False, "error": "找不到該持倉"}), 404


@positions_bp.route("/api/positions/<int:pid>", methods=["DELETE"])
@require_auth
def delete_position(pid: int):
    if container.pos_mgr.delete(pid):
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "找不到該持倉"}), 404


# ── 即時報價 ───────────────────────────────────────────────────

@positions_bp.route("/api/prices")
@require_auth
def get_prices():
    """持倉即時報價 — 優先使用 OHLCV DB 快取，僅在 DB 無資料時 fallback yfinance。
    避免與全市場掃描同時打 yfinance 造成 rate limit。
    """
    positions = container.pos_mgr.load_all()
    if not positions:
        return jsonify({"ok": True, "prices": {}})

    ind = container.ind_engine

    def fetch_one(p):
        try:
            code = p["code"].replace(".TW", "").replace(".TWO", "")
            df = ind.fetch_ohlcv(code, period="1mo")
            if df is not None and len(df) >= 2:
                curr    = round(float(df["close"].iloc[-1]), 2)
                prev    = round(float(df["close"].iloc[-2]), 2)
                chg     = round((curr - prev) / prev * 100, 2) if prev else 0
                pnl     = int(round((curr - p["entry"]) * p["shares"], 0))
                pnl_pct = round((curr - p["entry"]) / p["entry"] * 100, 2)
                return str(p["id"]), {"current": curr, "change_pct": chg, "pnl": pnl, "pnl_pct": pnl_pct}
        except Exception:
            pass
        return str(p["id"]), {"current": None, "change_pct": None, "pnl": None, "pnl_pct": None}

    prices = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=POSITION_FETCH_WORKERS) as ex:
        futs = {ex.submit(fetch_one, p): p for p in positions}
        for f in concurrent.futures.as_completed(futs, timeout=25):
            try:
                pid, data = f.result()
                prices[pid] = data
            except Exception:
                pass
    return jsonify({"ok": True, "prices": prices})


# ── 持倉分析報告 ───────────────────────────────────────────────

@positions_bp.route("/api/report")
@require_auth
def get_report():
    positions = container.pos_mgr.load_all()
    if not positions:
        return jsonify({"ok": True, "analyses": [], "date": str(datetime.date.today()), "summary": "目前無持倉"})

    analyses = []
    for p in positions:
        try:
            analyses.append(container.ind_engine.analyze_position(p))
        except Exception as e:
            analyses.append({"code": p["code"], "name": p["name"], "error": str(e)})

    all_alerts = [a for a in analyses if a.get("alerts")]
    summary = (
        f"⚠️ {len(all_alerts)} 筆持倉有警示，請優先處理。"
        if all_alerts else "✅ 所有持倉正常，日常防守看 20EMA。"
    )
    return jsonify({"ok": True, "analyses": analyses, "date": str(datetime.date.today()), "summary": summary})
