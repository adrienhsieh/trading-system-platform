"""trading/logger.py — 集中式日誌工廠。"""
import logging
import os


def get_logger(name: str) -> logging.Logger:
    """回傳 trading.<name> logger，首次呼叫時附加 StreamHandler。"""
    logger = logging.getLogger(f"trading.{name}")
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(
            "%(asctime)s [%(name)s] %(levelname)s %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
        logger.addHandler(handler)
        logger.propagate = False
    return logger


def setup_root_level() -> None:
    """依 LOG_LEVEL 環境變數設定根層級（預設 INFO）。呼叫一次即可。"""
    level = os.environ.get("LOG_LEVEL", "INFO").upper()
    logging.getLogger("trading").setLevel(getattr(logging, level, logging.INFO))
