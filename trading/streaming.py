"""
trading/streaming.py — SSE 工具函式
提供統一的 Server-Sent Events 事件格式化，解耦 app.py 中的串流邏輯。
"""
import json


class SSEStream:
    """SSE 事件序列化工具。所有方法皆為靜態，回傳符合 SSE 規範的字串。"""

    @staticmethod
    def event(payload: dict) -> str:
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    @staticmethod
    def start(total: int) -> str:
        return SSEStream.event({"type": "start", "total": total})

    @staticmethod
    def progress(done: int, total: int) -> str:
        return SSEStream.event({"type": "progress", "done": done, "total": total})

    @staticmethod
    def result(item: dict, done: int = 0, total: int = 0) -> str:
        return SSEStream.event({"type": "result", "done": done, "total": total, "item": item})

    @staticmethod
    def done(payload: dict) -> str:
        return SSEStream.event({**{"type": "done"}, **payload})

    @staticmethod
    def error(message: str) -> str:
        return SSEStream.event({"type": "error", "message": message})

    @staticmethod
    def scan_start(total: int) -> str:
        return SSEStream.event({"type": "scan_start", "total": total})

    @staticmethod
    def scan_progress(done: int, total: int, passed: int) -> str:
        return SSEStream.event({"type": "scan_progress", "done": done, "total": total, "passed": passed})

    @staticmethod
    def bt_start(total: int) -> str:
        return SSEStream.event({"type": "bt_start", "total": total})

    @staticmethod
    def bt_result(item: dict, done: int, total: int) -> str:
        return SSEStream.event({"type": "bt_result", "done": done, "total": total, "item": item})

    @staticmethod
    def bt_progress(done: int, total: int) -> str:
        return SSEStream.event({"type": "bt_progress", "done": done, "total": total})
