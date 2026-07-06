# trading/services/config_db.py
import os
import json
from pathlib import Path
from sqlalchemy import create_engine, Column, String, JSON, text, inspect
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# 確保路徑指向正確的專案根目錄
BASE_DIR = Path(__file__).parent.parent.parent
DATABASE_URL = f"sqlite:///{BASE_DIR}/trading_system.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# ==============================================================================
# 1. 資料庫資料表定義
# ==============================================================================
class UserPageConfig(Base):
    __tablename__ = "user_page_configs"
    
    user_id = Column(String, primary_key=True, index=True)
    module_id = Column(String, primary_key=True, index=True)
    configs = Column(JSON, nullable=False)

def init_db():
    """初始化資料庫（自動建表）"""
    Base.metadata.create_all(bind=engine)


# 🟢 修正後的系統預設設定值
DEFAULT_MODULE_CONFIGS = {
    "grid_trading": {
        "grid_num": 10,
        "lower_limit": 0,
        "auto_stop": False
    },
    "kline_chart": {
        "theme": "dark",
        "ma_line": [5, 10, 20, 60]  # 💡 補上了均線天數的預設列表值，修復語法錯誤
    },
    "settings_page": {
        "total_capital": 3000000,
        "consecutive_losses": 0
    }
}

# ==============================================================================
# 2. 🚀 策略端核心功能：讀取當前使用者設定
# ==============================================================================
def get_strategy_config(user_id: str, module_id: str) -> dict:
    """
    供 trading/ 內部策略腳本直接呼叫。
    用法範例：
        from trading.services.config_db import get_strategy_config
        cfg = get_strategy_config("jack", "grid_trading")
        print(cfg['grid_num'])  # 輸出 88
    """
    db = SessionLocal()
    try:
        record = db.query(UserPageConfig).filter(
            UserPageConfig.user_id == user_id,
            UserPageConfig.module_id == module_id
        ).first()
        if record:
            return record.configs
        return DEFAULT_MODULE_CONFIGS.get(module_id, {})
    finally:
        db.close()

# ==============================================================================
# 3. 🛠️ 資料表管理工具 與 🖥️ SQL 編輯器 (主控台模式)
# ==============================================================================
class DatabaseManager:
    @staticmethod
    def show_all_tables():
        """列出資料庫內所有的資料表與其結構"""
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        print(f"\n📁 [資料表總覽] 目前 SQLite 內共有 {len(tables)} 個資料表：")
        print("-" * 60)
        for table_name in tables:
            print(f" 🔹 資料表名稱: 【 {table_name} 】")
            columns = inspector.get_columns(table_name)
            col_details = [f"{col['name']} ({col['type']})" for col in columns]
            print(f"    ↳ 欄位結構: {', '.join(col_details)}")
        print("-" * 60)

    @staticmethod
    def execute_sql(sql_query: str):
        """🖥️ 內建 SQL 編輯器：執行任意 SQL 語句並格式化輸出結果"""
        print(f"\n⚡ [SQL EDITOR] 執行指令: {sql_query}")
        print("=" * 60)
        db = SessionLocal()
        try:
            # 使用 SQLAlchemy 1.4+ 規範的 text 物件執行
            result = db.execute(text(sql_query))
            
            # 如果是 SELECT 查詢，印出表格結果
            if result.returns_rows:
                rows = result.all()
                if not rows:
                    print(" ( 查詢成功，但資料表中目前沒有任何資料 )")
                else:
                    # 抓取欄位名稱當作表頭
                    headers = list(result.keys())
                    print(f" | {' | '.join(headers)} |")
                    print(" | " + " | ".join(["-" * len(h) for h in headers]) + " |")
                    for row in rows:
                        # 將欄位值轉換為字串印出，特別處理 JSON 物件使其易讀
                        row_strs = [json.dumps(val) if isinstance(val, (dict, list)) else str(val) for val in row]
                        print(f" | {' | '.join(row_strs)} |")
                print(f" 💡 總共回傳了 {len(rows)} 筆資料。")
            else:
                # 如果是 INSERT / UPDATE / DELETE
                db.commit()
                print(f" ✅ 執行成功！受影響的資料列列數: {result.rowcount}")
        except Exception as e:
            db.rollback()
            print(f" ❌ [SQL 錯誤]: {str(e)}")
        finally:
            db.close()
        print("=" * 60)

# ==============================================================================
# 當此檔案被直接執行時 (python trading/services/config_db.py) 啟動管理面板
# ==============================================================================
if __name__ == "__main__":
    init_db()
    print("\n==================================================")
    print("      ⚔️ 交易系統資料庫實時管理與 SQL 戰情面板 ⚔️")
    print("==================================================")
    
    # 1. 展示所有資料表
    DatabaseManager.show_all_tables()
    
    # 2. 模擬測試：策略核心程式碼讀取 Jack 的設定
    print("🔍 [策略測試] 模擬核心策略讀取目前使用者 'jack' 的 'grid_trading' 設定...")
    jack_cfg = get_strategy_config("jack", "grid_trading")
    print(f" 👉 讀取成功！當前網格數量為: {jack_cfg.get('grid_num')} 格，下限價格: {jack_cfg.get('lower_limit')}")
    print("-" * 60)

    # 3. 執行 SQL 查詢 (SQL Editor 實作展示)
    # 查詢目前所有使用者的自訂設定詳情
    DatabaseManager.execute_sql("SELECT user_id, module_id, configs FROM user_page_configs;")
    
    # 提示使用者如何自由使用此 SQL 編輯器
    print("\n💡 [提示] 您可以在程式碼下方的 `DatabaseManager.execute_sql(...)` 內，")
    print("   直接輸入任何合法的 SQL 語句（如 INSERT、UPDATE、DELETE）來手動維護資料庫！\n")
