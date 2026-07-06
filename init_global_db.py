# init_global_db.py — 多租戶主庫初始化腳本 (強制重刷防錯版)
import os
import sqlite3
from werkzeug.security import generate_password_hash

def init_main_db():
    # 確保兩處的核心資料庫檔案欄位完全同步且正確
    db_paths = ["trading_system.db", "db/trading_system.db"]
    os.makedirs("db", exist_ok=True)
    
    for db_path in db_paths:
        print(f"⚙️ 正在強制清理並初始化全域主庫: {os.path.abspath(db_path)} ...")
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        try:
            # 🟢 核心修正：為了防範舊欄位不相容，強制刪除舊表重新建立
            cursor.execute("DROP TABLE IF EXISTS users;")
            cursor.execute("DROP TABLE IF EXISTS tenant_map;")
            
            # 1. 建立租戶映射表（物理實體隔離關鍵路由表）
            cursor.execute("""
                CREATE TABLE tenant_map (
                    tenant_id TEXT PRIMARY KEY,
                    db_physical_path TEXT NOT NULL,
                    isolation_level TEXT DEFAULT 'PHYSICAL_FILE',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            
            # 2. 建立符合新版多租戶架構的使用者主表 (具備所有正確欄位)
            cursor.execute("""
                CREATE TABLE users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    system_api_key TEXT NOT NULL,
                    tenant_id TEXT,
                    tg_chat_id TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY(tenant_id) REFERENCES tenant_map(tenant_id)
                );
            """)
            
            # 3. 建立一個預設的測試租戶路由 (指向 trader_adrien 的隔離庫路徑)
            test_tenant_id = "tenant_adrien_01"
            test_db_path = "db/user_adrien/userdata.db"
            os.makedirs("db/user_adrien", exist_ok=True)
            
            cursor.execute("""
                INSERT INTO tenant_map (tenant_id, db_physical_path, isolation_level)
                VALUES (?, ?, 'PHYSICAL_FILE')
            """, (test_tenant_id, test_db_path))
            
            # 4. 塞入測試使用者資料，綁定該租戶
            test_username = "trader_adrien"
            test_password_hash = generate_password_hash("test1234")
            target_api_key = "5d36857accb57df98ffab13dae7de57788e599c50a96669e9fbc818231317304"
            
            cursor.execute("""
                INSERT INTO users (username, password_hash, system_api_key, tenant_id, tg_chat_id)
                VALUES (?, ?, ?, ?, ?)
            """, (test_username, test_password_hash, target_api_key, test_tenant_id, "123456789"))
            
            conn.commit()
            print(f"✅ 資料庫 [{db_path}] 表格重刷成功！測試帳號 trader_adrien 與租戶路由已完美寫入。\n")
            
        except Exception as e:
            print(f"❌ 初始化 [{db_path}] 發生錯誤: {e}")
        finally:
            conn.close()

if __name__ == "__main__":
    init_main_db()