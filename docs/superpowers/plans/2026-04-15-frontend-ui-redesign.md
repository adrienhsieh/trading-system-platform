# Frontend UI Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 將現有深色 Tabler 風格改為淺色現代 SaaS 風格（導航列重構、配色轉換、K 線圖內嵌持倉卡片），不改後端邏輯。

**Architecture:** 全面重寫 `static/css/main.css`（淺色配色 + 新元件樣式），重構 `index.html` 的 HTML 結構（雙行導航取代舊 navbar + 移除右側欄 + 移除 K 線 Modal），修改 `static/js/holdings.js` 將 K 線圖從 Modal 改為內嵌渲染，更新 `static/js/app.js` 配合新的導航列 DOM 結構。

**Tech Stack:** HTML, CSS, JavaScript, Lightweight Charts v4.1.3, Chart.js v4.4.4

**Spec:** `docs/superpowers/specs/2026-04-15-frontend-ui-redesign.md`

---

## File Structure

| 檔案 | 動作 | 職責 |
|------|------|------|
| `static/css/main.css` | Rewrite | 全面重寫：淺色配色變數、新導航列、卡片、表格、Modal、Toast 樣式 |
| `index.html` | Modify | HTML 結構重構：雙行導航、移除右側欄、持倉卡片加 K 線圖容器、移除 chart-modal |
| `static/js/app.js` | Modify | `loadMarket()` 更新 DOM id（配合導航列新結構）、`tick()` 更新時鐘 id |
| `static/js/holdings.js` | Modify | K 線圖從 Modal 改為內嵌渲染（每張持倉卡片自動載入日線圖 + EMA5/20/60 + 標記線 + Swing Low） |

---

## Task 1: CSS 全面重寫（淺色配色 + 新元件樣式）

**Files:**
- Rewrite: `static/css/main.css`

- [ ] **Step 1: 重寫 `static/css/main.css`**

完整取代現有 CSS。新 CSS 包含：
- 淺色配色變數（:root）
- body 基礎樣式（移除 scanline 效果）
- 雙行導航列（.nav-top、.nav-tabs）
- Tab panel 顯示/隱藏
- 持倉卡片（.pcard）— 白底淺色版
- 掃描結果卡片（.scard）— 淺色版
- 觀察名單卡片（.wcard）— 淺色版
- 新聞項目、Badge、按鈕
- Modal overlay — 淺色版（白底 + 淡黑半透明背景）
- Toast — 淺色版
- 表格、表單元素
- 工具類（.g .r .y .b .chg）
- K 線圖容器樣式
- 進度條、Spinner

完整 CSS 程式碼太長（~300 行），工程師需要：
1. 讀取現有 `static/css/main.css`（217 行）
2. 用 spec 中的配色 token 全面替換
3. 移除 `body::before` scanline
4. 將所有 `var(--bs-*)` Tabler 變數改為自訂變數
5. 導航列樣式從 `.navbar` Tabler 類別改為自訂 `.nav-top` / `.nav-tabs`
6. 卡片從深色底改為 `background: var(--card-bg); border: 1px solid var(--border); box-shadow: var(--shadow); border-radius: var(--radius);`
7. 所有文字顏色從亮色改為深色（`--text-primary`, `--text-secondary`, `--text-tertiary`）

- [ ] **Step 2: 瀏覽器驗證基礎配色正確**

啟動 `python run.py`，開啟瀏覽器確認頁面背景、文字、卡片邊框顏色正確。

- [ ] **Step 3: Commit**

```bash
git add static/css/main.css
git commit -m "style: 全面重寫 CSS — 深色→淺色 SaaS 風格"
```

---

## Task 2: HTML 結構重構（導航列 + 移除右側欄 + 移除 K 線 Modal）

**Files:**
- Modify: `index.html`

- [ ] **Step 1: 移除 `data-bs-theme="dark"` 和 Tabler navbar**

在 `index.html` line 1：
- 將 `<html lang="zh-TW" data-bs-theme="dark">` 改為 `<html lang="zh-TW">`

將舊的 `<header class="navbar ...">...</header>`（lines 16-27）替換為新的雙行導航列：

