# Frontend Restructure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 將 index.html（2,579 行）拆分為 HTML 骨架 + 1 個 CSS 檔 + 9 個 JS 檔，不改任何邏輯或外觀。

**Architecture:** 從 index.html 中抽出 `<style>` 內容至 `static/css/main.css`，抽出 `<script>` 內容按功能拆分為 `static/js/*.js`，index.html 只保留 HTML 結構和 `<link>`/`<script>` 引用。所有函式保持全域作用域，不使用 ES modules。

**Tech Stack:** HTML, CSS, JavaScript (vanilla), Flask static serving

**Spec:** `docs/superpowers/specs/2026-04-15-frontend-restructure-design.md`

---

## File Structure

| 檔案 | 動作 | 職責 |
|------|------|------|
| `static/css/main.css` | Create | 所有 CSS（從 index.html lines 12-230 抽出） |
| `static/js/app.js` | Create | 共用函式 + Tab 切換 + 時鐘 + 初始化 |
| `static/js/holdings.js` | Create | 持股戰情 tab 函式 + 全域變數 |
| `static/js/watchlist.js` | Create | 觀察名單 tab 函式 + 全域變數 |
| `static/js/scanner.js` | Create | 台股掃描 tab 函式 + 全域變數 |
| `static/js/backtest.js` | Create | 回測 tab 函式 + 全域變數 |
| `static/js/news.js` | Create | 財經情報 tab 函式 |
| `static/js/intelligence.js` | Create | AI 情報 tab 函式 |
| `static/js/topic.js` | Create | 主題搜尋 tab 函式 + 全域變數 |
| `static/js/settings.js` | Create | 設定 modal 函式 + 全域變數 |
| `index.html` | Modify | 精簡為 HTML 骨架 + 引用 |

---

## Task 1: 建立目錄結構 + 抽出 CSS

**Files:**
- Create: `static/css/main.css`
- Modify: `index.html`

- [ ] **Step 1: 建立 static 目錄結構**

```bash
mkdir -p static/css static/js
```

- [ ] **Step 2: 抽出 CSS 至 `static/css/main.css`**

從 `index.html` 抽出 lines 12-230（`<style>` 標籤之間的內容，不含 `<style>` 和 `</style>` 標籤本身）。原封不動複製，不做任何修改。

讀取 `index.html`，將 `<style>...</style>` 區塊（lines 11-230）的 CSS 內容寫入 `static/css/main.css`。

- [ ] **Step 3: 修改 index.html — 用 link 引用取代 inline style**

將 index.html 中的 `<style>...</style>` 區塊（lines 11-230）替換為：

```html
<link rel="stylesheet" href="/static/css/main.css">
```

- [ ] **Step 4: 啟動伺服器驗證 CSS 載入正常**

Run: `cd c:/Users/88698/Desktop/Workspace/trading_system && .venv/Scripts/python.exe -m unittest discover tests/ 2>&1 | tail -3`
Expected: `Ran 444 tests ... OK`

在瀏覽器開啟 http://localhost:8787 確認外觀不變。

- [ ] **Step 5: Commit**

```bash
git add static/css/main.css index.html
git commit -m "refactor: 抽出 CSS 至 static/css/main.css"
```

---

## Task 2: 抽出共用函式至 `static/js/app.js`

**Files:**
- Create: `static/js/app.js`
- Modify: `index.html`

- [ ] **Step 1: 建立 `static/js/app.js`**

從 index.html 的 `<script>` 區塊中抽出以下函式和邏輯，**原封不動**複製：

**包含的內容（按原始順序）：**
- lines 764-790：`getApiKey()`, `api()`, `esc()`, `toast()`, `fmtChg()`
- lines 792-799：`tick()` + `setInterval(tick, 1000); tick();`
- lines 801-813：Tab 切換邏輯（`document.querySelectorAll('.tab').forEach(...)` + `switchTab()` 函式）
- line 1015：`closeModal(id)` 函式
- lines 1664-1692：`_mktRetry` 變數 + `loadMarket()` 函式
- lines 2531-2534：Init 呼叫（`loadPositions()`, `loadMarket()`, `loadNews()`）
- lines 2536-2563：`_nameTimer` 變數 + `autoFetchName()` 函式

**注意：** Init 呼叫（lines 2531-2534）放在 `app.js` 的最底部，加上 `DOMContentLoaded` 事件包裹，因為 app.js 在 `<head>` 或 `<body>` 頂部載入時 DOM 可能尚未就緒：

```javascript
document.addEventListener('DOMContentLoaded', () => {
  loadPositions().catch(e => console.warn('positions 載入失敗', e));
  loadMarket();
  loadNews().catch(e => console.warn('news 載入失敗', e));
});
```

