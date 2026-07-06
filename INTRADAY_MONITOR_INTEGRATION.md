# trading-system 新功能整合方案
## 盤中監控台股頁簽 + invest-system 功能移植

---

## 📋 需求分析

### 從 invest-system 參考的功能
1. ✅ **即時行情監控**（6頁儀表板中的「策略監控」頁）
2. ✅ **法人籌碼分析**（TWSE/FinMind 資料）
3. ✅ **AI 市場情緒分析**（Groq/Gemini）
4. ✅ **每日市場報告**（daily_report.py）
5. ✅ **技術指標快照**（RSI/MA5/MA20/MA60）
6. ✅ **新聞情緒評分**（看多/看空/中性）

### 整合到 trading-system 的方式
- 利用現有的 `trading/market.py` + `monitor_tw_stock_save_data_OK_0622.py`
- 新增盤中監控頁簽 (intraday-monitor.html)
- 多用戶個性化設定
- 實時 WebSocket 推送

---

## 🗂️ 新增檔案結構

```
trading/
├── services/
│   ├── intraday_monitor.py          # ✨ 新建：盤中監控核心引擎
│   ├── market_mood_analyzer.py      # ✨ 新建：AI 情緒分析 (Groq/Gemini)
│   ├── technical_snapshot.py        # ✨ 新建：技術指標快照
│   ├── institutional_flow.py        # ✨ 新建：法人籌碼追蹤
│   └── container.py                 # 🔄 修改：注入新服務
│
├── api/
│   ├── intraday.py                  # ✨ 新建：盤中監控 API 路由
│   └── market.py                    # 🔄 修改：擴展行情 API
│
├── templates/
│   └── intraday-monitor.html       # ✨ 新建：盤中監控頁簽
│
└── static/
    └── intraday-monitor.js         # ✨ 新建：即時更新邏輯

db/
├── intraday_cache.db               # ✨ 新建：盤中快取資料庫
└── market_mood.db                  # ✨ 新建：情緒分析結果

```

---

## 🎯 核心模組設計

### 1️⃣ **盤中監控引擎** (`intraday_monitor.py`)

```python
class IntradayMonitor:
    """
    盤中實時監控引擎
    - 持續監控選定股票（用戶個性化清單）
    - 技術指標計算（RSI/MACD/布林帶）
    - 交易信號生成
    - WebSocket 即時推送
    """
    
    def __init__(self, container):
        self.stock_data_service = container.stock_data_service
        self.user_config_db = container.user_config_db
        self.cache = {}  # 每用戶 + 股票代碼的快取
        self.ws_clients = set()  # WebSocket 連線集合
    
    def subscribe_user(self, user_id, stock_codes: list):
        """用戶訂閱監控列表"""
        
    def calculate_technicals(self, ohlcv_data) -> dict:
        """計算 RSI / MACD / 布林帶 / MA5/20/60"""
        
    def generate_signals(self, technicals) -> dict:
        """
        交易信號生成
        - 超買超賣 (RSI > 70 / < 30)
        - 均線交叉 (MA5 > MA20)
        - 布林帶突破
        """
        
    def broadcast_to_user(self, user_id, data):
        """WebSocket 推送給該用戶"""
```

### 2️⃣ **AI 情緒分析** (`market_mood_analyzer.py`)

```python
class MarketMoodAnalyzer:
    """
    市場情緒分析器（整合 invest-system 邏輯）
    - 新聞爬蟲（Google News RSS）
    - AI 情緒分類 (Groq/Gemini)
    - 情緒評分聚合
    """
    
    def fetch_news(self, query: str) -> list:
        """從 Google News RSS 爬蟲新聞"""
        
    def analyze_sentiment(self, news_list) -> dict:
        """
        調用 Groq → Gemini (備援) 分析情緒
        回傳: {
            'bullish': count,
            'bearish': count,
            'neutral': count,
            'avg_score': float,
            'top_news': [{title, sentiment, score}]
        }
        """
        
    def get_mood_summary(self) -> dict:
        """取得最新情緒匯總"""
```

### 3️⃣ **技術指標快照** (`technical_snapshot.py`)

```python
class TechnicalSnapshot:
    """
    技術面情景描述（參考 daily_report.py 邏輯）
    """
    
    def calculate_rsi(self, closes: list, period=14) -> float:
        
    def calculate_ma(self, closes: list, period: int) -> float:
        
    def describe_technicals(self, symbol: str) -> dict:
        """
        回傳技術面文字描述
        - RSI 超買超賣判斷
        - MA 趨勢判斷
        - 季線支撐/壓力
        """
        
    def get_snapshot(self, symbol: str) -> dict:
        """一次性取得技術面快照"""
```

### 4️⃣ **法人籌碼追蹤** (`institutional_flow.py`)

