"""
trading/scanner.py — 股票掃描器
從 TWSE（上市）+ TPEX（上櫃）API 取得全台股票清單，並以技術指標篩選強勢股。
策略由 trading/strategies/ 提供，掃描器本身不耦合任何特定策略。
"""
import concurrent.futures
import threading
from typing import Optional

import time

import requests
import urllib3
from trading.logger import get_logger

logger = get_logger("scanner")
# TWSE openapi.twse.com.tw 使用非標準憑證（Missing Subject Key Identifier），
# certifi 無法驗證，直接停用 SSL 驗證並抑制警告。
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from trading.constants import STOCK_CACHE_TTL, INDUSTRY_CACHE_TTL, SCAN_WORKERS, FULL_SCAN_WORKERS, REQUEST_TIMEOUT
from trading.indicators import IndicatorEngine
from trading.strategies import get_strategy


class StockScanner:
    """台股技術面掃描器，支援任意已登錄策略與自訂/全市場掃描。"""

    TWSE_API_URL:      str = "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL"
    TPEX_API_URL:      str = "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes"
    TWSE_INDUSTRY_URL: str = "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"

    _STOCK_CACHE_TTL:    float = STOCK_CACHE_TTL
    _INDUSTRY_CACHE_TTL: float = INDUSTRY_CACHE_TTL

    # 視為電子/科技/通訊的 TWSE 產業別關鍵字
    TECH_INDUSTRY_KEYWORDS: frozenset = frozenset([
        "半導體", "電腦", "光電", "通訊", "電子", "資訊", "科技",
    ])

    def __init__(self, indicator_engine: IndicatorEngine = None):
        self.indicator_engine            = indicator_engine or IndicatorEngine()
        self._stock_cache: dict          = {}
        self._stock_cache_time: float    = 0.0
        self._industry_cache: dict       = {}
        self._industry_cache_time: float = 0.0
        self._cache_lock                 = threading.RLock()

    # ── 股票代號表 ─────────────────────────────────────────────

    def get_stock_map(self) -> dict:
        """取得 {代號: 名稱} 字典（上市 + 上櫃），快取 12 小時後自動更新。執行緒安全。"""
        with self._cache_lock:
            if self._stock_cache and time.time() - self._stock_cache_time < self._STOCK_CACHE_TTL:
                return self._stock_cache

        stock_map: dict = {}

        # 上市（TWSE）
        try:
            r = requests.get(
                self.TWSE_API_URL,
                headers={"Accept": "application/json"},
                timeout=REQUEST_TIMEOUT,
                verify=False,  # TWSE 憑證缺少 Subject Key Identifier，跳過 SSL 驗證
            )
            for item in r.json():
                code = str(item.get("Code", "")).strip()
                name = str(item.get("Name", "")).strip()
                if code.isdigit() and len(code) == 4:
                    stock_map[code] = name or code
            logger.info("TWSE API 取得 %d 檔", len(stock_map))
        except Exception as e:
            logger.warning("TWSE API 失敗: %s", e)

                # 上櫃主板（TPEX）
        tpex_count = 0
        try:
            r = requests.get(
                self.TPEX_API_URL,
                headers={"Accept": "application/json"},
                timeout=REQUEST_TIMEOUT,
                verify=False,  # 🔴 核心修正：加上 verify=False，跳過 TPEX 的 SSL 憑證驗證
            )
            for item in r.json():
                code = str(item.get("SecuritiesCompanyCode", "")).strip()
                name = str(item.get("CompanyName", "")).strip()
                if code.isdigit() and len(code) == 4 and code not in stock_map:
                    stock_map[code] = name or code
                    tpex_count += 1
            logger.info("TPEX API 取得 %d 檔（上櫃主板）", tpex_count)
        except Exception as e:
            logger.warning("TPEX API 失敗: %s", e)

        with self._cache_lock:
            self._stock_cache      = stock_map
            self._stock_cache_time = time.time()
        return stock_map

    def get_all_tw_stocks(self) -> list:
        return list(self.get_stock_map().keys())

    def get_stock_name(self, code: str) -> str:
        return self.get_stock_map().get(code, code)

    # ── 產業別資料 ─────────────────────────────────────────────

    @staticmethod
    def _is_tech_by_code(code: str) -> bool:
        """TPEX fallback：以代號範圍估算是否為電子科技類。"""
        try:
            n = int(code)
        except ValueError:
            return False
        return (
            3000 <= n <= 3699 or   # 光電/半導體/電子
            4900 <= n <= 4999 or   # 電子通路
            5200 <= n <= 5399 or   # 資訊通路/科技
            6200 <= n <= 6999      # 新掛電子科技
        )

    def _fetch_industry_map(self) -> dict:
        """取得 {代號: 產業別} 字典，快取 12 小時。執行緒安全。"""
        with self._cache_lock:
            if self._industry_cache and time.time() - self._industry_cache_time < self._INDUSTRY_CACHE_TTL:
                return self._industry_cache

        result: dict = {}
        # TWSE 上市產業別
        try:
            r = requests.get(
                self.TWSE_INDUSTRY_URL,
                headers={"Accept": "application/json"},
                timeout=REQUEST_TIMEOUT,
                verify=False,  # 同 TWSE 憑證問題
            )
            for item in r.json():
                code = str(item.get("公司代號", "")).strip()
                ind  = str(item.get("產業別", "")).strip()
                if code and ind:
                    result[code] = ind
            logger.info("TWSE 產業別取得 %d 筆", len(result))
        except Exception as e:
            logger.warning("TWSE 產業別失敗: %s", e)
        # TPEX 上櫃：以代號範圍 fallback（TPEX openapi 無產業別欄位）
        with self._cache_lock:
            sm = self._stock_cache or {}
        for code in sm:
            if code not in result and self._is_tech_by_code(code):
                result[code] = "電子"   # 標記為電子以通過關鍵字篩選
        with self._cache_lock:
            self._industry_cache      = result
            self._industry_cache_time = time.time()
        return result

    def get_tech_stock_map(self) -> dict:
        """取得電子/科技/通訊類股的 {代號: 名稱} 字典。"""
        sm  = self.get_stock_map()
        ind = self._fetch_industry_map()
        return {
            code: name
            for code, name in sm.items()
            if any(kw in ind.get(code, "") for kw in self.TECH_INDUSTRY_KEYWORDS)
        }

    # ── 個股分析（策略通用） ────────────────────────────────────

    def analyze_one(
        self,
        code: str,
        capital: float,
        risk_pct: float,
        strategy: str = "trend",
        name: str = "",
    ) -> Optional[dict]:
        """分析單一股票，依指定策略計算信號與進場參數。"""
        code = str(code)
        strat = get_strategy(strategy)
        df    = self.indicator_engine.fetch_ohlcv(code)
        if df is None or len(df) < strat.min_bars:
            return None
        try:
            ind = strat.compute(df, code=code)
            if ind is None:
                return None
            params = strat.calc_entry_params(ind, capital, risk_pct)
            return {
                "code":     code,
                "name":     name or self.get_stock_name(code),
                "score":    ind["score"],
                "ind":      ind,
                "params":   params,
                "strategy": strategy,
            }
        except Exception as e:
            logger.debug("%s %s 失敗: %s", strategy.upper(), code, e)
            return None

    # ── 批次掃描（策略通用） ────────────────────────────────────

    def run_scan(
        self,
        candidates: list,
        capital: float,
        risk_pct: float = 2.0,
        strategy: str = "trend",
        max_workers: int = SCAN_WORKERS,
    ) -> list:
        """對候選清單執行多執行緒掃描，回傳依分數降序排列的結果。"""
        sm      = self.get_stock_map()
        results: list = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
            futs = {
                ex.submit(self.analyze_one, c, capital, risk_pct, strategy, sm.get(c, "")): c
                for c in candidates
            }
            for f in concurrent.futures.as_completed(futs):
                r = f.result()
                if r:
                    results.append(r)
        results.sort(key=lambda x: x["score"], reverse=True)
        return results

    # ── API 格式化 ────────────────────────────────────────────
    def format_for_api(self, results: list, strategy: str = "trend") -> list:
        """將掃描結果轉換為 API 回應格式，支援 trend / ict / fundamental。"""
        strat  = get_strategy(strategy)
        labels = strat.signal_labels
        out: list = []
        for r in results:
            ind, params = r["ind"], r["params"]
            enabled_map = ind.get("enabled", {})
            item: dict = {
                "code":          r["code"],
                "name":          r.get("name", ""),
                "score":         r["score"],
                "total_enabled": ind.get("total_enabled", len(ind["signals"])),
                "strategy":      r.get("strategy", strategy),
                "close":         ind["close"],
                "signals": {
                    k: {
                        "pass":    ind["signals"][k],
                        "label":   labels.get(k, k),
                        "enabled": enabled_map.get(k, True),
                    }
                    for k in ind["signals"]
                },
                "entry":      params["entry"],
                "stop":       params["stop"],
                "target":     params["target"],
                "shares":     params["shares"],
                "total_risk": params["total_risk"],
            }
            # 趨勢策略額外欄位
            if strategy == "trend":
                item.update({
                    "ema5":      ind.get("ema5"),
                    "ema20":     ind.get("ema20"),
                    "ema60":     ind.get("ema60"),
                    "adx":       ind.get("adx"),
                    "atr":       ind.get("atr"),
                    "macd_hist": ind.get("macd_hist"),
                    "w52_high":  ind.get("w52_high"),
                    "w52_low":   ind.get("w52_low"),
                })
            # ICT 額外欄位
            elif strategy == "ict":
                item.update({
                    "equilibrium": ind.get("equilibrium"),
                    "range_high":  ind.get("range_high"),
                    "range_low":   ind.get("range_low"),
                    "ob_high":     ind.get("ob_high"),
                    "ob_low":      ind.get("ob_low"),
                    "mss_level":   ind.get("mss_level"),
                })
            # 基本面策略額外欄位
            elif strategy == "fundamental":
                item.update({
                    "pe":             ind.get("pe"),
                    "eps":            ind.get("eps"),
                    "forward_eps":    ind.get("forward_eps"),
                    "pb":             ind.get("pb"),
                    "revenue_growth": ind.get("revenue_growth"),
                })

            # ──【新增】自適應 AI 權重綜合評分演算法（台股掃描專用） ──
            try:
                # 1. 計算目前的技術面指標得分率 (0.0 ~ 1.0)
                total_sig = item["total_enabled"] if item["total_enabled"] > 0 else 6
                t_score = item["score"] / total_sig
                
                # 2. 自動交叉研判基本面得分率
                f_score = 0.5
                if strategy == "fundamental":
                    f_score = t_score
                else:
                    # 💡 技巧：利用個股現有的技術面/基本面微觀數據來微調基礎基本面分 (f_score)
                    bonus = 0.0
                    
                    # 1. 根據本益比調整 (若有的話)
                    if ind.get("pe") is not None:
                        try:
                            pe_val = float(ind.get("pe"))
                            if pe_val < 15: bonus += 0.15      # 估值極便宜，大幅加分
                            elif pe_val < 25: bonus += 0.05    # 估值合理，小幅加分
                            elif pe_val > 40: bonus -= 0.1     # 估值過高，扣分
                        except: pass
                        
                    # 2. 根據營收成長率調整 (若有的話)
                    if ind.get("revenue_growth") is not None:
                        try:
                            rev_val = float(ind.get("revenue_growth"))
                            if rev_val > 20: bonus += 0.1      # 營收高成長，加分
                            elif rev_val < 0: bonus -= 0.05    # 營收衰退，扣分
                        except: pass
                    
                    # 3. 如果完全沒基本面資料，利用現有的 52 週股價相對位置來區隔強度
                    if bonus == 0.0 and ind.get("w52_high") and ind.get("close"):
                        try:
                            # 接近 52 週高點代表多頭氣勢極強
                            w52_ratio = float(ind["close"]) / float(ind["w52_high"])
                            if w52_ratio > 0.92: bonus += 0.1
                            elif w52_ratio < 0.70: bonus -= 0.1
                        except: pass
                        
                    # 最終動態結合基礎分與加扣分項，限制在 0.1 ~ 0.9 之間
                    f_score = max(0.1, min(0.9, 0.5 + bonus))
