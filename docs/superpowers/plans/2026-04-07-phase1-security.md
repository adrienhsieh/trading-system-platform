# Phase 1：資安強化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 為公開部署的 trading_system 加上 API 認證、Rate Limiting、XSS 修復、Telegram fail-closed、安全 Headers、XXE 防護，讓 30+ Flask endpoint 不再裸奔。

**Architecture:** 在 `app.py` 加入 `@require_auth` decorator（讀取 `config.json` 中的 `api_key`），搭配 Flask-Limiter 限制端點呼叫頻率；前端修復 `esc()` 函數並將危險的 `innerHTML` 改為安全寫法；後端加入安全 HTTP headers；RSS 解析換用 defusedxml。

**Tech Stack:** Flask, Flask-Limiter, defusedxml, Python secrets module

---

## 檔案異動清單

| 動作 | 檔案 | 說明 |
|------|------|------|
| Modify | `trading/config.py` | DEFAULTS 加 `api_key`；`load()` 首次自動產生 key；`save()` 加 write lock |
| Modify | `app.py` | 加 `require_auth` decorator；套用至所有 `/api/*`；加 after_request security headers；限縮 CORS origin |
| Modify | `requirements.txt` | 加 `Flask-Limiter>=3.5.0`、`defusedxml>=0.7.1` |
| Modify | `trading/news.py` | `ET.fromstring` → `defusedxml.ElementTree.fromstring` |
| Modify | `trading/telegram/bot.py` | `is_allowed()` 改為 fail-closed |
| Modify | `index.html` | 修復 `esc()`；line 1149 `report-summary innerHTML` → 安全寫法 |
| Modify | `tests/test_config.py` | 補 api_key 自動產生與持久化測試 |
| Modify | `tests/test_news.py` | 補 defusedxml 路徑測試 |

---

## Task 1：ConfigManager 加入 api_key 自動產生

**Files:**
- Modify: `trading/config.py`
- Modify: `tests/test_config.py`

- [ ] **Step 1: 寫失敗測試**

在 `tests/test_config.py` 的最後加入：

```python
def test_api_key_auto_generated_on_first_load(self):
    """首次 load() 時若無 api_key，應自動產生並持久化。"""
    cfg1 = self.mgr.load()
    self.assertIn("api_key", cfg1)
    self.assertIsInstance(cfg1["api_key"], str)
    self.assertGreater(len(cfg1["api_key"]), 20)

def test_api_key_stable_across_loads(self):
    """重複 load() 應回傳相同的 api_key。"""
    cfg1 = self.mgr.load()
    cfg2 = self.mgr.load()
    self.assertEqual(cfg1["api_key"], cfg2["api_key"])
```

- [ ] **Step 2: 跑測試確認失敗**

```bash
cd "c:/Users/88698/Desktop/Workspace/trading_system"
python -m unittest tests.test_config.TestConfigManager.test_api_key_auto_generated_on_first_load -v
```

預期：`FAIL` — KeyError 或 AssertionError（`api_key` 不存在）

- [ ] **Step 3: 實作 api_key 自動產生**

修改 `trading/config.py`，在頂部加 `import secrets`，並修改 `load()` 方法：

