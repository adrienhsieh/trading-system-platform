"""
trading/positions.py — 持倉管理
使用 SQLite 儲存持倉，提供 CRUD 操作與風險統計。
"""
import datetime
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Optional


class PositionManager:
    """持倉 CRUD 管理，底層使用 SQLite。"""

    def __init__(self, db_file: Path = None):
        base = Path(__file__).parent.parent
        self.db_file = db_file or base / "positions.db"
        self._init_db()

    # ── 資料庫連線 ─────────────────────────────────────────────

    @contextmanager
    def _conn(self):
        con = sqlite3.connect(str(self.db_file), check_same_thread=False)
        con.row_factory = sqlite3.Row
        try:
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    # ── 初始化 ─────────────────────────────────────────────────

    def _init_db(self) -> None:
        """建立資料表（若不存在）。"""
        with self._conn() as con:
            con.execute("""
                CREATE TABLE IF NOT EXISTS positions (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    code          TEXT    NOT NULL,
                    name          TEXT    NOT NULL DEFAULT '',
                    date          TEXT    NOT NULL,
                    entry         REAL    NOT NULL,
                    shares        INTEGER NOT NULL,
                    stop          REAL    NOT NULL,
                    target        REAL,
                    status        TEXT    NOT NULL DEFAULT 'active',
                    risk_amount   INTEGER NOT NULL DEFAULT 0,
                    note          TEXT    NOT NULL DEFAULT ''
                )
            """)
            con.execute("""
                CREATE TABLE IF NOT EXISTS watchlist (
                    id       INTEGER PRIMARY KEY AUTOINCREMENT,
                    code     TEXT    NOT NULL UNIQUE,
                    name     TEXT    NOT NULL DEFAULT '',
                    added_at TEXT    NOT NULL
                )
            """)
            con.execute("""
                CREATE TABLE IF NOT EXISTS intraday_watch (
                    id       INTEGER PRIMARY KEY AUTOINCREMENT,
                    code     TEXT    NOT NULL UNIQUE,
                    name     TEXT    NOT NULL DEFAULT '',
                    added_at TEXT    NOT NULL
                )
            """)

    # ── 輔助 ───────────────────────────────────────────────────

    @staticmethod
    def _row_to_dict(row: sqlite3.Row) -> dict:
        return dict(row)

    @staticmethod
    def _calc_risk(entry: float, stop: float, shares: int, status: str) -> int:
        if status == "safe":
            return 0
        return max(0, int((entry - stop) * shares))

    # ── CRUD ───────────────────────────────────────────────────

    def load_all(self) -> list:
        """讀取所有持倉，依 id 排序。"""
        with self._conn() as con:
            rows = con.execute("SELECT * FROM positions ORDER BY id").fetchall()
        return [self._row_to_dict(r) for r in rows]

    def load_one(self, pid: int) -> Optional[dict]:
        """讀取單一持倉，不存在時回傳 None。"""
        with self._conn() as con:
            row = con.execute("SELECT * FROM positions WHERE id=?", (pid,)).fetchone()
        return self._row_to_dict(row) if row else None

    def create(self, data: dict) -> dict:
        """新增持倉，回傳含 id 的完整持倉字典。"""
        entry  = float(data["entry"])
        stop   = float(data["stop"])
        shares = int(data["shares"])
        status = data.get("status", "active")
        target = float(data["target"]) if data.get("target") else None
        risk   = self._calc_risk(entry, stop, shares, status)

        with self._conn() as con:
            cur = con.execute(
                "INSERT INTO positions "
                "(code,name,date,entry,shares,stop,target,status,risk_amount,note) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    str(data["code"]).strip(),
                    str(data["name"]).strip(),
                    str(data["date"]),
                    entry, shares, stop, target,
                    status, risk,
                    str(data.get("note", "")),
                ),
            )
            new_id = cur.lastrowid
        return self.load_one(new_id)

    def update(self, pid: int, data: dict) -> Optional[dict]:
        """更新持倉欄位，回傳更新後的持倉；不存在時回傳 None。"""
        pos = self.load_one(pid)
        if not pos:
            return None
        for f in ("code", "name", "date", "entry", "shares", "stop", "target", "status", "note"):
            if f in data:
                pos[f] = data[f]
        entry  = float(pos["entry"])
        stop   = float(pos["stop"])
        shares = int(pos["shares"])
        status = pos["status"]
        target = float(pos["target"]) if pos.get("target") else None
        risk   = self._calc_risk(entry, stop, shares, status)

        with self._conn() as con:
            con.execute(
                "UPDATE positions SET "
                "code=?,name=?,date=?,entry=?,shares=?,stop=?,target=?,status=?,risk_amount=?,note=? "
                "WHERE id=?",
                (
                    str(pos["code"]).strip(),
                    str(pos["name"]).strip(),
                    str(pos["date"]),
                    entry, shares, stop, target,
                    status, risk,
                    str(pos.get("note", "")),
                    pid,
                ),
            )
        return self.load_one(pid)

    def delete(self, pid: int) -> bool:
        """刪除持倉，成功回傳 True。"""
        with self._conn() as con:
            cur = con.execute("DELETE FROM positions WHERE id=?", (pid,))
        return cur.rowcount > 0

    # ── 風險統計 ───────────────────────────────────────────────

    def risk_summary(self, positions: list, total_capital: float) -> dict:
        """計算全部持倉的風險匯總。"""
        total_risk = sum(p.get("risk_amount", 0) for p in positions)
        pct = round(total_risk / total_capital * 100, 2) if total_capital else 0
        return {
            "total_risk":    total_risk,
            "total_capital": total_capital,
            "risk_pct":      pct,
            "count":         len(positions),
        }

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

    # ── 即時監控清單（獨立於觀察名單，供「即時監控」頁簽使用） ──────

    def intraday_watch_add(self, code: str, name: str = "") -> bool:
        """新增即時監控股票。重複 code 回傳 False。"""
        try:
            with self._conn() as con:
                con.execute(
                    "INSERT INTO intraday_watch (code, name, added_at) VALUES (?, ?, ?)",
                    (code, name, datetime.date.today().isoformat()),
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def intraday_watch_remove(self, code: str) -> bool:
        """移除即時監控股票。不存在回傳 False。"""
        with self._conn() as con:
            cur = con.execute("DELETE FROM intraday_watch WHERE code = ?", (code,))
            return cur.rowcount > 0

    def intraday_watch_list(self) -> list:
        """回傳所有即時監控股票 [{id, code, name, added_at}]。"""
        with self._conn() as con:
            rows = con.execute(
                "SELECT id, code, name, added_at FROM intraday_watch ORDER BY added_at ASC"
            ).fetchall()
        return [dict(r) for r in rows]