但因為 `<script>` 標籤會放在 `</body>` 之前（DOM 已就緒），所以不需要 DOMContentLoaded。直接保持原樣即可。

- [ ] **Step 2: 從 index.html 刪除已搬出的 JS 區塊**

刪除 index.html 中上述函式和變數的原始位置。

- [ ] **Step 3: 在 index.html 加入 script 引用**

在 `</body>` 前（在 coverage-modal div 之後）加入：

```html
<script src="/static/js/app.js"></script>
```

- [ ] **Step 4: 執行測試 + 瀏覽器驗證**

Run: `.venv\Scripts\python.exe -m unittest discover tests/ 2>&1 | tail -3`
Expected: `Ran 444 tests ... OK`

在瀏覽器驗證：頁面載入正常、Tab 切換正常、時鐘運轉、toast 正常。

- [ ] **Step 5: Commit**

```bash
git add static/js/app.js index.html
git commit -m "refactor: 抽出共用函式至 static/js/app.js"
```

---

## Task 3: 抽出持股戰情至 `static/js/holdings.js`

**Files:**
- Create: `static/js/holdings.js`
- Modify: `index.html`

- [ ] **Step 1: 建立 `static/js/holdings.js`**

從 index.html 抽出以下內容（原封不動）：

**全域變數：**
- `let _reportMap = {};`（line 816）
- `let positions = [];`（line 817）
- `let _posPage = 0;`（line 867）
- `const POS_PAGE_SIZE = 10;`（line 868）

**函式（按原始順序）：**
- `loadPositions()`（lines 819-831）
- `loadPrices()`（lines 832-866）
- `renderPositions()`（lines 870-946）
- `posPagePrev()`（line 947）
- `posPageNext()`（lines 948-952）
- `renderRisk()`（lines 953-964）
- `delPos()`（lines 965-973）
- `editPos()`（lines 974-992）
- `openAddModal()`（lines 994-1014）
- `savePos()`（lines 1017-1053）
- `renderPnlChart()`（lines 2303-2343）
- `openChartById()`（lines 2345-2350）
- `openChart()`（lines 2351-2403）
- `closeChartModal()`（lines 2404-2408）

**注意：** `renderPnlChart`, `openChartById`, `openChart`, `closeChartModal` 在原始檔案中位於較後面的位置（2303-2408），但它們都是持股戰情的功能，一起搬到 `holdings.js`。

- [ ] **Step 2: 從 index.html 刪除已搬出的區塊**

- [ ] **Step 3: 在 index.html 加入 script 引用**

在 `app.js` 引用之後加入：

```html
<script src="/static/js/holdings.js"></script>
```

- [ ] **Step 4: 瀏覽器驗證持股戰情 tab**

驗證：持倉載入、價格更新、新增/刪除持倉、K 線圖開啟、PnL 圖表渲染。

- [ ] **Step 5: Commit**

```bash
git add static/js/holdings.js index.html
git commit -m "refactor: 抽出持股戰情至 static/js/holdings.js"
```

---

## Task 4: 抽出觀察名單至 `static/js/watchlist.js`

**Files:**
- Create: `static/js/watchlist.js`
- Modify: `index.html`

- [ ] **Step 1: 建立 `static/js/watchlist.js`**

從 index.html 抽出以下內容（原封不動）：

**全域變數：**
- `let _wlAnalysisCache = null;`
- `let _wlAnalysisTime = 0;`
- `const _WL_CACHE_TTL = 5 * 60_000;`

**函式：**
- `openWlAddModal()`
- `saveWlAdd()`
- `removeWl()`
- `loadWatchlist()`
- `loadWatchlistAnalysis()`
- `_wm()`
- `renderWatchlistAnalysis()`

- [ ] **Step 2: 從 index.html 刪除已搬出的區塊**

- [ ] **Step 3: 在 index.html 加入 script 引用**

```html
<script src="/static/js/watchlist.js"></script>
```

- [ ] **Step 4: 瀏覽器驗證觀察名單 tab**

驗證：名單載入、新增/移除、分析功能、快取邏輯。

- [ ] **Step 5: Commit**

```bash
git add static/js/watchlist.js index.html
git commit -m "refactor: 抽出觀察名單至 static/js/watchlist.js"
```

---

## Task 5: 抽出台股掃描至 `static/js/scanner.js`

**Files:**
- Create: `static/js/scanner.js`
- Modify: `index.html`

- [ ] **Step 1: 建立 `static/js/scanner.js`**

**全域變數：**
- `let currentStrat = 'trend';`
- `let fullScanResults = [];`
- `let fullScanEs = null;`
- `let techFilterEnabled = true;`
- `let scanAbort = null;`

