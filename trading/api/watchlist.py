"""trading/api/watchlist.py — 觀察名單 API"""
import time

import requests
from defusedxml.ElementTree import fromstring
from flask import Blueprint, jsonify, request

from trading.api.auth import require_auth
from trading.services.container import container

watchlist_bp = Blueprint("watchlist", __name__)


@watchlist_bp.route("/api/watchlist")
@require_auth
def list_watchlist():
    items = container.pos_mgr.watchlist_list()
    return jsonify({"ok": True, "items": items})


@watchlist_bp.route("/api/watchlist", methods=["POST"])
@require_auth
def add_watchlist():
    data = request.get_json(silent=True) or {}
    code = str(data.get("code", "")).strip()
    if not code:
        return jsonify({"ok": False, "error": "缺少 code"}), 400
    name = container.scanner.get_stock_name(code)
    ok = container.pos_mgr.watchlist_add(code, name)
    if not ok:
        return jsonify({"ok": False, "error": f"{code} 已在觀察名單中"}), 409
    return jsonify({"ok": True, "code": code, "name": name})


@watchlist_bp.route("/api/watchlist/<code>", methods=["DELETE"])
@require_auth
def remove_watchlist(code: str):
    ok = container.pos_mgr.watchlist_remove(code)
    if not ok:
        return jsonify({"ok": False, "error": f"{code} 不在觀察名單中"}), 404
    return jsonify({"ok": True})


