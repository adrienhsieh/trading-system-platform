"""
trading/api/utils.py — JWT 憑證簽發、解密與驗證裝飾器（多人登入核心）

設計原則（對齊「JWT 多人版（Multi-tenant）改造規格說明書」）：
- 帳密表共用（db/users.db），個人資料物理隔離（db/user_{username}/）。
- Token 內夾帶 user_id + username，驗證通過後注入 flask.g，
  供 trading.services.container 依此動態切換至該用戶專屬的 DB／設定檔。
"""
import os
from datetime import datetime, timedelta, timezone
from functools import wraps

import jwt
from flask import g, jsonify, request

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

JWT_EXPIRY_HOURS = int(os.environ.get("JWT_EXPIRY_HOURS", 24))


def get_jwt_secret() -> str:
    """JWT 簽章密鑰。正式環境務必在 .env 設定 JWT_SECRET_KEY 覆蓋此開發用預設值。"""
    return os.environ.get("JWT_SECRET_KEY") or os.environ.get(
        "FLASK_SECRET_KEY", "trading_system_dev_only_change_me_2026"
    )


def generate_token(user_id, username: str = "") -> str:
    """生成 JWT Token，payload 內含 user_id 與 username。"""
    now = datetime.now(timezone.utc)
    payload = {
        "exp": now + timedelta(hours=JWT_EXPIRY_HOURS),
        "iat": now,
        "user_id": user_id,
        "username": username,
    }
    return jwt.encode(payload, get_jwt_secret(), algorithm="HS256")


def decode_token(token: str):
    """解密 Token，成功回傳 payload dict，失敗回傳 None（不拋例外，供 optional 驗證使用）。"""
    try:
        return jwt.decode(token, get_jwt_secret(), algorithms=["HS256"])
    except jwt.PyJWTError:
        return None


def _extract_bearer_token() -> str:
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header.split(" ", 1)[1].strip()
    return ""


def jwt_required(f):
    """強制要求合法 JWT；驗證通過後將 g.current_user_id / g.current_username 注入。"""
    @wraps(f)
    def decorated(*args, **kwargs):
        token = _extract_bearer_token()
        if not token:
            return jsonify({"ok": False, "error": "未提供憑證，請先登入"}), 401
        payload = decode_token(token)
        if payload is None:
            return jsonify({"ok": False, "error": "無效或過期的憑證，請重新登入"}), 401
        g.current_user_id = payload.get("user_id")
        g.current_username = payload.get("username", "")
        return f(*args, **kwargs)
    return decorated


def jwt_optional(f):
    """選填 JWT：若帶有效 Token 則注入 g.current_user_id；否則保持 None（維持單機／預設租戶行為）。
    用於需要同時相容「未登入單機模式」與「多人登入模式」的既有 API。"""
    @wraps(f)
    def decorated(*args, **kwargs):
        token = _extract_bearer_token()
        payload = decode_token(token) if token else None
        g.current_user_id = payload.get("user_id") if payload else None
        g.current_username = payload.get("username", "") if payload else ""
        return f(*args, **kwargs)
    return decorated
