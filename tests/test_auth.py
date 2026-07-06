"""tests/test_auth.py — 測試 API 認證 decorator"""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class TestRequireAuth(unittest.TestCase):
    def setUp(self):
        # 建立暫存 config.json，含已知 api_key
        self.tmpdir = tempfile.mkdtemp()
        self.config_path = Path(self.tmpdir) / "config.json"
        self.test_key = "test_api_key_abc123xyz456def789ghi012"
        with open(self.config_path, "w") as f:
            json.dump({"api_key": self.test_key}, f)

        # 讓 app 使用暫存設定路徑
        os.environ["TRADING_CONFIG_PATH"] = str(self.config_path)

        # 重新載入 app 模組以套用設定
        import app as app_module
        app_module.app.config["TESTING"] = True
        self.client = app_module.app.test_client()
        self.app_module = app_module

    def tearDown(self):
        if "TRADING_CONFIG_PATH" in os.environ:
            del os.environ["TRADING_CONFIG_PATH"]

    def test_request_without_key_returns_401(self):
        r = self.client.get("/api/positions")
        self.assertEqual(r.status_code, 401)
        data = json.loads(r.data)
        self.assertFalse(data["ok"])
        self.assertEqual(data["error"], "Unauthorized")

    def test_request_with_wrong_key_returns_401(self):
        r = self.client.get("/api/positions",
                            headers={"X-API-Key": "wrong_key_xyz"})
        self.assertEqual(r.status_code, 401)
        data = json.loads(r.data)
        self.assertFalse(data["ok"])

    def test_request_with_correct_key_passes_auth(self):
        r = self.client.get("/api/positions",
                            headers={"X-API-Key": self.test_key})
        # 通過認證（業務層可能有其他回應，但不應是 401）
        self.assertNotEqual(r.status_code, 401)

    def test_index_page_no_auth_required(self):
        r = self.client.get("/")
        self.assertNotEqual(r.status_code, 401)

    def test_key_via_query_param(self):
        r = self.client.get(f"/api/positions?key={self.test_key}")
        self.assertNotEqual(r.status_code, 401)

    def test_x_frame_options_header_present(self):
        r = self.client.get("/")
        self.assertEqual(r.headers.get("X-Frame-Options"), "SAMEORIGIN")

    def test_x_content_type_options_header_present(self):
        r = self.client.get("/")
        self.assertEqual(r.headers.get("X-Content-Type-Options"), "nosniff")


class TestEndpointAuthCoverage(unittest.TestCase):
    """確保容易被遺漏（曾用裸 fetch() 呼叫）的端點也正確受 @require_auth 保護。
    Regression: index.html 的 loadMarket() 和 showChart() 曾用裸 fetch()，
    未帶 X-API-Key，導致 401。修復：前端改用 api()，端點本身認證邏輯正確。
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.config_path = Path(self.tmpdir) / "config.json"
        self.test_key = "test_api_key_market_ohlcv_abc123"
        with open(self.config_path, "w") as f:
            json.dump({"api_key": self.test_key}, f)
        os.environ["TRADING_CONFIG_PATH"] = str(self.config_path)
        import app as app_module
        app_module.app.config["TESTING"] = True
        self.client = app_module.app.test_client()

    def tearDown(self):
        if "TRADING_CONFIG_PATH" in os.environ:
            del os.environ["TRADING_CONFIG_PATH"]

    # ── /api/market ─────────────────────────────────────────────

    def test_market_without_key_returns_401(self):
        """GET /api/market 無 key → 401（防止裸 fetch() 繞過認證的 regression）。"""
        r = self.client.get("/api/market")
        self.assertEqual(r.status_code, 401)
        data = json.loads(r.data)
        self.assertFalse(data["ok"])

    def test_market_with_correct_key_passes_auth(self):
        """GET /api/market 帶正確 key → 非 401，回應含 ok 欄位。"""
        r = self.client.get("/api/market", headers={"X-API-Key": self.test_key})
        self.assertNotEqual(r.status_code, 401)
        data = json.loads(r.data)
        self.assertIn("ok", data)

    def test_market_with_query_key_passes_auth(self):
        """GET /api/market?key=<key> → 非 401（SSE 相容路徑）。"""
        r = self.client.get(f"/api/market?key={self.test_key}")
        self.assertNotEqual(r.status_code, 401)

    # ── /api/ohlcv/<code> ────────────────────────────────────────

    def test_ohlcv_without_key_returns_401(self):
        """GET /api/ohlcv/2330 無 key → 401（K 線圖資料端點，曾被裸 fetch() 呼叫）。"""
        r = self.client.get("/api/ohlcv/2330")
        self.assertEqual(r.status_code, 401)
        data = json.loads(r.data)
        self.assertFalse(data["ok"])

    def test_ohlcv_with_wrong_key_returns_401(self):
        """GET /api/ohlcv/2330 帶錯誤 key → 401。"""
        r = self.client.get("/api/ohlcv/2330", headers={"X-API-Key": "wrong_key"})
        self.assertEqual(r.status_code, 401)

    def test_ohlcv_with_correct_key_passes_auth(self):
        """GET /api/ohlcv/2330 帶正確 key → 通過認證（資料不足時為 404，非 401）。"""
        r = self.client.get("/api/ohlcv/2330", headers={"X-API-Key": self.test_key})
        self.assertNotEqual(r.status_code, 401)


if __name__ == "__main__":
    unittest.main()
