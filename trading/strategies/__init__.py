"""
trading/strategies/__init__.py — 策略登錄表
新增策略只需：
  1. 建立 trading/strategies/my_strategy.py 並繼承 BaseStrategy
  2. 在此 REGISTRY 加一行
"""
from trading.strategies.trend import TrendStrategy
from trading.strategies.ict import ICTStrategy
from trading.strategies.fundamental import FundamentalStrategy

REGISTRY: dict = {
    "trend":       TrendStrategy(),
    "ict":         ICTStrategy(),
    "fundamental": FundamentalStrategy(),
}


def get_strategy(name: str):
    """依名稱取得策略實例，不存在時回傳 TrendStrategy。"""
    return REGISTRY.get(name, REGISTRY["trend"])