```python
import json
import secrets
import threading
from pathlib import Path


_write_lock = threading.Lock()


def _deep_merge(base: dict, override: dict) -> dict:
    """遞迴合併兩個 dict，override 的值覆蓋 base，巢狀 dict 保留 base 的預設值。"""
    result = dict(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


class ConfigManager:
    """管理 config.json 的讀寫與預設值。"""

    DEFAULTS: dict = {
        "total_capital":      3_000_000,
        "consecutive_losses": 0,
        "risk_mode":          "normal",
        "scan_candidates":    [],
        "api_key":            "",           # ← 新增：空字串表示待產生
        "strategy_params": {
            "trend": {
                "ema_arrangement": {"enabled": True},
                "slopes_up":       {"enabled": True},
                "adx_above_25":    {"enabled": True, "threshold": 25},
                "macd_positive":   {"enabled": True},
                "volume_spike":    {"enabled": True, "threshold": 1.5},
                "ema_crossover":   {"enabled": True},
            },
            "ict": {
                "bullish_ob":      {"enabled": True},
                "fvg_present":     {"enabled": True},
                "bos":             {"enabled": True},
                "liquidity_sweep": {"enabled": True},
                "discount_zone":   {"enabled": True},
                "ote_zone":        {"enabled": True, "fib_low": 0.618, "fib_high": 0.786},
                "mss":             {"enabled": True},
            },
            "fundamental": {
                "pe_reasonable":   {"enabled": True, "threshold": 30},
                "eps_positive":    {"enabled": True},
                "eps_growth":      {"enabled": True},
                "pb_reasonable":   {"enabled": True, "threshold": 2.5},
                "revenue_growth":  {"enabled": True},
            },
        },
    }

    def __init__(self, config_file: Path = None):
        self.config_file = config_file or Path(__file__).parent.parent / "config.json"

    # ── 公開介面 ───────────────────────────────────────────────

    def load(self) -> dict:
        """讀取設定，缺少的 key 補上預設值。首次執行時自動產生 api_key。"""
        cfg = _deep_merge({}, self.DEFAULTS)
        if self.config_file.exists():
            with open(self.config_file, encoding="utf-8") as f:
                cfg = _deep_merge(cfg, json.load(f))
        # 自動同步 risk_mode
        cfg["risk_mode"] = "slowdown" if cfg.get("consecutive_losses", 0) >= 3 else "normal"
        # 首次啟動自動產生 api_key
        if not cfg.get("api_key"):
            cfg["api_key"] = secrets.token_hex(32)
            self.save(cfg)
            print(f"\n{'='*60}")
            print(f"[Config] 首次啟動：已自動產生 API Key")
            print(f"[Config] API Key: {cfg['api_key']}")
            print(f"[Config] 請在前端設定頁面或 .env 中設定此 Key")
            print(f"{'='*60}\n")
        return cfg

    def save(self, cfg: dict) -> None:
        """寫回 config.json（thread-safe）。"""
        with _write_lock:
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)

    def update(self, data: dict) -> dict:
        """部分更新設定並存檔，回傳更新後的設定。"""
        cfg = self.load()
        for k in ("total_capital", "consecutive_losses", "scan_candidates", "strategy_params"):
            if k in data:
                cfg[k] = data[k]
        cfg["risk_mode"] = "slowdown" if cfg["consecutive_losses"] >= 3 else "normal"
        self.save(cfg)
        return cfg

    # ── 常用屬性 ───────────────────────────────────────────────

    @property
    def risk_pct(self) -> float:
        cfg = self.load()
        return 1.0 if cfg.get("consecutive_losses", 0) >= 3 else 2.0

    @property
    def total_capital(self) -> float:
        return float(self.load().get("total_capital", self.DEFAULTS["total_capital"]))

    @property
    def scan_candidates(self) -> list:
        return self.load().get("scan_candidates", [])
```

- [ ] **Step 4: 跑測試確認通過**

```bash
python -m unittest tests.test_config -v
```

預期：所有 test_config 測試通過（含兩個新測試）

- [ ] **Step 5: Commit**

```bash
git add trading/config.py tests/test_config.py
git commit -m "feat: add api_key auto-generation to ConfigManager with thread-safe save"
```

---

## Task 2：app.py 加入 require_auth decorator

**Files:**
- Modify: `app.py`

- [ ] **Step 1: 寫失敗測試**

建立 `tests/test_auth.py`：

