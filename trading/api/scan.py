"""
trading/api/scan.py — 股票資訊、個股分析、掃描（含全市場 SSE 串流）
"""
import concurrent.futures
import queue as _queue

from flask import Blueprint, Response, jsonify, request, stream_with_context

from trading.api.auth import require_auth, validate_code
from trading.api.extensions import limiter
from trading.constants import FULL_SCAN_WORKERS
from trading.services.container import container
from trading.strategies import REGISTRY
from trading.streaming import SSEStream

scan_bp = Blueprint("scan", __name__)


# ── 股票資訊 ───────────────────────────────────────────────────

@scan_bp.route("/api/stock_info/<code>")
@require_auth
def stock_info(code: str):
    code = code.strip()
    err = validate_code(code)
    if err:
        return err
    name = container.scanner.get_stock_name(code)
    if name and name != code:
        return jsonify({"ok": True, "code": code, "name": name, "market": "", "group": ""})
    import yfinance as yf
    for suffix in [".TW", ".TWO"]:
        try:
            info = yf.Ticker(f"{code}{suffix}").info
            name = info.get("longName") or info.get("shortName") or ""
            if name:
                return jsonify({"ok": True, "code": code, "name": name, "market": "", "group": ""})
        except Exception:
            pass
    return jsonify({"ok": False, "code": code, "name": ""}), 404


# ── 個股分析 ───────────────────────────────────────────────────

@scan_bp.route("/api/analyze/<code>")
@require_auth
def analyze_stock(code: str):
    code = code.strip()
    err = validate_code(code)
    if err:
        return err
    strategy = request.args.get("strategy", "trend")
    if strategy not in REGISTRY:
        return jsonify({"ok": False, "error": f"未知策略：{strategy}"}), 400
    cfg      = container.config_mgr.load()
    capital  = cfg["total_capital"]
    risk_pct = 1.0 if cfg.get("consecutive_losses", 0) >= 3 else 2.0
    result   = container.scanner.analyze_one(code, capital, risk_pct, strategy=strategy)
    if result is None:
        return jsonify({"ok": False, "error": "資料不足或代號錯誤"}), 404
    cov = None
    try:
        ov = container.coverage_reader.get_overview(code)
        if ov:
            cov = {
                "business":     ov["business"],
                "supply_chain": ov["supply_chain"],
                "wikilinks":    ov["wikilinks"],
            }
    except Exception:
        pass
    return jsonify({"ok": True, "strategy": strategy, "result": {
        "code":     result["code"],
        "name":     result["name"],
        "score":    result["score"],
        "ind":      result["ind"],
        "params":   result["params"],
        "coverage": cov,
    }})


# ── 候選清單掃描 ───────────────────────────────────────────────

@scan_bp.route("/api/scan", methods=["POST"])
@require_auth
def run_scan():
    body     = request.get_json(silent=True) or {}
    strategy = body.get("strategy") or request.args.get("strategy", "trend")
    if strategy not in REGISTRY:
        return jsonify({"ok": False, "error": f"未知策略：{strategy}"}), 400
    cfg        = container.config_mgr.load()
    capital    = cfg["total_capital"]
    risk_pct   = 1.0 if cfg.get("consecutive_losses", 0) >= 3 else 2.0
    candidates = cfg.get("scan_candidates", [])
    results    = container.scanner.run_scan(candidates, capital, risk_pct, strategy=strategy)
    api_results = container.scanner.format_for_api(results, strategy=strategy)
    return jsonify({
        "ok":       True,
        "strategy": strategy,
        "results":  api_results,
        "risk_pct": risk_pct,
        "scanned":  len(candidates),
    })


# ── 全市場掃描（SSE 串流） ─────────────────────────────────────

@scan_bp.route("/api/scan/full")
@require_auth
@limiter.limit("6 per minute")
def scan_full_stream():
    strategy  = request.args.get("strategy", "trend")
    tech_only = request.args.get("filter", "") == "tech"
    if strategy not in REGISTRY:
        strategy = "trend"
    cfg      = container.config_mgr.load()
    capital  = cfg["total_capital"]
    risk_pct = 1.0 if cfg.get("consecutive_losses", 0) >= 3 else 2.0

    def generate():
        sm    = container.scanner.get_tech_stock_map() if tech_only else container.scanner.get_stock_map()
        cands = list(sm.keys())
        total = len(cands)
        q     = _queue.Queue()
        results: list = []

        yield SSEStream.start(total)

        def _worker(code):
            r = container.scanner.analyze_one(code, capital, risk_pct, strategy=strategy, name=sm.get(code, ""))
            q.put((code, r))

        with concurrent.futures.ThreadPoolExecutor(max_workers=FULL_SCAN_WORKERS) as executor:
            for code in cands:
                executor.submit(_worker, code)

            for done in range(1, total + 1):
                try:
                    code, r = q.get(timeout=15)
                except _queue.Empty:
                    yield SSEStream.progress(done, total)
                    continue
                if r:
                    results.append(r)
                    fmt = container.scanner.format_for_api([r], strategy=strategy)[0]
                    yield SSEStream.result(fmt, done=done, total=total)
                else:
                    yield SSEStream.progress(done, total)

        results.sort(key=lambda x: x["score"], reverse=True)
        yield SSEStream.done({
            "results":  container.scanner.format_for_api(results, strategy=strategy),
            "total":    total,
            "risk_pct": risk_pct,
            "strategy": strategy,
        })

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
