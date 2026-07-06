# -*- coding: utf-8 -*-
r"""
15大台股核心訊號加權配置表 (可自行在此增減指標或調整權重分數)
專案路徑: D:\SourceCode\TypeScript\trading-system-main\trading\strategies\predict_config.py
"""

SIGNAL_CONFIG = {
    # ==========================================
    # 1. 技術面因子 (Technical Indicators)
    # ==========================================
    "ma_golden_cross": {
        "weight": 15, 
        "desc": "5MA 突破 20MA 黃金交叉",
        "category": "technical"
    },
    "kd_golden_cross": {
        "weight": 10, 
        "desc": "K值 突破 D值 黃金交叉",
        "category": "technical"
    },
    "rsi_oversold": {
        "weight": 10, 
        "desc": "RSI < 35 低檔超賣區反彈",
        "category": "technical"
    },
    "macd_bullish": {
        "weight": 15, 
        "desc": "MACD OSC柱狀體由綠翻紅或紅軸持續增長",
        "category": "technical"
    },
    "bollinger_support": {
        "weight": 10, 
        "desc": "股價觸及布林通道下軌且帶下影線",
        "category": "technical"
    },
    "volume_expansion": {
        "weight": 10, 
        "desc": "今日成交量大於 5日均量 1.5 倍 (帶量攻擊)",
        "category": "technical"
    },
    "weekly_breakout": {
        "weight": 15, 
        "desc": "收盤價突破過去 5 個交易日的最高價",
        "category": "technical"
    },

    # ==========================================
    # 2. 籌碼面與三大法人因子 (Institutional Chips)
    # ==========================================
    "foreign_buy_streak": {
        "weight": 25, 
        "desc": "外資連續 3 個交易日買超",
        "category": "chip"
    },
    "trust_buy_streak": {
        "weight": 20, 
        "desc": "投信連續 2 個交易日買超 (內資作帳行情)",
        "category": "chip"
    },
    "dealer_turn_buy": {
        "weight": 10, 
        "desc": "自營商今日由賣轉買超",
        "category": "chip"
    },
    "all_institutional_buy": {
        "weight": 30, 
        "desc": "三大法人同日全面合買 (多頭強烈訊號)",
        "category": "chip"
    },
    "chip_concentration": {
        "weight": 20, 
        "desc": "主力分點買超前15大券商，籌碼集中度 > 10%",
        "category": "chip"
    },

    # ==========================================
    # 3. 資券與大戶面因子 (Margin & Big Players)
    # ==========================================
    "margin_decrease": {
        "weight": 15, 
        "desc": "融資餘額減少且股價持穩 (散戶退場、籌碼歸向法人)",
        "category": "chip"
    },
    "short_covering": {
        "weight": 10, 
        "desc": "融券餘額在股價上漲時大增 (具備軋空潛力)",
        "category": "chip"
    },
    "insider_holding_up": {
        "weight": 15, 
        "desc": "千張大戶持股比例或董監持股本週上升",
        "category": "chip"
    }
}

# ==========================================
# 預測核心微調參數設定 (Prediction Settings)
# ==========================================
PREDICT_SETTINGS = {
    # 基礎開盤價波動係數。數值越大，代表預測模型算出來的「隔日開盤跳空漲跌幅」震盪會越激烈。
    "base_multiplier": 0.006,  # 預設 0.006 代表基礎波動 0.6%
    
    # 信心值多空判定門檻百分比 (%)
    "bull_threshold": 55,       # 看漲多空判斷基礎門檻
}
