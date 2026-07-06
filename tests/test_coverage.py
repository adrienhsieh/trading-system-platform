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


class TestKeywords(unittest.TestCase):

    def test_keywords_returns_sorted_by_count(self):
        """keywords() 回傳按出現次數排序的清單，高頻在前"""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            # 2330 有 CoWoS x1、HBM x1；2454 有 CoWoS x1（total CoWoS=2, HBM=1）
            _write_md(base / "Semis", "2330_台積電.md", "## 業務概況\n[[CoWoS]] [[HBM]]\n")
            _write_md(base / "Semis", "2454_聯發科.md", "## 業務概況\n[[CoWoS]]\n")
            from trading.coverage import CoverageReader
            reader = CoverageReader(base_dir=base)
            reader.reload()
            kws = reader.keywords()
        self.assertTrue(len(kws) >= 2)
        self.assertEqual(kws[0]["keyword"], "CoWoS")
        self.assertEqual(kws[0]["count"], 2)
        self.assertEqual(kws[1]["keyword"], "HBM")
        self.assertEqual(kws[1]["count"], 1)

    def test_keywords_respects_limit(self):
        """keywords(limit=1) 只回傳 1 個"""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            _write_md(base / "Semis", "2330_台積電.md", "## 業務概況\n[[A]] [[B]] [[C]]\n")
            from trading.coverage import CoverageReader
            reader = CoverageReader(base_dir=base)
            reader.reload()
            kws = reader.keywords(limit=1)
        self.assertEqual(len(kws), 1)

    def test_keywords_empty_when_no_data(self):
        """目錄不存在時 keywords() 回傳空列表"""
        from trading.coverage import CoverageReader
        reader = CoverageReader(base_dir=Path("/nonexistent/__test__"))
        reader.reload()
        self.assertEqual(reader.keywords(), [])


class TestSearchPriority(unittest.TestCase):

    def test_wikilink_hits_precede_content_hits(self):
        """wikilink 命中的股票必須排在純內文命中之前"""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            # 2317 只有內文命中（無 wikilink）
            _write_md(base / "Semis", "2317_鴻海.md",
                      "## 業務概況\nCoWoS 封裝技術應用廠商。\n")
            # 2330 有 wikilink 命中
            _write_md(base / "Semis", "2330_台積電.md",
                      "## 業務概況\n晶圓代工。\n[[CoWoS]]\n")
            from trading.coverage import CoverageReader
            reader = CoverageReader(base_dir=base)
            reader.reload()
            results = reader.search("CoWoS")
        codes = [r["code"] for r in results]
        self.assertIn("2330", codes)
        self.assertIn("2317", codes)
        # 2330（wikilink 命中）必須排在 2317（內文命中）之前
        self.assertLess(codes.index("2330"), codes.index("2317"))


class TestSync(unittest.TestCase):

    def test_sync_fails_gracefully_when_not_a_git_repo(self):
        """非 git 目錄時 sync() 回傳 ok=False，不拋例外"""
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "Pilot_Reports"
            base.mkdir()
            _write_md(base / "Semis", "2330_台積電.md", "## 業務概況\n測試\n")
            from trading.coverage import CoverageReader
            reader = CoverageReader(base_dir=base)
            reader.reload()
            result = reader.sync()
        self.assertFalse(result["ok"])
        self.assertIn("error", result)

    def test_sync_updates_added_count(self):
        """sync() 成功時回傳的 added 反映新增報告數"""
        import unittest.mock as mock
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "Pilot_Reports"
            base.mkdir()
            _write_md(base / "Semis", "2330_台積電.md", "## 業務概況\n測試\n")
            from trading.coverage import CoverageReader
            reader = CoverageReader(base_dir=base)
            reader.reload()
            # 模擬 git pull 成功，同時新增一份報告
            def fake_pull(*args, **kwargs):
                _write_md(base / "Semis", "2454_聯發科.md", "## 業務概況\n測試\n")
            with mock.patch("subprocess.run", side_effect=fake_pull):
                result = reader.sync()
        self.assertTrue(result["ok"])
        self.assertEqual(result["added"], 1)
        self.assertEqual(result["total"], 2)


if __name__ == "__main__":
    unittest.main()
