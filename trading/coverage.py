"""
trading/coverage.py — My-TW-Coverage 研究資料庫讀取器
"""
import re
import subprocess
import time
from collections import Counter
from pathlib import Path
from typing import Optional

from trading.logger import get_logger

logger = get_logger("coverage")

_DEFAULT_BASE = Path(__file__).parent.parent / "data" / "tw-coverage" / "Pilot_Reports"


class CoverageReader:
    """台股研究報告讀取器（In-Memory 索引）。

    reload() 時將所有報告內容讀入記憶體，
    search() / keywords() 皆使用快取，無需再次讀取磁碟。
    """

    def __init__(self, base_dir: Optional[Path] = None):
        self._base: Path = base_dir if base_dir is not None else _DEFAULT_BASE
        self._index: dict[str, dict] = {}
        self._kw_counter: Counter = Counter()

    # ── 公開方法 ─────────────────────────────────────────────────

    def reload(self) -> int:
        """掃描所有 .md，讀入記憶體建立索引，回傳檔案數。"""
        if not self._base.exists():
            self._index = {}
            self._kw_counter = Counter()
            return 0
        idx: dict[str, dict] = {}
        kw_counter: Counter = Counter()
        for path in self._base.rglob("*.md"):
            m = re.match(r"^(\d{4})_(.+)\.md$", path.name)
            if not m:
                continue
            code = m.group(1)
            name = m.group(2)
            sector = path.parent.name
            try:
                content = path.read_text(encoding="utf-8")
            except Exception as e:
                logger.warning("讀取 %s 失敗: %s", path.name, e)
                continue
            wikilinks = list(dict.fromkeys(re.findall(r"\[\[([^\]]+)\]\]", content)))
            kw_counter.update(wikilinks)
            if code in idx:
                logger.debug("代號 %s 重複: %s", code, path.name)
            idx[code] = {
                "name":      name,
                "sector":    sector,
                "content":   content,
                "wikilinks": wikilinks,
            }
        self._index = idx
        self._kw_counter = kw_counter
        logger.info("索引建立完成：%d 份報告，%d 個關鍵字", len(idx), len(kw_counter))
        return len(idx)

    def get_overview(self, code: str) -> Optional[dict]:
        """解析個股報告，回傳摘要字典；無此代號時回傳 None。"""
        entry = self._index.get(code)
        if entry is None:
            return None
        content = entry["content"]

        def _section(title: str) -> str:
            pattern = rf"##\s+{re.escape(title)}\s*\n(.*?)(?=\n##\s|\Z)"
            m = re.search(pattern, content, re.DOTALL)
            return m.group(1).strip() if m else ""

        return {
            "name":         entry["name"],
            "sector":       entry["sector"],
            "business":     _section("業務概況"),
            "supply_chain": _section("供應鏈位置"),
            "customers":    _section("主要客戶"),
            "suppliers":    _section("主要供應商"),
            "wikilinks":    entry["wikilinks"],
        }

    def search(self, keyword: str, limit: int = 20) -> list[dict]:
        """搜尋含 keyword 的報告。

        兩趟掃描確保 wikilink 精確比對優先：
          第一趟：收集所有 wikilink 命中的股票
          第二趟：以內文模糊比對補足剩餘名額
        """
        kw_lower = keyword.lower()
        wikilink_hits: list[dict] = []
        content_hits:  list[dict] = []

        for code, entry in self._index.items():
            matched = [lk for lk in entry["wikilinks"] if kw_lower in lk.lower()]
            if matched:
                wikilink_hits.append({
                    "code":          code,
                    "name":          entry["name"],
                    "sector":        entry["sector"],
                    "matched_links": list(dict.fromkeys(matched)),
                })
            elif kw_lower in entry["content"].lower():
                content_hits.append({
                    "code":          code,
                    "name":          entry["name"],
                    "sector":        entry["sector"],
                    "matched_links": [],
                })

        combined = wikilink_hits + content_hits
        return combined[:limit]

    def keywords(self, limit: int = 200) -> list[dict]:
        """回傳出現頻率最高的關鍵字列表。"""
        return [
            {"keyword": kw, "count": cnt}
            for kw, cnt in self._kw_counter.most_common(limit)
        ]

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