```html
<!-- ═══ Row 1: Logo + Market Ticker + Clock ═══ -->
<header class="nav-top">
  <div class="nav-top-inner">
    <div class="nav-left">
      <a href="/" class="nav-logo">⚔️ WARROOM</a>
      <div class="market-ticker">
        <span class="ticker-label">TAIEX</span>
        <span class="ticker-val" id="m-tw">--</span>
        <span id="m-tw-chg" class="chg">--</span>
        <span class="ticker-sep">│</span>
        <span class="ticker-label">NASDAQ</span>
        <span class="ticker-val" id="m-nd">--</span>
        <span id="m-nd-chg" class="chg">--</span>
        <span class="ticker-sep">│</span>
        <span class="ticker-label">S&amp;P500</span>
        <span class="ticker-val" id="m-sp">--</span>
        <span id="m-sp-chg" class="chg">--</span>
        <span class="ticker-sep">│</span>
        <span class="ticker-label">USD/TWD</span>
        <span class="ticker-val" id="m-fx">--</span>
        <span class="ticker-sep">│</span>
        <span class="ticker-label">濾網</span>
        <span id="m-filter" class="ticker-val">--</span>
      </div>
    </div>
    <div class="nav-right">
      <span id="clock" class="nav-clock">--:--:--</span>
      <button class="btn-icon" onclick="openSettings()" title="設定">⚙️</button>
    </div>
  </div>
</header>

<!-- ═══ Row 2: Tab bar ═══ -->
<nav class="nav-tabs-bar">
  <div class="tab active" data-tab="holdings">持股戰情</div>
  <div class="tab" data-tab="watchlist">觀察名單</div>
  <div class="tab" data-tab="scanner">台股掃描</div>
  <div class="tab" data-tab="backtest">回測</div>
  <div class="tab" data-tab="news">財經情報</div>
  <div class="tab" data-tab="ai">AI 情報</div>
  <div class="tab" data-tab="topic">主題搜尋</div>
</nav>
```

- [ ] **Step 2: 移除右側欄（col-lg-4 整個區塊）**

刪除 lines 304-393（`<!-- RIGHT: SIDEBAR -->` 到 `</div><!-- /col-lg-4 -->`）。

同時將左側 `col-12 col-lg-8` 改為 `col-12`（全寬）。

移除外層的 `.page-wrapper > .page-body > .container-fluid > .row` 巢狀結構，改為簡單的：

```html
<main class="main-content">
  <!-- panels 直接放這裡 -->
</main>
```

- [ ] **Step 3: 持股戰情 Tab 加入摘要卡片 + K 線圖容器**

將 `tab-holdings` 內容改為：

```html
<div class="panel active" id="tab-holdings">
  <!-- 摘要卡片 -->
  <div class="summary-grid">
    <div class="summary-card">
      <div class="summary-label">總資產</div>
      <div class="summary-value" id="summary-total">--</div>
      <div class="summary-sub" id="summary-pnl"></div>
    </div>
    <div class="summary-card">
      <div class="summary-label">持倉數</div>
      <div class="summary-value" id="pos-count">0</div>
      <div class="summary-sub" id="summary-wl"></div>
    </div>
    <div class="summary-card">
      <div class="summary-label">總風險曝露</div>
      <div class="summary-value" id="risk-pct">--%</div>
      <div class="summary-sub" id="risk-mode"></div>
    </div>
    <div class="summary-card">
      <div class="summary-label">大盤濾網</div>
      <div class="summary-value" id="m-ema">--</div>
      <div class="summary-sub" id="m-filter-sub"></div>
    </div>
  </div>

  <!-- 持倉列表 header -->
  <div class="section-header">
    <span class="section-title">持倉列表</span>
    <button class="btn-primary-sm" onclick="openAddModal()">+ 新增部位</button>
  </div>
  <div id="pos-list">
    <div class="empty"><div class="empty-icon">📭</div>載入中...</div>
  </div>
  <div id="pos-pagination" style="display:none;justify-content:center;align-items:center;gap:12px;margin-top:12px;">
    <button class="btn-sm-outline" onclick="posPagePrev()">◀ 上頁</button>
    <span id="pos-page-label" style="font-family:var(--mono);font-size:12px;">1 / 1</span>
    <button class="btn-sm-outline" onclick="posPageNext()">下頁 ▶</button>
  </div>
</div>
```

- [ ] **Step 4: 移除 K 線圖 Modal**

刪除 `<!-- K-LINE CHART MODAL -->` 區塊（lines 521-540）。

- [ ] **Step 5: 瀏覽器驗證結構正確**

