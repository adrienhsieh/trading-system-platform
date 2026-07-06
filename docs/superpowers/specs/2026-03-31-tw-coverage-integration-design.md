# My-TW-Coverage 整合設計

**日期**：2026-03-31
**狀態**：已核准
**範圍**：將 Timeverse/My-TW-Coverage 研究資料庫整合進戰情指揮中心

---

## 背景

My-TW-Coverage 是覆蓋 1,735 家台股公司的研究資料庫，目前已有 98 份報告，格式為 Markdown。每份報告包含業務概況、供應鏈位置、主要客戶、主要供應商、財務概況，以及 `[[wikilink]]` 知識圖譜。

整合目標：
- **A. 個股分析補充**：分析結果顯示業務概況 + 供應鏈
- **B. 主題關鍵字搜尋**：輸入 `CoWoS`、`液冷散熱` 找出相關台股
- **C. 股票名稱 + 產業別補全**：補強 stock_map 的 sector 資訊

---

## 資料位置

```
trading_system/
  data/
    tw-coverage/          ← git clone Timeverse/My-TW-Coverage
      Pilot_Reports/
        Semiconductors/
          2330_台積電.md
        ...
```

- 首次安裝：`git clone https://github.com/Timeverse/My-TW-Coverage data/tw-coverage`
- 每日 02:00 由 scheduler 執行 `git pull` 自動更新

---

## 架構

```
trading/coverage.py        新模組 CoverageReader（In-Memory 索引）
app.py                     新增 3 個 API 端點
trading/telegram/scheduler.py  新增每日 02:00 sync 任務
index.html                 台股掃描 Tab 兩處改動
```

---

## trading/coverage.py — CoverageReader

### 索引建立

啟動時呼叫 `reload()`，掃描 `Pilot_Reports/**/*.md`：
- 檔名格式：`XXXX_公司名.md`（4位數字代號）
- 建立記憶體索引：`_index: dict[str, dict]`

```python
_index = {
    "2330": {
        "name":    "台積電",
        "sector":  "Semiconductors",   # 來自父目錄名稱
        "path":    Path("..."),
    }
}
```

TTL：12 小時，`sync()` 後強制重建。

### 方法簽名

```python
class CoverageReader:
    def reload(self) -> int:
        """掃描所有 .md 建立索引，回傳檔案數"""

    def get_overview(self, code: str) -> dict | None:
        """
        解析個股報告，回傳：
        {
            "name":         str,
            "sector":       str,
            "business":     str,   # ## 業務概況 段落文字
            "supply_chain": str,   # ## 供應鏈位置 段落文字
            "customers":    str,   # ## 主要客戶 段落文字
            "suppliers":    str,   # ## 主要供應商 段落文字
            "wikilinks":    list[str],   # 所有 [[...]] 去重列表
        }
        無此代號時回傳 None
        """

    def search(self, keyword: str, limit: int = 20) -> list[dict]:
        """
        搜尋含 keyword 的報告（wikilink 精確比對優先，內文模糊比對次之）
        回傳：[{"code": str, "name": str, "sector": str, "matched_links": list[str]}]
        """

    def get_sector(self, code: str) -> str:
        """回傳產業別字串，無資料時回傳空字串"""

    def sync(self) -> dict:
        """
        執行 git pull，重建索引
        回傳：{"added": int, "total": int, "duration_sec": float}
        """

    @property
    def total(self) -> int:
        """目前索引的報告數"""
```

### Markdown 解析規則

- **段落切割**：以 `^##\s+` 分割，取標題文字對應段落內容
- **Wikilink 提取**：`re.findall(r'\[\[([^\]]+)\]\]', content)`
- **未找到段落**：回傳空字串，不拋例外

---

## app.py — 新增 API 端點

### GET `/api/coverage/<code>`

回傳個股研究摘要。

```json
{
  "ok": true,
  "code": "2330",
  "name": "台積電",
  "sector": "Semiconductors",
  "business": "...",
  "supply_chain": "...",
  "customers": "...",
  "suppliers": "...",
  "wikilinks": ["CoWoS", "HBM", "先進封裝"]
}
```

無資料時：`{"ok": false, "error": "no coverage data"}`, 404