@watchlist_bp.route("/api/watchlist/analyze")
@require_auth
def analyze_watchlist():
    items = container.pos_mgr.watchlist_list()
    if not items:
        return jsonify({"ok": True, "results": []})

    cfg = container.config_mgr.load()
    capital = cfg.get("total_capital", 3000000)
    risk_pct = 1.0 if cfg.get("consecutive_losses", 0) >= 3 else 2.0

    results = []
    for item in items:
        code, name = item["code"], item["name"]
        result = {"code": code, "name": name}

        # 趨勢策略（含數值：adx, macd_hist, close, ema20 等）
        trend = container.scanner.analyze_one(code, capital, risk_pct, strategy="trend")
        if trend:
            fmt = container.scanner.format_for_api([trend], strategy="trend")
            if fmt:
                f0 = fmt[0]
                sigs = f0.get("signals", {})
                passed = sum(1 for s in sigs.values() if s.get("pass"))
                result["trend"] = {
                    "score": passed, "total": len(sigs), "signals": sigs,
                    "close": f0.get("close"), "adx": f0.get("adx"),
                    "macd_hist": f0.get("macd_hist"), "atr": f0.get("atr"),
                    "ema5": f0.get("ema5"), "ema20": f0.get("ema20"), "ema60": f0.get("ema60"),
                    "volume": f0.get("volume"), "vol_avg": f0.get("vol_avg"),
                }
        if "trend" not in result:
            result["trend"] = None

        # 基本面策略（含數值：pe, eps, pb, revenue_growth 等）
        fund = container.scanner.analyze_one(code, capital, risk_pct, strategy="fundamental")
        if fund:
            fmt = container.scanner.format_for_api([fund], strategy="fundamental")
            if fmt:
                f0 = fmt[0]
                sigs = f0.get("signals", {})
                passed = sum(1 for s in sigs.values() if s.get("pass"))
                result["fundamental"] = {
                    "score": passed, "total": len(sigs), "signals": sigs,
                    "pe": f0.get("pe"), "eps": f0.get("eps"),
                    "forward_eps": f0.get("forward_eps"),
                    "pb": f0.get("pb"), "revenue_growth": f0.get("revenue_growth"),
                }
        if "fundamental" not in result:
            result["fundamental"] = None


        # Google News 最近 5 筆
        result["news"] = _fetch_google_news(name or code, limit=5)

        # ──【新增】長處一：自適應 AI 權重綜合評分演算法 ──
        if result.get("trend") and result.get("fundamental"):
            # 1. 計算目前的指標得分率 (0.0 ~ 1.0)
            t_score = result["trend"]["score"] / result["trend"]["total"] if result["trend"]["total"] > 0 else 0.5
            f_score = result["fundamental"]["score"] / result["fundamental"]["total"] if result["fundamental"]["total"] > 0 else 0.5
            
            # 2. 計算量化指標的衝突度 (Conflict Degree)
            # 當一個極多、一個極空時，相減絕對值接近 1 (衝突高)；兩者分數相近時接近 0 (一致性高)
            conflict_degree = abs(t_score - f_score)
            
            # 3. 根據衝突度，自適應動態調配 AI 與量化指標的權重
            # 一致性高 (conflict 低) -> 降低 AI 權重至 30%，讓數據說話
            # 衝突度高 (conflict 高) -> 提高 AI 權重至 55%，引入 AI 模糊邏輯研判
            ai_weight = 0.30 + (0.25 * (1.0 - conflict_degree))  # 範圍限制在 30% ~ 55%
            quant_weight = 1.0 - ai_weight                       # 剩餘權重分配給技術與基本面
            
            # 4. 模擬取得來自 Groq/Gemini 的 AI 預測分數 (預設基礎分為 0.6)
            # 未來您可以直接對接您的 AI 情緒分析結果 (正面新聞比例)
            ai_sentiment_score = 0.6  
            if result.get("news"):
                # 簡單示範：若最近新聞標題包含利多字眼，酌量加分
                bullish_count = sum(1 for n in result["news"] if any(w in n["title"] for w in ["漲", "紅", "追捧", "新高", "翻身"]))
                if len(result["news"]) > 0:
                    ai_sentiment_score = 0.5 + (0.5 * (bullish_count / len(result["news"])))

            # 5. 加權計算最終綜合多空得分 (百分制)
            quant_base = (t_score * 0.5 + f_score * 0.5) * quant_weight
            ai_base = ai_sentiment_score * ai_weight
            final_composite_score = round((quant_base + ai_base) * 100, 1)
            
            # 6. 判定綜合建議
            if final_composite_score >= 65:
                recommendation = "強勢看多 (量化共識)" if conflict_degree > 0.5 else "多頭配置 (AI 加持)"
            elif final_composite_score <= 45:
                recommendation = "保守觀望"
            else:
                recommendation = "多空交戰 (AI 權重擴大中)" if conflict_degree < 0.4 else "中性盤整"
                
            # 將算好的自適應評分包進回傳結果中
            result["adaptive_analysis"] = {
                "composite_score": final_composite_score,
                "ai_weight_pct": round(ai_weight * 100, 1),
                "quant_weight_pct": round(quant_weight * 100, 1),
                "conflict_degree": round(conflict_degree, 2),
                "recommendation": recommendation
            }
        else:
            result["adaptive_analysis"] = None

        results.append(result)
        time.sleep(0.3)

    return jsonify({"ok": True, "results": results})


def _fetch_google_news(query: str, limit: int = 3) -> list:
    """從 Google News RSS 搜尋相關新聞。"""
    url = f"https://news.google.com/rss/search?q={requests.utils.quote(query)}+股票&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
    try:
        resp = requests.get(url, timeout=10)
        if not resp.ok:
            return []
        root = fromstring(resp.content)
        items = []
        for item in root.iter("item"):
            title = item.findtext("title", "")
            link = item.findtext("link", "")
            pub = item.findtext("pubDate", "")
            date_str = ""
            if pub:
                parts = pub.split()
                if len(parts) >= 4:
                    day, mon, year = parts[1], parts[2], parts[3]
                    months = {"Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04",
                              "May": "05", "Jun": "06", "Jul": "07", "Aug": "08",
                              "Sep": "09", "Oct": "10", "Nov": "11", "Dec": "12"}
                    date_str = f"{year}-{months.get(mon, '01')}-{day.zfill(2)}"
            items.append({"title": title, "url": link, "date": date_str})
            if len(items) >= limit:
                break
        return items
    except Exception:
        return []
