import sqlite3

class GlobalStorageManager:
    @classmethod
    def save_ticks_to_cache(cls, batch_results: list):
        if not batch_results:
            return
        conn = sqlite3.connect("db/ohlcv_cache.db", timeout=30.0)
        conn.execute("PRAGMA journal_mode=WAL;")
        cursor = conn.cursor()
        try:
            for item in batch_results:
                cursor.execute("""
                    INSERT INTO intraday_ticks (timestamp, ticker, data_source, price, volume)
                    VALUES (?, ?, ?, ?, ?)
                """, (
                    f"{item['query_date']} {item['query_time']}",
                    item['stock_code'],
                    item['data_source'],
                    item['price'],
                    item['volume']
                ))
            conn.commit()
            print(f"   🤖 [Worker] 成功同步 {len(batch_results)} 筆 Tick 至快取庫。")
        except Exception as e:
            conn.rollback()
            print(f"   ❌ [Worker] 寫入失敗: {e}")
        finally:
            conn.close()