**函式：**
- `toggleTechFilter()`
- `setStrat()`
- `runScan()`
- `stopScan()`
- `stopFullScan()`
- `runFullScan()`
- `renderScan()`
- `quickAdd()`
- `showCoverage()`
- `closeCoverageModal()`
- `loadCoverageKeywords()`（含 `let _kwLoaded = false;`）

- [ ] **Step 2: 從 index.html 刪除已搬出的區塊**

- [ ] **Step 3: 在 index.html 加入 script 引用**

```html
<script src="/static/js/scanner.js"></script>
```

- [ ] **Step 4: 瀏覽器驗證台股掃描 tab**

驗證：策略切換、候選掃描、全市場掃描（SSE）、電子股 toggle、個股分析、Coverage modal。

- [ ] **Step 5: Commit**

```bash
git add static/js/scanner.js index.html
git commit -m "refactor: 抽出台股掃描至 static/js/scanner.js"
```

---

## Task 6: 抽出回測至 `static/js/backtest.js`

**Files:**
- Create: `static/js/backtest.js`
- Modify: `index.html`

- [ ] **Step 1: 建立 `static/js/backtest.js`**

**全域變數：**
- `let btAbort = null;`
- `let fullBtEs = null;`
- `let btTechFilterEnabled = false;`
- `let _btTrades = [];`
- `const BT_COLORS = ['#58a6ff','#3fb950','#f78166','#e3b341','#bc8cff','#39d353'];`
- `let _optEs = null;`

**函式：**
- `runBacktest()`
- `stopBacktest()`
- `toggleBtTechFilter()`
- `stopFullBacktest()`
- `runFullBacktest()`
- `renderFullBtResult()`
- `renderBacktestResult()`
- `renderMultiBacktestResult()`
- `exportTradesCsv()`
- `exportEquityPng()`
- `exportChartPng()`
- `runOptimizer()`
- `renderOptimizerResult()`

- [ ] **Step 2: 從 index.html 刪除已搬出的區塊**

- [ ] **Step 3: 在 index.html 加入 script 引用**

```html
<script src="/static/js/backtest.js"></script>
```

- [ ] **Step 4: 瀏覽器驗證回測 tab**

驗證：單檔回測、多檔回測、全市場回測（SSE）、權益曲線圖、CSV 匯出、策略參數掃描。

- [ ] **Step 5: Commit**

```bash
git add static/js/backtest.js index.html
git commit -m "refactor: 抽出回測至 static/js/backtest.js"
```

---

## Task 7: 抽出財經情報至 `static/js/news.js`

**Files:**
- Create: `static/js/news.js`
- Modify: `index.html`

- [ ] **Step 1: 建立 `static/js/news.js`**

**函式（無全域變數）：**
- `loadNews()`
- `fmtNewsDate()`
- `renderNews()`

- [ ] **Step 2: 從 index.html 刪除已搬出的區塊**

- [ ] **Step 3: 在 index.html 加入 script 引用**

```html
<script src="/static/js/news.js"></script>
```

- [ ] **Step 4: 瀏覽器驗證財經情報 tab**

驗證：RSS 新聞載入、標籤分類、日期格式。

- [ ] **Step 5: Commit**

```bash
git add static/js/news.js index.html
git commit -m "refactor: 抽出財經情報至 static/js/news.js"
```

---

## Task 8: 抽出 AI 情報至 `static/js/intelligence.js`

**Files:**
- Create: `static/js/intelligence.js`
- Modify: `index.html`

- [ ] **Step 1: 建立 `static/js/intelligence.js`**

**函式（無全域變數）：**
- `loadAiSentiment()`
- `loadXIntel()`
- `_renderSummary()`
- `loadDailySummary()`
- `generateSummary()`

- [ ] **Step 2: 從 index.html 刪除已搬出的區塊**

- [ ] **Step 3: 在 index.html 加入 script 引用**

```html
<script src="/static/js/intelligence.js"></script>
```

- [ ] **Step 4: 瀏覽器驗證 AI 情報 tab**

驗證：AI 情緒分析、X 情報載入、每日摘要載入/生成。

- [ ] **Step 5: Commit**

```bash
git add static/js/intelligence.js index.html
git commit -m "refactor: 抽出 AI 情報至 static/js/intelligence.js"
```

---

## Task 9: 抽出主題搜尋至 `static/js/topic.js`

**Files:**
- Create: `static/js/topic.js`
- Modify: `index.html`

- [ ] **Step 1: 建立 `static/js/topic.js`**

**全域變數：**
- `let _kwLoaded = false;`（注意：如果這已在 scanner.js 的 `loadCoverageKeywords` 中搬過，此處不重複）

