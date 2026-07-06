"""
trading/strategies/base.py — 策略基底類別
所有策略繼承 BaseStrategy，實作 compute() 與 calc_entry_params()。
"""
from abc import ABC, abstractmethod
from typing import Optional

import pandas as pd


class BaseStrategy(ABC):
    """策略介面：每個策略必須提供名稱、信號標籤、計算與進場參數方法。"""

    name: str = ""          # 唯一識別鍵，例如 "trend" / "ict"
    label: str = ""         # 顯示名稱，例如 "趨勢策略"
    min_bars: int = 30      # 最少需要的 K 棒數量
    signal_labels: dict = {}

    @abstractmethod
    def compute(self, df: pd.DataFrame, code: str = "") -> Optional[dict]:
        """計算信號，回傳含 signals / score 的字典；資料不足時回傳 None。
        code 為股票代號，基本面策略需要此參數取得財務資料。"""

    @abstractmethod
    def calc_entry_params(self, ind: dict, capital: float, risk_pct: float = 2.0) -> dict:
        """依指標結果計算進場價、停損價、目標價與建議股數。"""