```python
"""tests/test_auth.py — 測試 API 認證 decorator"""
import unittest
import json
from unittest.mock import patch, MagicMock
from pathlib import Path
import tempfile
import os


class TestRequireAuth(unittest.TestCase):
    def setUp(self):
        # 建立暫存 config.json，含已知 api_key
        self.tmpdir = tempfile.mkdtemp()
        self.config_path = Path(self.tmpdir) / "config.json"
        self.test_key = "test_api_key_abc123"
        with open(self.config_path, "w") as f:
            json.dump({"api_key": self.test_key}, f)

        # 透過 env var 讓 app 使用此暫存設定
        os.environ["TRADING_CONFIG_PATH"] = str(self.config_path)
        import importlib
        import app as app_module
        importlib.reload(app_module)
        self.app = app_module.app
        self.client = self.app.test_client()

    def tearDown(self):
        import os
        if "TRADING_CONFIG_PATH" in os.environ:
            del os.environ["TRADING_CONFIG_PATH"]

    def test_request_without_key_returns_401(self):
        r = self.client.get("/api/positions")
        self.assertEqual(r.status_code, 401)
        data = json.loads(r.data)
        self.assertFalse(data["ok"])

    def test_request_with_wrong_key_returns_401(self):
        r = self.client.get("/api/positions",
                            headers={"X-API-Key": "wrong_key"})
        self.assertEqual(r.status_code, 401)

    def test_request_with_correct_key_passes_auth(self):
        r = self.client.get("/api/positions",
                            headers={"X-API-Key": self.test_key})
        # 通過認證（可能 200 或其他業務錯誤，但不是 401）
        self.assertNotEqual(r.status_code, 401)

    def test_index_page_no_auth_required(self):
        r = self.client.get("/")
        self.assertNotEqual(r.status_code, 401)
```

- [ ] **Step 2: 跑測試確認失敗**

```bash
python -m unittest tests.test_auth -v
```

預期：`FAIL` — 目前所有 API 請求都回傳 200（無認證）

- [ ] **Step 3: 實作 require_auth decorator**

在 `app.py` 的 `import` 區段後、服務實例建立前（第 28 行附近），加入以下程式碼：

```python
import functools
from flask import Flask, Response, jsonify, request, send_from_directory, stream_with_context
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
```

並在 `BASE_DIR = Path(__file__).parent` 之後、服務實例之前加入：

```python
# ── 認證輔助 ───────────────────────────────────────────────────

def _get_api_key() -> str:
    """從 config.json 讀取 api_key（每次請求讀取以支援熱更新）。"""
    try:
        cfg_path = Path(os.environ.get("TRADING_CONFIG_PATH", "")) or (BASE_DIR / "config.json")
        if cfg_path.exists():
            with open(cfg_path, encoding="utf-8") as f:
                return json.load(f).get("api_key", "")
    except Exception:
        pass
    return ""


def require_auth(f):
    """裝飾器：驗證 X-API-Key header。"""
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        key = request.headers.get("X-API-Key") or request.args.get("key", "")
        expected = _get_api_key()
        if not expected or key != expected:
            return jsonify({"ok": False, "error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated
```

- [ ] **Step 4: 套用 @require_auth 至所有 `/api/*` route**

在 `app.py` 中，找到每一個 `/api/` route（保留 `GET /` index 不加），在 `@app.route(...)` 下一行加上 `@require_auth`。

共需套用的 route（每個都加）：
- `stock_info`, `get_positions`, `create_position`, `update_position`, `delete_position`
- `get_prices`, `get_config`, `update_config`, `get_strategy_params`, `update_strategy_params`
- `analyze_stock`, `scan_candidates`, `scan_full_stream`
- `daily_report`, `get_news`, `get_market`
- `backtest`, `backtest_full_stream`, `optimize_params`
- `get_ohlcv`, `get_intelligence_news`, `get_intelligence_summary`, `generate_summary`, `get_x_posts`
- `get_ohlcv_stats`, `update_ohlcv_cache`

範例（每個 route 都這樣加）：
```python
@app.route("/api/positions", methods=["GET"])
@require_auth
def get_positions():
    ...
```

- [ ] **Step 5: 跑測試確認通過**

