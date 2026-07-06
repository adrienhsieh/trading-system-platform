# 合併每日分析 + 新增觀察名單 實作計劃

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 將「每日分析」tab 的技術警示合併進持倉卡片，移除獨立 tab；新增「觀察名單」tab 提供 CRUD + 策略分析 + 新聞。

**Architecture:** 後端在 `positions.py` 新增 watchlist table + CRUD，新建 `trading/api/watchlist.py` Blueprint（4 端點）。前端修改 `renderPositions()` 嵌入技術指標，新增觀察名單 tab + 相關 JS。

**Tech Stack:** Python / Flask / SQLite / yfinance / Google News RSS / HTML+JS

**Spec:** `docs/superpowers/specs/2026-04-14-merge-report-watchlist.md`

---

## 檔案結構

| 檔案 | 動作 | 職責 |
|------|------|------|
| `trading/positions.py` | 修改 | 新增 watchlist table + CRUD 方法 |
| `trading/api/watchlist.py` | 新建 | Flask Blueprint（4 端點） |
| `trading/api/__init__.py` | 修改 | 註冊 watchlist_bp |
| `index.html` | 修改 | 移除 report tab、合併技術指標到持倉卡片、新增觀察名單 tab |
| `tests/test_positions.py` | 修改 | 新增 watchlist CRUD 測試 |

---

## Task 1: watchlist table + CRUD（後端）

**Files:**
- Modify: `trading/positions.py`
- Modify: `tests/test_positions.py`

- [ ] **Step 1: 在 `_init_db()` 新增 watchlist table**

在 `trading/positions.py` 的 `_init_db()` 方法中，在 `CREATE TABLE IF NOT EXISTS positions (...)` 之後新增：

```python
        con.execute("""
            CREATE TABLE IF NOT EXISTS watchlist (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                code     TEXT    NOT NULL UNIQUE,
                name     TEXT    NOT NULL DEFAULT '',
                added_at TEXT    NOT NULL
            )
        """)
```

- [ ] **Step 2: 新增 3 個 watchlist 方法**

在 `PositionManager` class 末尾（`risk_summary` 之後）新增：

```python
    # ── Watchlist ────────────────────────────────────────────

    def watchlist_add(self, code: str, name: str = "") -> bool:
        """新增觀察股票。重複 code 回傳 False。"""
        try:
            with self._conn() as con:
                con.execute(
                    "INSERT INTO watchlist (code, name, added_at) VALUES (?, ?, ?)",
                    (code, name, datetime.date.today().isoformat()),
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def watchlist_remove(self, code: str) -> bool:
        """移除觀察股票。不存在回傳 False。"""
        with self._conn() as con:
            cur = con.execute("DELETE FROM watchlist WHERE code = ?", (code,))
            return cur.rowcount > 0

    def watchlist_list(self) -> list:
        """回傳所有觀察股票 [{id, code, name, added_at}]。"""
        with self._conn() as con:
            rows = con.execute(
                "SELECT id, code, name, added_at FROM watchlist ORDER BY added_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]
```

確保檔案頂部有 `import datetime`（若尚未匯入）。

- [ ] **Step 3: 寫 watchlist 測試**

在 `tests/test_positions.py` 末尾（`if __name__` 之前）新增：

