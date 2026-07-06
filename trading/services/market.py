class MarketService:
    def __init__(self):
        # 股票代碼快取
        self.cache = {}

    def update_cache(self, data: dict):
        # data 格式: { "2330.TW": {...}, "2303.TW": {...} }
        self.cache.update(data)

    def get_data(self):
        return self.cache

    def get_stock_info(self, code: str):
        # 支援不同代碼格式
        if code in self.cache:
            return self.cache[code]
        elif f"{code}.TW" in self.cache:
            return self.cache[f"{code}.TW"]
        elif f"{code}.TWO" in self.cache:
            return self.cache[f"{code}.TWO"]
        return None
