# trading/services/news.py
import requests
import datetime

class NewsAggregator:
    def __init__(self):
        self.sources = [
            "https://news.cnyes.com/api/v3/news/category/tw_stock?limit=10",  # 鉅亨網
            "https://tw.stock.yahoo.com/rss"  # Yahoo Finance RSS
        ]

    def fetch(self):
        results = []
        for src in self.sources:
            try:
                resp = requests.get(src, timeout=5)
                if resp.status_code == 200:
                    data = resp.json() if "cnyes" in src else None
                    if data:
                        for item in data.get("items", []):
                            results.append({
                                "source": "cnyes",
                                "title": item.get("title"),
                                "content": item.get("content"),
                                "timestamp": datetime.datetime.now().isoformat(),
                                "sentiment": self._sentiment(item.get("title", ""))
                            })
            except Exception as e:
                results.append({"source": src, "error": str(e)})
        return results

    def _sentiment(self, text: str) -> str:
        # 簡單情緒分析：包含「大漲」「利多」→ positive；包含「大跌」「利空」→ negative
        if any(word in text for word in ["大漲", "利多", "看好"]):
            return "positive"
        elif any(word in text for word in ["大跌", "利空", "看壞"]):
            return "negative"
        return "neutral"