```python
class TestWatchlist(unittest.TestCase):
    """Watchlist CRUD 測試。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        db_file = Path(self.tmp.name) / "test.db"
        self.mgr = PositionManager(db_file=db_file)

    def tearDown(self):
        self.tmp.cleanup()

    def test_add_returns_true(self):
        self.assertTrue(self.mgr.watchlist_add("2330", "台積電"))

    def test_add_duplicate_returns_false(self):
        self.mgr.watchlist_add("2330", "台積電")
        self.assertFalse(self.mgr.watchlist_add("2330", "台積電"))

    def test_list_empty(self):
        self.assertEqual(len(self.mgr.watchlist_list()), 0)

    def test_list_after_add(self):
        self.mgr.watchlist_add("2330", "台積電")
        self.mgr.watchlist_add("2317", "鴻海")
        items = self.mgr.watchlist_list()
        self.assertEqual(len(items), 2)
        codes = [i["code"] for i in items]
        self.assertIn("2330", codes)
        self.assertIn("2317", codes)

    def test_list_has_correct_keys(self):
        self.mgr.watchlist_add("2330", "台積電")
        item = self.mgr.watchlist_list()[0]
        for key in ("id", "code", "name", "added_at"):
            self.assertIn(key, item)

    def test_remove_existing(self):
        self.mgr.watchlist_add("2330", "台積電")
        self.assertTrue(self.mgr.watchlist_remove("2330"))
        self.assertEqual(len(self.mgr.watchlist_list()), 0)

    def test_remove_nonexistent(self):
        self.assertFalse(self.mgr.watchlist_remove("9999"))

    def test_add_with_empty_name(self):
        self.assertTrue(self.mgr.watchlist_add("2330"))
        item = self.mgr.watchlist_list()[0]
        self.assertEqual(item["name"], "")
```

- [ ] **Step 4: 跑測試**

```bash
.venv/Scripts/python.exe -m unittest tests/test_positions.py -v 2>&1 | tail -15
```

Expected: 原 22 + 新 8 = 30 tests, all PASS

- [ ] **Step 5: 跑全部測試確認無 regression**

```bash
.venv/Scripts/python.exe -m unittest discover tests/ 2>&1 | tail -5
```

Expected: 417+ tests OK

- [ ] **Step 6: Commit**

```bash
git add trading/positions.py tests/test_positions.py
git commit -m "feat: watchlist table + CRUD 方法

positions.db 新增 watchlist table，PositionManager 新增
watchlist_add / watchlist_remove / watchlist_list。8 個測試通過。"
```

---

## Task 2: watchlist Flask API Blueprint

**Files:**
- Create: `trading/api/watchlist.py`
- Modify: `trading/api/__init__.py`

- [ ] **Step 1: 建立 `trading/api/watchlist.py`**

