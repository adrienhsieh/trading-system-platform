# trading/strategies/compositor.py
from trading.strategies import REGISTRY

class StrategyEngine:
    def run(self, strategy, df, code):
        # TODO: 實作不同策略
        return {"signal": "buy", "confidence": 0.85}


#class StrategyEngine:
#    def __init__(self):
#        self.strategies = REGISTRY
#
#    def run(self, strategy_name: str, df, code: str = ""):
#        if strategy_name not in self.strategies:
#            return {"ok": False, "error": f"策略 {strategy_name} 不存在"}
#        strat_cls = self.strategies[strategy_name]
#        strat = strat_cls()
#        result = strat.compute(df, code)
#        return {"ok": True, "strategy": strategy_name, "result": result}
#
#    def auto_select(self, market_state: str, df, code: str = ""):
#        # 簡單策略選擇邏輯
#        if market_state == "trend":
#            return self.run("trend", df, code)
#        elif market_state == "chip":
#            return self.run("fundamental", df, code)
#        else:
#            return self.run("ict", df, code)
#