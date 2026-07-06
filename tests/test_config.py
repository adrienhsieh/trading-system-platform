"""tests/test_config.py — ConfigManager 單元測試"""
import json
import tempfile
import unittest
from pathlib import Path

from trading.config import ConfigManager


class TestConfigManager(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg_file = Path(self.tmp.name) / "config.json"
        self.mgr = ConfigManager(config_file=self.cfg_file)

    def tearDown(self):
        self.tmp.cleanup()

    # ── load ───────────────────────────────────────────────────

    def test_load_returns_defaults_when_no_file(self):
        cfg = self.mgr.load()
        self.assertEqual(cfg["total_capital"],      ConfigManager.DEFAULTS["total_capital"])
        self.assertEqual(cfg["consecutive_losses"], ConfigManager.DEFAULTS["consecutive_losses"])
        self.assertIn("scan_candidates", cfg)

    def test_load_reads_existing_file(self):
        self.cfg_file.write_text(json.dumps({"total_capital": 5_000_000}), encoding="utf-8")
        cfg = self.mgr.load()
        self.assertEqual(cfg["total_capital"], 5_000_000)

    def test_load_fills_missing_keys_with_defaults(self):
        self.cfg_file.write_text(json.dumps({"total_capital": 1_000_000}), encoding="utf-8")
        cfg = self.mgr.load()
        self.assertIn("consecutive_losses", cfg)
        self.assertIn("scan_candidates", cfg)

    # ── risk_mode 自動同步 ─────────────────────────────────────

    def test_risk_mode_normal_when_losses_lt_3(self):
        self.cfg_file.write_text(json.dumps({"consecutive_losses": 2}), encoding="utf-8")
        cfg = self.mgr.load()
        self.assertEqual(cfg["risk_mode"], "normal")

    def test_risk_mode_slowdown_when_losses_gte_3(self):
        self.cfg_file.write_text(json.dumps({"consecutive_losses": 3}), encoding="utf-8")
        cfg = self.mgr.load()
        self.assertEqual(cfg["risk_mode"], "slowdown")

    # ── save ───────────────────────────────────────────────────

    def test_save_and_reload_roundtrip(self):
        cfg = self.mgr.load()
        cfg["total_capital"] = 9_999_999
        self.mgr.save(cfg)
        reloaded = self.mgr.load()
        self.assertEqual(reloaded["total_capital"], 9_999_999)

    # ── update ─────────────────────────────────────────────────

    def test_update_changes_specified_key(self):
        cfg = self.mgr.update({"total_capital": 2_000_000})
        self.assertEqual(cfg["total_capital"], 2_000_000)

    def test_update_ignores_unknown_keys(self):
        cfg = self.mgr.update({"unknown_key": "abc"})
        self.assertNotIn("unknown_key", cfg)

    def test_update_persists_to_file(self):
        self.mgr.update({"total_capital": 7_777_777})
        reloaded = self.mgr.load()
        self.assertEqual(reloaded["total_capital"], 7_777_777)

    # ── 屬性 ───────────────────────────────────────────────────

    def test_risk_pct_normal_returns_2(self):
        self.cfg_file.write_text(json.dumps({"consecutive_losses": 1}), encoding="utf-8")
        self.assertEqual(self.mgr.risk_pct, 2.0)

    def test_risk_pct_slowdown_returns_1(self):
        self.cfg_file.write_text(json.dumps({"consecutive_losses": 3}), encoding="utf-8")
        self.assertEqual(self.mgr.risk_pct, 1.0)

    def test_total_capital_property(self):
        self.cfg_file.write_text(json.dumps({"total_capital": 8_000_000}), encoding="utf-8")
        self.assertEqual(self.mgr.total_capital, 8_000_000.0)

    def test_scan_candidates_property(self):
        self.cfg_file.write_text(json.dumps({"scan_candidates": ["2330", "2317"]}), encoding="utf-8")
        self.assertEqual(self.mgr.scan_candidates, ["2330", "2317"])

    # ── api_key ────────────────────────────────────────────────

    def test_api_key_auto_generated_on_first_load(self):
        """首次 load() 時若無 api_key，應自動產生並持久化。"""
        cfg1 = self.mgr.load()
        self.assertIn("api_key", cfg1)
        self.assertIsInstance(cfg1["api_key"], str)
        self.assertEqual(len(cfg1["api_key"]), 64)  # secrets.token_hex(32) = 64 hex chars

    def test_api_key_stable_across_loads(self):
        """重複 load()（含新實例）應回傳相同的 api_key（確認已持久化到磁碟）。"""
        cfg1 = self.mgr.load()
        # 使用新實例確認從磁碟讀取，而非記憶體快取
        mgr2 = ConfigManager(config_file=self.mgr.config_file)
        cfg2 = mgr2.load()
        self.assertEqual(cfg1["api_key"], cfg2["api_key"])

    def test_api_key_persisted_to_disk(self):
        """api_key 應被寫入 config.json，而非只存在於回傳的 dict 中。"""
        import json as _json
        cfg1 = self.mgr.load()
        key = cfg1["api_key"]
        raw = _json.loads(self.mgr.config_file.read_text(encoding="utf-8"))
        self.assertEqual(raw.get("api_key"), key)


if __name__ == "__main__":
    unittest.main()