```python
"""trading/api/watchlist.py — 觀察名單 API"""
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from defusedxml.ElementTree import fromstring
from flask import Blueprint, jsonify, request

from trading.api.auth import require_auth
from trading.services.container import container

watchlist_bp = Blueprint("watchlist", __name__)


@watchlist_bp.route("/api/watchlist")
@require_auth
def list_watchlist():
    items = container.pos_mgr.watchlist_list()
    return jsonify({"ok": True, "items": items})


@watchlist_bp.route("/api/watchlist", methods=["POST"])
@require_auth
def add_watchlist():
    data = request.get_json(silent=True) or {}
    code = str(data.get("code", "")).strip()
    if not code:
        return jsonify({"ok": False, "error": "缺少 code"}), 400
    name = container.scanner.get_stock_name(code)
    ok = container.pos_mgr.watchlist_add(code, name)
    if not ok:
        return jsonify({"ok": False, "error": f"{code} 已在觀察名單中"}), 409
    return jsonify({"ok": True, "code": code, "name": name})


@watchlist_bp.route("/api/watchlist/<code>", methods=["DELETE"])
@require_auth
def remove_watchlist(code: str):
    ok = container.pos_mgr.watchlist_remove(code)
    if not ok:
        return jsonify({"ok": False, "error": f"{code} 不在觀察名單中"}), 404
    return jsonify({"ok": True})


@watchlist_bp.route("/api/watchlist/analyze")
@require_auth
def analyze_watchlist():
    items = container.pos_mgr.watchlist_list()
    if not items:
        return jsonify({"ok": True, "results": []})

    cfg = container.config_mgr.load()
    capital = cfg.get("total_capital", 3000000)
    risk_pct = 1.0 if cfg.get("consecutive_losses", 0) >= 3 else 2.0

    results = []
    for item in items:
        code, name = item["code"], item["name"]
        result = {"code": code, "name": name}

        # 趨勢策略
        trend = container.scanner.analyze_one(code, capital, risk_pct, strategy="trend")
        if trend:
            fmt = container.scanner.format_for_api([trend], strategy="trend")
            if fmt:
                sigs = fmt[0].get("signals", {})
                passed = sum(1 for s in sigs.values() if s.get("pass"))
                result["trend"] = {"score": passed, "total": len(sigs), "signals": sigs}
        if "trend" not in result:
            result["trend"] = None

        # 基本面策略
        fund = container.scanner.analyze_one(code, capital, risk_pct, strategy="fundamental")
        if fund:
            fmt = container.scanner.format_for_api([fund], strategy="fundamental")
            if fmt:
                sigs = fmt[0].get("signals", {})
                passed = sum(1 for s in sigs.values() if s.get("pass"))
                result["fundamental"] = {"score": passed, "total": len(sigs), "signals": sigs}
        if "fundamental" not in result:
            result["fundamental"] = None

        # 財報狗連結
        result["report_url"] = f"https://statementdog.com/analysis/{code}"

        # Google News 最近 3 筆
        result["news"] = _fetch_google_news(name or code, limit=3)

        results.append(result)
        time.sleep(0.3)

    return jsonify({"ok": True, "results": results})


def _fetch_google_news(query: str, limit: int = 3) -> list:
    """從 Google News RSS 搜尋相關新聞。"""
    url = f"https://news.google.com/rss/search?q={requests.utils.quote(query)}+股票&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
    try:
        resp = requests.get(url, timeout=10)
        if not resp.ok:
            return []
        root = fromstring(resp.content)
        items = []
        for item in root.iter("item"):
            title = item.findtext("title", "")
            link = item.findtext("link", "")
            pub = item.findtext("pubDate", "")
            # pubDate 格式: "Mon, 14 Apr 2026 08:00:00 GMT"
            date_str = ""
            if pub:
                parts = pub.split()
                if len(parts) >= 4:
                    day, mon, year = parts[1], parts[2], parts[3]
                    months = {"Jan":"01","Feb":"02","Mar":"03","Apr":"04","May":"05","Jun":"06",
                              "Jul":"07","Aug":"08","Sep":"09","Oct":"10","Nov":"11","Dec":"12"}
                    date_str = f"{year}-{months.get(mon,'01')}-{day.zfill(2)}"
            items.append({"title": title, "url": link, "date": date_str})
            if len(items) >= limit:
                break
        return items
    except Exception:
        return []
```

- [ ] **Step 2: 在 `trading/api/__init__.py` 註冊 blueprint**

在 import 區塊末尾加入：
```python
from trading.api.watchlist    import watchlist_bp
```

在 `register_blueprints()` 末尾加入：
```python
    app.register_blueprint(watchlist_bp)
```

- [ ] **Step 3: 跑全部測試**

```bash
.venv/Scripts/python.exe -m unittest discover tests/ 2>&1 | tail -5
```

Expected: all PASS

- [ ] **Step 4: Commit**

```bash
git add trading/api/watchlist.py trading/api/__init__.py
git commit -m "feat: watchlist Flask API — 4 端點

GET/POST /api/watchlist（列表/新增）
DELETE /api/watchlist/<code>（刪除）
GET /api/watchlist/analyze（趨勢+基本面+新聞分析）"
```

---

## Task 3: 合併每日分析到持倉卡片（前端）

**Files:**
- Modify: `index.html`

- [ ] **Step 1: 移除 report tab 按鈕**

找到 `<div class="tab" data-tab="report">📋 每日分析</div>` 並刪除整行。

- [ ] **Step 2: 移除 report panel HTML**

找到 `<div class="panel" id="tab-report">` 到其結束 `</div>`（含 report-summary 和 report-list），整段刪除。

- [ ] **Step 3: 移除 tab handler 中的 report 觸發**

找到 `if(tab.dataset.tab==='report') loadReport();` 並刪除。

- [ ] **Step 4: 修改 `loadPositions()` — 同時取得 report 資料**

將現有 `loadPositions()` 替換為：