**函式：**
- `searchTopic()`
- `runTopicSearch()`

**注意：** `loadCoverageKeywords()` 和 `_kwLoaded` 已在 Task 5（scanner.js）中搬出。`searchTopic()` 和 `runTopicSearch()` 呼叫 `loadCoverageKeywords()`，因為是全域函式所以跨檔案可以直接呼叫。

- [ ] **Step 2: 從 index.html 刪除已搬出的區塊**

- [ ] **Step 3: 在 index.html 加入 script 引用**

```html
<script src="/static/js/topic.js"></script>
```

- [ ] **Step 4: 瀏覽器驗證主題搜尋 tab**

驗證：關鍵字雲載入、搜尋功能。

- [ ] **Step 5: Commit**

```bash
git add static/js/topic.js index.html
git commit -m "refactor: 抽出主題搜尋至 static/js/topic.js"
```

---

## Task 10: 抽出設定至 `static/js/settings.js`

**Files:**
- Create: `static/js/settings.js`
- Modify: `index.html`

- [ ] **Step 1: 建立 `static/js/settings.js`**

**全域變數：**
- `let _stratParams = null;`
- `const STRAT_META = { ... };`（lines 1709-1735 的完整物件）

**函式：**
- `openSettings()`
- `saveSettings()`
- `openStratSettings()`
- `renderStratSettingsModal()`
- `ssToggle()`
- `collectStratParams()`
- `saveStratSettings()`
- `resetStratSettings()`

- [ ] **Step 2: 從 index.html 刪除已搬出的區塊**

- [ ] **Step 3: 在 index.html 加入 script 引用**

```html
<script src="/static/js/settings.js"></script>
```

- [ ] **Step 4: 瀏覽器驗證設定功能**

驗證：開啟設定 modal、儲存設定、策略設定 modal、門檻調整、重置。

- [ ] **Step 5: Commit**

```bash
git add static/js/settings.js index.html
git commit -m "refactor: 抽出設定至 static/js/settings.js"
```

---

## Task 11: 清理 index.html + 最終驗證

**Files:**
- Modify: `index.html`

- [ ] **Step 1: 確認 index.html 中 `<script>` 標籤已被完全移除**

index.html 中應該不再有 `<script>` 標籤包含 inline JavaScript。只應有：

```html
<!-- CDN -->
<script src="https://cdn.jsdelivr.net/npm/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js"></script>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js"></script>

<!-- 本地 JS -->
<script src="/static/js/app.js"></script>
<script src="/static/js/holdings.js"></script>
<script src="/static/js/watchlist.js"></script>
<script src="/static/js/scanner.js"></script>
<script src="/static/js/backtest.js"></script>
<script src="/static/js/news.js"></script>
<script src="/static/js/intelligence.js"></script>
<script src="/static/js/topic.js"></script>
<script src="/static/js/settings.js"></script>
```

若原始的 `<script>...</script>` 區塊仍殘留任何程式碼，將其搬到對應的 JS 檔。

- [ ] **Step 2: 確認 index.html 行數已大幅縮減**

預期 index.html 約 ~780 行（純 HTML 結構 + 引用，不含 JS/CSS）。

- [ ] **Step 3: 執行後端測試**

Run: `.venv\Scripts\python.exe -m unittest discover tests/ 2>&1 | tail -3`
Expected: `Ran 444 tests ... OK`

- [ ] **Step 4: 全功能回歸測試（瀏覽器手動）**

逐一驗證：

| Tab | 驗證項目 |
|-----|---------|
| 持股戰情 | 持倉載入、價格更新、新增/刪除、K 線圖、PnL 圖 |
| 觀察名單 | 名單載入、新增/移除、雙策略分析、快取 |
| 台股掃描 | 策略切換、候選掃描、全市場 SSE、電子股 toggle |
| 回測 | 單檔/多檔/全市場回測、權益曲線、CSV 匯出、參數掃描 |
| 財經情報 | RSS 新聞載入 |
| AI 情報 | AI 情緒、X 情報、每日摘要 |
| 主題搜尋 | 關鍵字雲、搜尋結果 |
| 設定 | 設定讀寫、策略門檻調整 |
| 大盤側欄 | 行情載入、EMA 狀態 |
| Modal | 所有 modal 開關正常 |
| Toast | 通知顯示正常 |

- [ ] **Step 5: 更新 .gitignore（如需要）**

確認 `static/` 目錄未被 gitignore 排除。

- [ ] **Step 6: Commit**

```bash
git add index.html
git commit -m "refactor: 完成前端拆分 — index.html 精簡為 HTML 骨架"
```
