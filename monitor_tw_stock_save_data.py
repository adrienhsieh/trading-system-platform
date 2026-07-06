import os
import json
import time
import sqlite3
from datetime import datetime
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker

# ==================== 系統全域內嵌設定區 ====================
STOCK_TARGETS = ["2330", "2317"]  
FETCH_INTERVAL = 5  

FINMIND_TOKEN = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJ1c2VyX2lkIjoiYWRyaWVuIiwiZW1haWwiOiJhZHJpZW5oc2llaEBnbWFpbC5jb20iLCJ0b2tlbl92ZXJzaW9uIjoxfQ.BMrXqaq-yrlwwS7h-qpUQuKPeqqc26fhOA6ly_lf7ZA"

LOCAL_DB_FILE = "stock_monitor.db"
EXCEL_FILE = "stock_records.xlsx"

# 🌟 [Supabase 已填入設定] 採用 Pooler 模式 (Port: 6543) 確保長時間連線穩定
#SUPABASE_CONN_STRING = "postgresql://postgres.dgxghhxoagxinhhhpvis:.SkyTree123@aws-0-ap-northeast-1.pooler.supabase.com:6543/postgres"
SUPABASE_CONN_STRING = "postgresql://postgres.dgxghhxoagxinhhhpvis:.SkyTree123@aws-0-ap-northeast-1.pooler.supabase.com:5432/postgres"

TWSE_TICK_URL = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"
FINMIND_TICK_URL = "https://api.finmindtrade.com/api/v4/data"

TWSE_FAILURE_THRESHOLD = 3
FINMIND_FAILURE_THRESHOLD = 3

# ---- 資料庫 Engine 初始化 ----
sqlite_engine = create_engine(f"sqlite:///{LOCAL_DB_FILE}")
SqliteSession = sessionmaker(bind=sqlite_engine)

supabase_engine = create_engine(
    SUPABASE_CONN_STRING, 
    pool_size=3, 
    max_overflow=0, 
    pool_recycle=300
)
SupabaseSession = sessionmaker(bind=supabase_engine)

Base = declarative_base()

twse_failure_count = 0      
finmind_failure_count = 0   
current_channel = "TWSE"     
excel_buffer = []           