驗證：導航列雙行顯示、Tab 可切換、右側欄已消失、頁面全寬。

- [ ] **Step 6: Commit**

```bash
git add index.html
git commit -m "refactor: HTML 重構 — 雙行導航、移除右側欄、移除 K 線 Modal"
```

---

## Task 3: app.js 更新（配合新 DOM 結構）

**Files:**
- Modify: `static/js/app.js`

- [ ] **Step 1: 更新 `loadMarket()` 的 DOM id**

原本 `loadMarket()` 更新的是右側欄的市場資料 DOM（`m-tw`, `m-nd`, `m-sp`, `m-fx`, `m-filter`, `m-ema`）。新結構中這些 id 已移到導航列第一行，id 名稱保持不變，所以 `loadMarket()` 不需要修改。

但需要移除更新右側欄「資金風控」的 DOM 操作（`risk-val`, `risk-fill`, `risk-pct`, `consec`, `risk-mode`）。這些元素原本在右側欄，現在移到了持股戰情的摘要卡片中（`summary-total`, `risk-pct`, `risk-mode`）。

`renderRisk()` 函式在 `holdings.js` 中，需要更新 DOM id 引用。

- [ ] **Step 2: 更新 Tab 切換邏輯中的選擇器**

Tab 結構從 `.nav-tabs .tab` 改為 `.nav-tabs-bar .tab`。更新 `app.js` 中的 `document.querySelectorAll('.tab')` — 這個選擇器仍然正確因為 class 是 `.tab`，不需要改。

- [ ] **Step 3: 瀏覽器驗證市場數據顯示在導航列**

- [ ] **Step 4: Commit**

```bash
git add static/js/app.js
git commit -m "refactor: app.js 配合新導航列 DOM 結構"
```

---

## Task 4: holdings.js 改造（K 線圖內嵌 + 摘要卡片 + renderRisk 更新）

**Files:**
- Modify: `static/js/holdings.js`

- [ ] **Step 1: 更新 `renderPositions()` — 每張持倉卡片加 K 線圖容器**

在每張 `.pcard` 的 HTML 模板中，在持倉資訊下方加入 K 線圖 div：

```html
<div class="pcard-chart" id="chart-${p.code}" style="height:220px;"></div>
```

- [ ] **Step 2: 新增 `renderInlineCharts()` 函式**

在 `loadPrices()` 完成後呼叫。對每筆持倉：
1. 呼叫 `/api/ohlcv/${code}` 取得 K 線數據
2. 用 Lightweight Charts 在 `#chart-${code}` 容器渲染日線圖
3. 計算並疊加 EMA5（橘 #f59e0b）、EMA20（藍 #3b82f6）、EMA60（紫 #a855f7）
4. 加入水平標記線：目標價（綠虛線 #10b981）、進場價（灰虛線 #9ca3af）、停損價（紅虛線 #ef4444）
5. 計算 Swing Low（近 20 根最低點）加入靛色虛線 #6366f1
6. 圖表字體 12px JetBrains Mono

- [ ] **Step 3: 更新 `renderRisk()` — 改寫為更新摘要卡片**

原本更新右側欄的 DOM id（`risk-val`, `risk-fill`, `risk-pct`, `consec`, `risk-mode`），改為更新摘要卡片中的新 id（`summary-total`, `risk-pct`, `risk-mode`, `summary-pnl`, `summary-wl`）。

- [ ] **Step 4: 移除 `openChart()`, `openChartById()`, `closeChartModal()`, `exportChartPng()` 函式**

這些是 K 線 Modal 相關函式，不再需要。

- [ ] **Step 5: 移除 `renderPnlChart()` 的舊損益概覽 bar chart**

損益資訊已在摘要卡片中顯示，不需要獨立的 bar chart。

- [ ] **Step 6: 瀏覽器全面驗證持股戰情**

驗證：摘要卡片顯示（總資產/持倉數/風險/濾網）、持倉列表、每張卡片下方 K 線圖自動載入（含 EMA5/20/60 + 停損/進場/目標線 + Swing Low）。

- [ ] **Step 7: Commit**

```bash
git add static/js/holdings.js
git commit -m "feat: 持股戰情 K 線圖內嵌 + 摘要卡片 + 移除 Modal"
```

---

## Task 5: 其他 JS 檔微調（DOM id/class 引用）

