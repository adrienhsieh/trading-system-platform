# trading/api/user_config.py
from flask import Blueprint, request, jsonify, g
from trading.services.config_db import SessionLocal, UserPageConfig, DEFAULT_MODULE_CONFIGS
from trading.api.utils import decode_token

# 🟢 核心修正：改用獨立的 URL 前綴 /api/user_page_config，徹底避開大總管設定的干擾
user_setting_bp = Blueprint("user_page_settings", __name__, url_prefix="/api/user_page_config")


def _resolve_user_id(fallback: str = None) -> str:
    """若帶有效 JWT，優先以登入身分作為 user_id（多人登入時彼此隔離）；
    否則相容舊版直接由前端傳入 user_id 的行為。"""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        payload = decode_token(auth_header.split(" ", 1)[1].strip())
        if payload:
            return payload.get("username") or str(payload.get("user_id"))
    return fallback


@user_setting_bp.route("", methods=["GET"])
def get_user_page_config():
    module_id = request.args.get("module_id")
    user_id = _resolve_user_id(request.args.get("user_id"))

    if not user_id or not module_id:
        return jsonify({"ok": False, "error": "缺少參數 user_id 或 module_id"}), 400
        
    db = SessionLocal()
    try:
        record = db.query(UserPageConfig).filter(
            UserPageConfig.user_id == user_id,
            UserPageConfig.module_id == module_id
        ).first()
        
        if record:
            return jsonify({"ok": True, "data": record.configs})
        # 查無紀錄時，發放系統預設值
        return jsonify({"ok": True, "data": DEFAULT_MODULE_CONFIGS.get(module_id, {})})
    finally:
        db.close()

@user_setting_bp.route("/save", methods=["POST"])
def save_user_page_config():
    data = request.get_json() or {}
    module_id = data.get("module_id")
    configs = data.get("configs")
    user_id = _resolve_user_id(data.get("user_id"))

    if not user_id or not module_id or configs is None:
        return jsonify({"ok": False, "error": "資料欄位不完整"}), 400
        
    db = SessionLocal()
    try:
        record = db.query(UserPageConfig).filter(
            UserPageConfig.user_id == user_id,
            UserPageConfig.module_id == module_id
        ).first()
        
        if record:
            record.configs = configs
        else:
            new_record = UserPageConfig(user_id=user_id, module_id=module_id, configs=configs)
            db.add(new_record)
            
        db.commit()
        return jsonify({"ok": True, "message": "儲存成功"})
    except Exception as e:
        db.rollback()
        return jsonify({"ok": False, "error": str(e)}), 500
    finally:
        db.close()

# ── 💡 智慧新增：直接貼在檔案最底部（完美併入 user_setting_bp 藍圖） ─────────────────
import os
import json
from pathlib import Path

# 💡 智慧相對路徑定位：因為當前檔案在 trading/api/ 下，必須向上推三層才能精準鎖定根目錄的 config.json
BASE_DIR = Path(__file__).parent.parent.parent
CONFIG_FILE_PATH = os.path.join(str(BASE_DIR), "config.json")

@user_setting_bp.route("/query_config", methods=["GET"])
def query_local_config():
    """
    🔍 讀取與 app.py 根目錄同路徑下的 config.json 全局配置文件內容
    """
    # 💡 1. 物理安全防禦：檢查檔案是否存在，不在就噴錯不崩潰
    if not os.path.exists(CONFIG_FILE_PATH):
        return jsonify({
            "ok": False,
            "error": "檔案不存在",
            "message": f"在根目錄找不到 config.json，請確認檔案位置！(預期路徑: {CONFIG_FILE_PATH})"
        }), 404

    try:
        # 💡 2. 安全讀取：指定 utf-8 編碼，完美兼容中文字元防止亂碼
        with open(CONFIG_FILE_PATH, "r", encoding="utf-8") as f:
            config_data = json.load(f)
            
        # 💡 3. 精準吐回：以標準 JSON 格式傳回給前端
        return jsonify({
            "ok": True,
            "data": config_data
        }), 200

    except json.JSONDecodeError as je:
        # 💡 4. 語法防禦：防範 config.json 內部有語法錯字或漏掉引號導致解析出錯
        return jsonify({
            "ok": False,
            "error": "JSON 語法錯誤",
            "message": f"config.json 格式破裂，解析失敗：{str(je)}"
        }), 500
        
    except Exception as e:
        # 💡 5. 全域防禦：攔截任何未知的系統讀取與權限異常
        return jsonify({
            "ok": False,
            "error": "讀取異常",
            "message": str(e)
        }), 500
        
@user_setting_bp.route("/update_config", methods=["POST"])
def update_local_config():
    """
    💾 接收前端修改後的 JSON 字串，安全語法查核後，覆寫寫入 config.json
    """
    data = request.get_json() or {}
    new_config_str = data.get("config_json_str", "").strip()

    if not new_config_str:
        return jsonify({"ok": False, "error": "非法請求", "message": "傳入的 JSON 內容不可為空！"}), 400

    try:
        # 💡 1. 嚴格語法預審：在寫入硬碟前，先嘗試用 json.loads 驗證格式。
        #      如果使用者少打了引號、逗號，會在記憶體中直接被攔截，100% 防止系統設定檔被改壞！
        parsed_json = json.loads(new_config_str)

        # 💡 2. 安全覆寫：使用 utf-8 萬國碼寫入，並加上 indent=4 保持檔案排版精美易讀
        with open(CONFIG_FILE_PATH, "w", encoding="utf-8") as f:
            json.dump(parsed_json, f, ensure_ascii=False, indent=4)

        return jsonify({"ok": True, "message": "全域配置 config.json 已成功安全覆寫並套用！"})

    except json.JSONDecodeError as je:
        # 💡 3. 語法防禦：即時噴出錯在哪一行、哪一個字元，方便使用者 debug
        return jsonify({
            "ok": False,
            "error": "JSON 語法格式錯誤",
            "message": f"請檢查括號或逗號是否對齊！解析失敗原因：{str(je)}"
        }), 400
    except Exception as e:
        return jsonify({"ok": False, "error": "寫入異常", "message": str(e)}), 500
