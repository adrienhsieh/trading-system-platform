# -*- coding: utf-8 -*-
r"""
台股多因子加權預測 API 路由中樞 (終極資料庫對齊版本)
專案路徑: D:\SourceCode\TypeScript\trading-system-main\trading\api\predict.py
"""

import os
import sqlite3
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify

# 引入原系統的驗證機制與容器服務
from trading.api.auth import require_auth
from trading.services.container import container
from trading.services.predict_service import TaiwanStockPredictService

predict_bp = Blueprint("predict", __name__)
predict_service = TaiwanStockPredictService()

# ── 🟢 絕對路徑死死鎖定中心 ──────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB_PATH = os.path.join(BASE_DIR, "trading_system.db")

def init_db_structure():
    """
    強效防禦機制：確保 SQLite 資料表 100% 存在
    並且強行校正舊資料表，防範 `no such column: is_correct` 死鎖錯誤
    """
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            
            # 1. 先確保基礎資料表結構存在
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS tw_stock_predictions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    stock_id TEXT NOT NULL,
                    predict_date TEXT NOT NULL,
                    last_close REAL NOT NULL,
                    predicted_open REAL NOT NULL,
                    bull_pct INTEGER NOT NULL,
                    bear_pct INTEGER NOT NULL,
                    confidence REAL NOT NULL,
                    target_date TEXT NOT NULL,
                    status TEXT DEFAULT 'PENDING'
                )
            """)
            conn.commit()
            
            # 2. 🟢 關鍵克星修復：強行檢查並為舊有的資料表追加缺失的 is_correct 欄位！
            try:
                cursor.execute("ALTER TABLE tw_stock_predictions ADD COLUMN is_correct INTEGER DEFAULT NULL")
                conn.commit()
                print("🎉 [資料庫中樞] 偵測到舊結構，已成功為 SQLite 動態升級補上 `is_correct` 欄位！")
            except sqlite3.OperationalError:
                # 如果欄位本來就存在，ALTER TABLE 會拋出此錯誤，我們直接 pass 忽略即可
                pass
                
    except Exception as e:
        print(f"⚠️ 初始化預測資料表或動態追加欄位失敗: {e}")

# 立即激活初始化
init_db_structure()


# ── 1. 預測計算接口 ───────────────────────────────────────────────────

@predict_bp.route("/api/predict/calculate", methods=["POST"])
def calculate_prediction():
    try:
        req_data = request.get_json() or {}
        stock_id = req_data.get('stock_id', '').strip()
        
        if not stock_id:
            return jsonify({"ok": False, "error": "請提供有效的台股股票代號。"}), 400
        
        df_kline = pd.DataFrame()
        df_chip = pd.DataFrame()

        try:
            if hasattr(container, 'market_svc'):
                df_kline = container.market_svc.get_history(stock_id, days=60)
        except Exception:
            pass

        if df_kline.empty:
            try:
                import yfinance as yf
                raw_df = yf.download(f"{stock_id}.TW", period="60d", progress=False)
                if not raw_df.empty:
                    df_kline = raw_df.copy()
                    if isinstance(df_kline.columns, pd.MultiIndex):
                        df_kline.columns = df_kline.columns.get_level_values(0)
                    df_kline.columns = [str(col).capitalize() for col in df_kline.columns]
                    df_kline = df_kline.dropna(subset=['Close', 'High', 'Low', 'Volume'])
                    
                    df_kline['Close'] = df_kline['Close'].astype(float)
                    df_kline['High'] = df_kline['High'].astype(float)
                    df_kline['Low'] = df_kline['Low'].astype(float)
                    df_kline['Volume'] = df_kline['Volume'].astype(float)
                    df_kline['MA5'] = df_kline['Close'].rolling(window=5).mean()
                    df_kline['MA20'] = df_kline['Close'].rolling(window=20).mean()
                    
                    low_9 = df_kline['Low'].rolling(window=9).min()
                    high_9 = df_kline['High'].rolling(window=9).max()
                    denom = (high_9 - low_9).clip(lower=0.01)
                    
                    rsv = ((df_kline['Close'] - low_9) / denom) * 100
                    df_kline['K'] = rsv.ewm(com=2).mean().fillna(50.0)
                    df_kline['D'] = df_kline['K'].ewm(com=2).mean().fillna(50.0)
                    
                    delta = df_kline['Close'].diff()
                    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
                    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean().clip(lower=0.01)
                    df_kline['RSI'] = (100 - (100 / (1 + (gain / loss)))).fillna(50.0)
                    df_kline['MACD_Hist'] = (df_kline['Close'].ewm(span=12).mean() - df_kline['Close'].ewm(span=26).mean()).fillna(0.0)
                    df_kline = df_kline.fillna(0.0)
            except Exception:
                pass

        if df_kline.empty or len(df_kline) < 5:
            return jsonify({"ok": False, "error": f"無法取得股票代號 {stock_id} 的完整交易 K 線。"}), 400

        result = predict_service.calculate_prediction(df_kline, df_chip)
        
        def sanitize_dict(d):
            clean = {}
            for k, v in d.items():
                if isinstance(v, dict): clean[k] = sanitize_dict(v)
                elif isinstance(v, (np.floating, float)): clean[k] = 0.0 if np.isnan(v) or np.isinf(v) else float(v)
                elif isinstance(v, (np.integer, int)): clean[k] = int(v)
                elif isinstance(v, np.ndarray): clean[k] = v.tolist()
                else: clean[k] = v
            return clean

        return jsonify({"ok": True, "stock_id": stock_id, "results": sanitize_dict(result)})
    except Exception as global_err:
        return jsonify({"ok": False, "error": str(global_err)}), 200


# ── 2. 建立預測紀錄接口 ─────────────────────────────────────────────────

@predict_bp.route("/api/predict/save", methods=["POST"])
def save_prediction_record():
    try:
        data = request.get_json() or {}
        stock_id = data.get('stock_id', '').strip()
        
        if not stock_id:
            return jsonify({"ok": False, "error": "Missing stock_id"}), 400

        today_str = datetime.now().strftime("%Y-%m-%d")
        target_str = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d") # 結算目標設為隔日

        # 強力寫入 SQLite 絕對路徑
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO tw_stock_predictions 
                (stock_id, predict_date, last_close, predicted_open, bull_pct, bear_pct, confidence, target_date, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'PENDING')
            """, (
                stock_id, today_str, 
                float(data.get('last_close', 269.0)), 
                float(data.get('predicted_open', 272.0)),
                int(data.get('bull_percentage', 56)), 
                int(data.get('bear_percentage', 44)),
                float(data.get('confidence', 34.9)), 
                target_str
            ))
            conn.commit()

        return jsonify({"ok": True, "message": "Prediction log recorded successfully"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 200


# ── 3. 歷史預測紀錄與自動結算接口 ──────────────────────────────────────────

@predict_bp.route("/api/predict/history", methods=["GET"])
def get_prediction_history():
    try:
        today_str = datetime.now().strftime("%Y-%m-%d")
        init_db_structure() # 安全防禦加載
        
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # 自動開盤價回測結算
            cursor.execute("SELECT id, stock_id, target_date, predicted_open, last_close FROM tw_stock_predictions WHERE status = 'PENDING' AND target_date <= ?", (today_str,))
            pending_records = cursor.fetchall()
            
            if pending_records:
                try:
                    import yfinance as yf
                    for row in pending_records:
                        r_id, s_id, t_date = row['id'], row['stock_id'], row['target_date']
                        df = yf.download(f"{s_id}.TW", start=t_date, end=(datetime.strptime(t_date, "%Y-%m-%d") + timedelta(days=3)).strftime("%Y-%m-%d"), progress=False)
                        if not df.empty:
                            if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
                            df.columns = [str(c).capitalize() for c in df.columns]
                            actual_open = float(df['Open'].iloc[0])
                            is_correct = 1 if ((row['predicted_open'] > row['last_close']) == (actual_open > row['last_close'])) else 0
                            cursor.execute("UPDATE tw_stock_predictions SET status = 'SETTLED', is_correct = ? WHERE id = ?", (is_correct, r_id))
                    conn.commit()
                except Exception:
                    pass

            # 計算總體歷史勝率
            cursor.execute("SELECT COUNT(*) as tot FROM tw_stock_predictions WHERE status = 'SETTLED'")
            total_settled = cursor.fetchone()['tot']
            cursor.execute("SELECT COUNT(*) as corr FROM tw_stock_predictions WHERE status = 'SETTLED' AND is_correct = 1")
            total_correct = cursor.fetchone()['corr']
            win_rate = round((total_correct / total_settled) * 100, 1) if total_settled > 0 else 0.0

            # 🟢 欄位完全對齊：精確讀取 8 大基礎欄位
            cursor.execute("SELECT stock_id, predict_date, last_close, predicted_open, bull_pct, confidence, status, is_correct FROM tw_stock_predictions ORDER BY id DESC LIMIT 15")
            history_rows = cursor.fetchall()
            
            list_data = []
            for r in history_rows:
                list_data.append({
                    "stock_id": str(r["stock_id"]),
                    "predict_date": str(r["predict_date"]),
                    "last_close": float(r["last_close"]),
                    "predicted_open": float(r["predicted_open"]),
                    "bull_pct": int(r["bull_pct"]),
                    "confidence": float(r["confidence"]),
                    "status": str(r["status"]),
                    "is_correct": int(r["is_correct"]) if r["is_correct"] is not None else None
                })

        return jsonify({
            "ok": True,
            "win_rate": win_rate,
            "total_count": total_settled,
            "history": list_data
        })
    except Exception as e:
        print(f"❌ 後端撈取歷史紀錄發生例外錯誤: {str(e)}")
        return jsonify({
            "ok": False, 
            "error": f"資料庫讀取失敗: {str(e)}",
            "win_rate": 0.0,
            "total_count": 0,
            "history": []
        }), 200