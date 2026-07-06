# -*- coding: utf-8 -*-
r"""
台股多因子加權預測核心服務引擎
專案路徑: D:\SourceCode\TypeScript\trading-system-main\trading\services\predict_service.py
"""

import numpy as np
import pandas as pd
from datetime import datetime, timedelta

# 🟢 修正引用路徑：精確對應您 trading/strategies/predict_config.py 的路徑
from trading.strategies.predict_config import SIGNAL_CONFIG, PREDICT_SETTINGS

class TaiwanStockPredictService:
    def __init__(self):
        self.config = SIGNAL_CONFIG
        self.settings = PREDICT_SETTINGS

    def _evaluate_signals(self, df_kline: pd.DataFrame, df_chip: pd.DataFrame) -> dict:
        """
        核心訊號判定邏輯：將 K 線與籌碼面的最新數據，轉化為 1 (看漲) 或 -1 (看跌)
        """
        activated_signals = {}
        
        # 基礎數據安全檢查
        if df_kline.empty or len(df_kline) < 20:
            return activated_signals

        # ==========================================
        # 1. 技術面因子判定 (從交易系統既有的 K 線數據提取)
        # ==========================================
        try:
            # 5MA 與 20MA 交叉判定
            activated_signals['ma_golden_cross'] = 1 if df_kline['MA5'].iloc[-1] > df_kline['MA20'].iloc[-1] else -1
            
            # KD 交叉
            if 'K' in df_kline.columns and 'D' in df_kline.columns:
                activated_signals['kd_golden_cross'] = 1 if (df_kline['K'].iloc[-1] > df_kline['D'].iloc[-1]) and (df_kline['K'].iloc[-2] <= df_kline['D'].iloc[-2]) else -1
            else:
                activated_signals['kd_golden_cross'] = 0

            # RSI 區間
            if 'RSI' in df_kline.columns:
                activated_signals['rsi_oversold'] = 1 if df_kline['RSI'].iloc[-1] < 35 else (-1 if df_kline['RSI'].iloc[-1] > 75 else 0)
            else:
                activated_signals['rsi_oversold'] = 0

            # MACD 判定
            if 'MACD_Hist' in df_kline.columns:
                activated_signals['macd_bullish'] = 1 if df_kline['MACD_Hist'].iloc[-1] > df_kline['MACD_Hist'].iloc[-2] else -1
            else:
                activated_signals['macd_bullish'] = 0

            # 布林通道下軌觸及
            if 'BB_Low' in df_kline.columns:
                activated_signals['bollinger_support'] = 1 if df_kline['Close'].iloc[-1] <= df_kline['BB_Low'].iloc[-1] else 0
            else:
                activated_signals['bollinger_support'] = 0

            # 帶量攻擊
            if 'Volume' in df_kline.columns:
                ma5_vol = df_kline['Volume'].rolling(5).mean().iloc[-1]
                activated_signals['volume_expansion'] = 1 if df_kline['Volume'].iloc[-1] > (ma5_vol * 1.5) else 0
            else:
                activated_signals['volume_expansion'] = 0

            # 突破週高點
            weekly_max = df_kline['High'].shift(1).tail(5).max()
            activated_signals['weekly_breakout'] = 1 if df_kline['Close'].iloc[-1] > weekly_max else -1

        except Exception as e:
            print(f"⚠️ 技術指標訊號計算異常: {e}")

        # ==========================================
        # 2. 籌碼與法人因子判定
        # ==========================================
        try:
            if not df_chip.empty and len(df_chip) >= 3:
                # 外資連 3 買 / 投信連 2 買 / 自營商今日買
                activated_signals['foreign_buy_streak'] = 1 if (df_chip['Foreign_Net'].tail(3) > 0).all() else -1
                activated_signals['trust_buy_streak'] = 1 if (df_chip['Trust_Net'].tail(2) > 0).all() else 0
                activated_signals['dealer_turn_buy'] = 1 if df_chip['Dealer_Net'].iloc[-1] > 0 else -1
                
                # 三大法人同步全買
                if df_chip['Foreign_Net'].iloc[-1] > 0 and df_chip['Trust_Net'].iloc[-1] > 0 and df_chip['Dealer_Net'].iloc[-1] > 0:
                    activated_signals['all_institutional_buy'] = 1
                else:
                    activated_signals['all_institutional_buy'] = 0
                
                # 主力籌碼集中度
                if 'Concentration' in df_chip.columns:
                    activated_signals['chip_concentration'] = 1 if df_chip['Concentration'].iloc[-1] > 10 else 0
                else:
                    activated_signals['chip_concentration'] = 0
                    
                # 融資減肥
                if 'Margin_Balance' in df_chip.columns:
                    activated_signals['margin_decrease'] = 1 if df_chip['Margin_Balance'].iloc[-1] < df_chip['Margin_Balance'].iloc[-2] else -1
                else:
                    activated_signals['margin_decrease'] = 0
            else:
                # 無籌碼資料時，預設填入 0 (不計分) 防錯
                chip_keys = ['foreign_buy_streak', 'trust_buy_streak', 'dealer_turn_buy', 'all_institutional_buy', 'chip_concentration', 'margin_decrease']
                for k in chip_keys:
                    activated_signals[k] = 0

            # 預留無特定資料流之欄位
            activated_signals['short_covering'] = 0
            activated_signals['insider_holding_up'] = 0

        except Exception as e:
            print(f"⚠️ 籌碼面訊號計算異常: {e}")

        # 防呆確保 15 個指標在回傳字典中都存在
        for key in self.config.keys():
            if key not in activated_signals:
                activated_signals[key] = 0

        return activated_signals

    def calculate_prediction(self, df_kline: pd.DataFrame, df_chip: pd.DataFrame) -> dict:
        """
        對外主要調用接口：輸入 K 線與籌碼 DataFrame，輸出加權預測結果與隔日開盤價
        """
        signals = self._evaluate_signals(df_kline, df_chip)
        
        bullish_score = 0
        bearish_score = 0
        max_possible_weight = sum(self.config[k]['weight'] for k in self.config)

        # 逐一加權計分
        for signal_name, direction in signals.items():
            weight = self.config[signal_name]['weight']
            if direction == 1:
                bullish_score += weight
            elif direction == -1:
                bearish_score += weight

        total_active_score = bullish_score + bearish_score
        
        if total_active_score == 0:
            bull_pct, bear_pct, confidence = 50, 50, 0.0
        else:
            bull_pct = int(round((bullish_score / total_active_score) * 100))
            bear_pct = 100 - bull_pct
            # 信心值計算公式：(多空淨力差 / 總可能權重) * 100
            confidence = round((abs(bullish_score - bearish_score) / max_possible_weight) * 100, 1)

        # 隔日開盤價預測演算法
        last_close = float(df_kline['Close'].iloc[-1]) if 'Close' in df_kline.columns else 0.0
        
        # 依據得分力道，精算跳空幅度
        score_delta = (bull_pct - 50) / 50  # 範圍：-1 到 +1
        expected_variance = score_delta * self.settings['base_multiplier'] * (1 + confidence / 100)
        predicted_open = round(last_close * (1 + expected_variance), 2)

        return {
            "last_close": last_close,
            "predicted_open": predicted_open,
            "bull_percentage": bull_pct,
            "bear_percentage": bear_pct,
            "confidence": confidence,
            "signal_results": signals
        }
