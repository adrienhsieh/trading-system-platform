import os
import json
import time
import sqlite3
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime
import pandas as pd
import requests
from sqlalchemy import create_engine

# ==================== 系統全域設定 ====================
STOCK_CODE = "2330"  # 目標股號
FINMIND_TOKEN = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJ1c2VyX2lkIjoiYWRyaWVuIiwiZW1haWwiOiJhZHJpZW5oc2llaEBnbWFpbC5jb20iLCJ0b2tlbl92ZXJzaW9uIjoxfQ.BMrXqaq-yrlwwS7h-qpUQuKPeqqc26fhOA6ly_lf7ZA"

# 修正後的核心 API 端點
FINMIND_URL = "https://finmindtrade.com"
TWSE_URL = f"https://twse.com.tw_{STOCK_CODE}.tw|tse_{STOCK_CODE}_odd.tw"

# 檔案儲存路徑
DB_FILE = "stock_monitor.db"
EXCEL_FILE = "stock_records.xlsx"

# 警示價位設定
ALERT_HIGH = 2420.0
ALERT_LOW = 2400.0
FETCH_INTERVAL = 5  # 更新頻率 (秒)

# Supabase 連線帳密安全編碼處理 (防止特殊字元破壞連線)
DB_USER = "postgres"
DB_PASS = urllib.parse.quote_plus(".SkyTree123")  # 自動處理密碼中的點號與特殊字元
DB_HOST = "://supabase.com"
DB_PORT = "5432"
DB_NAME = "postgres"

SUPABASE_URI = f"postgresql+psycopg2://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
# ====================================================


# ====================================================
# 核心功能一：獨立資料擷取函數 (預設 FinMind，傳參切 TWSE)
# ====================================================
def fetch_market_data(stock_id: str, force_fallback: bool = False) -> str:
    """擷取股票數據。
    預設固定使用 FinMind，當 force_fallback=True 或 FinMind 異常時才切換 TWSE。
    回傳值：統一自訂結構的 JSON 字串。
    """
    now = datetime.now()
    sys_date = now.strftime("%Y-%m-%d")
    sys_time = now.strftime("%H:%M:%S")

    # 初始化統一的自訂回傳 JSON 結構
    result_data = {
        "status": "success",
        "data_source": "FinMind",
        "query_date": sys_date,
        "query_time": sys_time,
        "stock_code": stock_id,
        "stock_name": "台積電",
        "price": 0.0,
        "volume": 0,
        "type": "整股",
    }

    # 條件判斷：若非強制使用備援，則優先走 FinMind 通道
    if not force_fallback:
        try:
            params = {
                "dataset": "TaiwanStockTick",
                "data_id": stock_id,
                "date": sys_date,
            }
            if FINMIND_TOKEN:
                params["token"] = FINMIND_TOKEN

            response = requests.get(FINMIND_URL, params=params, timeout=5)
            if response.status_code == 200:
                res_json = response.json()
                if res_json.get("status") == 200 and res_json.get("data"):
                    latest_tick = res_json["data"][-1]
                    result_data["price"] = float(latest_tick.get("deal_price", 0))
                    result_data["volume"] = int(latest_tick.get("volume", 0))
                    result_data["data_source"] = "FinMind"
                    result_data["type"] = "整股(FinMind)"
                    return json.dumps(result_data, ensure_ascii=False)
        except Exception as e:
            print(f"⚠️ [系統提示] FinMind 擷取失敗，準備自動導向 TWSE 備援。錯誤: {e}")

    # 備援機制通道 (或由參數強制指定)
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        response = requests.get(TWSE_URL, headers=headers, timeout=5)
        if response.status_code == 200:
            twse_json = response.json()
            msg_array = twse_json.get("msgArray", [])
            if msg_array:
                # 優先抓取整股資料 (通常在陣列第一筆)
                stock_info = msg_array[0]
                for item in msg_array:
                    if "_odd" not in item.get("@", ""):
                        stock_info = item
                        break

                result_data["stock_name"] = stock_info.get("n", "台積電")
                try:
                    result_data["price"] = float(stock_info.get("z", 0))
                except:
                    result_data["price"] = 0.0
                try:
                    result_data["volume"] = int(stock_info.get("v", 0))
                except:
                    result_data["volume"] = 0
                
                is_odd = "_odd" in stock_info.get("@", "")
                result_data["type"] = "零股" if is_odd else "整股"
                result_data["data_source"] = "TWSE"
                return json.dumps(result_data, ensure_ascii=False)
    except Exception as e:
        result_data["status"] = "failed"
        print(f"❌ [重大異常] 所有資料管道皆無法連線。錯誤: {e}")

    return json.dumps(result_data, ensure_ascii=False)


