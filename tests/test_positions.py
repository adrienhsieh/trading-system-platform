"""tests/test_positions.py — PositionManager 單元測試"""
import tempfile
import unittest
from pathlib import Path

from trading.positions import PositionManager


def _sample_data(**overrides) -> dict:
    """回傳一筆預設的建倉資料，可透過 overrides 覆寫欄位。"""
    base = {
        "code":   "2330",
        "name":   "台積電",
        "date":   "2024-01-15",
        "entry":  900.0,
        "stop":   850.0,
        "shares": 1000,
        "target": 1050.0,
        "status": "active",
        "note":   "",
    }
    base.update(overrides)
    return base


class TestPositionManagerCRUD(unittest.TestCase):

    def setUp(self):
        self.tmp     = tempfile.TemporaryDirectory()
        self.pos_mgr = PositionManager(
            db_file=Path(self.tmp.name) / "test.db",
            )

    def tearDown(self):
        self.tmp.cleanup()

    # ── create ─────────────────────────────────────────────────

    def test_create_returns_dict_with_id(self):
        pos = self.pos_mgr.create(_sample_data())
        self.assertIsNotNone(pos)
        self.assertIn("id", pos)
        self.assertIsInstance(pos["id"], int)

    def test_create_persists_all_fields(self):
        data = _sample_data()
        pos  = self.pos_mgr.create(data)
        self.assertEqual(pos["code"],   data["code"])
        self.assertEqual(pos["name"],   data["name"])
        self.assertEqual(pos["entry"],  data["entry"])
        self.assertEqual(pos["stop"],   data["stop"])
        self.assertEqual(pos["shares"], data["shares"])
        self.assertEqual(pos["status"], data["status"])

    def test_create_multiple_positions_have_unique_ids(self):
        pos1 = self.pos_mgr.create(_sample_data(code="2330"))
        pos2 = self.pos_mgr.create(_sample_data(code="2317"))
        self.assertNotEqual(pos1["id"], pos2["id"])

    def test_create_calculates_risk_amount_for_active(self):
        # risk = (entry - stop) * shares = (900-850)*1000 = 50000
        pos = self.pos_mgr.create(_sample_data(entry=900, stop=850, shares=1000, status="active"))
        self.assertEqual(pos["risk_amount"], 50_000)

    def test_create_risk_amount_zero_for_safe(self):
        pos = self.pos_mgr.create(_sample_data(status="safe"))
        self.assertEqual(pos["risk_amount"], 0)

    def test_create_allows_none_target(self):
        pos = self.pos_mgr.create(_sample_data(target=None))
        self.assertIsNone(pos["target"])

    # ── load_all ───────────────────────────────────────────────

    def test_load_all_empty_initially(self):
        result = self.pos_mgr.load_all()
        self.assertEqual(result, [])

    def test_load_all_returns_all_positions(self):
        self.pos_mgr.create(_sample_data(code="2330"))
        self.pos_mgr.create(_sample_data(code="2317"))
        result = self.pos_mgr.load_all()
        self.assertEqual(len(result), 2)

    def test_load_all_ordered_by_id(self):
        self.pos_mgr.create(_sample_data(code="2330"))
        self.pos_mgr.create(_sample_data(code="2317"))
        result = self.pos_mgr.load_all()
        ids    = [p["id"] for p in result]
        self.assertEqual(ids, sorted(ids))

    # ── load_one ───────────────────────────────────────────────

    def test_load_one_returns_correct_position(self):
        pos = self.pos_mgr.create(_sample_data())
        loaded = self.pos_mgr.load_one(pos["id"])
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["id"],   pos["id"])
        self.assertEqual(loaded["code"], pos["code"])

    def test_load_one_returns_none_for_missing_id(self):
        result = self.pos_mgr.load_one(99999)
        self.assertIsNone(result)

    # ── update ─────────────────────────────────────────────────

    def test_update_modifies_field(self):
        pos     = self.pos_mgr.create(_sample_data())
        updated = self.pos_mgr.update(pos["id"], {"note": "已調整停損"})
        self.assertEqual(updated["note"], "已調整停損")

    def test_update_returns_none_for_missing_id(self):
        result = self.pos_mgr.update(99999, {"note": "test"})
        self.assertIsNone(result)

    def test_update_recalculates_risk_amount(self):
        pos = self.pos_mgr.create(_sample_data(entry=900, stop=850, shares=1000))
        # 調整停損 → risk 應重新計算
        updated = self.pos_mgr.update(pos["id"], {"stop": 800.0})
        self.assertEqual(updated["risk_amount"], int((900 - 800) * 1000))

    def test_update_to_safe_sets_risk_zero(self):
        pos     = self.pos_mgr.create(_sample_data(status="active"))
        updated = self.pos_mgr.update(pos["id"], {"status": "safe"})
        self.assertEqual(updated["risk_amount"], 0)

    # ── delete ─────────────────────────────────────────────────

    def test_delete_returns_true_on_success(self):
        pos    = self.pos_mgr.create(_sample_data())
        result = self.pos_mgr.delete(pos["id"])
        self.assertTrue(result)

    def test_delete_removes_from_db(self):
        pos = self.pos_mgr.create(_sample_data())
        self.pos_mgr.delete(pos["id"])
        self.assertIsNone(self.pos_mgr.load_one(pos["id"]))

    def test_delete_returns_false_for_missing_id(self):
        result = self.pos_mgr.delete(99999)
        self.assertFalse(result)


class TestRiskSummary(unittest.TestCase):

    def setUp(self):
        self.tmp     = tempfile.TemporaryDirectory()
        self.pos_mgr = PositionManager(
            db_file=Path(self.tmp.name) / "test.db",
            )

    def tearDown(self):
        self.tmp.cleanup()

    def test_risk_summary_empty(self):
        summary = self.pos_mgr.risk_summary([], total_capital=1_000_000)
        self.assertEqual(summary["total_risk"], 0)
        self.assertEqual(summary["count"],      0)

    def test_risk_summary_calculation(self):
        positions = [
            {"risk_amount": 10_000},
            {"risk_amount": 20_000},
        ]
        summary = self.pos_mgr.risk_summary(positions, total_capital=1_000_000)
        self.assertEqual(summary["total_risk"],    30_000)
        self.assertEqual(summary["total_capital"], 1_000_000)
        self.assertAlmostEqual(summary["risk_pct"], 3.0, places=2)

    def test_risk_summary_count(self):
        positions = [{"risk_amount": 0}, {"risk_amount": 5000}, {"risk_amount": 3000}]
        summary   = self.pos_mgr.risk_summary(positions, total_capital=500_000)
        self.assertEqual(summary["count"], 3)

    def test_risk_pct_zero_when_no_capital(self):
        positions = [{"risk_amount": 5000}]
        summary   = self.pos_mgr.risk_summary(positions, total_capital=0)
        self.assertEqual(summary["risk_pct"], 0)



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


if __name__ == "__main__":
    unittest.main()
