# create_admin.py
from app import app
from trading.api.admin_ui import db_appbuilder, init_admin_web_ui  # 💡 新增：引入初始化函式

with app.app_context():
    # 💡 核心修正：在讀取 Extensions 之前，先強制讓 Flask 載入 AppBuilder 引擎
    init_admin_web_ui(app)
    
    # 現在 app.extensions['appbuilder'] 已經安全存在，可以放心讀取了
    sm = app.extensions['appbuilder'].sm
    
    # 檢查 admin 帳號是否已經存在
    existing_admin = sm.find_user(username="admin")
    
    if not existing_admin:
        print("🔍 偵測到尚未建立管理員，正在為 trading.com SQLite Browser 初始化系統最高權限帳號...")
        
        # 建立一個擁有 Admin 角色的最高權限用戶
        admin_role = sm.find_role("Admin")
        new_admin = sm.add_user(
            username="admin",
            first_name="trading.com",
            last_name="管理員",
            email="admin@trading.com",
            role=admin_role,
            password="admin123"  # 💡 這裡輸入您想要的登入密碼！
        )
        if new_admin:
            print("==================================================")
            print(" ✅ 網頁版 SQLite Browser trading.com 最高權限建立成功！")
            print(" 👉 登入帳號: admin")
            print(" 👉 初始密碼: admin123")
            print("==================================================")
    else:
        print("ℹ️ 管理員帳號 'admin' 已存在，無需重複建立。")
