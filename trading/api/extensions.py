"""
trading/api/extensions.py — Flask 擴充套件（使用 init_app 模式，避免循環 import）
"""
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

limiter = Limiter(
    get_remote_address,
    default_limits=["200 per minute"],
    storage_uri="memory://",
)