**Files:**
- Modify: `static/js/scanner.js`, `static/js/watchlist.js`, `static/js/backtest.js`, `static/js/news.js`, `static/js/intelligence.js`, `static/js/settings.js`, `static/js/topic.js`

- [ ] **Step 1: 全面搜尋 JS 中引用的舊 DOM id/class**

搜尋所有 JS 檔中引用的 `var(--bs-*)` Tabler CSS 變數（在 inline style 中），替換為新的自訂變數：

| 舊 | 新 |
|----|-----|
| `var(--bs-card-bg)` | `var(--card-bg)` |
| `var(--bs-secondary-color)` | `var(--text-secondary)` |
| `var(--bs-tertiary-color)` | `var(--text-tertiary)` |
| `var(--bs-body-color)` | `var(--text-primary)` |
| `var(--bs-border-color)` | `var(--border)` |
| `var(--bs-card-border-color)` | `var(--border)` |
| `var(--bs-tertiary-bg)` | `var(--bg)` |
| `var(--bs-secondary-bg)` | `#e5e7eb` |
| `var(--accent)` | `var(--blue)` |
| `var(--text2)` | `var(--text-secondary)` |
| `var(--text3)` | `var(--text-tertiary)` |

也更新所有 JS 中的舊色值引用：
| 舊 | 新 |
|----|-----|
| `#3fb950` | `var(--green)` 或 `#10b981` |
| `#f85149` | `var(--red)` 或 `#ef4444` |
| `#58a6ff` | `var(--blue)` 或 `#3b82f6` |
| `#d29922` | `var(--yellow)` 或 `#f59e0b` |

- [ ] **Step 2: 更新 `quickAdd()` 中的 Tab 點擊引用**

`quickAdd()` 在 scanner.js 中用 `document.querySelectorAll('.tab')[0].click()` 切換到持股 Tab — 這個選擇器在新結構中仍然正確。

- [ ] **Step 3: 瀏覽器全面驗證所有 Tab**

逐一驗證：
- 觀察名單：載入、新增/移除、分析
- 台股掃描：策略切換、掃描、全市場 SSE
- 回測：單檔/多檔/全市場、圖表
- 財經情報：新聞載入
- AI 情報：情緒分析、X 情報、摘要
- 主題搜尋：關鍵字雲、搜尋
- 設定/策略設定 Modal

- [ ] **Step 4: Commit**

```bash
git add static/js/*.js
git commit -m "style: 全 JS 檔更新 CSS 變數引用（深色→淺色）"
```

---

## Task 6: 最終清理 + 回歸測試

**Files:**
- Modify: `index.html` (minor cleanup)

- [ ] **Step 1: 確認不需要 Tabler JS**

目前只用了 Tabler CSS。確認 `index.html` 沒有引用 Tabler JS（`tabler.min.js`）。如果沒有，不需要改動。

- [ ] **Step 2: 執行後端測試**

Run: `.venv\Scripts\python.exe -m unittest discover tests/ 2>&1 | tail -3`
Expected: `Ran 444 tests ... OK`

- [ ] **Step 3: 全功能瀏覽器回歸測試**

| 功能 | 驗證項目 |
|------|---------|
| 導航列第一行 | TAIEX / NASDAQ / S&P500 / USD-TWD 即時更新 |
| 導航列第二行 | 7 Tab 切換正常，active 底線 |
| 持股戰情 | 摘要卡片 4 欄、持倉列表、每張 K 線圖內嵌 |
| K 線圖 | 日線、EMA5/20/60、停損/進場/目標線、Swing Low |
| 觀察名單 | 載入、分析（趨勢+基本面）、新增/移除 |
| 台股掃描 | 策略切換、掃描、全市場 SSE、電子股 toggle |
| 回測 | 單檔/多檔/全市場、資產曲線、CSV 匯出 |
| 財經情報 | RSS 載入 |
| AI 情報 | 情緒/X 情報/摘要 |
| 主題搜尋 | 關鍵字雲/搜尋 |
| Modal | 新增部位/設定/策略設定/Coverage |
| Toast | 通知正常顯示 |

- [ ] **Step 4: 更新 spec 狀態**

In `docs/superpowers/specs/2026-04-15-frontend-ui-redesign.md`, change `> 狀態：待實作` to `> 狀態：已完成`。

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/specs/2026-04-15-frontend-ui-redesign.md
git commit -m "docs: mark UI redesign spec as complete"
```
