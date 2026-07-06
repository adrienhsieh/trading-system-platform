# 前端元件打磨設計 — Sub-project 3

> 日期：2026-04-15
> 狀態：待實作
> 前置：Sub-project 1（前端拆分）+ Sub-project 2（UI 重設計）已完成

## 目標

引入 3 個輕量 CDN 插件提升互動體驗，不改後端邏輯。

## 插件規格

### 1. CountUp.js（~4KB）

CDN：`https://cdn.jsdelivr.net/npm/countup.js@2.8.0/dist/countUp.umd.min.js`

數字從 0 滾動到目標值，duration 1.2 秒。

| 使用位置 | 檔案 | 說明 |
|---------|------|------|
| 摘要卡片 — 總資產 | `holdings.js` `renderRisk()` | `$4,529,594` 滾動顯示 |
| 摘要卡片 — 風險比例 | `holdings.js` `renderRisk()` | `4.8%` 滾動顯示 |
| 回測 — 績效指標 | `backtest.js` `renderBacktestResult()` | 勝率 / 報酬率 / 盈虧比 / 回撤 滾動 |

CountUp 選項：
```javascript
{ duration: 1.2, separator: ',', decimal: '.', prefix: '', suffix: '' }
```

### 2. NProgress（~2KB）

CDN JS：`https://cdn.jsdelivr.net/npm/nprogress@0.2.0/nprogress.min.js`
CDN CSS：`https://cdn.jsdelivr.net/npm/nprogress@0.2.0/nprogress.min.css`

頂部細進度條，配合 SSE 串流進度。

| 使用位置 | 檔案 | 觸發 |
|---------|------|------|
| 全市場掃描 | `scanner.js` `runFullScan()` | start → set(done/total) → done |
| 全市場回測 | `backtest.js` `runFullBacktest()` | start → set(done/total) → done |
| 觀察名單分析 | `watchlist.js` `loadWatchlistAnalysis()` | start → done |

自訂顏色（配合淺色主題）：
```css
#nprogress .bar { background: #3b82f6; }
#nprogress .peg { box-shadow: 0 0 10px #3b82f6, 0 0 5px #3b82f6; }
#nprogress .spinner-icon { border-top-color: #3b82f6; border-left-color: #3b82f6; }
```

NProgress 設定：
```javascript
NProgress.configure({ showSpinner: false, minimum: 0.08, speed: 300 });
```

### 3. SweetAlert2（~40KB）

CDN：`https://cdn.jsdelivr.net/npm/sweetalert2@11/dist/sweetalert2.all.min.js`

取代瀏覽器原生 `confirm()`，淺色風格彈窗。

| 使用位置 | 檔案 | 原始程式碼 |
|---------|------|-----------|
| 刪除持倉 | `holdings.js` `delPos()` | `if(!confirm(...))` → `Swal.fire()` |
| 移除觀察名單 | `watchlist.js` `removeWl()` | 新增確認（目前無確認直接刪除） |
| 重置策略設定 | `settings.js` `resetStratSettings()` | `if(!confirm(...))` → `Swal.fire()` |

SweetAlert2 共用樣式：
```javascript
Swal.fire({
  title: '確認刪除？',
  text: '此操作無法復原',
  icon: 'warning',
  showCancelButton: true,
  confirmButtonColor: '#ef4444',
  cancelButtonColor: '#6b7280',
  confirmButtonText: '確認刪除',
  cancelButtonText: '取消',
})
```

## 改動檔案

| 檔案 | 改動 |
|------|------|
| `index.html` | 加 3 個 CDN 引用（2 script + 1 link） |
| `static/css/main.css` | NProgress 顏色覆寫（3 行） |
| `static/js/holdings.js` | CountUp 摘要卡片 + SweetAlert2 delPos |
| `static/js/scanner.js` | NProgress 全市場掃描 |
| `static/js/backtest.js` | NProgress 全市場回測 + CountUp 績效指標 |
| `static/js/watchlist.js` | NProgress 分析 + SweetAlert2 移除確認 |
| `static/js/settings.js` | SweetAlert2 重置確認 |

## 不動的部分

- 後端 API / Telegram Bot / 測試
- 功能邏輯不變，只換 UI 互動元件

## 驗證方式

- 後端測試通過（444 tests）
- 瀏覽器手動驗證：數字滾動、進度條、確認彈窗