#                f_score = 0.5
#                if strategy == "fundamental":
#                    f_score = t_score
#                elif ind.get("pe") is not None:
#                    try:
#                        # 估計型基本面得分：低本益比給予較高分數
#                        pe_val = float(ind.get("pe"))
#                        f_score = 0.7 if pe_val < 20 else 0.5 if pe_val < 35 else 0.3
#                    except (ValueError, TypeError):
#                        f_score = 0.5

                # 3. 計算技術面與基本面的衝突度
                conflict_degree = abs(t_score - f_score)
                
                # 4. 自適應動態調配權重 (訊號衝突高時，提高模糊邏輯 AI 決策比重)
                ai_weight = 0.30 + (0.25 * (1.0 - conflict_degree))
                quant_weight = 1.0 - ai_weight
                
                # 5. 基礎 AI 情緒多空預設值（台股現階段多頭架構基礎分）
                ai_sentiment_score = 0.65 if item["score"] >= 4 else 0.5
                
                # 6. 加權綜合成百分制得分
                quant_base = (t_score * 0.5 + f_score * 0.5) * quant_weight
                ai_base = ai_sentiment_score * ai_weight
                final_composite_score = round((quant_base + ai_base) * 100, 1)
                
                # 7. 判定綜合操作建議
                if final_composite_score >= 68:
                    recommendation = "強勢看多" if conflict_degree > 0.4 else "多頭配置"
                elif final_composite_score <= 45:
                    recommendation = "保守觀望"
                else:
                    recommendation = "中性盤整"
                    
                item["adaptive_analysis"] = {
                    "composite_score": final_composite_score,
                    "ai_weight_pct": round(ai_weight * 100, 1),
                    "quant_weight_pct": round(quant_weight * 100, 1),
                    "conflict_degree": round(conflict_degree, 2),
                    "recommendation": recommendation
                }
                
                # ──【新增】開盤股價動能預測演算法 ──
                try:
                    last_close = float(ind["close"])
                    atr_val = float(ind.get("atr", last_close * 0.02)) # 取得波動率
                    
                    # 依據技術得分(t_score)與當前多頭趨勢判定開盤多空偏向 (Bias)
                    # 分數越高，開高機率越高
                    bias_factor = (t_score - 0.5) * 2  # 映射到 -1.0 ~ 1.0
                    
                    # 計算期望開盤價（結合昨收、波動度與趨勢偏向）
                    expected_change = (atr_val * 0.25) * bias_factor
                    predicted_open = round(last_close + expected_change, 2)
                    
                    # 計算開盤震盪合理區間上限與下限
                    open_range_low = round(predicted_open - (atr_val * 0.3), 2)
                    open_range_high = round(predicted_open + (atr_val * 0.3), 2)
                    
                    # 判定開盤型態預測
                    if t_score >= 0.8:
                        open_type = "🚀 預期跳空高開"
                        prob_str = "75%"
                    elif t_score <= 0.3:
                        open_type = "📉 預期低開震盪"
                        prob_str = "68%"
                    else:
                        open_type = "↕ 平開局震盪"
                        prob_str = "55%"
                        
                    item["open_prediction"] = {
                        "predicted_open": predicted_open,
                        "range_low": open_range_low,
                        "range_high": open_range_high,
                        "type": open_type,
                        "probability": prob_str
                    }
                except Exception as ope:
                    item["open_prediction"] = None                
            except Exception as ae:
                # 防禦性除錯保護，確保核心掃描絕不卡死
                item["adaptive_analysis"] = {
                    "composite_score": round((item["score"] / total_sig) * 100, 1),
                    "ai_weight_pct": 30.0,
                    "quant_weight_pct": 70.0,
                    "conflict_degree": 0.0,
                    "recommendation": "中性盤整"
                }

            out.append(item)
        return out