```python
class InstitutionalFlow:
    """
    法人買賣超追蹤（參考 invest-system 籌碼模組）
    - FinMind API：法人/投信/自營買賣超
    - TWSE OpenAPI：融資融券
    - 連買天數統計
    """
    
    def fetch_foreign_flow(self, symbol: str) -> dict:
        """外資買賣超"""
        
    def fetch_trust_flow(self, symbol: str) -> dict:
        """投信買賣超"""
        
    def fetch_margin_debt(self, symbol: str) -> dict:
        """融資融券"""
        
    def analyze_flow(self, symbol: str) -> dict:
        """
        綜合分析籌碼面
        - 連買天數
        - 融資遞減信號
        - 籌碼洗淨度
        """
```

---

## 🌐 API 路由 (`api/intraday.py`)

```python
# WebSocket 即時推送
@app.route('/api/intraday/ws')
def intraday_websocket():
    """WebSocket 即時行情推送"""
    # ws://localhost:8080/api/intraday/ws?user_id=xxx&codes=2330,2317

# 用戶訂閱
@app.route('/api/intraday/subscribe', methods=['POST'])
@require_auth
def subscribe_stocks(user_id):
    """
    POST {
        "stock_codes": ["2330", "2317"],
        "interval": 5  # 秒數
    }
    """

# 盤中快照
@app.route('/api/intraday/snapshot/<symbol>')
@require_auth
def get_snapshot(user_id, symbol):
    """取得指定股票的盤中快照"""
    return {
        "stock_code": "2330",
        "price": 890.0,
        "change": +5.0,
        "change_pct": +0.57,
        "technicals": {
            "rsi": 65.5,
            "ma5": 885,
            "ma20": 875,
            "ma60": 870,
            "trend": "多頭排列"
        },
        "signals": {
            "rsi_signal": "接近超買",
            "ma_signal": "短期強勢",
            "volume_signal": "成交量放大"
        },
        "mood": {
            "bullish_pct": 68,
            "avg_score": 7.2,
            "sentiment": "看多"
        },
        "institutional": {
            "foreign_net": "+50000",
            "trust_net": "-5000",
            "dealer_net": "+2000",
            "consecutive_days": 5  # 連買天數
        }
    }

# 市場情緒
@app.route('/api/intraday/mood')
def get_market_mood():
    """取得全市場情緒"""
    return {
        "bullish": 120,
        "bearish": 85,
        "neutral": 45,
        "total": 250,
        "avg_score": 6.5,
        "top_news": [
            {
                "title": "台積電新廠投資",
                "sentiment": "bullish",
                "score": 8.5,
                "category": "利多"
            }
        ]
    }

# 技術面情景
@app.route('/api/intraday/technical/<symbol>')
def get_technical_description(symbol):
    """技術面文字描述"""
    return {
        "symbol": "2330",
        "description": "短中期均線多頭排列，RSI 接近超買區...",
        "trend": "上升趨勢",
        "support": 880.0,
        "resistance": 900.0
    }
```

---

## 🖥️ 前端頁簽 (`intraday-monitor.html`)

### 頁面佈局
```
┌─────────────────────────────────────────────────┐
│ 🔴 盤中監控                  [刷新] [設定]      │
├─────────────────────────────────────────────────┤
│  
│ 📊 實時行情面板
│ ┌──────────┬────┬────┬────┬───────┐
│ │ 代碼 | 股名 | 價 | 漲跌 | RSI | 趨勢
│ ├──────────┼────┼────┼────┼───────┤
│ │ 2330  │台積│890│+5  │ 65 │多頭 │
│ │ 2317  │鴻海│185│-2  │ 45 │中立 │
│ └──────────┴────┴────┴────┴───────┘
│
│ 🎯 技術指標
│ ┌─────────────────────────────────┐
│ │ RSI(14): 65.5 [接近超買]        │
│ │ MA(5): 885, MA(20): 875, MA(60) │
│ │ 描述：短中期均線多頭排列...      │
│ └─────────────────────────────────┘
│
│ 💡 市場情緒
│ ┌─────────────────────────────────┐
│ │ 看多: 68% | 看空: 20% | 中性: 12% │
│ │ 情緒分數: 7.2/10               │
│ │ 重要新聞: [台積電新廠投資]      │
│ └─────────────────────────────────┘
│
│ 🏦 法人籌碼
│ ┌─────────────────────────────────┐
│ │ 外資淨買超: +50,000              │
│ │ 投信淨買超: -5,000               │
│ │ 連買天數: 5 天                  │
│ │ 融資遞減信號: ✅ 洗淨中           │
│ └─────────────────────────────────┘
│
└─────────────────────────────────────────────────┘
```

### 關鍵特性
- ✅ **自動刷新**：5/15/60 秒可選
- ✅ **WebSocket 推送**：延遲 < 100ms
- ✅ **響應式設計**：深色主題 (CSS 同步 invest-system)
- ✅ **多股對比**：最多 10 支
- ✅ **告警機制**：超買/超賣/均線交叉推送

---

## 📊 資料庫擴展 (`intraday_cache.db`)