# ====================================================
# 工具函數：將 JSON 轉為 XML 格式
# ====================================================
def convert_json_to_xml(json_str: str) -> str:
    """將自訂 JSON 格式字串轉換為 XML 格式字串."""
    data = json.loads(json_str)
    root = ET.Element("StockInfo")
    for key, val in data.items():
        child = ET.SubElement(root, key)
        child.text = str(val)
    return ET.tostring(root, encoding="utf-8").decode("utf-8")


# ====================================================
# 核心功能二：多媒介混合硬資料跨資料庫通用存儲模組
# ====================================================
class DataStorageManager:
    """專門負責將混硬格式資料 (JSON/XML) 解析並分流儲存至多種不同的資料庫媒介。"""

    @staticmethod
    def _to_dataframe(mixed_data: str) -> pd.DataFrame:
        """萬能格式解析器：自動支援將輸入的 JSON 或 XML 轉換為 DataFrame。"""
        if mixed_data.strip().startswith("<"):
            root = ET.fromstring(mixed_data)
            data_dict = {child.tag: child.text for child in root}
            data_dict["price"] = float(data_dict.get("price", 0))
            data_dict["volume"] = int(data_dict.get("volume", 0))
        else:
            data_dict = json.loads(mixed_data)
        return pd.DataFrame([data_dict])

    @classmethod
    def save_to_excel(cls, mixed_data: str, filename: str = EXCEL_FILE):
        df_new = cls._to_dataframe(mixed_data)
        if os.path.exists(filename):
            try:
                df_old = pd.read_excel(filename)
                df_combined = pd.concat([df_old, df_new], ignore_index=True)
            except:
                df_combined = df_new
        else:
            df_combined = df_new
        df_combined.to_excel(filename, index=False)
        print("💾 已成功寫入/附加至 Excel")

    @classmethod
    def save_to_sqlite(cls, mixed_data: str, db_name: str = DB_FILE):
        df = cls._to_dataframe(mixed_data)
        conn = sqlite3.connect(db_name)
        df.to_sql("stock_logs", con=conn, if_exists="append", index=False)
        conn.close()
        print("💾 已成功 Insert 至 SQLite")

    @classmethod
    def save_to_relational_db(cls, mixed_data: str, db_type: str, connection_string: str):
        """透過 SQLAlchemy 引擎，自動將資料字典寫入遠端/雲端關聯式資料庫。"""
        df = cls._to_dataframe(mixed_data)
        try:
            engine = create_engine(connection_string)
            df.to_sql("stock_logs", con=engine, if_exists="append", index=False)
            print(f" Let's Go! 資料已成功寫入 {db_type} 資料庫。")
        except Exception as e:
            print(f"❌ 寫入 {db_type} 失敗，請檢查連線設定與套件。錯誤: {e}")


# ====================================================
# 主監控與排程流程
# ====================================================
def start_monitor(use_fallback_initially: bool = False):
    """啟動即時追蹤與雙儲存排程，預設固定使用 FinMind API。"""
    print("====== 雙核心自動化台股監控系統啟動 ======")
    print(f"目前設定 -> 高價警示: {ALERT_HIGH} | 低價警示: {ALERT_LOW}\n")
    
    # 決定初始是否手動強制開啟備援 (一般狀況下為 False)
    force_fallback = use_fallback_initially

    try:
        while True:
            # 1. 抓取格式固定的監控資料 (JSON 字串)
            raw_json_str = fetch_market_data(STOCK_CODE, force_fallback=force_fallback)
            data_dict = json.loads(raw_json_str)

            # 2. 終端機即時排版輸出
            sys_time = data_dict["query_time"]
            name = data_dict["stock_name"]
            code = data_dict["stock_code"]
            price = data_dict["price"]
            volume = data_dict["volume"]
            source = data_dict["data_source"]

            print(f"[{sys_time}] {name}({code}) | 來源: {source} | 最新價: {price} | 累積量: {volume}")

            # 3. 觸發價格警示機制
            if price > 0:
                if price >= ALERT_HIGH:
                    print(f"🚨【高價警示】{name} 當前價格 {price} 已達或超過設定目標 {ALERT_HIGH}！")
                elif price <= ALERT_LOW:
                    print(f"📉【低價警示】{name} 當前價格 {price} 已達或低於設定目標 {ALERT_LOW}！")

            # 4. 多資料庫並行儲存 (同時相容 JSON / XML 混硬模式)
            if data_dict["status"] == "success":
                # 本地儲存
                DataStorageManager.save_to_excel(raw_json_str)
                DataStorageManager.save_to_sqlite(raw_json_str)
                
                # 雲端 Supabase PostgreSQL 儲存
                DataStorageManager.save_to_relational_db(raw_json_str, "Supabase", SUPABASE_URI)
            
            print("-" * 60)
            time.sleep(FETCH_INTERVAL)

    except KeyboardInterrupt:
        print("\n👋 監控程式已由使用者手動終止。")


if __name__ == "__main__":
    # 執行監控主流程 (若想手動切換到 TWSE 備援，可將參數改為 True)
    start_monitor(use_fallback_initially=False)