```bash
python -m unittest tests.test_auth -v
```

預期：4 個測試全部通過

- [ ] **Step 6: 跑全套測試確認無破壞**

```bash
python -m unittest discover tests/ 2>&1 | tail -5
```

預期：`OK`（現有測試因為直接呼叫服務物件，不走 HTTP，所以不受影響）

- [ ] **Step 7: Commit**

```bash
git add app.py tests/test_auth.py
git commit -m "feat: add X-API-Key authentication to all /api/* endpoints"
```

---

## Task 3：Flask-Limiter Rate Limiting

**Files:**
- Modify: `requirements.txt`
- Modify: `app.py`

- [ ] **Step 1: 安裝 Flask-Limiter**

在 `requirements.txt` 加入一行：

```
Flask-Limiter>=3.5.0
```

```bash
pip install "Flask-Limiter>=3.5.0"
```

- [ ] **Step 2: 初始化 Limiter**

在 `app.py` 的 Flask app 建立後（`app = Flask(...)` 之後）加入：

```python
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per minute"],
    storage_uri="memory://",
)
```

- [ ] **Step 3: 套用端點級別限制**

在對應的三個耗資源端點上加 `@limiter.limit()`，**緊接在** `@require_auth` **之後**：

```python
@app.route("/api/scan/full")
@require_auth
@limiter.limit("2 per minute")
def scan_full_stream():
    ...

@app.route("/api/backtest/full")
@require_auth
@limiter.limit("2 per minute")
def backtest_full_stream():
    ...

@app.route("/api/backtest/optimize", methods=["POST"])
@require_auth
@limiter.limit("1 per 5 minutes")
def optimize_params():
    ...
```

以及 intelligence 相關端點：

```python
@app.route("/api/intelligence/news")
@require_auth
@limiter.limit("10 per minute")
def get_intelligence_news():
    ...

@app.route("/api/intelligence/summary")
@require_auth
@limiter.limit("10 per minute")
def get_intelligence_summary():
    ...

@app.route("/api/intelligence/generate_summary", methods=["POST"])
@require_auth
@limiter.limit("10 per minute")
def generate_summary():
    ...

@app.route("/api/intelligence/x")
@require_auth
@limiter.limit("10 per minute")
def get_x_posts():
    ...
```

- [ ] **Step 4: 跑全套測試**

```bash
python -m unittest discover tests/ 2>&1 | tail -5
```

預期：`OK`

- [ ] **Step 5: Commit**

```bash
git add requirements.txt app.py
git commit -m "feat: add Flask-Limiter rate limiting to resource-intensive endpoints"
```

---

## Task 4：CORS 限縮 + 安全 HTTP Headers

**Files:**
- Modify: `app.py`

- [ ] **Step 1: 修改 CORS 設定**

在 `app.py` 找到這行：

```python
CORS(app)
```

改為（從 env var 讀取允許的 origin，預設 localhost）：

```python
_allowed_origin = os.environ.get("CORS_ORIGIN", "http://localhost:8787")
CORS(app, resources={r"/api/*": {"origins": [_allowed_origin]}})
```

- [ ] **Step 2: 加入 after_request 安全 headers**

在 `CORS(...)` 之後加入：

```python
@app.after_request
def set_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    return response
```

- [ ] **Step 3: 寫測試驗證 headers**

在 `tests/test_auth.py` 加入：

```python
def test_security_headers_present(self):
    r = self.client.get("/", headers={"X-API-Key": self.test_key})
    self.assertEqual(r.headers.get("X-Frame-Options"), "DENY")
    self.assertEqual(r.headers.get("X-Content-Type-Options"), "nosniff")
```

- [ ] **Step 4: 跑 test_auth 確認通過**

```bash
python -m unittest tests.test_auth -v
```

預期：5 個測試全部通過

- [ ] **Step 5: Commit**

```bash
git add app.py tests/test_auth.py
git commit -m "feat: restrict CORS to configured origin, add security headers"
```

