"""
trading/api/market.py — 大盤行情、新聞
"""
# ✨ 修正：在這裡補上 request 匯入，否則會引發 NameError 噴 500 錯誤！
from flask import Blueprint, jsonify, request

from trading.api.auth import require_auth
from trading.services.container import container

market_bp = Blueprint("market", __name__)


@market_bp.route("/api/market")
@require_auth
def get_market():
    cache = container.market_svc.get_data()
    return jsonify({"ok": True, "market": cache, "cached": bool(cache)})


@market_bp.route("/api/news")
@require_auth
def get_news():
    return jsonify({"ok": True, "news": container.news_agg.fetch()})


@market_bp.route("/api/news/analyze")
@require_auth
def analyze_news():
    stock_map = container.scanner.get_stock_map()
    results   = container.news_agg.analyze_sentiment(stock_map)
    return jsonify({"ok": True, "results": results, "total": len(results)})


@market_bp.route("/api/market/name", methods=["GET"])
@require_auth
def get_stock_name():
    try:
        ticker = request.args.get("ticker", "").strip()
        if not ticker:
            return jsonify({"ok": False, "error": "Missing ticker"}), 400
        
        # 從你的 scanner 服務獲取代號對應的名稱
        stock_map = container.scanner.get_stock_map()
        name = stock_map.get(ticker)
        
        # ✨ 補上 "ok": True/False，讓 login.html 驗證與首頁都能順利解讀
        if name:
            return jsonify({
                "ok": True,
                "ticker": ticker,
                "name": name
            }), 200
        else:
            return jsonify({
                "ok": True,            # 驗證本身成功，只是沒這隻股票，依然給登入
                "ticker": ticker,
                "name": f"台股 {ticker}" # 防禦性防崩潰：查無時自動顯示代號
            }), 200

    except Exception as e:
        # 萬一內部又有其他未預期錯誤，直接噴出來除錯
        return jsonify({"ok": False, "error": f"後端內部錯誤: {str(e)}"}), 500