def create_session_with_retry():
    session = requests.Session()
    retry = Retry(total=3, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session

# ====================================================
# ORM 模型定義
# ====================================================
class StockLog(Base):
    __tablename__ = 'stock_logs'
    id = Column(Integer, primary_key=True, autoincrement=True)
    status = Column(String(20), default="success")
    data_source = Column(String(50))
    query_date = Column(String(20))
    query_time = Column(String(20))
    stock_code = Column(String(20), index=True)
    stock_name = Column(String(50))
    price = Column(Float, default=0.0)
    volume = Column(Integer, default=0)
    type = Column(String(20), default="整股")
    created_at = Column(DateTime, default=datetime.now)

print("正在初始化本地與雲端資料庫資料表...")
Base.metadata.create_all(sqlite_engine)
print("💾 本地 SQLite 資料表初始化成功！")
#try:
#    Base.metadata.create_all(supabase_engine)
#    print("☁️ 雲端 Supabase PostgreSQL 資料表同步初始化成功！\n")
#except Exception as e:
#    print(f"⚠️ Supabase 初始化失敗 (請檢查專案狀態或網路): {e}\n")

# ====================================================
# 核心擷取邏輯（獨立通道測試）
# ====================================================
def fetch_by_specific_channel(channel_name, targets) -> list:
    now = datetime.now()
    sys_date = now.strftime("%Y-%m-%d")
    sys_time = now.strftime("%H:%M:%S")
    output_list = []
    session = create_session_with_retry()

    if channel_name == "TWSE":
        try:
            ex_ch_list = [f"tse_{code}.tw" for code in targets]
            params = {"ex_ch": "|".join(ex_ch_list), "_": int(time.time() * 1000)}
            response = session.get(TWSE_TICK_URL, params=params, timeout=8)
            if response.status_code == 200:
                data = response.json()
                if "msgArray" in data and data["msgArray"]:
                    for msg in data["msgArray"]:
                        stock_code = msg.get("c")
                        price_str = msg.get("z")
                        if not price_str or price_str == "-":
                            b_list = msg.get("b", "").split("_")
                            price_str = b_list[0] if b_list and b_list[0] and b_list[0] != "-" else msg.get("y")
                        output_list.append({
                            "status": "success", "data_source": "TWSE_Official", "query_date": sys_date,
                            "query_time": sys_time, "stock_code": stock_code, "stock_name": msg.get("n", "").strip(),
                            "price": float(price_str) if price_str else 0.0, "volume": int(msg.get("v", 0)) if msg.get("v") else 0, "type": "整股(TWSE)"
                        })
        except Exception as e:
            print(f"      ❌ TWSE 測試異常: {e}")

    elif channel_name == "FinMind":
        try:
            headers = {"Authorization": f"Bearer {FINMIND_TOKEN}"} if FINMIND_TOKEN else {}
            for stock_code in targets:
                params = {"dataset": "TaiwanStockPrice", "data_id": stock_code, "start_date": sys_date}
                response = session.get(FINMIND_TICK_URL, headers=headers, params=params, timeout=10)
                if response.status_code == 200:
                    data = response.json()
                    records = data.get("data", [])
                    if not records:
                        params["start_date"] = (pd.Timestamp(sys_date) - pd.Timedelta(days=5)).strftime("%Y-%m-%d")
                        records = session.get(FINMIND_TICK_URL, headers=headers, params=params, timeout=10).json().get("data", [])
                    if records:
                        latest = records[-1]
                        output_list.append({
                            "status": "success", "data_source": "FinMind_API", "query_date": sys_date,
                            "query_time": sys_time, "stock_code": stock_code, "stock_name": f"個股_{stock_code}",
                            "price": float(latest.get("close", 0)), "volume": int(latest.get("volume", 0)), "type": "整股(API)"
                        })
        except Exception as e:
            print(f"      ❌ FinMind 測試異常: {e}")

    elif channel_name == "YFinance":
        try:
            import yfinance as yf
            for stock_code in targets:
                ticker = yf.Ticker(f"{stock_code}.TW")
                hist = ticker.history(period="1d")
                if hist.empty:
                    hist = ticker.history(period="5d")
                if not hist.empty:
                    latest = hist.iloc[-1]
                    output_list.append({
                        "status": "success", "data_source": "YFinance_Fallback", "query_date": sys_date,
                        "query_time": sys_time, "stock_code": stock_code, "stock_name": f"個股_{stock_code}",
                        "price": float(latest['Close']), "volume": int(latest['Volume']), "type": "整股(備用)"
                    })
        except Exception as e:
            print(f"      ❌ YFinance 測試異常: {e}")

    return output_list


def fetch_market_data_batch(targets) -> list:
    global twse_failure_count, finmind_failure_count, current_channel
    output_list = fetch_by_specific_channel(current_channel, targets)
    
    if current_channel == "TWSE":
        if output_list: twse_failure_count = 0
        else:
            twse_failure_count += 1
            if twse_failure_count >= TWSE_FAILURE_THRESHOLD:
                current_channel = "FinMind"
                print(f"   🚨 TWSE 連續失敗，自動切換至 [通道 2: FinMind]")
    elif current_channel == "FinMind":
        if output_list: finmind_failure_count = 0
        else:
            finmind_failure_count += 1
            if finmind_failure_count >= FINMIND_FAILURE_THRESHOLD:
                current_channel = "YFinance"
                print(f"   🚨 FinMind 連續失敗，自動切換至 [通道 3: YFinance]")
                
    return output_list

# ====================================================
# 雙重儲存控制器 (SQLite + Supabase PostgreSQL)
# ====================================================
class DataStorageManager:
    @classmethod
    def save_to_all_db(cls, clean_dict: dict):
        # 1. 寫入本地 SQLite
        with SqliteSession() as db_sql:
            try:
                db_sql.add(StockLog(**clean_dict))
                db_sql.commit()
                print(f"      💾 [SQLite] {clean_dict['stock_code']} 寫入成功")
            except Exception as e:
                db_sql.rollback()
                print(f"      ❌ [SQLite] 寫入失敗: {e}")

        # 2. 寫入雲端 Supabase
        #with SupabaseSession() as db_supa:
        #    try:
        #        db_supa.add(StockLog(**clean_dict))
        #        db_supa.commit()
        #        print(f"      ☁️ [Supabase] {clean_dict['stock_code']} 寫入成功")
        #    except Exception as e:
        #        db_supa.rollback()
        #        print(f"      ❌ [Supabase] 寫入失敗: {e}")
        #
        #global excel_buffer
        #excel_buffer.append(clean_dict)
        #if len(excel_buffer) >= 20:
        #    cls.flush_buffer_to_excel()

    @classmethod
    def flush_buffer_to_excel(cls):
        global excel_buffer
        if not excel_buffer: return
        try:
            df_new = pd.DataFrame(excel_buffer)
            df_combined = pd.concat([pd.read_excel(EXCEL_FILE), df_new], ignore_index=True) if os.path.exists(EXCEL_FILE) else df_new
            df_combined.to_excel(EXCEL_FILE, index=False)
            print(f"      📊 [Excel] 成功同步 {len(excel_buffer)} 筆紀錄至硬碟。")
            excel_buffer.clear()
        except Exception as e:
            print(f"      ❌ [Excel] 寫入失敗: {e}")

# ====================================================
# 主執行流程
# ====================================================
if __name__ == "__main__":
    print("\n" + "="*60)
    print(" 🚀 啟動階段一：強制檢測三種 API 通道")
    print("="*60)
    
    channels_to_test = ["TWSE", "FinMind", "YFinance"]
    for ch in channels_to_test:
        print(f"\n🔍 [測試中] 正在測試通道：{ch} ...")
        res = fetch_by_specific_channel(ch, STOCK_TARGETS)
        if res:
            print(f"   ✅ 通道 {ch} 測試成功！成功獲取資料：")
            for item in res:
                print(f"      - {item['stock_code']} | 價: {item['price']} | 源: {item['data_source']}")
        else:
            print(f"   ❌ 通道 {ch} 本次測試未取得有效資料")
        time.sleep(1)
        
    #print("\n" + "="*60)
    #print(" 🚀 啟動階段二：測試寫入一筆資料到 Supabase DB")
    #print("="*60)
    #test_data = {
    #    "status": "success", "data_source": "Supabase_Test_Function", 
    #    "query_date": datetime.now().strftime("%Y-%m-%d"), "query_time": datetime.now().strftime("%H:%M:%S"), 
    #    "stock_code": "0000", "stock_name": "連線測試股", "price": 888.8, "volume": 168, "type": "測試"
    #}
    #with SupabaseSession() as db_supa:
    #    try:
    #        db_supa.add(StockLog(**test_data))
    #        db_supa.commit()
    #        print("   ✅ [Supabase] 獨立寫入測試成功！請至 Supabase 後台查看 stock_logs 資料表。")
    #    except Exception as e:
    #        db_supa.rollback()
    #        print(f"   ❌ [Supabase] 獨立寫入測試失敗，原因: {e}")

    print("\n" + "="*60)
    print(" 🎯 測試完畢！現在切回「原有自動化監控與雙重儲存模式」...")
    print("="*60 + "\n")
    
    try:
        iteration = 0
        while True:
            iteration += 1
            print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            print(f"📍 監控模式 - 第 {iteration} 次循環 (當前通道: {current_channel})")
            
            batch_results = fetch_market_data_batch(STOCK_TARGETS)
            if batch_results:
                for stock_record_dict in batch_results:
                    print(f"   [{stock_record_dict['query_time']}] {stock_record_dict['stock_name']}({stock_record_dict['stock_code']}) | 價: {stock_record_dict['price']}")
                    DataStorageManager.save_to_all_db(stock_record_dict)
            else:
                print("   ⚠️ 本次無任何通道回傳資料")
                
            time.sleep(FETCH_INTERVAL)
            
    except KeyboardInterrupt:
        print("\n👋 收到終止訊號，正在安全導出剩餘資料...")
        DataStorageManager.flush_buffer_to_excel()
        print("系統安全關閉。")