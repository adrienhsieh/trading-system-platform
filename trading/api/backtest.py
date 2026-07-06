"""
trading/api/backtest.py — 回測、策略參數掃描、全市場回測（SSE 串流）
"""
import concurrent.futures
import queue as _queue

from flask import Blueprint, Response, jsonify, request, stream_with_context

from trading.api.auth import require_auth
from trading.api.extensions import limiter
from trading.constants import FULL_SCAN_WORKERS
from trading.services.container import container
from trading.strategies import REGISTRY
from trading.streaming import SSEStream

backtest_bp = Blueprint("backtest", __name__)


# ── 回測（單/多檔） ────────────────────────────────────────────

@backtest_bp.route("/api/backtest", methods=["POST"])
@require_auth
def run_backtest():
    from trading.backtest import BacktestEngine
    body           = request.get_json(silent=True) or {}
    raw_code       = (body.get("code") or "").strip()
    strategy       = body.get("strategy", "trend")
    capital        = float(body.get("capital") or container.config_mgr.load().get("total_capital", 1_000_000))
    risk_pct       = float(body.get("risk_pct", 2.0))
    min_score      = int(body.get("min_score", 4))
    period         = body.get("period", "2y")
    commission_pct = float(body.get("commission_pct", 0.001425))
    slippage_pct   = float(body.get("slippage_pct", 0.0005))

    if not raw_code:
        return jsonify({"ok": False, "error": "請輸入股票代號"}), 400
    if strategy not in REGISTRY:
        return jsonify({"ok": False, "error": f"未知策略：{strategy}"}), 400
    if period not in ("6mo", "1y", "2y", "3y", "5y"):
        period = "2y"

    engine = BacktestEngine(indicator_engine=container.ind_engine)
    codes  = [c.strip() for c in raw_code.replace("，", ",").split(",") if c.strip()]

    if len(codes) == 1:
        result = engine.run(
            codes[0], strategy=strategy, capital=capital,
            risk_pct=risk_pct, min_score=min_score, period=period,
            commission_pct=commission_pct, slippage_pct=slippage_pct,
        )
        if result.get("ok") and result.get("trades"):
            result["monte_carlo"] = engine.monte_carlo(
                result["trades"], capital=capital, n=500
            )
        result["multi"] = False
        return jsonify(result)

    result = engine.run_multi(
        codes, strategy=strategy, capital=capital,
        risk_pct=risk_pct, min_score=min_score, period=period,
        commission_pct=commission_pct, slippage_pct=slippage_pct,
    )
    result["multi"] = True
    return jsonify(result)


# ── 策略參數最佳化（SSE 串流） ─────────────────────────────────

@backtest_bp.route("/api/backtest/optimize")
@require_auth
@limiter.limit("1 per 5 minutes")
def backtest_optimize_stream():
    """枚舉 param_grid 所有組合，SSE 串流回傳進度。"""
    import json
    from trading.optimizer import StrategyOptimizer
    code     = request.args.get("code", "").strip()
    strategy = request.args.get("strategy", "trend")
    period   = request.args.get("period", "2y")
    if period not in ("6mo", "1y", "2y", "3y", "5y"):
        period = "2y"
    cfg            = container.config_mgr.load()
    capital        = float(request.args.get("capital", cfg["total_capital"]))
    risk_pct       = float(request.args.get("risk_pct", 2.0))
    commission_pct = float(request.args.get("commission_pct", 0.001425))
    slippage_pct   = float(request.args.get("slippage_pct", 0.0005))

    try:
        body       = request.get_json(silent=True) or {}
        param_grid = body.get("param_grid") or json.loads(request.args.get("param_grid", "{}"))
    except Exception:
        param_grid = {}

    if not code:
        def _err():
            yield SSEStream.error("請提供 code 參數")
        return Response(stream_with_context(_err()), mimetype="text/event-stream")

    opt = StrategyOptimizer(indicator_engine=container.ind_engine)

    def generate():
        for event in opt.sweep_stream(
            code,
            strategy=strategy,
            param_grid=param_grid,
            capital=capital,
            risk_pct=risk_pct,
            period=period,
            commission_pct=commission_pct,
            slippage_pct=slippage_pct,
        ):
            yield SSEStream.event(event)

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── 全市場回測（SSE 串流） ─────────────────────────────────────

@backtest_bp.route("/api/backtest/full")
@require_auth
@limiter.limit("2 per minute")
def backtest_full_stream():
    """先掃描全市場取得高分股，再依序回測並以 SSE 推送進度。"""
    from trading.backtest import BacktestEngine
    strategy  = request.args.get("strategy", "trend")
    if strategy not in REGISTRY:
        strategy = "trend"
    period    = request.args.get("period", "2y")
    if period not in ("6mo", "1y", "2y", "3y", "5y"):
        period = "2y"
    min_score = int(request.args.get("min_score", 4))
    tech_only = request.args.get("filter", "") == "tech"
    cfg       = container.config_mgr.load()
    capital   = float(request.args.get("capital", cfg["total_capital"]))
    risk_pct  = 1.0 if cfg.get("consecutive_losses", 0) >= 3 else 2.0

    def generate():
        sm    = container.scanner.get_tech_stock_map() if tech_only else container.scanner.get_stock_map()
        cands = list(sm.keys())
        total = len(cands)
        yield SSEStream.scan_start(total)

        pass_scored = []
        scan_q = _queue.Queue()

        def _scan_worker(code):
            r = container.scanner.analyze_one(
                code, capital, risk_pct, strategy=strategy, name=sm.get(code, "")
            )
            scan_q.put((code, r))

        with concurrent.futures.ThreadPoolExecutor(max_workers=FULL_SCAN_WORKERS) as executor:
            for code in cands:
                executor.submit(_scan_worker, code)

            for i in range(1, total + 1):
                try:
                    code, r = scan_q.get(timeout=15)
                except _queue.Empty:
                    continue
                if r and r["score"] >= min_score:
                    pass_scored.append((r["score"], code))
                if i % 50 == 0 or i == total:
                    yield SSEStream.scan_progress(i, total, len(pass_scored))

        pass_scored.sort(key=lambda x: x[0], reverse=True)
        pass_list = [code for _, code in pass_scored[:30]]

        bt_total = len(pass_list)
        yield SSEStream.bt_start(bt_total)

        engine     = BacktestEngine(indicator_engine=container.ind_engine)
        bt_results = []
        for i, code in enumerate(pass_list, 1):
            r = engine.run(code, strategy=strategy, capital=capital,
                           risk_pct=risk_pct, min_score=min_score, period=period)
            r["code"] = code
            r["name"] = sm.get(code, code)
            if r.get("ok"):
                bt_results.append(r)
                s = r["stats"]
                yield SSEStream.bt_result(
                    {"code": code, "name": r["name"], "total_return": s["total_return"],
                     "win_rate": s["win_rate"], "total_trades": s["total_trades"]},
                    done=i, total=bt_total,
                )
            else:
                yield SSEStream.bt_progress(i, bt_total)

        bt_results.sort(key=lambda x: x["stats"]["total_return"], reverse=True)
        summary = [
            {"code": r["code"], "name": r["name"],
             "total_return": r["stats"]["total_return"],
             "win_rate": r["stats"]["win_rate"],
             "total_trades": r["stats"]["total_trades"],
             "profit_factor": r["stats"]["profit_factor"],
             "max_drawdown": r["stats"]["max_drawdown"],
             "final_equity": r["final_equity"]}
            for r in bt_results
        ]
        yield SSEStream.done({"summary": summary, "strategy": strategy, "period": period})

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
