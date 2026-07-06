# 合併每日分析 + 新增觀察名單 Tab

**日期：** 2026-04-14
**狀態：** 已核准
**範疇：** 前端 + 後端（新增 watchlist table + API + UI）

---

## 1. 目標

1. 將「每日分析」tab 的技術警示合併進「持股戰情」的每張持倉卡片，移除獨立 tab
2. 新增「觀察名單」tab（第二個位置），提供新增/刪除觀察股票、趨勢+基本面策略分析、財報狗連結、Google News 最近 3 筆新聞

---

## 2. 設計決策

| 項目 | 選擇 |
|------|------|
| 每日分析合併方式 | 嵌入每張持倉卡片（非獨立區塊） |
| 觀察名單儲存 | `positions.db` 新增 `watchlist` table |
| 分析觸發方式 | 進入 tab 時自動分析全部（有快取同日不重跑） |
| 新聞來源 | Google News RSS 搜尋股票名稱 |
| Tab 位置 | 持股戰情後面（第二個） |

---

## 3. 變更 1：合併「每日分析」到「持股戰情」

### 3-1. 持倉卡片新增技術指標行

每張持倉卡片（`.pcard`）在現有損益資訊下方新增一行：

```
進場 900 ｜ 現價 920 (+2.22%)
浮盈 +22,000 元
───────────────────
EMA20: 895 ✅ 站上 ｜ 停損距: -7.6% ｜ 目標距: +14.1%
⚠️ 接近停損
```

**技術指標來源：** `loadPositions()` 時同時 call `/api/report`，將 `analyses` 依 code 對應到各持倉卡片。

**警示規則（沿用現有 `/api/report` 邏輯）：**
- `below_ema20 == true` → 「❌ 跌破 EMA20」（紅色）
- 停損距離 < 5% → 「⚠️ 接近停損」（黃色）
- 目標距離 < 5% → 「✅ 接近目標」（綠色）

### 3-2. 移除項目

- `tab-report` tab 按鈕（`data-tab="report"`）
- `tab-report` panel HTML
- tab handler 中 `if(tab.dataset.tab==='report') loadReport();`
- `loadReport()` 函式
- `renderReport()` 函式

### 3-3. 保留項目

- `/api/report` 後端端點（Telegram `/報告` 指令仍使用）
- `report-summary` 的摘要文字移到持倉列表上方（簡化為一行大盤狀態）

---

## 4. 變更 2：新增「觀察名單」Tab

### 4-1. SQLite Schema

在 `positions.db` 新增 table（由 `PositionManager._init_db()` 建立）：

```sql
CREATE TABLE IF NOT EXISTS watchlist (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    code     TEXT NOT NULL UNIQUE,
    name     TEXT NOT NULL DEFAULT '',
    added_at TEXT NOT NULL
);
```

### 4-2. PositionManager 新增方法

```python
# watchlist CRUD
def watchlist_add(self, code: str, name: str) -> bool:
    """新增觀察股票。重複 code 回傳 False。"""

def watchlist_remove(self, code: str) -> bool:
    """移除觀察股票。不存在回傳 False。"""

def watchlist_list(self) -> list[dict]:
    """回傳所有觀察股票 [{id, code, name, added_at}]"""
```

### 4-3. 後端 API

**新增 Blueprint：** `trading/api/watchlist.py`

| 路徑 | Method | 用途 | 回傳 |
|------|--------|------|------|
| `/api/watchlist` | GET | 列出觀察名單 | `{ok, items: [{code, name, added_at}]}` |
| `/api/watchlist` | POST | 新增（body: `{code}`） | `{ok, code, name}` |
| `/api/watchlist/<code>` | DELETE | 刪除 | `{ok}` |
| `/api/watchlist/analyze` | GET | 分析全部 | `{ok, results: [...]}` |

### 4-4. `/api/watchlist/analyze` 回傳結構