```javascript
async function loadPositions(){
  const [d, rpt] = await Promise.all([
    api('GET','/api/positions'),
    api('GET','/api/report').catch(()=>({analyses:[]})),
  ]);
  positions = d.positions||[];
  _reportMap = {};
  (rpt.analyses||[]).forEach(a => { if(a.code) _reportMap[a.code] = a; });
  renderPositions();
  renderRisk(d.summary, d.config);
  loadPrices();
}
```

在 `loadPositions` 之前新增全域變數：
```javascript
let _reportMap = {};
```

- [ ] **Step 5: 修改 `renderPositions()` — 在每張卡片中嵌入技術指標**

在持倉卡片的 `${prog}` 那行之後、`${p.note?...}` 之前，插入技術指標行：

```javascript
    const rpt = _reportMap[p.code];
    const techRow = rpt ? `<div class="ptech">
      <span>${rpt.ema20 ? `EMA20: ${rpt.ema20}` : ''} ${rpt.below_ema20 ? '<span class="r">▼ 跌破</span>' : '<span class="g">▲ 站上</span>'}</span>
      ${rpt.pct_to_target != null ? `<span>目標距: ${rpt.pct_to_target > 0 ? '+' : ''}${rpt.pct_to_target}%</span>` : ''}
      ${(rpt.alerts||[]).map(a => `<span class="r" style="font-size:10px">${esc(a)}</span>`).join('')}
    </div>` : '';
```

然後在卡片 HTML 中插入 `${techRow}`。

- [ ] **Step 6: 新增 `.ptech` CSS**

在 `.pcard` 相關 CSS 之後新增：

```css
.ptech { display:flex;flex-wrap:wrap;gap:8px;padding:6px 0 0;border-top:1px solid var(--bs-border-color);font-size:10px;font-family:var(--mono);color:var(--bs-secondary-color); }
```

- [ ] **Step 7: 移除 `loadReport()` 和 `renderReport()` 函式**

找到並刪除這兩個函式及相關的 `.rcard` / `.ema20-row` / `.alert-item` CSS。

- [ ] **Step 8: 在瀏覽器驗證 — 持倉卡片有技術指標行，report tab 已消失**

- [ ] **Step 9: Commit**

```bash
git add index.html
git commit -m "refactor: 合併每日分析到持倉卡片

移除獨立的 report tab，技術警示（EMA20/停損距/目標距）
直接嵌入每張持倉卡片底部。"
```

---

## Task 4: 觀察名單 Tab（前端）

**Files:**
- Modify: `index.html`

- [ ] **Step 1: 新增 tab 按鈕（第二個位置）**

在 `<div class="tab active" data-tab="holdings">📊 持股戰情</div>` 之後加入：

```html
                <div class="tab" data-tab="watchlist">📋 觀察名單</div>
```

- [ ] **Step 2: 新增 panel HTML**

在 `</div><!-- /tab-holdings 附近 -->` 之後，下一個 panel 之前，加入：

```html
              <!-- 觀察名單 -->
              <div class="panel" id="tab-watchlist">
                <div class="sec-hdr">
                  <div class="sec-title-mono">觀察名單 <em id="wl-count">0</em> 檔</div>
                  <div style="display:flex;gap:6px">
                    <button class="btn-xs" id="wl-refresh-btn" onclick="loadWatchlistAnalysis()" title="重新分析">↻ 分析</button>
                    <button class="btn btn-sm btn-success" onclick="openWlAddModal()">+ 新增</button>
                  </div>
                </div>
                <div id="wl-list">
                  <div class="empty"><div class="empty-icon">👀</div>尚無觀察股票，點擊「+ 新增」開始追蹤</div>
                </div>
              </div>
```

- [ ] **Step 3: 新增觀察名單 Modal**

在頁面底部的 modal 區域（其他 modal 附近）加入：

```html
<div class="overlay" id="wl-add-modal" onclick="if(event.target===this)closeModal('wl-add-modal')">
  <div class="modal-box" style="max-width:360px">
    <div class="modal-hdr">+ 新增觀察股票</div>
    <div style="padding:12px 16px">
      <label class="form-label">股票代號</label>
      <input class="form-control form-control-sm" id="wl-code" placeholder="例：2330" maxlength="6"
        onkeydown="if(event.key==='Enter')saveWlAdd()">
    </div>
    <div class="modal-btns">
      <button class="btn btn-sm btn-outline-secondary" onclick="closeModal('wl-add-modal')">取消</button>
      <button class="btn btn-sm btn-success" onclick="saveWlAdd()">✓ 新增</button>
    </div>
  </div>
</div>
```