---

## Task 5：defusedxml 取代 ElementTree（防 XXE）

**Files:**
- Modify: `requirements.txt`
- Modify: `trading/news.py`
- Modify: `tests/test_news.py`

- [ ] **Step 1: 安裝 defusedxml**

在 `requirements.txt` 加入一行：

```
defusedxml>=0.7.1
```

```bash
pip install "defusedxml>=0.7.1"
```

- [ ] **Step 2: 寫失敗測試**

在 `tests/test_news.py` 加入：

```python
def test_xxe_payload_is_rejected(self):
    """確認 XXE payload 不會被執行（defusedxml 會拋出例外）。"""
    import defusedxml.ElementTree as dET
    xxe_payload = b"""<?xml version="1.0"?>
<!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>
<rss><channel><item><title>&xxe;</title></item></channel></rss>"""
    with self.assertRaises(Exception):
        dET.fromstring(xxe_payload)
```

- [ ] **Step 3: 跑測試（應通過，因為是測 defusedxml 本身的行為）**

```bash
python -m unittest tests.test_news.TestNewsAggregator.test_xxe_payload_is_rejected -v
```

預期：`OK`（defusedxml 正確拒絕 XXE）

- [ ] **Step 4: 修改 news.py 使用 defusedxml**

在 `trading/news.py` 頂部，找到：

```python
import xml.etree.ElementTree as ET
```

改為：

```python
import defusedxml.ElementTree as ET
```

（其餘程式碼不需改動，因為 API 相容）

- [ ] **Step 5: 跑全套 news 測試**

```bash
python -m unittest tests.test_news -v
```

預期：全部通過（defusedxml API 與 stdlib 相容）

- [ ] **Step 6: Commit**

```bash
git add requirements.txt trading/news.py tests/test_news.py
git commit -m "feat: replace xml.etree.ElementTree with defusedxml to prevent XXE attacks"
```

---

## Task 6：Telegram Bot Fail-Closed

**Files:**
- Modify: `trading/telegram/bot.py`
- Modify: `tests/test_telegram_bot.py`

- [ ] **Step 1: 找到 is_allowed 方法**

在 `trading/telegram/bot.py` 找到 `is_allowed` 方法（目前邏輯：空白 allowed_ids 時 return True）。

- [ ] **Step 2: 寫失敗測試**

在 `tests/test_telegram_bot.py` 找到 `TestTelegramBot` 類別，加入：

```python
def test_is_allowed_returns_false_when_allowed_ids_empty(self):
    """空白 allowed_ids 應拒絕所有請求（fail-closed）。"""
    bot_no_ids = TelegramBot(
        token="test",
        allowed_ids=set(),
        config_manager=self.config_mgr,
        position_manager=self.pos_mgr,
        scanner=self.scanner,
        indicator_engine=self.ind_engine,
        news_aggregator=self.news_agg,
        market_service=self.market_svc,
    )
    self.assertFalse(bot_no_ids.is_allowed("anyone"))

def test_is_allowed_returns_false_when_allowed_ids_none(self):
    """None allowed_ids 應拒絕所有請求（fail-closed）。"""
    bot_no_ids = TelegramBot(
        token="test",
        allowed_ids=None,
        config_manager=self.config_mgr,
        position_manager=self.pos_mgr,
        scanner=self.scanner,
        indicator_engine=self.ind_engine,
        news_aggregator=self.news_agg,
        market_service=self.market_svc,
    )
    self.assertFalse(bot_no_ids.is_allowed("anyone"))
```

- [ ] **Step 3: 跑測試確認失敗**

```bash
python -m unittest tests.test_telegram_bot.TestTelegramBot.test_is_allowed_returns_false_when_allowed_ids_empty -v
```

預期：`FAIL`（目前空白 allowed_ids 回傳 True）

- [ ] **Step 4: 修改 is_allowed 方法**

在 `trading/telegram/bot.py` 找到 `is_allowed` 方法，修改為：

