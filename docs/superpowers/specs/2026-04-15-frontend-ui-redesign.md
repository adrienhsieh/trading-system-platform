# 前端 UI 重設計 — Sub-project 2

> 日期：2026-04-15
> 狀態：待實作
> 前置：Sub-project 1（前端拆分）已完成

## 目標

將現有深色 Tabler 風格改為淺色現代 SaaS 風格，不改後端邏輯。

## 設計規格

### 全域配色

| Token | 值 | 用途 |
|-------|------|------|
| --bg | #f8f9fa | 頁面背景 |
| --card-bg | #ffffff | 卡片背景 |
| --border | #e5e7eb | 卡片/分隔線邊框 |
| --text-primary | #111827 | 主要文字 |
| --text-secondary | #6b7280 | 次要文字 |
| --text-tertiary | #9ca3af | 標籤/說明 |
| --green | #10b981 | 漲/正/通過 |
| --red | #ef4444 | 跌/負/未通過 |
| --yellow | #f59e0b | 警示 |
| --blue | #3b82f6 | 資訊/EMA20 |
| --purple | #a855f7 | EMA60 |
| --indigo | #6366f1 | Swing Low |
| --shadow | 0 1px 3px rgba(0,0,0,0.04) | 卡片陰影 |
| --radius | 10px | 卡片圓角 |
| --mono | 'JetBrains Mono', monospace | 數字字體 |
| --sans | 'Noto Sans TC', system-ui, sans-serif | 中文字體 |

### 導航列

**第一行（Logo bar）：**
- 左側：`⚔️ WARROOM` Logo
- 中間：TAIEX / NASDAQ / S&P500 / USD-TWD 即時指標（JetBrains Mono，11px）
  - 格式：`名稱 數值 ▲/▼百分比%`
  - 漲綠跌紅
- 右側：時鐘（`YYYY/MM/DD HH:MM:SS TST`）+ 設定齒輪按鈕
- 背景白色，底部 1px 邊框

**第二行（Tab bar）：**
- 7 個 Tab 文字水平排列，padding 12px 16px
- Active tab：`color: #111; border-bottom: 2px solid #111; font-weight: 500`
- Inactive tab：`color: #9ca3af`
- 背景白色，底部 1px 邊框

### 持股戰情 Tab

**摘要卡片（4 欄 grid）：**
- 總資產、持倉數、總風險曝露、大盤濾網
- 白底 + 邊框 + 陰影，圓角 10px
- 標題 11px 灰色，數值 22px 粗體 JetBrains Mono

**持倉卡片（每筆一張）：**
- Header 行：代號（14px 粗體 mono）+ 名稱 + 損益 badge + 數據列（現價/進場/停損/目標/損益）+ 操作按鈕（編輯/刪除）
- K 線圖區域：直接內嵌在卡片下方

**K 線圖規格：**
- Lightweight Charts 日線蠟燭圖
- 疊加三條均線：EMA5（#f59e0b 橘）、EMA20（#3b82f6 藍）、EMA60（#a855f7 紫）
- 水平標記線：目標價（#10b981 綠虛線）、進場價（#9ca3af 灰虛線）、停損價（#ef4444 紅虛線）
- Swing Low 標記（#6366f1 靛色虛線 + 三角指標）
- 圖表內字體需清晰可讀（12px mono）
- 圖例顯示在圖表右上角
- 資料來源：`/api/ohlcv/<code>`，套用 2PM 新鮮度快取
- 不再需要 K 線圖 Modal（移除 chart-modal）

### 其他 Tab 共通風格

所有 Tab 套用同樣的淺色卡片風格：
- 觀察名單、台股掃描、回測、財經情報、AI 情報、主題搜尋
- 卡片：白底 + 邊框 + 陰影
- 按鈕：深色底（#111）+ 白字，或淺灰底（#f3f4f6）
- Badge：淺色底 + 對應色文字（如 `background:#ecfdf5; color:#10b981`）
- 表格：無深色底，用 #f3f4f6 隔行或 hover 效果
- Toast：維持現有邏輯，改為淺色風格
- Modal：白底 + 陰影，overlay 改為 rgba(0,0,0,0.3)
- 進度條/Spinner：配合淺色主題

### 移除的元素

- 大盤右側邊欄（已移至導航列第一行）
- K 線圖 Modal（已內嵌至持倉卡片）
- Tabler 深色主題（`data-bs-theme="dark"` 移除）

### 保留不動的

- 所有 JS 函式邏輯（static/js/*.js）— 只改 CSS 和 HTML 結構
- 所有 API 端點
- Telegram Bot
- 後端測試

## 實作範圍

| 檔案 | 改動 |
|------|------|
| `static/css/main.css` | 全面重寫（深色→淺色，新 CSS 變數，新卡片/導航/表格樣式） |
| `index.html` | HTML 結構調整（導航列重構、移除右側欄、持倉卡片加 K 線圖容器） |
| `static/js/holdings.js` | K 線圖從 Modal 改為內嵌渲染，自動載入 |
| `static/js/app.js` | `loadMarket()` 更新 DOM id（配合導航列新結構） |
| 其他 JS 檔 | 可能需要微調 DOM id/class 引用 |

## 驗證方式

- 每步執行後端測試確認不壞
- 每步在瀏覽器手動確認 UI 正確
- 最終全功能回歸測試