- [ ] **Step 4: 新增觀察名單 CSS**

```css
.wcard { background:var(--bs-tertiary-bg);border:1px solid var(--bs-border-color);border-radius:6px;padding:10px 12px;margin-bottom:8px; }
.wcard-hdr { display:flex;justify-content:space-between;align-items:center;margin-bottom:8px; }
.wcard-signals { display:flex;flex-wrap:wrap;gap:4px;margin-bottom:6px; }
.wcard-news { font-size:11px;line-height:1.7; }
.wcard-news a { color:var(--accent);text-decoration:none; }
.wcard-news a:hover { text-decoration:underline; }
.wcard-news-date { color:var(--bs-tertiary-color);font-family:var(--mono);font-size:10px;margin-left:6px; }
```

- [ ] **Step 5: 新增觀察名單 JS**

在 tab handler 中新增：
```javascript
    if(tab.dataset.tab==='watchlist') loadWatchlist();
```

新增以下函式：

```javascript
// ── Watchlist ───────────────────────────────────────────────
let _wlAnalysisCache = null;
let _wlAnalysisDate = '';

function openWlAddModal() {
  document.getElementById('wl-code').value = '';
  document.getElementById('wl-add-modal').classList.add('open');
  document.getElementById('wl-code').focus();
}

async function saveWlAdd() {
  const code = document.getElementById('wl-code').value.trim();
  if (!code) return;
  try {
    const r = await api('POST', '/api/watchlist', { code });
    if (!r.ok) { toast(r.error || '新增失敗', 'err'); return; }
    closeModal('wl-add-modal');
    toast(`✓ 已新增 ${r.code} ${r.name}`, 'ok');
    _wlAnalysisCache = null;
    loadWatchlist();
  } catch (e) { toast('新增失敗', 'err'); }
}

async function removeWl(code) {
  try {
    const r = await api('DELETE', `/api/watchlist/${code}`);
    if (r.ok) { toast(`已移除 ${code}`, 'ok'); _wlAnalysisCache = null; loadWatchlist(); }
  } catch (e) { toast('移除失敗', 'err'); }
}

async function loadWatchlist() {
  const el = document.getElementById('wl-list');
  el.innerHTML = '<div class="loader"><div class="spinner"></div>載入觀察名單...</div>';
  try {
    const r = await api('GET', '/api/watchlist');
    const items = r.items || [];
    document.getElementById('wl-count').textContent = items.length;
    if (!items.length) {
      el.innerHTML = '<div class="empty"><div class="empty-icon">👀</div>尚無觀察股票，點擊「+ 新增」開始追蹤</div>';
      return;
    }
    // 先渲染基本清單
    el.innerHTML = items.map(i => `<div class="wcard" id="wl-${i.code}">
      <div class="wcard-hdr">
        <span><span class="stkcode">${esc(i.code)}</span> <b>${esc(i.name)}</b></span>
        <button class="btn-xs danger" onclick="removeWl('${i.code}')">✕</button>
      </div>
      <div class="wcard-body" style="color:var(--bs-secondary-color);font-size:11px">載入分析中...</div>
    </div>`).join('');
    // 自動分析
    loadWatchlistAnalysis();
  } catch (e) {
    el.innerHTML = '<div class="empty" style="color:var(--red)">載入失敗</div>';
  }
}

async function loadWatchlistAnalysis() {
  const today = new Date().toISOString().slice(0, 10);
  if (_wlAnalysisCache && _wlAnalysisDate === today) {
    renderWatchlistAnalysis(_wlAnalysisCache);
    return;
  }
  const btn = document.getElementById('wl-refresh-btn');
  if (btn) { btn.disabled = true; btn.textContent = '分析中...'; }
  try {
    const r = await api('GET', '/api/watchlist/analyze');
    _wlAnalysisCache = r.results || [];
    _wlAnalysisDate = today;
    renderWatchlistAnalysis(_wlAnalysisCache);
  } catch (e) {
    // 分析失敗不影響清單顯示
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = '↻ 分析'; }
  }
}

function renderWatchlistAnalysis(results) {
  results.forEach(r => {
    const el = document.querySelector(`#wl-${r.code} .wcard-body`);
    if (!el) return;

    let html = '';

    // 趨勢策略
    if (r.trend) {
      const sigs = Object.values(r.trend.signals || {});
      html += `<div style="margin-bottom:6px"><b>🛡️ 趨勢 ${r.trend.score}/${r.trend.total}</b></div>`;
      html += `<div class="wcard-signals">${sigs.map(s =>
        `<span class="sig ${s.pass ? 'pass' : 'fail'}">${s.pass ? '✓' : '✗'} ${esc(s.label)}</span>`
      ).join('')}</div>`;
    }

    // 基本面策略
    if (r.fundamental) {
      const sigs = Object.values(r.fundamental.signals || {});
      html += `<div style="margin-bottom:6px"><b>📊 基本面 ${r.fundamental.score}/${r.fundamental.total}</b></div>`;
      html += `<div class="wcard-signals">${sigs.map(s =>
        `<span class="sig ${s.pass ? 'pass' : 'fail'}">${s.pass ? '✓' : '✗'} ${esc(s.label)}</span>`
      ).join('')}</div>`;
    }

    if (!r.trend && !r.fundamental) {
      html += '<div style="color:var(--bs-tertiary-color)">分析資料不足</div>';
    }

    // 財報狗 + 新聞
    html += `<div style="margin-top:8px;display:flex;gap:12px;font-size:11px">`;
    html += `<a href="${r.report_url}" target="_blank" style="color:var(--accent)">📊 財報狗</a>`;
    html += `</div>`;

    if (r.news && r.news.length) {
      html += `<div class="wcard-news" style="margin-top:6px">`;
      r.news.forEach(n => {
        html += `<div>· <a href="${esc(n.url)}" target="_blank">${esc(n.title)}</a><span class="wcard-news-date">${esc(n.date)}</span></div>`;
      });
      html += `</div>`;
    }

    el.innerHTML = html;
  });
}
```

- [ ] **Step 6: 在瀏覽器驗證**

```
□ 觀察名單 tab 出現（第二個位置）
□ 點「+ 新增」→ modal → 輸入 2330 → 新增成功
□ 卡片顯示趨勢策略分數 + 信號清單
□ 卡片顯示基本面策略分數 + 信號清單
□ 財報狗連結可點擊、開新分頁
□ 最近 3 筆新聞有標題 + 日期 + 連結
□ 點 ✕ 可刪除觀察股票
□ 切到其他 tab 再切回來，不重跑分析（快取）
```

- [ ] **Step 7: Commit**

```bash
git add index.html
git commit -m "feat: 觀察名單 Tab — 策略分析 + 財報狗 + 新聞

新增觀察名單 tab（第二個位置），支援新增/刪除股票、
趨勢+基本面策略滿足狀態、財報狗連結、Google News 3 筆新聞。"
```

---

## Task 5: 全部測試 + 最終推送

- [ ] **Step 1: 跑全部測試**

```bash
.venv/Scripts/python.exe -m unittest discover tests/ 2>&1 | tail -5
```

Expected: 425+ tests OK

- [ ] **Step 2: Push**

```bash
git push
```

---

## Spec 覆蓋對照

| Spec 區塊 | Task |
|-----------|------|
| 3-1 持倉卡片新增技術指標 | Task 3 |
| 3-2 移除 report tab | Task 3 |
| 3-3 保留 /api/report | 不改動 |
| 4-1 watchlist SQLite schema | Task 1 |
| 4-2 PositionManager CRUD | Task 1 |
| 4-3 Flask API 4 端點 | Task 2 |
| 4-4 /api/watchlist/analyze 結構 | Task 2 |
| 4-5 前端 UI | Task 4 |
