// static/js/user_config.js

#const USER_CONFIG_BASE_URL = 'http://localhost:8787/api/user_config';
const USER_CONFIG_BASE_URL = '/api/user_config';

/**
 * 🔍 讀取特定使用者在特定網頁模組的獨立設定
 * @param {string} userId - 使用者 ID (如 'jack')
 * @param {string} moduleId - 網頁模組 ID (如 'grid_trading')
 * @returns {Promise<object|null>} 傳回設定物件或 null
 */
async function getWebUserConfig(userId, moduleId) {
    try {
        const url = `${USER_CONFIG_BASE_URL}?user_id=${encodeURIComponent(userId)}&module_id=${encodeURIComponent(moduleId)}`;
        const response = await fetch(url, { method: 'GET' });
        
        if (!response.ok) throw new Error(`HTTP 錯誤！狀態碼: ${response.status}`);
        
        const jsonResult = await response.json();
        if (jsonResult.ok) {
            return jsonResult.data; // 💡 成功拿到後端的數據
        } else {
            console.error('後端回傳錯誤:', jsonResult.error);
            return null;
        }
    } catch (error) {
        console.error('讀取設定失敗:', error);
        return null;
    }
}

/**
 * 💾 儲存特定使用者的網頁獨立設定
 * @param {string} userId - 使用者 ID
 * @param {string} moduleId - 網頁模組 ID
 * @param {object} configs - 要儲存的自訂設定物件
 * @returns {Promise<boolean>} 是否儲存成功
 */
async function saveWebUserConfig(userId, moduleId, configs) {
    try {
        const url = `${USER_CONFIG_BASE_URL}/save`;
        const response = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                user_id: userId,
                module_id: moduleId,
                configs: configs
            })
        });

        if (!response.ok) throw new Error(`HTTP 錯誤！狀態碼: ${response.status}`);

        const jsonResult = await response.json();
        return jsonResult.ok === true;
    } catch (error) {
        console.error('儲存設定失敗:', error);
        return false;
    }
}