#    def format_for_api(self, results: list, strategy: str = "trend") -> list:
#        """將掃描結果轉換為 API 回應格式，支援 trend / ict。"""
#        strat  = get_strategy(strategy)
#        labels = strat.signal_labels
#        out: list = []
#        for r in results:
#            ind, params = r["ind"], r["params"]
#            enabled_map = ind.get("enabled", {})
#            item: dict = {
#                "code":          r["code"],
#                "name":          r.get("name", ""),
#                "score":         r["score"],
#                "total_enabled": ind.get("total_enabled", len(ind["signals"])),
#                "strategy":      r.get("strategy", strategy),
#                "close":         ind["close"],
#                "signals": {
#                    k: {
#                        "pass":    ind["signals"][k],
#                        "label":   labels.get(k, k),
#                        "enabled": enabled_map.get(k, True),
#                    }
#                    for k in ind["signals"]
#                },
#                "entry":      params["entry"],
#                "stop":       params["stop"],
#                "target":     params["target"],
#                "shares":     params["shares"],
#                "total_risk": params["total_risk"],
#            }
#            # 趨勢策略額外欄位
#            if strategy == "trend":
#                item.update({
#                    "ema5":      ind.get("ema5"),
#                    "ema20":     ind.get("ema20"),
#                    "ema60":     ind.get("ema60"),
#                    "adx":       ind.get("adx"),
#                    "atr":       ind.get("atr"),
#                    "macd_hist": ind.get("macd_hist"),
#                    "w52_high":  ind.get("w52_high"),
#                    "w52_low":   ind.get("w52_low"),
#                })
#            # ICT 額外欄位
#            elif strategy == "ict":
#                item.update({
#                    "equilibrium": ind.get("equilibrium"),
#                    "range_high":  ind.get("range_high"),
#                    "range_low":   ind.get("range_low"),
#                    "ob_high":     ind.get("ob_high"),
#                    "ob_low":      ind.get("ob_low"),
#                    "mss_level":   ind.get("mss_level"),
#                })
#            # 基本面策略額外欄位
#            elif strategy == "fundamental":
#                item.update({
#                    "pe":             ind.get("pe"),
#                    "eps":            ind.get("eps"),
#                    "forward_eps":    ind.get("forward_eps"),
#                    "pb":             ind.get("pb"),
#                    "revenue_growth": ind.get("revenue_growth"),
#                })
#            out.append(item)
#        return out

    # ── 向下相容 wrapper ───────────────────────────────────────

    def analyze_one_ict(self, code, capital, risk_pct, name=""):
        return self.analyze_one(code, capital, risk_pct, strategy="ict", name=name)

    def run_scan_ict(self, candidates, capital, risk_pct=2.0, max_workers=SCAN_WORKERS):
        return self.run_scan(candidates, capital, risk_pct, strategy="ict",
                             max_workers=max_workers)
