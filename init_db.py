import sqlite3

def init_global_intraday_table():
    conn = sqlite3.connect("db/ohlcv_cache.db")
    cursor = conn.cursor()
    
    # 建立即時行情表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS intraday_ticks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,      -- 格式: 2026-07-02 09:05:00
            ticker TEXT NOT NULL,         -- 股票代號
            data_source TEXT NOT NULL,    -- 來源標記 (TWSE_Official / FinMind_API / YFinance_Fallback)
            price REAL DEFAULT 0.0,       -- 最新成交價
            volume INTEGER DEFAULT 0,     -- 當前累積成交量
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    
    # 建立複合索引加速盤中滾動式策略計算
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ticker_timestamp ON intraday_ticks (ticker, timestamp);")
    conn.commit()
    conn.close()

if __name__ == "__main__":
    init_global_intraday_table()
    print("✅ 全域即時行情表已建立成功！")
