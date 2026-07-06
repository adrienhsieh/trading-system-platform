"""
trading/constants.py — 集中管理全系統魔法數字
修改數值時只需改此檔，不必搜尋各模組。
"""

# ── 掃描器 ─────────────────────────────────────────────────────
SCAN_WORKERS          = 16    # ThreadPoolExecutor 最大工作執行緒數（候選清單掃描）
FULL_SCAN_WORKERS     = 2     # 全市場 SSE 掃描（避免 yfinance rate limit）
POSITION_FETCH_WORKERS = 10   # 持倉報價並行抓取

# ── 快取 TTL（秒） ──────────────────────────────────────────────
MARKET_CACHE_TTL      = 300          # MarketService：5 分鐘
STOCK_CACHE_TTL       = 12 * 3600    # StockScanner：12 小時
INDUSTRY_CACHE_TTL    = 12 * 3600    # StockScanner 產業別：12 小時

# ── 網路請求 ───────────────────────────────────────────────────
REQUEST_TIMEOUT       = 15    # requests.get() 逾時秒數
YFINANCE_RETRY_COUNT  = 2     # yfinance fetch 最大重試次數（含首次，共試 2 次）
YFINANCE_MIN_INTERVAL = 0.5   # 相鄰兩次 yfinance 呼叫的最短間隔（秒），防 rate limit

# ── 風險管理 ───────────────────────────────────────────────────
CONSECUTIVE_LOSS_THRESHOLD = 3      # 連虧達此次數後切換為 1% 風險模式
DEFAULT_RISK_PCT           = 2.0    # 預設單筆風險百分比
REDUCED_RISK_PCT           = 1.0    # 連虧後降低的風險百分比

# ── 回測 ───────────────────────────────────────────────────────
DEFAULT_COMMISSION_PCT = 0.001425   # 預設手續費率（台股券商費率）
DEFAULT_SLIPPAGE_PCT   = 0.0005     # 預設滑價率
DEFAULT_CAPITAL        = 1_000_000  # 預設回測資金（元）
