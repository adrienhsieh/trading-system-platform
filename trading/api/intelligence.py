"""
trading/api/intelligence.py — AI 情報系統、OHLCV 快取
"""
from flask import Blueprint, jsonify, request

from trading.api.auth import require_auth
from trading.api.extensions import limiter
from trading.indicators import IndicatorEngine
from trading.services.container import container

intelligence_bp = Blueprint("intelligence", __name__)


# ── 情報 API ──────────────────────────────────────────────────

@intelligence_bp.route("/api/intelligence/news")
@require_auth
@limiter.limit("10 per minute")
def intelligence_news():
    hours = int(request.args.get("hours", 24))
    limit = int(request.args.get("limit", 20))
    items = container.intel_daemon.get_recent_news(hours=hours, limit=limit)
    return jsonify({"ok": True, "items": items})


@intelligence_bp.route("/api/intelligence/summary")
@require_auth
@limiter.limit("10 per minute")
def intelligence_summary():
    summary = container.intel_daemon.get_latest_summary()
    stats   = container.intel_daemon.get_news_sentiment_stats(hours=24)
    return jsonify({"ok": True, "summary": summary, "stats": stats})


@intelligence_bp.route("/api/intelligence/x")
@require_auth
@limiter.limit("10 per minute")
def intelligence_x():
    hours = int(request.args.get("hours", 24))
    limit = int(request.args.get("limit", 20))
    from trading.xmonitor import XMonitor
    x_mon = XMonitor()
    posts = x_mon.get_recent(hours=hours, limit=limit)
    stats = x_mon.sentiment_summary(hours=hours)
    fallback = False
    if not posts:
        posts = x_mon.get_recent(hours=24 * 365, limit=limit)
        stats = x_mon.sentiment_summary(hours=24 * 365)
        fallback = True
    return jsonify({"ok": True, "posts": posts, "stats": stats, "fallback": fallback})


@intelligence_bp.route("/api/intelligence/collect", methods=["POST"])
@require_auth
def intelligence_collect():
    container.intel_daemon.force_collect()
    return jsonify({"ok": True, "message": "情報收集已觸發"})


@intelligence_bp.route("/api/intelligence/generate_summary", methods=["POST"])
@require_auth
@limiter.limit("10 per minute")
def intelligence_generate_summary():
    ok = container.intel_daemon.generate_summary_now()
    if ok:
        summary = container.intel_daemon.get_latest_summary()
        return jsonify({"ok": True, "summary": summary})
    from trading.groq_client import GroqClient
    groq_ok = GroqClient().is_available()
    if not groq_ok:
        return jsonify({"ok": False, "groq_available": False, "error": "摘要生成失敗（未設定 GROQ_API_KEY）"})
    return jsonify({"ok": False, "groq_available": True, "error": "摘要生成失敗（新聞不足）"})


@intelligence_bp.route("/api/intelligence/ai_sentiment")
@require_auth
def intelligence_ai_sentiment():
    from trading.groq_client import GroqClient
    if not GroqClient().is_available():
        return jsonify({"ok": False, "groq_available": False, "error": "Groq 未設定（請在 .env 加入 GROQ_API_KEY）"})
    result = container.news_agg.analyze_sentiment_ai(limit=20)
    if result is None:
        return jsonify({"ok": False, "error": "Groq API 呼叫失敗（可能為額度用盡或 Key 無效，請查看終端機輸出）"})
    return jsonify({"ok": True, **result})


# ── OHLCV 快取 API ────────────────────────────────────────────

@intelligence_bp.route("/api/ohlcv/<code>")
@require_auth
def get_ohlcv(code: str):
    df = container.ind_engine.fetch_ohlcv(code.strip())
    if df is None or df.empty:
        return jsonify({"ok": False, "error": "資料不足或代號錯誤"}), 404
    ema5  = IndicatorEngine._ema(df["close"], 5)
    ema20 = IndicatorEngine._ema(df["close"], 20)
    ema60 = IndicatorEngine._ema(df["close"], 60)
    candles, e5, e20, e60 = [], [], [], []
    for ts, row in df.iterrows():
        d = str(ts.date())
        candles.append({
            "time":  d,
            "open":  round(float(row["open"]),  2),
            "high":  round(float(row["high"]),  2),
            "low":   round(float(row["low"]),   2),
            "close": round(float(row["close"]), 2),
        })
        e5.append( {"time": d, "value": round(float(ema5[ts]),  2)})
        e20.append({"time": d, "value": round(float(ema20[ts]), 2)})
        e60.append({"time": d, "value": round(float(ema60[ts]), 2)})
    return jsonify({"ok": True, "code": code, "candles": candles, "ema5": e5, "ema20": e20, "ema60": e60})


@intelligence_bp.route("/api/ohlcv/stats")
@require_auth
def ohlcv_stats():
    return jsonify({"ok": True, "stats": container.ohlcv_db.stats()})


@intelligence_bp.route("/api/ohlcv/update", methods=["POST"])
@require_auth
@limiter.limit("5 per minute")
def ohlcv_update():
    data  = request.get_json() or {}
    codes = data.get("codes", [])
    if len(codes) > 50:
        return jsonify({"ok": False, "error": "codes 清單最多 50 筆"}), 400
    if not codes:
        return jsonify({"ok": False, "error": "請提供 codes 清單"}), 400
    updated = 0
    failed  = []
    for code in codes:
        df = container.ind_engine.fetch_ohlcv(code, period="1y")
        if df is not None and not df.empty:
            container.ohlcv_db.upsert(code, df)
            updated += 1
        else:
            failed.append(code)
    return jsonify({"ok": True, "updated": updated, "failed": failed})
