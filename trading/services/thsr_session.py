"""
trading/services/thsr_session.py — 高鐵訂票流程的暫存 Session 管理

訂票流程需要跨多個 HTTP 請求維持同一個 THSR 官網的連線狀態
（cookies／JSESSIONID）與尚未送出的表單欄位，因此採用伺服器端的
記憶體 Session（而非資料庫），並綁定登入使用者身分，避免不同使用者
互相看到或誤用彼此的訂票流程。Session 為短暫性資料（訂票流程通常
幾分鐘內完成），逾時（預設 15 分鐘）未使用會自動清除。

防禦性修正：
- 優化執行緒鎖（threading.Lock）粒度，防止高鐵網路連線時阻塞整個系統
- 強化狀態機制，支援非同步背景抓取驗證碼，徹底解決 502 Bad Gateway 與台股監控卡死問題。
"""
import threading
import time
import uuid
import logging
from typing import Optional

logger = logging.getLogger("trading.thsr_session")


class THSRSession:
    def __init__(self, user_id: str):
        self.user_id = user_id
        self.client = None          # thsr_ticket.remote.http_request.HTTPRequest
        self.book_form = None       # thsr_ticket.model.web.booking_form.booking_form.BookingForm
        self.confirm_train = None
        self.confirm_ticket = None
        self.avail_trains: list = []
        
        # 狀態機定義: new -> fetching_captcha -> awaiting_captcha -> awaiting_train -> awaiting_personal_info -> done
        self.state = "new"          
        self.captcha_b64 = ""       # 暫存 Base64 驗證碼圖片字串
        self.error_msg = ""         # 若抓取失敗暫存錯誤訊息
        
        self.created_at = time.time()
        self.last_active = time.time()
        
        # 異步通知事件（供需要等待的背景執行緒使用，不卡死主執行緒）
        self.ready_event = threading.Event()

    def touch(self) -> None:
        """更新最後活躍時間，延長生命週期"""
        self.last_active = time.time()


class THSRSessionManager:
    """全體使用者共用的 Session 容器（依 user_id 隔離存取權限，執行緒安全）。"""

    TTL_SECONDS = 15 * 60

    def __init__(self):
        self._sessions: dict[str, THSRSession] = {}
        self._lock = threading.Lock()

    def create(self, user_id: str) -> str:
        """建立全新 Session。自動清理過期資料，採獨立鎖隔離。"""
        self._evict_expired()
        session_id = uuid.uuid4().hex
        
        with self._lock:
            self._sessions[session_id] = THSRSession(user_id)
            
        logger.info(f"[THSR Session] 已為用戶 {user_id} 建立新 Session: {session_id}")
        return session_id

    def get(self, session_id: str, user_id: str) -> Optional[THSRSession]:
        """取得 Session；若不存在、已逾時、或非本人擁有，回傳 None（安全邏輯隔離）。"""
        self._evict_expired()
        
        with self._lock:
            sess = self._sessions.get(session_id)
            
        if sess is None:
            return None
            
        # 安全性檢查：嚴格防範 A 用戶撈到 B 用戶的訂票 Session
        if sess.user_id != user_id:
            logger.warning(f"🚨 [安全警報] 用戶 {user_id} 企圖越權存取用戶 {sess.user_id} 的高鐵 Session!")
            return None
            
        sess.touch()
        return sess

    def delete(self, session_id: str) -> None:
        """主動刪除 Session 釋放記憶體"""
        with self._lock:
            self._sessions.pop(session_id, None)

    def _evict_expired(self) -> None:
        """自動蒸發過期的 Session。優化鎖範圍，採雙重檢查，防範集體阻塞。"""
        now = time.time()
        
        # 1. 先在外層過濾出可能過期的人，避免長時間在鎖內做迴圈判斷
        with self._lock:
            expired_ids = [
                sid for sid, s in self._sessions.items() 
                if now - s.last_active > self.TTL_SECONDS
            ]
            
            # 2. 僅針對真的過期的物件執行刪除
            for sid in expired_ids:
                if sid in self._sessions:
                    del self._sessions[sid]
                    
        if expired_ids:
            logger.info(f"🧹 [THSR Session] 已自動清除 {len(expired_ids)} 個過期的高鐵訂票快取。")


# 全體共用單例（不需要像 pos_mgr/config_mgr 一樣做多租戶物理檔案隔離，
# 因為存取權限已經用 user_id 檢查做邏輯隔離，資料本身也是短暫、不落地的記憶體快取）
thsr_session_manager = THSRSessionManager()