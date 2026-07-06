"""
trading/groq_client.py — Groq API 客戶端
使用純 REST 呼叫（OpenAI 相容格式），不依賴額外套件。
支援新聞情緒分析、個股影響評估、每日市場摘要。

免費額度：~14,400 req/day（llama-3.3-70b-versatile）
"""
import json
import os
import threading
import time
from typing import Optional

import requests

from trading.logger import get_logger

logger = get_logger("groq_client")


class GroqClient:
    """Groq API 輕量封裝（純 REST，OpenAI 相容）。"""

    BASE_URL      = "https://api.groq.com/openai/v1/chat/completions"
    DEFAULT_MODEL = "llama-3.3-70b-versatile"

    # 類別級別的全域限流（所有實例共用，防止並發與過高頻率）
    _lock         = threading.Lock()
    _last_call_ts = 0.0
    MIN_INTERVAL  = 2   # 兩次呼叫之間最少間隔秒數（Groq 限流寬鬆，2 秒足夠）

    def __init__(self, api_key: str = None, model: str = None):
        self.api_key = api_key or os.environ.get("GROQ_API_KEY", "")
        self.model   = model or self.DEFAULT_MODEL

    def is_available(self) -> bool:
        return bool(self.api_key)

    # ── 底層呼叫 ───────────────────────────────────────────────

    def generate(self, prompt: str, max_tokens: int = 1024) -> Optional[str]:
        """
        發送 prompt 給 Groq，回傳文字回應。
        - 類別級 Lock：防止並發呼叫
        - MIN_INTERVAL 冷卻：兩次呼叫至少間隔 2 秒
        - 429 時單次重試（退避 Retry-After 或 30 秒）
        """
        if not self.api_key:
            return None

        with GroqClient._lock:
            elapsed = time.time() - GroqClient._last_call_ts
            if elapsed < self.MIN_INTERVAL:
                time.sleep(self.MIN_INTERVAL - elapsed)

            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type":  "application/json",
            }
            body = {
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens":  max_tokens,
                "temperature": 0.2,
            }

            for attempt in range(2):
                try:
                    r = requests.post(self.BASE_URL, headers=headers, json=body, timeout=30)
                    if r.status_code == 429:
                        if attempt == 0:
                            retry_after = int(r.headers.get("Retry-After", 30))
                            logger.warning("429 rate limit，等待 %ds 後重試", retry_after)
                            time.sleep(retry_after)
                            continue
                        logger.warning("429 rate limit，略過本次呼叫")
                        return None
                    r.raise_for_status()
                    GroqClient._last_call_ts = time.time()
                    return r.json()["choices"][0]["message"]["content"]
                except Exception as e:
                    if "429" in str(e) and attempt == 0:
                        logger.warning("429，等待 30s 後重試")
                        time.sleep(30)
                        continue
                    logger.error("API 呼叫失敗: %s", e)
                    return None
        return None

    def _parse_json(self, text: str) -> Optional[dict]:
        """從回應中解析 JSON（處理 markdown code block）。"""
        if not text:
            return None
        text = text.strip()
        if "```" in text:
            parts = text.split("```")
            for part in parts:
                part = part.strip()
                if part.startswith("json"):
                    part = part[4:].strip()
                try:
                    return json.loads(part)
                except Exception:
                    continue
        try:
            return json.loads(text)
        except Exception:
            return None

    # ── 公開分析介面 ───────────────────────────────────────────

    def analyze_news_batch(self, titles: list) -> Optional[dict]:
        """
        分析多則新聞標題的整體市場情緒。

        Returns:
            {mood, confidence, themes, summary}
            mood: "bullish" | "bearish" | "neutral"
            confidence: 1-10
            themes: list[str]
            summary: str（繁中，50字內）
        """
        if not self.is_available() or not titles:
            return None
        news_text = "\n".join(f"- {t}" for t in titles[:20])
        prompt = (
            "你是一個專業的台股市場分析師。請分析以下財經新聞標題，評估整體市場情緒。\n\n"
            f"新聞標題：\n{news_text}\n\n"
            "請以 JSON 格式回答，包含以下欄位：\n"
            '- mood: "bullish" | "bearish" | "neutral"（整體多空判斷）\n'
            "- confidence: 1-10（信心分數）\n"
            "- themes: 最多 3 個主要主題（字串陣列）\n"
            "- summary: 50 字以內的市場情緒摘要（繁體中文）\n\n"
            "只回傳 JSON，不要其他文字。"
        )
        return self._parse_json(self.generate(prompt, max_tokens=512))

    def analyze_single_news(self, title: str) -> Optional[dict]:
        """
        分析單則新聞對台股的情緒與影響。

        Returns:
            {sentiment, confidence, impact, reason}
        """
        if not self.is_available():
            return None
        prompt = (
            f"分析以下財經新聞標題對台股市場的影響：\n\n標題：{title}\n\n"
            "以 JSON 格式回答：\n"
            '- sentiment: "bullish" | "bearish" | "neutral"\n'
            "- confidence: 1-10\n"
            "- impact: 預期影響（最多 30 字，繁體中文）\n"
            "- reason: 判斷理由（最多 30 字，繁體中文）\n\n"
            "只回傳 JSON。"
        )
        return self._parse_json(self.generate(prompt, max_tokens=256))

    def analyze_news_sentiments(self, titles: list) -> Optional[list]:
        """
        分析多則新聞標題各自的情緒，一次 API 呼叫取得所有結果。

        Returns:
            list of "bullish"|"bearish"|"neutral"，順序對應 titles；或 None（API 不可用時）
        """
        if not self.is_available() or not titles:
            return None
        numbered = "\n".join(f"{i+1}. {t}" for i, t in enumerate(titles[:20]))
        prompt = (
            "你是台股市場分析師。請判斷以下每則財經新聞標題對台股的情緒。\n\n"
            f"新聞標題：\n{numbered}\n\n"
            "請以 JSON 陣列回答，每個元素對應一則新聞的情緒，值只能是 \"bullish\"、\"bearish\" 或 \"neutral\"。\n"
            f"陣列長度必須是 {len(titles[:20])}。\n"
            "範例（3則）：[\"bullish\", \"neutral\", \"bearish\"]\n\n"
            "只回傳 JSON 陣列，不要其他文字。"
        )
        result = self.generate(prompt, max_tokens=300)
        if not result:
            return None
        text = result.strip()
        if "```" in text:
            for part in text.split("```"):
                part = part.strip().lstrip("json").strip()
                try:
                    parsed = json.loads(part)
                    if isinstance(parsed, list):
                        return parsed
                except Exception:
                    continue
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return parsed
        except Exception:
            pass
        return None

    def generate_daily_summary(self, news_items: list, x_posts: list = None) -> Optional[str]:
        """
        根據新聞 + X 推文生成每日市場情報摘要（繁體中文）。

        Args:
            news_items: list of {title, sentiment}
            x_posts:    list of {content} (optional)
        """
        if not self.is_available():
            return None
        news_text = "\n".join(
            f"- [{n.get('sentiment','?')}] {n.get('title','')}"
            for n in news_items[:15]
        )
        x_section = ""
        if x_posts:
            x_section = "\n\nX/Twitter 熱門討論：\n" + "\n".join(
                f"- {p.get('content','')[:80]}" for p in x_posts[:5]
            )
        prompt = (
            "你是台股市場情報分析師。根據以下今日財經資訊，產生一份簡潔的市場情報摘要。\n\n"
            f"今日新聞：\n{news_text}{x_section}\n\n"
            "請產生（繁體中文，200 字以內）：\n"
            "1. 整體市場情緒（多頭/空頭/中性）及主因（1句）\n"
            "2. 3-5 個關鍵主題（條列）\n"
            "3. 對台股操作的建議方向（1-2句）"
        )
        return self.generate(prompt, max_tokens=600)
