# 策略說明

## 目錄

- [策略框架（BaseStrategy）](#策略框架basestrategy)
- [趨勢策略（TrendStrategy）](#趨勢策略trendstrategy)
- [ICT 策略（ICTStrategy）](#ict-策略ictstrategy)
- [基本面策略（FundamentalStrategy）](#基本面策略fundamentalstrategy)
- [新增自訂策略](#新增自訂策略)

---

## 策略框架（BaseStrategy）

檔案：`trading/strategies/base.py`

所有策略繼承 `BaseStrategy`（ABC），必須實作兩個抽象方法：

```python
class BaseStrategy(ABC):
    name: str         # 唯一識別鍵，同時是 API 查詢參數值
    label: str        # 顯示名稱（中文）
    min_bars: int     # 計算所需最少 K 棒數量
    signal_labels: dict  # {信號鍵: 中文名稱}

    def compute(self, df: pd.DataFrame, code: str = "") -> Optional[dict]:
        """計算信號，回傳含 signals / score 的字典；資料不足時回傳 None。"""

    def calc_entry_params(self, ind: dict, capital: float, risk_pct: float = 2.0) -> dict:
        """依指標結果計算進場價、停損價、目標價與建議股數。"""
```

`compute()` 回傳的 dict 必須包含：

| 鍵 | 型別 | 說明 |
|----|------|------|
| `signals` | `dict[str, bool]` | 各信號是否通過 |
| `score` | `int` | 通過的啟用信號數 |
| `enabled` | `dict[str, bool]` | 各信號是否啟用（讀自 config.json） |
| `total_enabled` | `int` | 總啟用信號數 |
| `close` | `float` | 最新收盤價 |

`calc_entry_params()` 回傳的 dict 必須包含：

| 鍵 | 說明 |
|----|------|
| `entry` | 進場價（通常為現收盤價） |
| `stop` | 停損價 |
| `target` | 目標價 |
| `shares` | 建議股數 |
| `risk_per_share` | 每股風險金額 |
| `total_risk` | 總風險金額（元） |

策略登錄表：`trading/strategies/__init__.py` 的 `REGISTRY`

```python
REGISTRY = {
    "trend":       TrendStrategy(),
    "ict":         ICTStrategy(),
    "fundamental": FundamentalStrategy(),
}
```

**注意**：`"trend"` / `"ict"` / `"fundamental"` 是 API 對外介面，不得更名。

---

## 趨勢策略（TrendStrategy）

檔案：`trading/strategies/trend.py`

- `name = "trend"` | `min_bars = 65`
- 以均線多頭排列為核心，搭配趨勢強度、動能與成交量共 **6 個信號**

### 信號說明

| 信號鍵 | 中文名 | 計算邏輯 |
|--------|--------|---------|
| `ema_arrangement` | 均線排列 | 收盤價 > EMA5 > EMA20 > EMA60（多頭排列） |
| `slopes_up` | 三線齊揚 | EMA5、EMA20、EMA60 的最新值均高於 3 根前的值 |
| `adx_above_25` | ADX>25 | 14 日 ADX 值 > 閾值（預設 25，可調） |
| `macd_positive` | MACD紅 | MACD Histogram（DIF - MACD Signal）> 0 |
| `volume_spike` | 爆量 | 當日成交量 > 20 日均量 × 倍數（預設 1.5，可調） |
| `ema_crossover` | 5穿20 | 近 3 根內 EMA5 由下穿上 EMA20 |

### 進場參數計算

```
stop   = swing_low（近 20 根最低點）- 1.5 × ATR14
target = entry + (entry - stop) × 2     # 2:1 風報比
shares = (capital × risk_pct%) / (entry - stop)
```

### 指標輔助計算

使用 `IndicatorEngine` 靜態方法：

- `IE._ema(series, length)` — 指數移動平均（pandas ewm）
- `IE._sma(series, length)` — 簡單移動平均
- `IE._atr(high, low, close, 14)` — Average True Range
- `IE._adx(high, low, close, 14)` — Average Directional Index
- `IE._macd(close)` → `(macd, signal, histogram)`

### 可調參數（config.json）

```json
"strategy_params": {
  "trend": {
    "adx_above_25": { "enabled": true, "threshold": 25 },
    "volume_spike": { "enabled": true, "threshold": 1.5 }
  }
}
```

---

## ICT 策略（ICTStrategy）

檔案：`trading/strategies/ict.py`

- `name = "ict"` | `min_bars = 30`
- 以機構訂單流與價格結構為核心，共 **7 個信號**

### 信號說明

| 信號鍵 | 中文名 | 計算邏輯 |
|--------|--------|---------|
| `bullish_ob` | 多頭OB | 近 30 根內：找到一根跌棒（close < open），其後 1–2 根收盤突破該棒高點，且現價站上 OB 高點 |
| `fvg_present` | FVG不平衡 | 近 15 根內：存在三棒跳空（`high[i-2] < low[i]`，即中間 K 棒上下皆空）且現價 ≥ 缺口底部 |
| `bos` | 結構突破(BOS) | 現收盤價 > 近 5–25 根（排除最後 2 根）的最高高點 |
| `liquidity_sweep` | 流動性掃除 | 近 5 根內曾跌破前段（-20 到 -5 根）擺動低點，但最新收盤已收回該低點上方 |
| `discount_zone` | 折扣區 | 現價 < 近 20 根（最高 + 最低）/ 2（均衡價），代表在折扣區 |
| `ote_zone` | OTE回檔區 | 現價落在近 40 根「擺動低→擺動高」的 61.8%–78.6% Fibonacci 回檔區間（預設 fib_low=0.618, fib_high=0.786） |
| `mss` | 市場結構轉換(MSS) | 識別近 40 根的擺動高點序列；若最近形成 lower high，現價突破該 lower high → 空頭結構被打破 |

### 進場參數計算

```
stop   = ob_low × 0.99      # 若無 OB，改用 range_low × 0.99
target = swing_high_ref     # 若無結構高點，改用 entry + risk_per × 2
shares = (capital × risk_pct%) / (entry - stop)
```

### 可調參數（config.json）

```json
"strategy_params": {
  "ict": {
    "ote_zone": { "enabled": true, "fib_low": 0.618, "fib_high": 0.786 }
  }
}
```

---

## 基本面策略（FundamentalStrategy）

檔案：`trading/strategies/fundamental.py`

- `name = "fundamental"` | `min_bars = 20`
- 以 yfinance 取得財務數據，共 **5 個信號**

### 信號說明

| 信號鍵 | 中文名 | 計算邏輯 |
|--------|--------|---------|
| `pe_reasonable` | 本益比合理 | 0 < trailingPE < 閾值（預設 30） |
| `eps_positive` | EPS為正 | trailingEPS > 0 |
| `eps_growth` | EPS成長 | forwardEPS > trailingEPS（預期成長） |
| `pb_reasonable` | PB合理 | 0 < priceToBook < 閾值（預設 2.5） |
| `revenue_growth` | 營收成長 | revenueGrowth > 0 |

數據來源：`yfinance.Ticker("{code}.TW").info`

### 進場參數計算

```
stop   = swing_low（近 20 根最低點）× 0.98
target = entry + (entry - stop) × 2     # 2:1 風報比
shares = (capital × risk_pct%) / (entry - stop)
```

### 可調參數（config.json）

```json
"strategy_params": {
  "fundamental": {
    "pe_reasonable": { "enabled": true, "threshold": 30 },
    "pb_reasonable": { "enabled": true, "threshold": 2.5 }
  }
}
```

---

## 新增自訂策略

1. 建立 `trading/strategies/my_strategy.py`，繼承 `BaseStrategy`：

```python
from trading.strategies.base import BaseStrategy

class MyStrategy(BaseStrategy):
    name     = "my_strategy"   # API 查詢鍵
    label    = "我的策略"
    min_bars = 50
    signal_labels = {
        "signal_a": "信號A說明",
        "signal_b": "信號B說明",
    }

    def compute(self, df, code=""):
        if len(df) < self.min_bars:
            return None
        # ... 計算邏輯 ...
        signals = {"signal_a": True, "signal_b": False}
        score   = sum(signals.values())
        return {
            "close":         float(df["close"].iloc[-1]),
            "signals":       signals,
            "enabled":       {k: True for k in signals},
            "score":         score,
            "total_enabled": len(signals),
        }

    def calc_entry_params(self, ind, capital, risk_pct=2.0):
        entry    = ind["close"]
        stop     = entry * 0.95
        risk_per = entry - stop
        shares   = int((capital * risk_pct / 100) / risk_per)
        return {
            "entry": entry, "stop": stop,
            "target": round(entry + risk_per * 2, 2),
            "shares": shares,
            "risk_per_share": round(risk_per, 2),
            "total_risk": int(risk_per * shares),
        }
```

2. 在 `trading/strategies/__init__.py` 的 `REGISTRY` 加入：

```python
from trading.strategies.my_strategy import MyStrategy

REGISTRY = {
    "trend":       TrendStrategy(),
    "ict":         ICTStrategy(),
    "fundamental": FundamentalStrategy(),
    "my_strategy": MyStrategy(),    # 新增
}
```

3. 在 `config.json` 的 `strategy_params` 加入對應參數區塊（可選）。

4. 在 `tests/` 補充測試，參考 `test_scanner.py` 的 `TestAnalyzeOne`。
