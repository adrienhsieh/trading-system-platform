"""
trading/api/auth.py — 多人登入（註冊 / 登入 / 個人資料）+ API 認證與輸入驗證輔助

多人登入帳密表：db/users.db（僅帳密表共用；每個使用者的持倉／觀察名單／策略設定
皆物理隔離於 db/user_{username}/，見 trading/services/container.py）。

為了不影響既有以 X-API-Key 驅動的內部工具／Telegram Bot／測試腳本，
require_auth 同時接受「合法 JWT（多人登入）」或「合法 X-API-Key（單機／內部）」，
兩者擇一通過即可放行；未帶 JWT 時 g.current_user_id 維持 None，
container 會自動退回單機預設租戶（相容既有 positions.db / config.json）。
"""
import functools
import hmac
import os
import re
import sqlite3
from pathlib import Path

from flask import Blueprint, g, jsonify, request

from trading.api.utils import decode_token, generate_token, jwt_required

BASE_DIR = Path(__file__).parent.parent.parent
USERS_DB_PATH = BASE_DIR / "db" / "users.db"
_USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,32}$")

api_auth = Blueprint("api_auth", __name__)


# ── 帳密資料庫（共用，僅存帳號/密碼雜湊） ──────────────────────────

def _get_users_conn() -> sqlite3.Connection:
    USERS_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(USERS_DB_PATH), timeout=15.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            display_name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()
    return conn


def ensure_users_db() -> None:
    """啟動時呼叫一次，確保 db/users.db 與資料表存在。"""
    _get_users_conn().close()


# ── 註冊 / 登入 / 個人資料 ──────────────────────────────────────

@api_auth.route("/api/auth/register", methods=["POST"])
def register():
    from werkzeug.security import generate_password_hash

    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    display_name = (data.get("display_name") or username).strip()

    if not _USERNAME_RE.match(username):
        return jsonify({"ok": False, "error": "帳號需為 3-32 碼英數字（可含 . _ -）"}), 400
    if len(password) < 6:
        return jsonify({"ok": False, "error": "密碼長度至少 6 碼"}), 400

    conn = _get_users_conn()
    try:
        conn.execute(
            "INSERT INTO users (username, password_hash, display_name) VALUES (?, ?, ?)",
            (username, generate_password_hash(password), display_name),
        )
        conn.commit()
        return jsonify({"ok": True, "message": "註冊成功，請登入"}), 201
    except sqlite3.IntegrityError:
        return jsonify({"ok": False, "error": "帳號已存在"}), 409
    finally:
        conn.close()


@api_auth.route("/api/auth/login", methods=["POST"])
def login():
    from werkzeug.security import check_password_hash

    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""

    conn = _get_users_conn()
    try:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if not row or not check_password_hash(row["password_hash"], password):
            return jsonify({"ok": False, "error": "帳號或密碼錯誤"}), 401

        token = generate_token(row["id"], row["username"])
        return jsonify({
            "ok": True,
            "token": token,
            "user_id": row["id"],
            "username": row["username"],
            "display_name": row["display_name"] or row["username"],
        })
    finally:
        conn.close()


@api_auth.route("/api/auth/me", methods=["GET"])
@jwt_required
def me():
    conn = _get_users_conn()
    try:
        row = conn.execute(
            "SELECT id, username, display_name, created_at FROM users WHERE username = ?",
            (g.current_username,),
        ).fetchone()
        return jsonify({"ok": True, "user": dict(row) if row else {}})
    finally:
        conn.close()


# ── 既有 API 認證（X-API-Key，單機／內部工具相容） ──────────────

def _get_api_key() -> str:
    """讀取 api_key。支援 TRADING_CONFIG_PATH env var 覆寫（測試用）。"""
    import json
    try:
        cfg_path_env = os.environ.get("TRADING_CONFIG_PATH", "")
        default_path = BASE_DIR / "config.json"
        cfg_path = Path(cfg_path_env) if cfg_path_env else default_path
        if cfg_path.exists():
            with open(cfg_path, encoding="utf-8") as f:
                return json.load(f).get("api_key", "")
    except Exception:
        pass
    return ""


def require_auth(f):
    """
    裝飾器：接受「合法 JWT（多人登入 Bearer Token）」或「合法 X-API-Key」擇一通過。

    - 帶有效 JWT → g.current_user_id / g.current_username 設定為該登入用戶，
      container 會自動切換至該用戶專屬資料庫（多人隔離）。
    - 帶有效 X-API-Key（沒有 JWT）→ g.current_user_id 維持 None，
      container 退回單機預設租戶（相容既有 positions.db / config.json，
      供 Telegram Bot、排程器、測試腳本等背景流程使用）。

    白名單例外：
    - /api/config/* — 網頁設定相關（未來應交由 Session 驗證）
    - /api/user_page_config/* — 新版設定 API
    """
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        is_whitelisted = request.path.startswith(("/api/config", "/api/user_page_config"))

        # EventSource（SSE 串流：/api/scan/full、回測進度…）無法自訂 Header，
        # 允許把 JWT 放在 query string ?token=... 傳遞，效果等同 Authorization: Bearer。
        query_token = request.args.get("token", "")
        bearer_token = ""
        if auth_header.startswith("Bearer "):
            bearer_token = auth_header.split(" ", 1)[1].strip()
        token = bearer_token or query_token

        if token:
            payload = decode_token(token)
            if payload is not None:
                g.current_user_id = payload.get("user_id")
                g.current_username = payload.get("username", "")
                return f(*args, **kwargs)
            if is_whitelisted:
                g.current_user_id = None
                g.current_username = ""
                return f(*args, **kwargs)
            return jsonify({"ok": False, "error": "無效或過期的憑證，請重新登入"}), 401

        if is_whitelisted:
            g.current_user_id = None
            g.current_username = ""
            return f(*args, **kwargs)

        key = request.headers.get("X-API-Key") or request.args.get("key", "")
        expected = _get_api_key()
        if expected and hmac.compare_digest(key, expected):
            g.current_user_id = None
            g.current_username = ""
            return f(*args, **kwargs)

        return jsonify({"ok": False, "error": "Unauthorized"}), 401
    return decorated


def validate_code(code: str):
    """驗證股票代號為 4 位數字；不合格時回傳 400 Response，否則回傳 None。"""
    if not re.match(r'^\d{4}$', code):
        return jsonify({"ok": False, "error": f"無效股票代號：{code}（需為 4 位數字）"}), 400
    return None


def validate_number(val, name: str):
    """嘗試將 val 轉為 float；失敗時回傳 400 Response，否則回傳 None。"""
    try:
        float(val)
        return None
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": f"欄位 {name} 需為數字"}), 400
