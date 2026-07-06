"""
trading/config.py — 設定管理
讀寫 config.json，統一管理全域設定。
"""
import json
import logging
import secrets
import threading
from pathlib import Path
from trading.constants import CONSECUTIVE_LOSS_THRESHOLD, DEFAULT_RISK_PCT, REDUCED_RISK_PCT


_write_lock = threading.Lock()
_logger = logging.getLogger("trading.config")


def _deep_merge(base: dict, override: dict) -> dict:
    """遞迴合併兩個 dict，override 的值覆蓋 base，巢狀 dict 保留 base 的預設值。"""
    result = dict(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


class ConfigManager:
    """管理 config.json 的讀寫與預設值。"""

    DEFAULTS: dict = {
        "total_capital":      3_000_000,
        "consecutive_losses": 0,
        "risk_mode":          "normal",   # "normal" | "slowdown"
        "scan_candidates":    [],
        "api_key":            "",           # 空字串表示待產生
        "strategy_params": {
            "trend": {
                "ema_arrangement": {"enabled": True},
                "slopes_up":       {"enabled": True},
                "adx_above_25":    {"enabled": True, "threshold": 25},
                "macd_positive":   {"enabled": True},
                "volume_spike":    {"enabled": True, "threshold": 1.5},
                "ema_crossover":   {"enabled": True},
            },
            "ict": {
                "bullish_ob":      {"enabled": True},
                "fvg_present":     {"enabled": True},
                "bos":             {"enabled": True},
                "liquidity_sweep": {"enabled": True},
                "discount_zone":   {"enabled": True},
                "ote_zone":        {"enabled": True, "fib_low": 0.618, "fib_high": 0.786},
                "mss":             {"enabled": True},
            },
            "fundamental": {
                "pe_reasonable":   {"enabled": True, "threshold": 30},
                "eps_positive":    {"enabled": True},
                "eps_growth":      {"enabled": True},
                "pb_reasonable":   {"enabled": True, "threshold": 2.5},
                "revenue_growth":  {"enabled": True},
            },
        },
    }

    def __init__(self, config_file: Path = None):
        self.config_file = config_file or Path(__file__).parent.parent / "config.json"

    # ── 公開介面 ───────────────────────────────────────────────

    def load(self) -> dict:
        """讀取設定，缺少的 key 補上預設值（巢狀 dict 深度合併）。首次執行時自動產生 api_key。"""
        cfg = _deep_merge({}, self.DEFAULTS)
        if self.config_file.exists():
            with open(self.config_file, encoding="utf-8") as f:
                cfg = _deep_merge(cfg, json.load(f))
        # 自動同步 risk_mode
        cfg["risk_mode"] = "slowdown" if cfg.get("consecutive_losses", 0) >= 3 else "normal"
        # 首次啟動自動產生 api_key（double-checked locking 防止 race condition）
        if not cfg.get("api_key"):
            with _write_lock:
                # Re-read inside the lock to prevent TOCTOU race
                if self.config_file.exists():
                    with open(self.config_file, encoding="utf-8") as f:
                        stored = _deep_merge(_deep_merge({}, self.DEFAULTS), json.load(f))
                    cfg["api_key"] = stored.get("api_key", "")
                if not cfg.get("api_key"):
                    cfg["api_key"] = secrets.token_hex(32)
                    # Write directly (already hold the lock; calling self.save() would deadlock)
                    self.config_file.parent.mkdir(parents=True, exist_ok=True)
                    with open(self.config_file, "w", encoding="utf-8") as f:
                        json.dump(cfg, f, ensure_ascii=False, indent=2)
                    _logger.warning("[Config] 首次啟動：已自動產生 API Key，請從 config.json 讀取")
        return cfg

    def save(self, cfg: dict) -> None:
        """寫回 config.json（thread-safe）。"""
        with _write_lock:
            self.config_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_file, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)

    def update(self, data: dict) -> dict:
        """部分更新設定並存檔，回傳更新後的設定。"""
        cfg = self.load()
        for k in ("total_capital", "consecutive_losses", "scan_candidates", "strategy_params"):
            if k in data:
                cfg[k] = data[k]
        cfg["risk_mode"] = "slowdown" if cfg["consecutive_losses"] >= 3 else "normal"
        self.save(cfg)
        return cfg

    # ── 常用屬性 ───────────────────────────────────────────────

    @property
    def risk_pct(self) -> float:
        """依連續虧損次數決定每筆風險百分比（%）。"""
        cfg = self.load()
        return 1.0 if cfg.get("consecutive_losses", 0) >= 3 else 2.0

    @property
    def total_capital(self) -> float:
        return float(self.load().get("total_capital", self.DEFAULTS["total_capital"]))

    @property
    def scan_candidates(self) -> list:
        return self.load().get("scan_candidates", [])
