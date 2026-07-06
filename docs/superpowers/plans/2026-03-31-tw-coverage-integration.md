# My-TW-Coverage 整合實作計畫

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 將 My-TW-Coverage 研究資料庫（1,735 家台股）整合進戰情指揮中心，提供個股研究摘要、主題關鍵字搜尋與產業別補全。

**Architecture:** 新增 `trading/coverage.py` 的 `CoverageReader`（In-Memory 索引），在 `app.py` 暴露 3 個新 API 端點，並修改 `/api/analyze` 加入 `coverage` 欄位；前端在掃描 Tab 的每張卡片加入「研究」按鈕（開啟 coverage modal），並在掃描結果上方加入主題搜尋列；排程每日 02:00 執行 `git pull` 自動更新索引。

**Tech Stack:** Python pathlib/re/subprocess, Flask routes, JavaScript fetch + modal, data/tw-coverage（nested git repo）

---

## 檔案異動清單

| 操作 | 路徑 | 說明 |
|------|------|------|
| Create | `trading/coverage.py` | CoverageReader 模組 |
| Create | `tests/test_coverage.py` | 8 個單元測試 |
| Modify | `app.py` | 初始化 coverage_reader，新增 3 端點，修改 analyze |
| Modify | `trading/telegram/scheduler.py` | 新增 coverage_reader 參數 + 02:00 sync |
| Modify | `run.py` | import coverage_reader，傳入 TradingScheduler |
| Modify | `index.html` | 研究按鈕 + coverage modal + 主題搜尋列 |
| Modify | `.gitignore` | 排除 data/tw-coverage/ |

---

## Task 1: Repository Setup

**Files:**
- Modify: `.gitignore`

- [ ] **Step 1: Clone My-TW-Coverage 研究資料庫**

```bash
cd c:/Users/88698/Desktop/Workspace/trading_system
git clone https://github.com/Timeverse/My-TW-Coverage data/tw-coverage
```

Expected output: `Cloning into 'data/tw-coverage'...` followed by success message.

- [ ] **Step 2: 確認目錄結構**

```bash
ls data/tw-coverage/Pilot_Reports/ | head -10
```

Expected: 看到 `Semiconductors/` 等子目錄。

- [ ] **Step 3: 把 data/tw-coverage/ 加入 .gitignore**

讀取現有 `.gitignore` 並在末尾加入：

```
data/tw-coverage/
```

- [ ] **Step 4: 確認 git 不追蹤 tw-coverage**

```bash
git status --short data/tw-coverage
```

Expected: 無輸出（已被 .gitignore 排除）。

- [ ] **Step 5: Commit .gitignore 修改**

```bash
git add .gitignore
git commit -m "chore: 將 data/tw-coverage 加入 .gitignore

巢狀 git repo，不應追蹤進主 repo。

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 2: 寫失敗測試（tests/test_coverage.py）

**Files:**
- Create: `tests/test_coverage.py`

- [ ] **Step 1: 建立測試檔**

建立 `tests/test_coverage.py`，內容如下：

```python
"""tests/test_coverage.py — CoverageReader 單元測試"""
import tempfile
import unittest
from pathlib import Path


def _make_reader(tmp_dir: str):
    from trading.coverage import CoverageReader
    return CoverageReader(base_dir=Path(tmp_dir))


def _write_md(directory: Path, filename: str, content: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / filename).write_text(content, encoding="utf-8")


class TestReload(unittest.TestCase):

    def test_reload_empty_dir(self):
        """目錄不存在時 reload() 回傳 0，不拋例外"""
        from trading.coverage import CoverageReader
        reader = CoverageReader(base_dir=Path("/nonexistent/__test_coverage__"))
        count = reader.reload()
        self.assertEqual(count, 0)
        self.assertEqual(reader.total, 0)

    def test_reload_parses_files(self):
        """正確解析 mock .md 檔，建立索引"""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            _write_md(
                base / "Semiconductors",
                "2330_台積電.md",
                "## 業務概況\n大型IC製造商\n",
            )
            reader = _make_reader(tmp)
            count = reader.reload()
        self.assertEqual(count, 1)
        self.assertEqual(reader.total, 1)

    def test_reload_ignores_non_numeric_prefix(self):
        """檔名不符合 XXXX_公司名.md 格式的檔案應被忽略"""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            _write_md(base / "Semiconductors", "README.md", "# readme\n")
            _write_md(base / "Semiconductors", "2330_台積電.md", "## 業務概況\n測試\n")
            reader = _make_reader(tmp)
            count = reader.reload()
        self.assertEqual(count, 1)