```python
def is_allowed(self, chat_id: str) -> bool:
    """檢查 chat_id 是否在白名單中。未設定白名單時拒絕所有人（fail-closed）。"""
    if not self.allowed_ids:
        return False
    return str(chat_id) in self.allowed_ids
```

- [ ] **Step 5: 跑 telegram bot 測試**

```bash
python -m unittest tests.test_telegram_bot -v
```

預期：全部通過（現有測試使用的 bot 都有設定 allowed_ids，不受影響）

- [ ] **Step 6: Commit**

```bash
git add trading/telegram/bot.py tests/test_telegram_bot.py
git commit -m "fix: telegram bot is_allowed now fail-closed when allowed_ids is empty"
```

---

## Task 7：XSS 修復（index.html）

**Files:**
- Modify: `index.html`

> 注意：index.html 沒有對應的單元測試（純前端）。修復後需手動在瀏覽器驗證。

- [ ] **Step 1: 修復 esc() 函數**

在 `index.html` 找到第 876 行的 `esc` 函數：

```javascript
function esc(s){ return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
```

改為：

```javascript
function esc(s){ return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#x27;'); }
```

- [ ] **Step 2: 修復 report-summary 的 innerHTML（line 1149）**

找到 `index.html` 第 1149 行：

```javascript
document.getElementById('report-summary').innerHTML = r.summary||'';
```

改為（先 escape 再設定 innerHTML，保留顏色邏輯）：

```javascript
const summaryEl = document.getElementById('report-summary');
summaryEl.textContent = r.summary||'';
summaryEl.style.color = (r.summary||'').includes('⚠️') ? 'var(--yellow)' : 'var(--green)';
```

同時刪除原本第 1150 行（顏色設定已移入上方）：

```javascript
document.getElementById('report-summary').style.color = (r.summary||'').includes('⚠️') ? 'var(--yellow)' : 'var(--green)';
```

- [ ] **Step 3: 確認 _renderSummary 已安全（line 1913, 1929）**

檢查 `index.html` 中的 `_renderSummary` 函數（約 line 1890-1905），確認函數內部已用 `esc()` 包住所有變數（`esc(s.summary)`、`esc(s.created_at||'')`）。若已包覆，則 line 1913 和 1929 的 `innerHTML = _renderSummary(...)` 是安全的，不需改動。

- [ ] **Step 4: 手動驗證（瀏覽器）**

啟動系統後，在瀏覽器 Console 執行：

```javascript
// 測試 esc() 是否完整轉義
console.assert(esc('<script>') === '&lt;script&gt;', 'tag escape OK');
console.assert(esc('"test"') === '&quot;test&quot;', 'quote escape OK');
console.assert(esc("'test'") === '&#x27;test&#x27;', 'single quote escape OK');
console.log('esc() 測試通過');
```

預期：Console 顯示 `esc() 測試通過`，無 assertion 錯誤

- [ ] **Step 5: Commit**

```bash
git add index.html
git commit -m "fix: patch esc() to escape quotes, replace report-summary innerHTML with textContent"
```

---

## Task 8：最終驗證

- [ ] **Step 1: 安裝所有新依賴**

```bash
pip install -r requirements.txt
```

- [ ] **Step 2: 跑全套測試**

```bash
python -m unittest discover tests/ -v 2>&1 | tail -10
```

預期：`OK`（原有 299+ tests + 新增 ~8 tests，全部通過）

- [ ] **Step 3: 手動 API 認證驗證**

```bash
# 先啟動（另一個終端）
python run.py

# 測試：無 key 應回 401
curl -s http://localhost:8787/api/positions | python -m json.tool
# 預期：{"ok": false, "error": "Unauthorized"}

# 測試：從 config.json 取 key
python -c "import json; print(json.load(open('config.json'))['api_key'])"

# 測試：正確 key 應通過
curl -s -H "X-API-Key: <上面輸出的key>" http://localhost:8787/api/positions | python -m json.tool
# 預期：{"positions": [...], ...}

# 測試：rate limit（連打 3 次 full scan）
for i in 1 2 3; do curl -s -H "X-API-Key: <key>" http://localhost:8787/api/scan/full -o /dev/null -w "%{http_code}\n"; done
# 預期：200, 200, 429
```