### 表結構

#### `intraday_snapshot` (盤中快照)
```sql
CREATE TABLE intraday_snapshot (
    id INTEGER PRIMARY KEY,
    user_id TEXT,
    symbol TEXT,
    timestamp TIMESTAMP,
    price FLOAT,
    change FLOAT,
    change_pct FLOAT,
    rsi FLOAT,
    ma5 FLOAT,
    ma20 FLOAT,
    ma60 FLOAT,
    volume INTEGER,
    signal_code TEXT,  -- "oversold"/"overbought"/"ma_cross"/etc
    UNIQUE(user_id, symbol, timestamp)
);
```

#### `market_mood_cache` (情緒快取)
```sql
CREATE TABLE market_mood_cache (
    id INTEGER PRIMARY KEY,
    timestamp TIMESTAMP,
    bullish_count INTEGER,
    bearish_count INTEGER,
    neutral_count INTEGER,
    avg_score FLOAT,
    last_updated TIMESTAMP
);
```

#### `news_sentiment` (新聞情緒)
```sql
CREATE TABLE news_sentiment (
    id INTEGER PRIMARY KEY,
    title TEXT,
    url TEXT,
    sentiment TEXT,  -- "bullish"/"bearish"/"neutral"
    score FLOAT,
    category TEXT,
    reason TEXT,
    analyzed_at TIMESTAMP
);
```

---

## 🔄 整合流程

### Phase 1: 核心引擎 (2天)
1. ✅ 實作 `stock_data_service.py`（三層備援）
2. ✅ 實作 `intraday_monitor.py`（即時計算）
3. ✅ 實作 `market_mood_analyzer.py`（AI 分析）
4. ✅ 實作 `technical_snapshot.py`（技術指標）

### Phase 2: API 端點 (1天)
1. ✅ 建立 `/api/intraday/*` 路由
2. ✅ WebSocket 連線管理
3. ✅ 用戶級別資料隔離

### Phase 3: 前端 UI (2天)
1. ✅ 建立 `intraday-monitor.html`
2. ✅ 實時行情更新邏輯
3. ✅ 技術指標視覺化
4. ✅ 告警推送

### Phase 4: 自動化 (1天)
1. ✅ 背景監控守護程序
2. ✅ 每日報告生成 (daily_report.py)
3. ✅ Telegram 推播

### Phase 5: 測試 (1天)
1. ✅ 單元測試
2. ✅ 整合測試
3. ✅ UI 測試

---

## 💾 搬遷 invest-system 代碼

### 要複製的核心邏輯

| 來源 | 功能 | 目的地 |
|------|------|--------|
| `daily_report.py:_get_technical_snapshot()` | 技術指標計算 | `technical_snapshot.py` |
| `daily_report.py:_generate_ai_market_summary()` | AI 情緒總結 | `market_mood_analyzer.py` |
| `daily_report.py:_call_groq()` | Groq API | `market_mood_analyzer.py` |
| `daily_report.py:get_institutional_summary()` | 法人籌碼 | `institutional_flow.py` |
| `intelligence.py` 新聞爬蟲邏輯 | Google News 抓取 | `market_mood_analyzer.py` |

---

## 🚀 預期效果

✅ **盤中實時監控**  
✅ **個性化股票清單**（用戶級）  
✅ **AI 情緒分析** (Groq/Gemini)  
✅ **技術指標快照**  
✅ **法人籌碼追蹤**  
✅ **自動告警推播** (Telegram)  
✅ **多用戶隔離**  
✅ **WebSocket 低延遲** (< 100ms)  

---

## 📦 依賴新增

```
# 新增到 requirements.txt
python-socketio>=5.9.0          # WebSocket
python-engineio>=4.7.0
groq>=0.4.0                     # Groq API
google-generativeai>=0.3.0      # Gemini API
feedparser>=6.0                 # RSS 新聞爬蟲
```

---

## 🔐 安全考量

- ✅ WebSocket 連線認證 (JWT token)
- ✅ 用戶資料隔離 (WHERE user_id = ?)
- ✅ API Key 加密存儲
- ✅ 速率限制 (Limiter)

---

## 預計工期

**總計**: 7-10 天

- Phase 1-2: 3 天
- Phase 3: 2 天
- Phase 4-5: 2 天
- 緩衝: 2 天

---

## 完成清單

- [ ] 實作 `stock_data_service.py`
- [ ] 實作 `intraday_monitor.py`
- [ ] 實作 `market_mood_analyzer.py`
- [ ] 實作 `technical_snapshot.py`
- [ ] 實作 `institutional_flow.py`
- [ ] 建立 `/api/intraday` 路由
- [ ] 建立 `intraday-monitor.html`
- [ ] 建立 WebSocket 推送邏輯
- [ ] 建立背景監控守護程序
- [ ] 整合 daily_report.py 邏輯
- [ ] 撰寫單元測試
- [ ] 部署驗證