```json
{
  "ok": true,
  "results": [
    {
      "code": "2330",
      "name": "台積電",
      "trend": {
        "score": 4,
        "total": 6,
        "signals": {
          "ema_arrangement": {"pass": true, "label": "均線排列"},
          "slopes_up": {"pass": true, "label": "三線齊揚"},
          "adx_above_25": {"pass": false, "label": "ADX > 25"},
          "macd_positive": {"pass": true, "label": "MACD 紅柱"},
          "volume_spike": {"pass": false, "label": "爆量"},
          "ema_crossover": {"pass": true, "label": "5穿20"}
        }
      },
      "fundamental": {
        "score": 3,
        "total": 5,
        "signals": {
          "pe_reasonable": {"pass": true, "label": "本益比合理"},
          "eps_positive": {"pass": true, "label": "EPS 為正"},
          "eps_growth": {"pass": false, "label": "EPS 成長"},
          "pb_reasonable": {"pass": true, "label": "股淨比合理"},
          "revenue_growth": {"pass": false, "label": "營收成長"}
        }
      },
      "report_url": "https://statementdog.com/analysis/2330",
      "news": [
        {"title": "台積電Q1營收創新高", "url": "https://...", "date": "2026-04-14"},
        {"title": "CoWoS產能再擴張", "url": "https://...", "date": "2026-04-13"},
        {"title": "外資連買台積電", "url": "https://...", "date": "2026-04-12"}
      ]
    }
  ]
}
```

**分析邏輯：**
- 趨勢：`scanner.analyze_one(code, capital, risk_pct, strategy="trend")` → 取 `ind.signals`
- 基本面：`scanner.analyze_one(code, capital, risk_pct, strategy="fundamental")` → 取 `ind.signals`
- 財報連結：`f"https://statementdog.com/analysis/{code}"`
- 新聞：Google News RSS `https://news.google.com/rss/search?q={name}+股票&hl=zh-TW&gl=TW&ceid=TW:zh-Hant`，取最近 3 筆，parse title + link + pubDate

### 4-5. 前端 UI

**Tab 按鈕：** `📋 觀察名單`（data-tab="watchlist"，第二個位置）

**Panel 結構：**

```html
<!-- 觀察名單 -->
<div class="panel" id="tab-watchlist">
  <div class="sec-hdr">
    <div class="sec-title-mono">觀察名單 <em id="wl-count">0</em> 檔</div>
    <button class="btn btn-sm btn-success" onclick="openWatchlistAddModal()">+ 新增</button>
  </div>
  <div id="wl-list">
    <div class="empty"><div class="empty-icon">👀</div>尚無觀察股票，點擊「+ 新增」開始追蹤</div>
  </div>
</div>
```

**觀察股票卡片：**

```
┌─────────────────────────────────────┐
│ 2330 台積電                      [✕] │
│                                      │
│ 🛡️ 趨勢 4/6                         │
│  ✓ 均線排列  ✓ 三線齊揚  ✗ ADX>25   │
│  ✓ MACD紅柱  ✗ 爆量  ✓ 5穿20        │
│                                      │
│ 📊 基本面 3/5                        │
│  ✓ PE合理  ✓ EPS正  ✗ EPS成長       │
│  ✓ PB合理  ✗ 營收成長               │
│                                      │
│ 📊 財報狗  📰 最近新聞              │
│  · 台積電Q1營收創新高    2026-04-14  │
│  · CoWoS產能再擴張      2026-04-13  │
│  · 外資連買台積電        2026-04-12  │
└─────────────────────────────────────┘
```

**新增 Modal：**
- 輸入框：股票代號（4 位數）
- POST `/api/watchlist` → 成功後重新載入列表
- 自動帶出名稱（後端從 `scanner.get_stock_name()` 取得）

**載入流程：**
1. 切到觀察名單 tab → `loadWatchlist()`
2. GET `/api/watchlist` → 渲染清單
3. GET `/api/watchlist/analyze` → 填入分析結果（可能 10-30 秒）
4. 同一天內快取結果，不重跑分析

---

## 5. 檔案變動清單

| 檔案 | 動作 | 內容 |
|------|------|------|
| `trading/positions.py` | 修改 | 新增 watchlist table + CRUD 方法 |
| `trading/api/watchlist.py` | 新建 | Flask Blueprint（4 端點） |
| `trading/api/__init__.py` | 修改 | 註冊 watchlist_bp |
| `index.html` | 修改 | 移除 report tab、合併技術指標到持倉卡片、新增觀察名單 tab + UI |
| `tests/test_positions.py` | 修改 | 新增 watchlist CRUD 測試 |

---

## 6. 不改動項目

- `/api/report` 後端端點保留（Telegram `/報告` 指令使用）
- Telegram Bot 的 `/報告` 指令不受影響
- 持倉的新增/刪除/編輯功能不變
