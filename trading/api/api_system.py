"""
trading/api/api_system.py — 系統狀態、健康檢查、Token 驗證
"""
import time
from flask import Blueprint, jsonify, request
from datetime import datetime
from trading.api.utils import decode_token

api_system = Blueprint("api_system", __name__)

_start_time = time.time()


@api_system.route("/api/health", methods=["GET"])
def health_check():
    return jsonify({
        "status": "ok",
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })


@api_system.route("/api/token/verify", methods=["GET"])
def token_verify():
    auth_header = request.headers.get("Authorization", None)
    if not auth_header or not auth_header.startswith("Bearer "):
        return jsonify({"error": "缺少或格式錯誤的 Authorization header"}), 401

    token = auth_header.split(" ", 1)[1]
    payload = decode_token(token)
    if not payload:
        return jsonify({"error": "無效或過期的 Token"}), 401

    return jsonify({
        "status": "valid",
        "user_id": payload.get("user_id"),
        "username": payload.get("username"),
        "issued_at": payload.get("iat"),
        "expires_at": payload.get("exp")
    })


@api_system.route("/api/system/info", methods=["GET"])
def system_info():
    uptime_seconds = int(time.time() - _start_time)
    uptime_str = (
        f"{uptime_seconds // 3600}h "
        f"{uptime_seconds % 3600 // 60}m "
        f"{uptime_seconds % 60}s"
    )
    return jsonify({
        "version": "1.0.0",
        "uptime": uptime_str,
        "services": [
            "pos_mgr", "ind_engine", "scanner",
            "market_svc", "news_agg", "intel_daemon", "coverage_reader"
        ]
    })


@api_system.route("/api/strategy_params", methods=["GET"])
def strategy_params():
    return jsonify({
        "params": {
            "risk_level": "medium",
            "max_positions": 10,
            "stop_loss": 0.05,
            "take_profit": 0.1,
            "rebalance_interval": "daily"
        }
    })