# market_fetcher.py
import time
from datetime import datetime, time as datetime_time
import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

class TaiwanStockBackupFetcher:
    def __init__(self, targets, finmind_token=None):
        self.targets = targets
        self.finmind_token = finmind_token
        self.current_channel = "TWSE"
        self.twse_failure_count = 0
        self.finmind_failure_count = 0
        
        self.TWSE_FAILURE_THRESHOLD = 3
        self.FINMIND_FAILURE_THRESHOLD = 3
        self.TWSE_TICK_URL = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp"
        self.FINMIND_TICK_URL = "https://api.finmindtrade.com/api/v4/data"
        self.session = self._create_session_with_retry()
        print("TaiwanStockBackupFetcher 已建立") 

    def _create_session_with_retry(self):
        session = requests.Session()
        retry = Retry(total=3, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504])
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session

    def get_market_status(self):
        now = datetime.now()
        print("get_market_status 已啟動")
        if now.weekday() >= 5:
            return "WEEKEND"
        current_time = now.time()
        if datetime_time(8, 30) <= current_time <= datetime_time(13, 35):
            return "TRADING_HOURS"
        elif datetime_time(13, 35) < current_time <= datetime_time(15, 0):
            return "POST_MARKET"
        else:
            return "OFF_HOURS"

    def reset_channel_if_needed(self):
        """夜間或開盤前由主系統呼叫，重置通道"""
        if self.current_channel != "TWSE":
            self.current_channel = "TWSE"
            self.twse_failure_count = 0
            print("🔄 [備援模組] 已自動重置為預設通道 [TWSE Official]。")

    def fetch_data(self) -> dict:
        """
        主功能：獲取最新價格。
        回傳標準格式，例如：{'2330': {'price': 930.0, 'source': 'TWSE_Official'}, ...}
        """
        status = self.get_market_status()
        print("fetch_data 已啟動")
        if status != "TRADING_HOURS":
            return {} # 非盤中時間，不進行高頻請求

        output_list = []
        sys_date = datetime.now().strftime("%Y-%m-%d")
        sys_time = datetime.now().strftime("%H:%M:%S")

        # ---- 通道 1: TWSE ----
        if self.current_channel == "TWSE":
            try:
                ex_ch_list = [f"tse_{code}.tw" for code in self.targets]
                params = {"ex_ch": "|".join(ex_ch_list), "_": int(time.time() * 1000)}
                response = self.session.get(self.TWSE_TICK_URL, params=params, timeout=5)
                if response.status_code == 200:
                    data = response.json()
                    if "msgArray" in data and data["msgArray"]:
                        for msg in data["msgArray"]:
                            stock_code = msg.get("c")
                            price_str = msg.get("z")
                            if not price_str or price_str == "-":
                                b_list = msg.get("b", "").split("_")
                                price_str = b_list[0] if b_list and b_list[0] and b_list[0] != "-" else msg.get("y")
                            output_list.append({
                                "stock_code": stock_code, "price": float(price_str) if price_str else 0.0,
                                "volume": int(msg.get("v", 0)) if msg.get("v") else 0, "source": "TWSE_Official"
                            })
            except Exception as e:
                print(f"🚨 TWSE 異常: {e}")

        # ---- 通道 2: FinMind ----
        elif self.current_channel == "FinMind":
            try:
                headers = {"Authorization": f"Bearer {self.finmind_token}"} if self.finmind_token else {}
                for stock_code in self.targets:
                    params = {"dataset": "TaiwanStockPrice", "data_id": stock_code, "start_date": sys_date}
                    response = self.session.get(self.FINMIND_TICK_URL, headers=headers, params=params, timeout=5)
                    if response.status_code == 200:
                        records = response.json().get("data", [])
                        if not records:
                            params["start_date"] = (pd.Timestamp(sys_date) - pd.Timedelta(days=5)).strftime("%Y-%m-%d")
                            records = self.session.get(self.FINMIND_TICK_URL, headers=headers, params=params, timeout=5).json().get("data", [])
                        if records:
                            latest = records[-1]
                            output_list.append({
                                "stock_code": stock_code, "price": float(latest.get("close", 0)),
                                "volume": int(latest.get("volume", 0)), "source": "FinMind_API"
                            })
            except Exception as e:
                print(f"🚨 FinMind 異常: {e}")

        # ---- 通道 3: YFinance ----
        elif self.current_channel == "YFinance":
            try:
                import yfinance as yf
                for stock_code in self.targets:
                    ticker = yf.Ticker(f"{stock_code}.TW")
                    hist = ticker.history(period="1d")
                    if hist.empty: hist = ticker.history(period="5d")
                    if not hist.empty:
                        latest = hist.iloc[-1]
                        output_list.append({
                            "stock_code": stock_code, "price": float(latest['Close']),
                            "volume": int(latest['Volume']), "source": "YFinance_Fallback"
                        })
            except Exception as e:
                print(f"🚨 YFinance 異常: {e}")

        # ---- 狀態機維護：通道狀態切換 ----
        if self.current_channel == "TWSE":
            if output_list: self.twse_failure_count = 0
            else:
                self.twse_failure_count += 1
                if self.twse_failure_count >= self.TWSE_FAILURE_THRESHOLD:
                    self.current_channel = "FinMind"
                    print("🚨 TWSE 連續失敗，自動切換至 [通道 2: FinMind]")
        elif self.current_channel == "FinMind":
            if output_list: self.finmind_failure_count = 0
            else:
                self.finmind_failure_count += 1
                if self.finmind_failure_count >= self.FINMIND_FAILURE_THRESHOLD:
                    self.current_channel = "YFinance"
                    print("🚨 FinMind 連續失敗，自動切換至 [通道 3: YFinance]")

        # 轉換為 dict 格式方便主系統 O(1) 查詢
        return {item['stock_code']: {"price": item['price'], "volume": item['volume'], "source": item['source']} for item in output_list}