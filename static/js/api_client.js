/**
 * 交易系統多人版：全域網路通訊攔截器 (API 封裝模組)
 * 負責自動注入 JWT 憑證、高頻過期過濾，以及異常攔截
 */
const API = {
    /**
     * 底層核心攔截器 Request
     */
    async request(url, options = {}) {
        // 1. 【攔截請求】：自動從瀏覽器緩存取出剛才登入發放的 JWT
        const token = localStorage.getItem('trade_sys_jwt');
        
        // 2. 建立預設的核心 Headers 結構
        const headers = {
            'Content-Type': 'application/json',
            ...options.headers
        };
        
        // 3. 【憑證注入】：如果 Token 存在，自動加上 Bearer 安全鎖頭
        if (token) {
            headers['Authorization'] = `Bearer ${token}`;
        }
        
        const config = {
            ...options,
            headers
        };
        
        try {
            // 4. 發出網路請求
            const response = await fetch(url, config);
            
            // 5. 【攔截回應】：若後端回傳 401（憑證過期或無效），強制清除快取並導回登入頁面
            if (response.status === 401) {
                console.warn("⚠️ JWT 憑證已過期或失效，自動清除 LocalStorage 並引導至登入頁面。");
                localStorage.removeItem('trade_sys_jwt');
                window.location.href = '/login.html'; // 💡 請確保您的專案有對應的登入頁面路徑
                return null;
            }
            
            // 6. 如果是其他 HTTP 錯誤（如 400, 500），拋出錯誤
            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                throw new Error(errorData.error || `伺服器回應錯誤 (狀態碼: ${response.status})`);
            }
            
            // 7. 驗證完全通過，將後端已經「自動補齊 api_key」的完整 JSON 數據解出回傳
            return await response.json();
            
        } catch (error) {
            console.error(`❌ API 請求失敗 [${options.method || 'GET'} -> ${url}]:`, error.message);
            throw error;
        }
    },

    // 💡 提供給專案各分頁 JavaScript 呼叫的快捷方法
    async get(url) { return this.request(url, { method: 'GET' }); },
    async post(url, body) { return this.request(url, { method: 'POST', body: JSON.stringify(body) }); },
    async delete(url) { return this.request(url, { method: 'DELETE' }); }
};
