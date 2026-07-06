# 前端重構設計 — Sub-project 1：檔案拆分

> 日期：2026-04-15
> 狀態：待實作
> 範圍：Sub-project 1（共 3 期）

## 背景

`index.html` 共 2,579 行，70% 是 JavaScript（1,802 行、72 個函式），所有 CSS（219 行）和 HTML 結構（531 行）全部塞在一個檔案裡。後續要進行 UI 重設計（Sub-project 2），必須先把檔案拆開，否則在單一巨大檔案上改 UI 極度痛苦。

## 目標

1. 將 `index.html` 從 2,579 行精簡為 ~150 行的 HTML 骨架
2. CSS 抽出至 `static/css/main.css`
3. JavaScript 按 Tab/功能拆分為 9 個獨立 `.js` 檔案
4. **不改任何邏輯、不改外觀、不改函式名稱** — 純搬遷
5. 所有現有功能正常運作（後端測試通過 + 手動驗證 UI）

## 設計決策（完整 3 期規劃）

以下決策在 brainstorming 階段確認，適用於整個 3 期重構：

| 項目 | 決定 |
|------|------|
| 整體風格 | 現代 SaaS（Linear / Vercel 風格） |
| 導航方式 | 頂部雙行（Logo + 大盤指標行 / Tab 行，底線 active） |
| 配色方案 | 淺色主題（白色/淺灰背景） |
| 拆分策略 | 純前端拆分（static/js + static/css，不用打包工具） |
| 分頁數量 | 維持 7 個不合併 |
| 卡片風格 | 有邊框 + 輕微陰影（Stripe 風格） |
| 大盤側欄 | 移到頂部導航列，小型指標嵌在 Logo 旁 |

本 Sub-project 1 只處理檔案拆分，不涉及 UI 變更。

## 拆分後檔案結構

```
trading_system/
├── index.html                  # HTML 骨架（~150 行）
├── static/
│   ├── css/
│   │   └── main.css            # 所有 CSS（~220 行，從 index.html <style> 抽出）
│   └── js/
│       ├── app.js              # 共用：api(), toast(), esc(), getApiKey(), fmtChg(), tick(), closeModal(), loadMarket(), autoFetchName(), switchTab(), 初始化邏輯
│       ├── holdings.js         # 持股戰情：loadPositions(), loadPrices(), renderPositions(), posPagePrev(), posPageNext(), renderRisk(), delPos(), editPos(), openAddModal(), savePos(), renderPnlChart(), openChartById(), openChart(), closeChartModal()
│       ├── watchlist.js        # 觀察名單：openWlAddModal(), saveWlAdd(), removeWl(), loadWatchlist(), loadWatchlistAnalysis(), _wm(), renderWatchlistAnalysis()
│       ├── scanner.js          # 台股掃描：toggleTechFilter(), setStrat(), runScan(), stopScan(), stopFullScan(), runFullScan(), renderScan(), quickAdd(), showCoverage(), closeCoverageModal(), loadCoverageKeywords()
│       ├── backtest.js         # 回測：runBacktest(), stopBacktest(), toggleBtTechFilter(), stopFullBacktest(), runFullBacktest(), renderFullBtResult(), renderBacktestResult(), renderMultiBacktestResult(), runOptimizer(), renderOptimizerResult()
│       ├── news.js             # 財經情報：loadNews(), fmtNewsDate(), renderNews()
│       ├── intelligence.js     # AI 情報：loadAiSentiment(), loadXIntel(), _renderSummary(), loadDailySummary(), generateSummary()
│       ├── topic.js            # 主題搜尋：searchTopic(), runTopicSearch()
│       └── settings.js         # 設定：openSettings(), saveSettings(), openStratSettings(), renderStratSettingsModal(), ssToggle(), collectStratParams(), saveStratSettings(), resetStratSettings()
```

## index.html 骨架結構

```html
<!DOCTYPE html>
<html lang="zh-Hant">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>戰情指揮中心</title>
  <!-- 外部 CDN -->
  <link href="https://fonts.googleapis.com/css2?family=..." rel="stylesheet">
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/@tabler/core@1.0.0/dist/css/tabler.min.css">
  <script src="https://cdn.jsdelivr.net/npm/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js"></script>
  <!-- 本地 CSS -->
  <link rel="stylesheet" href="/static/css/main.css">
</head>
<body>
  <!-- 導航列 -->
  <!-- 7 個 Tab 容器 -->
  <!-- Modal 定義 -->

  <!-- JS：app.js 第一個載入（定義共用函式），其餘按順序 -->
  <script src="/static/js/app.js"></script>
  <script src="/static/js/holdings.js"></script>
  <script src="/static/js/watchlist.js"></script>
  <script src="/static/js/scanner.js"></script>
  <script src="/static/js/backtest.js"></script>
  <script src="/static/js/news.js"></script>
  <script src="/static/js/intelligence.js"></script>
  <script src="/static/js/topic.js"></script>
  <script src="/static/js/settings.js"></script>
</body>
</html>
```

## 遷移策略

### 原則

- 純搬遷，不改邏輯 — 函式原封不動搬到對應 JS 檔
- inline event handler 保留 — `onclick="openAddModal()"` 不動
- 全域函式 — 不使用 ES module，所有函式掛在 `window` 全域
- 逐步搬遷 — 每搬一個區塊就驗證

### 搬遷順序

1. 抽出 CSS → `static/css/main.css`
2. 抽出共用函式 + 初始化邏輯 → `static/js/app.js`
3. 逐個抽出 Tab JS：holdings → watchlist → scanner → backtest → news → intelligence → topic → settings
4. 每步確認 `index.html` 的 `<script>` 引用順序正確

### 共用變數處理

`app.js` 中定義的全域變數（如 `let _apiKey`）在其他檔案中可直接存取，因為所有 JS 都在同一個全域作用域。不需要特殊的匯出/匯入機制。

## 驗證方式

- 每步執行 `python -m unittest discover tests/` 確認後端不壞
- 每步啟動 `python run.py` 在瀏覽器手動確認該 Tab 功能正常
- 最終全部搬完後，全 7 個 Tab + 設定 Modal + K 線圖 Modal 功能回歸測試

## 不動的部分

| 項目 | 原因 |
|------|------|
| Flask 後端（app.py, trading/api/*） | 不在此次範圍 |
| Telegram Bot | 不在此次範圍 |
| 測試（tests/*） | 後端測試不涉及前端 |
| 外觀 / UI 設計 | Sub-project 2 的範圍 |
| 功能邏輯 | 純搬遷不改邏輯 |

## Flask 靜態檔案

Flask 預設 serve `static/` 目錄，路徑為 `/static/...`。不需要修改 `app.py` 或新增路由。

## 後續子專案（僅記錄，不在此次實作）

- **Sub-project 2**：UI 重設計 — 淺色 SaaS 風格、雙行導航、Stripe 卡片、大盤嵌入導航列
- **Sub-project 3**：元件打磨 — CountUp.js / NProgress / SweetAlert2 等互動增強