- [ ] **Step 4: 確認前端可正常載入**

在瀏覽器開啟 `http://localhost:8787`，確認：
- 頁面正常顯示（`GET /` 不需認證）
- 打開 Network tab，確認 `/api/*` 請求都帶有 `X-API-Key` header（前端 `api()` 函數需更新以自動帶入 key）

> ⚠️ **注意**：前端目前的 `api()` 函數（index.html line 869）沒有自動帶入 `X-API-Key`。需在此 task 中一併修復，否則前端所有 API 呼叫都會收到 401。

- [ ] **Step 5: 修復前端 api() 函數自動帶入 API Key**

在 `index.html` 找到第 869-875 行的 `api()` 函數：

```javascript
async function api(method, path, body, signal){
  const opts = { method, headers:{'Content-Type':'application/json'} };
  if (body) opts.body = JSON.stringify(body);
  if (signal) opts.signal = signal;
  const r = await fetch(path, opts);
  return r.json();
}
```

改為（從 `window._apiKey` 讀取，初始化時從 `/api/auth_check` 或直接讀 localStorage）：

```javascript
// API Key 管理（從 localStorage 讀取，首次由啟動畫面設定）
function getApiKey() {
  return localStorage.getItem('trading_api_key') || '';
}

async function api(method, path, body, signal){
  const opts = { method, headers:{
    'Content-Type':'application/json',
    'X-API-Key': getApiKey()
  }};
  if (body) opts.body = JSON.stringify(body);
  if (signal) opts.signal = signal;
  const r = await fetch(path, opts);
  if (r.status === 401) {
    const key = prompt('請輸入 API Key（可在伺服器終端機啟動訊息中找到）：');
    if (key) {
      localStorage.setItem('trading_api_key', key);
      return api(method, path, body, signal); // 重試一次
    }
    throw new Error('Unauthorized');
  }
  return r.json();
}
```

- [ ] **Step 6: 跑全套測試**

```bash
python -m unittest discover tests/ 2>&1 | tail -5
```

預期：`OK`

- [ ] **Step 7: 最終 Commit**

```bash
git add index.html
git commit -m "feat: frontend api() auto-includes X-API-Key from localStorage with prompt fallback"
```

---

## 驗收標準（Phase 1 完成條件）

| 項目 | 驗證方式 | 預期結果 |
|------|---------|---------|
| API 認證 | `curl /api/positions` | 401 Unauthorized |
| API 認證 | `curl -H "X-API-Key: <key>" /api/positions` | 200 OK |
| Rate Limit | 連打 3 次 `/api/scan/full` | 第 3 次回 429 |
| XSS | 瀏覽器 Console 執行 esc() 測試 | 全部通過 |
| Telegram | `is_allowed("")` with empty allowed_ids | False |
| Security Headers | 任意 response headers | `X-Frame-Options: DENY` |
| defusedxml | 對 XXE payload 呼叫 `dET.fromstring()` | 拋出例外 |
| 全套測試 | `python -m unittest discover tests/` | OK，無失敗 |

---

## 重要注意事項

1. **CORS_ORIGIN env var**：若你的前端不是在 `localhost:8787` 存取 API，需在 `.env` 設定 `CORS_ORIGIN=https://your-domain.com`
2. **API Key 首次啟動**：啟動 `python run.py` 時，終端機會印出 API Key，複製後存入瀏覽器 localStorage 或使用 prompt
3. **現有測試不受影響**：現有測試直接呼叫服務物件，不走 HTTP，因此不需修改現有測試的 setUp
4. **Phase 2 執行前**：確認此 Phase 所有測試通過且手動驗證完成