### GET `/api/coverage/search?q=CoWoS&limit=20`

主題關鍵字搜尋。

```json
{
  "ok": true,
  "keyword": "CoWoS",
  "results": [
    {"code": "2330", "name": "台積電", "sector": "Semiconductors", "matched_links": ["CoWoS"]},
    ...
  ]
}
```

### POST `/api/coverage/sync`

手動觸發 git pull + 重建索引。

```json
{"ok": true, "added": 5, "total": 103, "duration_sec": 2.3}
```

### `/api/analyze/<code>` 修改

在現有回應的 `result` 內加入 `"coverage"` 欄位：

```json
{
  "ok": true,
  "result": {
    "code": "2330",
    "coverage": {
      "business": "...",
      "supply_chain": "...",
      "wikilinks": ["CoWoS", "HBM"]
    }
  }
}
```

無 coverage 資料時 `"coverage": null`，不影響現有行為。

---

## 前端改動（index.html）

### ① 個股分析結果 — 研究摘要折疊區塊

在技術分析卡片下方，若 `result.coverage` 不為 null，顯示：

```
▼ 研究摘要（My-TW-Coverage）          [展開/收合]
  業務概況：大型積體電路製造商...
  供應鏈：晶圓代工（中游）
  主要客戶：[[Apple]] [[NVIDIA]] [[AMD]]
  相關標的：CoWoS · HBM · 先進封裝
```

- 預設收合，點擊展開
- Wikilink 可點擊，觸發主題搜尋

### ② 台股掃描 Tab — 主題搜尋列

在掃描結果上方加一列：

```
[關鍵字輸入框          ] [搜尋主題]
→ 顯示符合的股票卡片（同掃描結果樣式 .scard）
```

搜尋結果卡片顯示：代號、名稱、產業別、匹配 wikilink。

---

## 排程（scheduler.py）

在 `TradingScheduler._loop()` 新增每日 02:00 任務：

```python
if now_time == "02:00":
    coverage_reader.sync()
```

`coverage_reader` 透過 constructor injection 傳入，與其他服務保持一致。

---

## 服務初始化（app.py + run.py）

```python
# app.py — 模組層級建立單例
from trading.coverage import CoverageReader
coverage_reader = CoverageReader()
coverage_reader.reload()   # 啟動時同步建立索引；例外被 try/except 吞掉，不阻斷啟動
```

`data/tw-coverage` 是巢狀 git repo，需加入 `.gitignore`：

```
data/tw-coverage/
```

`TradingScheduler` constructor 新增 `coverage_reader` 參數。

---

## 錯誤處理

| 情境 | 行為 |
|------|------|
| `data/tw-coverage` 目錄不存在 | `reload()` 回傳 0，API 回傳 `coverage: null`，不影響其他功能 |
| git pull 失敗 | `sync()` 回傳 `{"ok": false, "error": "..."}` |
| 報告檔解析失敗 | 記錄 log，該檔跳過，不中斷整體 reload |
| 主題搜尋無結果 | 回傳 `{"ok": true, "results": []}` |

---

## 測試（tests/test_coverage.py）

| 測試案例 | 驗證項目 |
|----------|---------|
| `test_reload_empty_dir` | 目錄不存在時 reload() 回傳 0 |
| `test_reload_parses_files` | 正確解析 mock .md 檔，建立索引 |
| `test_get_overview_found` | 回傳正確的 business / supply_chain / wikilinks |
| `test_get_overview_not_found` | 無此代號時回傳 None |
| `test_search_wikilink_match` | keyword 精確比對 wikilink |
| `test_search_content_match` | keyword 模糊比對內文 |
| `test_search_no_results` | 無結果時回傳空列表 |
| `test_get_sector` | 回傳正確產業別 |

新增約 **15 個**測試案例，合計達 **273 tests**。

---

## 實作順序

1. `git clone` data/tw-coverage
2. `trading/coverage.py` — CoverageReader
3. `tests/test_coverage.py` — 單元測試
4. `app.py` — 服務初始化 + 3 個新端點 + analyze 修改
5. `trading/telegram/scheduler.py` — 每日 sync 任務
6. `index.html` — 研究摘要折疊區塊 + 主題搜尋列
7. 全部測試通過後 commit