class TestGetOverview(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        md = (
            "## 業務概況\n大型IC製造商，主要生產 3nm 製程晶片。\n"
            "## 供應鏈位置\n晶圓代工（中游）\n"
            "## 主要客戶\n[[Apple]] [[NVIDIA]]\n"
            "## 主要供應商\n[[ASML]]\n"
        )
        _write_md(base / "Semiconductors", "2330_台積電.md", md)
        from trading.coverage import CoverageReader
        self.reader = CoverageReader(base_dir=base)
        self.reader.reload()

    def tearDown(self):
        self._tmp.cleanup()

    def test_get_overview_found(self):
        result = self.reader.get_overview("2330")
        self.assertIsNotNone(result)
        self.assertEqual(result["name"], "台積電")
        self.assertEqual(result["sector"], "Semiconductors")
        self.assertIn("大型IC製造商", result["business"])
        self.assertIn("晶圓代工", result["supply_chain"])
        self.assertIn("Apple", result["wikilinks"])
        self.assertIn("NVIDIA", result["wikilinks"])
        # 去重：ASML 來自供應商段落，應在 wikilinks 中
        self.assertIn("ASML", result["wikilinks"])

    def test_get_overview_not_found(self):
        result = self.reader.get_overview("9999")
        self.assertIsNone(result)


class TestSearch(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        _write_md(
            base / "Semiconductors",
            "2330_台積電.md",
            "## 業務概況\n晶圓代工龍頭。\n## 供應鏈位置\n中游\n[[CoWoS]] [[HBM]]\n",
        )
        _write_md(
            base / "Semiconductors",
            "2454_聯發科.md",
            "## 業務概況\nIC設計龍頭。\n## 供應鏈位置\n上游設計\n[[WiFi7]]\n",
        )
        from trading.coverage import CoverageReader
        self.reader = CoverageReader(base_dir=base)
        self.reader.reload()

    def tearDown(self):
        self._tmp.cleanup()

    def test_search_wikilink_match(self):
        """wikilink 精確比對優先：搜 CoWoS 應只回傳 2330"""
        results = self.reader.search("CoWoS")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["code"], "2330")
        self.assertIn("CoWoS", results[0]["matched_links"])

    def test_search_content_match(self):
        """內文模糊比對：搜 IC設計 應回傳 2454"""
        results = self.reader.search("IC設計")
        codes = [r["code"] for r in results]
        self.assertIn("2454", codes)

    def test_search_no_results(self):
        """無結果時回傳空列表"""
        results = self.reader.search("XXXXXXXXNOTEXIST")
        self.assertEqual(results, [])


class TestGetSector(unittest.TestCase):

    def test_get_sector(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            _write_md(base / "Semiconductors", "2330_台積電.md", "## 業務概況\n測試\n")
            from trading.coverage import CoverageReader
            reader = CoverageReader(base_dir=base)
            reader.reload()
            self.assertEqual(reader.get_sector("2330"), "Semiconductors")
            self.assertEqual(reader.get_sector("9999"), "")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 確認測試目前失敗（模組尚未實作）**

```bash
cd c:/Users/88698/Desktop/Workspace/trading_system
python -m unittest tests/test_coverage.py 2>&1 | head -20
```

Expected output: `ImportError: cannot import name 'CoverageReader' from 'trading.coverage'` 或類似的 `ModuleNotFoundError`。

---

## Task 3: 實作 trading/coverage.py

**Files:**
- Create: `trading/coverage.py`

- [ ] **Step 1: 建立 trading/coverage.py**

```python
"""
trading/coverage.py — My-TW-Coverage 研究資料庫讀取器
"""
import re
import subprocess
import time
from pathlib import Path
from typing import Optional

_DEFAULT_BASE = Path(__file__).parent.parent / "data" / "tw-coverage" / "Pilot_Reports"


class CoverageReader:
    """台股研究報告讀取器（In-Memory 索引）。

    使用方式：
        reader = CoverageReader()
        reader.reload()           # 啟動時建立索引
        ov = reader.get_overview("2330")
        results = reader.search("CoWoS")
    """

    def __init__(self, base_dir: Optional[Path] = None):
        self._base: Path = base_dir if base_dir is not None else _DEFAULT_BASE
        self._index: dict[str, dict] = {}

    # ── 公開方法 ─────────────────────────────────────────────────

    def reload(self) -> int:
        """掃描所有 .md 建立索引，回傳檔案數。目錄不存在時回傳 0。"""
        if not self._base.exists():
            self._index = {}
            return 0
        idx: dict[str, dict] = {}
        for path in self._base.rglob("*.md"):
            m = re.match(r"^(\d{4})_(.+)\.md$", path.name)
            if not m:
                continue
            code = m.group(1)
            name = m.group(2)
            sector = path.parent.name
            idx[code] = {"name": name, "sector": sector, "path": path}
        self._index = idx
        print(f"[CoverageReader] 索引建立完成：{len(idx)} 份報告")
        return len(idx)

    def get_overview(self, code: str) -> Optional[dict]:
        """解析個股報告，回傳摘要字典；無此代號時回傳 None。"""
        entry = self._index.get(code)
        if entry is None:
            return None
        try:
            content = entry["path"].read_text(encoding="utf-8")
        except Exception as e:
            print(f"[CoverageReader] 讀取 {code} 失敗: {e}")
            return None

        def _section(title: str) -> str:
            pattern = rf"##\s+{re.escape(title)}\s*\n(.*?)(?=\n##\s|\Z)"
            m = re.search(pattern, content, re.DOTALL)
            return m.group(1).strip() if m else ""

        wikilinks = list(dict.fromkeys(re.findall(r"\[\[([^\]]+)\]\]", content)))
        return {
            "name":         entry["name"],
            "sector":       entry["sector"],
            "business":     _section("業務概況"),
            "supply_chain": _section("供應鏈位置"),
            "customers":    _section("主要客戶"),
            "suppliers":    _section("主要供應商"),
            "wikilinks":    wikilinks,
        }

    def search(self, keyword: str, limit: int = 20) -> list[dict]:
        """搜尋含 keyword 的報告（wikilink 精確比對優先，內文模糊比對次之）。"""
        results: list[dict] = []
        kw_lower = keyword.lower()
        for code, entry in self._index.items():
            if len(results) >= limit:
                break
            try:
                content = entry["path"].read_text(encoding="utf-8")
            except Exception:
                continue
            links = re.findall(r"\[\[([^\]]+)\]\]", content)
            matched = [lk for lk in links if kw_lower in lk.lower()]
            if matched:
                results.append({
                    "code":          code,
                    "name":          entry["name"],
                    "sector":        entry["sector"],
                    "matched_links": list(dict.fromkeys(matched)),
                })
            elif kw_lower in content.lower():
                results.append({
                    "code":          code,
                    "name":          entry["name"],
                    "sector":        entry["sector"],
                    "matched_links": [],
                })
        return results

    def get_sector(self, code: str) -> str:
        """回傳產業別字串，無資料時回傳空字串。"""
        entry = self._index.get(code)
        return entry["sector"] if entry else ""

    def sync(self) -> dict:
        """執行 git pull，重建索引。回傳統計資訊。"""
        repo_dir = self._base.parent
        start = time.time()
        try:
            subprocess.run(
                ["git", "-C", str(repo_dir), "pull"],
                capture_output=True,
                text=True,
                check=True,
                timeout=60,
            )
        except subprocess.CalledProcessError as e:
            return {"ok": False, "error": e.stderr.strip()}
        except Exception as e:
            return {"ok": False, "error": str(e)}
        old_total = len(self._index)
        new_total = self.reload()
        return {
            "ok":           True,
            "added":        new_total - old_total,
            "total":        new_total,
            "duration_sec": round(time.time() - start, 2),
        }

    @property
    def total(self) -> int:
        """目前索引的報告數。"""
        return len(self._index)
```

- [ ] **Step 2: 執行測試，確認全部通過**

```bash
cd c:/Users/88698/Desktop/Workspace/trading_system
python -m unittest tests/test_coverage.py -v 2>&1 | tail -20
```

Expected: `Ran 8 tests in ...s` + `OK`

- [ ] **Step 3: 執行全部測試，確認無回歸**

```bash
python -m unittest discover tests/ 2>&1 | grep -E "^(Ran|OK|FAIL|ERROR)"
```

Expected: `Ran 266 tests in ...s` + `OK`（258 原有 + 8 新增）

- [ ] **Step 4: Commit**

```bash
git add trading/coverage.py tests/test_coverage.py
git commit -m "feat: 新增 CoverageReader 模組與 8 個單元測試

讀取 data/tw-coverage/Pilot_Reports/**/*.md，提供個股摘要、
主題搜尋與產業別查詢功能。

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 4: 修改 app.py（服務初始化 + 3 端點 + analyze 修改）

**Files:**
- Modify: `app.py`

**在修改前先 `Read app.py`。**

- [ ] **Step 1: 在 app.py 的 import 區加入 CoverageReader**

在 `app.py` 現有 import 區（`from trading.intelligence import IntelligenceDaemon` 之後）加入：

```python
from trading.coverage import CoverageReader
```

- [ ] **Step 2: 在服務單例區加入 coverage_reader 初始化**

在 `intel_daemon = IntelligenceDaemon(...)` 之後（約第 39 行之後）加入：

```python
coverage_reader = CoverageReader()
try:
    coverage_reader.reload()
except Exception as e:
    print(f"[app] coverage_reader 載入失敗（忽略）: {e}")
```

- [ ] **Step 3: 在 analyze_stock route 加入 coverage 欄位**

找到 `analyze_stock` 路由的回傳段（約第 197 行），將：

```python
    return jsonify({"ok": True, "strategy": strategy, "result": {
        "code":     result["code"],
        "name":     result["name"],
        "score":    result["score"],
        "ind":      result["ind"],
        "params":   result["params"],
    }})
```

改為：

```python
    cov = None
    try:
        ov = coverage_reader.get_overview(code.strip())
        if ov:
            cov = {
                "business":     ov["business"],
                "supply_chain": ov["supply_chain"],
                "wikilinks":    ov["wikilinks"],
            }
    except Exception:
        pass
    return jsonify({"ok": True, "strategy": strategy, "result": {
        "code":     result["code"],
        "name":     result["name"],
        "score":    result["score"],
        "ind":      result["ind"],
        "params":   result["params"],
        "coverage": cov,
    }})
```

- [ ] **Step 4: 新增 3 個 coverage API 端點**

在 `analyze_stock` route 之前（或之後，順序不影響 Flask routing），加入以下三個端點。`/api/coverage/search` 必須在 `/api/coverage/<code>` **之前**定義，以確保 "search" 不被當成 `code`：

```python
# ══════════════════════════════════════════════════════════════
#  Coverage API（My-TW-Coverage 研究資料庫）
# ══════════════════════════════════════════════════════════════

@app.route("/api/coverage/search")
def search_coverage():
    keyword = request.args.get("q", "").strip()
    if not keyword:
        return jsonify({"ok": False, "error": "q parameter required"}), 400
    limit = min(int(request.args.get("limit", 20)), 50)
    results = coverage_reader.search(keyword, limit=limit)
    return jsonify({"ok": True, "keyword": keyword, "results": results})


@app.route("/api/coverage/sync", methods=["POST"])
def sync_coverage():
    result = coverage_reader.sync()
    return jsonify(result)


@app.route("/api/coverage/<code>")
def get_coverage(code: str):
    ov = coverage_reader.get_overview(code.strip())
    if ov is None:
        return jsonify({"ok": False, "error": "no coverage data"}), 404
    return jsonify({"ok": True, "code": code.strip(), **ov})
```

- [ ] **Step 5: 執行全部測試，確認無回歸**

```bash
python -m unittest discover tests/ 2>&1 | grep -E "^(Ran|OK|FAIL|ERROR)"
```

Expected: `OK`（同 Task 3 的測試數量，app.py 修改不應觸發測試失敗）

- [ ] **Step 6: Commit**

```bash
git add app.py
git commit -m "feat: 新增 coverage API 端點並在 analyze 加入 coverage 欄位

新增 GET /api/coverage/<code>、GET /api/coverage/search、
POST /api/coverage/sync 三個端點；
/api/analyze/<code> 回應加入 coverage 欄位（無資料時為 null）。

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 5: 修改 scheduler.py（新增 coverage_reader 參數 + 02:00 sync）

**Files:**
- Modify: `trading/telegram/scheduler.py`

**在修改前先 `Read trading/telegram/scheduler.py`。**

- [ ] **Step 1: 在 `__init__` 加入 coverage_reader 選用參數**

將現有 `__init__`：

```python
    def __init__(
        self,
        telegram_bot: "TelegramBot",
        position_manager: PositionManager,
        indicator_engine: IndicatorEngine,
    ):
        self.bot      = telegram_bot
        self.pos_mgr  = position_manager
        self.ind_eng  = indicator_engine
```

改為：

```python
    def __init__(
        self,
        telegram_bot: "TelegramBot",
        position_manager: PositionManager,
        indicator_engine: IndicatorEngine,
        coverage_reader=None,
    ):
        self.bot               = telegram_bot
        self.pos_mgr           = position_manager
        self.ind_eng           = indicator_engine
        self._coverage_reader  = coverage_reader
```

- [ ] **Step 2: 在 `_loop` 加入 02:00 coverage sync 任務**

在 `_loop` 方法的 `try:` 區塊內（`wday <= 4` 判斷式**之後**，`except Exception` **之前**），加入：

```python
                # 4. Coverage sync：每日 02:00（不限交易日）
                if hhmm == "02:00" and "coverage_sync" not in sent_today:
                    if self._coverage_reader is not None:
                        sent_today.add("coverage_sync")
                        print("[TradingScheduler] 執行 coverage sync")
                        threading.Thread(
                            target=self._coverage_reader.sync,
                            daemon=True,
                        ).start()
```

- [ ] **Step 3: 執行全部測試，確認無回歸**

```bash
python -m unittest discover tests/ 2>&1 | grep -E "^(Ran|OK|FAIL|ERROR)"
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add trading/telegram/scheduler.py
git commit -m "feat: scheduler 新增 coverage_reader 參數與每日 02:00 sync 任務

TradingScheduler 接受選用的 coverage_reader 參數，
每日 02:00 自動執行 git pull + 重建索引。

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 6: 修改 run.py（傳入 coverage_reader）

**Files:**
- Modify: `run.py`

**在修改前先 `Read run.py`。**

- [ ] **Step 1: 修改 run.py 的 import 行加入 coverage_reader**

找到第 57 行（`from app import app, config_mgr, ...`），將：

```python
from app import app, config_mgr, pos_mgr, ind_engine, scanner, market_svc, news_agg, intel_daemon  # noqa: E402
```

改為：

```python
from app import app, config_mgr, pos_mgr, ind_engine, scanner, market_svc, news_agg, intel_daemon, coverage_reader  # noqa: E402
```

- [ ] **Step 2: 在 TradingScheduler 建構式加入 coverage_reader**

找到（約第 93 行）：

```python
    scheduler = TradingScheduler(
        telegram_bot     = bot,
        position_manager = pos_mgr,
        indicator_engine = ind_engine,
    )
```

改為：

```python
    scheduler = TradingScheduler(
        telegram_bot     = bot,
        position_manager = pos_mgr,
        indicator_engine = ind_engine,
        coverage_reader  = coverage_reader,
    )
```

- [ ] **Step 3: 執行全部測試，確認無回歸**

```bash
python -m unittest discover tests/ 2>&1 | grep -E "^(Ran|OK|FAIL|ERROR)"
```

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add run.py
git commit -m "feat: run.py 將 coverage_reader 傳入 TradingScheduler

完成 constructor injection，讓排程器可執行每日 sync 任務。

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Task 7: 修改 index.html（研究按鈕 + Coverage Modal + 主題搜尋列）

**Files:**
- Modify: `index.html`

**在修改前先 `Read index.html`。特別閱讀：`renderScan` 函式區段、掃描 Tab HTML 區段（`id="scan-result"` 附近）、現有 modal 結構。**

本 Task 分為三部分：
1. 加入 `#coverage-modal` HTML 與 CSS
2. 加入主題搜尋列 HTML
3. 修改 `renderScan` JS + 加入相關 JS 函式

### Part A — Coverage Modal HTML & CSS

- [ ] **Step 1: 新增 coverage-modal CSS**

在 `<style>` 區段的末尾（現有 `.modal-overlay` 相關 CSS 之後）加入：

```css
/* Coverage Modal */
#coverage-modal .modal-box { max-width:560px;max-height:80vh;overflow-y:auto; }
.cov-section { margin-bottom:14px; }
.cov-section h5 { font-size:12px;color:var(--text3);text-transform:uppercase;letter-spacing:.06em;margin-bottom:4px; }
.cov-section p  { font-size:13px;line-height:1.6;white-space:pre-wrap;color:var(--text1); }
.cov-tags { display:flex;flex-wrap:wrap;gap:6px;margin-top:4px; }
.cov-tag  { background:rgba(88,166,255,.12);border:1px solid rgba(88,166,255,.25);color:var(--accent);
            font-size:11px;padding:2px 8px;border-radius:12px;cursor:pointer; }
.cov-tag:hover { background:rgba(88,166,255,.22); }
.cov-empty { color:var(--text3);font-size:13px;font-style:italic; }
```

- [ ] **Step 2: 新增 coverage-modal HTML**

在 `</body>` 標籤之前（與其他 modal div 並排），加入：

```html
<!-- Coverage Modal -->
<div class="modal-overlay" id="coverage-modal" onclick="if(event.target===this)closeCoverageModal()" style="display:none">
  <div class="modal-box">
    <div class="modal-header">
      <span id="cov-modal-title">研究摘要</span>
      <button class="modal-close" onclick="closeCoverageModal()">✕</button>
    </div>
    <div id="cov-modal-body" style="padding:14px 0;">
      <div class="empty">載入中...</div>
    </div>
  </div>
</div>
```

### Part B — 主題搜尋列 HTML

- [ ] **Step 3: 在掃描 Tab 的 `scan-result` 之前加入主題搜尋列**

找到 `<div id="scan-result">` 這一行（約第 314 行），在其**之前**插入：

```html
<!-- 主題搜尋列 -->
<div style="display:flex;gap:8px;margin-bottom:10px;align-items:center;">
  <input class="form-control form-control-sm" id="scan-topic-q" placeholder="輸入主題關鍵字（如 CoWoS、液冷散熱）" style="max-width:320px"
         onkeydown="if(event.key==='Enter')searchTopic()">
  <button class="btn btn-sm btn-outline-primary" onclick="searchTopic()">搜尋主題</button>
</div>
<div id="scan-topic-result" style="margin-bottom:10px;"></div>
```

### Part C — JavaScript 修改

- [ ] **Step 4: 修改 renderScan，在每張 scard 加入「研究」按鈕**

找到 `renderScan` 函式中每張 scard 的 return 語句（約第 1127 行）：

```javascript
    return `<div class="scard" onclick='quickAdd(${JSON.stringify({code:s.code,name:s.name||'',entry:s.entry,stop:s.stop,target:s.target})})'>
      <div class="scard-hdr">
        <div><div class="sc-code">${s.code} <span style="font-size:11px;font-weight:400;color:var(--text2)">${s.name||''}</span></div><div class="sc-sub">${sub}</div></div>
        <div><div class="sc-score" style="color:${sc(s.score,total)}">${s.score}/${total}</div><div style="font-size:9px;color:var(--text3)">得分</div></div>
      </div>
      <div class="dots">${dots}</div>
      <div class="sc-params">停損 ${s.stop} ｜ 目標 ${s.target} ｜ 建議 ${s.shares} 股</div>
      ${extra}
    </div>`;
```

改為（在 `sc-params` 行之後、`${extra}` 之前插入研究按鈕）：

```javascript
    return `<div class="scard" onclick='quickAdd(${JSON.stringify({code:s.code,name:s.name||'',entry:s.entry,stop:s.stop,target:s.target})})'>
      <div class="scard-hdr">
        <div><div class="sc-code">${s.code} <span style="font-size:11px;font-weight:400;color:var(--text2)">${s.name||''}</span></div><div class="sc-sub">${sub}</div></div>
        <div><div class="sc-score" style="color:${sc(s.score,total)}">${s.score}/${total}</div><div style="font-size:9px;color:var(--text3)">得分</div></div>
      </div>
      <div class="dots">${dots}</div>
      <div class="sc-params">停損 ${s.stop} ｜ 目標 ${s.target} ｜ 建議 ${s.shares} 股</div>
      ${extra}
      <div style="margin-top:6px;text-align:right">
        <button class="btn btn-sm" style="font-size:10px;padding:2px 8px;opacity:.7"
          onclick="event.stopPropagation();showCoverage('${s.code}','${(s.name||'').replace(/'/g,'')}')">研究</button>
      </div>
    </div>`;
```

- [ ] **Step 5: 加入 showCoverage、closeCoverageModal、searchTopic JS 函式**

在 `quickAdd` 函式之後（約第 1140 行之後）加入以下三個函式：

```javascript
// ── Coverage Modal ───────────────────────────────────────────
async function showCoverage(code, name) {
  const modal = document.getElementById('coverage-modal');
  const body  = document.getElementById('cov-modal-body');
  const title = document.getElementById('cov-modal-title');
  title.textContent = `研究摘要 · ${code} ${name}`;
  body.innerHTML = '<div class="empty">載入中...</div>';
  modal.style.display = 'flex';
  try {
    const d = await api('GET', `/api/coverage/${code}`);
    if (!d.ok) { body.innerHTML = `<div class="cov-empty">此股票尚無研究資料</div>`; return; }
    const wikiHtml = d.wikilinks.length
      ? d.wikilinks.map(w => `<span class="cov-tag" onclick="runTopicSearch('${w.replace(/'/g,'')}')">${w}</span>`).join('')
      : '<span class="cov-empty">—</span>';
    body.innerHTML = `
      ${d.business ? `<div class="cov-section"><h5>業務概況</h5><p>${d.business}</p></div>` : ''}
      ${d.supply_chain ? `<div class="cov-section"><h5>供應鏈位置</h5><p>${d.supply_chain}</p></div>` : ''}
      ${d.customers ? `<div class="cov-section"><h5>主要客戶</h5><p>${d.customers}</p></div>` : ''}
      ${d.suppliers ? `<div class="cov-section"><h5>主要供應商</h5><p>${d.suppliers}</p></div>` : ''}
      <div class="cov-section"><h5>相關標的</h5><div class="cov-tags">${wikiHtml}</div></div>
      <div style="font-size:10px;color:var(--text3);margin-top:10px">資料來源：My-TW-Coverage · 產業：${d.sector||'—'}</div>`;
  } catch(e) {
    body.innerHTML = `<div class="cov-empty">載入失敗，請確認伺服器執行中</div>`;
  }
}

function closeCoverageModal() {
  document.getElementById('coverage-modal').style.display = 'none';
}

// ── 主題搜尋 ─────────────────────────────────────────────────
async function searchTopic() {
  const q = document.getElementById('scan-topic-q').value.trim();
  if (!q) return;
  const container = document.getElementById('scan-topic-result');
  container.innerHTML = '<div class="empty">搜尋中...</div>';
  try {
    const d = await api('GET', `/api/coverage/search?q=${encodeURIComponent(q)}&limit=20`);
    if (!d.ok) { container.innerHTML = `<div class="empty" style="color:var(--red)">${d.error}</div>`; return; }
    if (!d.results.length) { container.innerHTML = `<div class="empty">找不到與「${q}」相關的台股</div>`; return; }
    const cards = d.results.map(r => `
      <div class="scard" onclick="showCoverage('${r.code}','${(r.name||'').replace(/'/g,'')}')"
           style="cursor:pointer">
        <div class="scard-hdr">
          <div>
            <div class="sc-code">${r.code} <span style="font-size:11px;font-weight:400;color:var(--text2)">${r.name||''}</span></div>
            <div class="sc-sub">${r.sector||''}</div>
          </div>
        </div>
        ${r.matched_links.length ? `<div class="cov-tags" style="margin-top:4px">${r.matched_links.map(l=>`<span class="cov-tag">${l}</span>`).join('')}</div>` : ''}
      </div>`).join('');
    container.innerHTML = `<div style="font-size:11px;color:var(--text3);margin-bottom:6px">主題「${q}」：${d.results.length} 筆相關台股（點擊查看研究摘要）</div><div class="scan-grid">${cards}</div>`;
  } catch(e) {
    container.innerHTML = `<div class="empty" style="color:var(--red)">搜尋失敗，請確認伺服器執行中</div>`;
  }
}

function runTopicSearch(keyword) {
  closeCoverageModal();
  document.getElementById('scan-topic-q').value = keyword;
  searchTopic();
  // 切換到台股掃描 Tab（若尚未在此 Tab）
  const scanTabBtn = document.querySelector('[data-tab="scan"]');
  if (scanTabBtn) scanTabBtn.click();
}
```

- [ ] **Step 6: 執行全部測試，確認無回歸**

```bash
python -m unittest discover tests/ 2>&1 | grep -E "^(Ran|OK|FAIL|ERROR)"
```

Expected: `OK`

- [ ] **Step 7: 確認前端 DOM id 無衝突**

```bash
grep -n 'id="coverage-modal"\|id="cov-modal-title"\|id="cov-modal-body"\|id="scan-topic-q"\|id="scan-topic-result"' \
  c:/Users/88698/Desktop/Workspace/trading_system/index.html
```

Expected: 每個 id 只出現一次。

- [ ] **Step 8: Commit**

```bash
git add index.html
git commit -m "feat: 掃描卡片加入研究按鈕、coverage modal 與主題搜尋列

每張掃描結果卡片右下角新增「研究」按鈕，點擊開啟 coverage modal
顯示業務概況、供應鏈、主要客客及相關標的（wikilink 可點擊觸發主題搜尋）；
掃描 Tab 上方加入主題搜尋列，輸入關鍵字如 CoWoS 後顯示相關台股卡片。

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## 驗收測試

完成所有 Task 後，執行以下手動驗證：

1. **服務啟動**：`python run.py` → 應看到 `[CoverageReader] 索引建立完成：N 份報告`
2. **coverage API**：`GET /api/coverage/2330` → 應回傳 `{"ok": true, "business": "...", ...}`
3. **搜尋 API**：`GET /api/coverage/search?q=CoWoS` → 應回傳相關台股列表
4. **analyze 含 coverage**：`GET /api/analyze/2330` → `result.coverage` 不為 null
5. **前端研究按鈕**：執行掃描 → 點擊任一卡片的「研究」按鈕 → modal 開啟顯示研究摘要
6. **主題搜尋**：在主題搜尋列輸入 `CoWoS` → 顯示相關台股卡片
7. **無資料降級**：`GET /api/coverage/9999` → `{"ok": false, "error": "no coverage data"}`, 404
8. **全部測試通過**：`python -m unittest discover tests/ 2>&1 | grep -E "^(Ran|OK)"` → `OK`

---

## 自我審查（Spec Coverage）

| Spec 需求 | 對應 Task |
|-----------|-----------|
| A. 個股分析補充（業務+供應鏈）| Task 3 get_overview, Task 4 analyze coverage 欄位, Task 7 coverage modal |
| B. 主題關鍵字搜尋 | Task 3 search(), Task 4 /api/coverage/search, Task 7 主題搜尋列 |
| C. 股票名稱+產業別補全 | Task 3 get_sector(), Task 4 /api/coverage/<code>.sector |
| CoverageReader.reload() | Task 3 |
| CoverageReader.get_overview() | Task 3 |
| CoverageReader.search() | Task 3 |
| CoverageReader.get_sector() | Task 3 |
| CoverageReader.sync() | Task 3 |
| GET /api/coverage/<code> | Task 4 |
| GET /api/coverage/search | Task 4 |
| POST /api/coverage/sync | Task 4 |
| /api/analyze 加 coverage 欄位 | Task 4 |
| 排程每日 02:00 sync | Task 5 |
| run.py 傳入 coverage_reader | Task 6 |
| 掃描 Tab 研究摘要 UI | Task 7 |
| 掃描 Tab 主題搜尋列 | Task 7 |
| data/tw-coverage 加入 .gitignore | Task 1 |
| 錯誤處理：目錄不存在 | Task 3 (reload returns 0) |
| 錯誤處理：無資料 404 | Task 4 |
