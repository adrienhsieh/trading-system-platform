/**
 * static/js/thsr.js — 高鐵訂票頁簽（修正版）
 * 修正了 API 路徑對齊與防禦性錯誤處理。
 */

let thsrSessionId = null;
let thsrInitialized = false;

async function initThsrTab() {
    if (thsrInitialized) return;
    thsrInitialized = true;
    await thsrLoadStations();
    const dateInput = document.getElementById('thsr-date');
    if (dateInput) {
        const tomorrow = new Date(Date.now() + 24 * 3600 * 1000);
        dateInput.value = tomorrow.toISOString().slice(0, 10);
    }
}

async function thsrLoadStations() {
    try {
        const r = await api('GET', '/api/thsr/stations');
        console.log("站點資料:", r); // 🟢 加入這行以便在 Console 查看資料是否收到

        if (!r || !r.ok) {
            console.error("無法取得站點資料");
            return;
        }

        const startSel = document.getElementById('thsr-start');
        const destSel = document.getElementById('thsr-dest');
        
        // 清空並填入選項
        if (startSel && r.stations) {
            startSel.innerHTML = '';
            r.stations.forEach(s => {
                startSel.add(new Option(s.name, s.id));
            });
        }
        // 對 destSel 與其他下拉選單執行相同邏輯
    } catch (e) {
        console.error("連線錯誤:", e);
    }
}


// 修正後的選擇車次函數
async function thsrSelectTrain(index) {
    thsrShowStep(2);
    thsrSetMsg(2, '正在為您鎖定座位...', false);
    
    try {
        // 明確使用完整路徑 /api/thsr/select-train
        const r = await api('POST', '/api/thsr/select-train', { 
            session_id: thsrSessionId, 
            index: index 
        });
        
        // 防禦性檢查：若伺服器回傳異常
        if (!r || !r.ok) {
            const errorMsg = (r && r.errors && Array.isArray(r.errors)) ? r.errors.join('；') : (r ? r.error : '伺服器無回應');
            thsrSetMsg(2, errorMsg || '選擇車次失敗');
            return;
        }
        
        thsrSetMsg(2, '');
        thsrShowStep(3); // 成功跳轉
    } catch (e) {
        thsrSetMsg(2, '連線發生錯誤');
        console.error('前端請求失敗:', e);
    }
}

// 修正後的送出訂票確認函數
async function thsrSubmitPassenger() {
    const personalId = document.getElementById('thsr-personal-id').value.trim();
    const phone = document.getElementById('thsr-phone').value.trim();
    
    if (personalId.length !== 10) {
        thsrSetMsg(4, '身分證字號需為 10 碼');
        return;
    }
    
    thsrSetMsg(4, '送出中...', false);
    try {
        // 明確使用完整路徑 /api/thsr/confirm
        const r = await api('POST', '/api/thsr/confirm', { 
            session_id: thsrSessionId, 
            personal_id: personalId, 
            phone: phone 
        });
        
        if (!r || !r.ok) {
            const errorMsg = (r && r.errors && Array.isArray(r.errors)) ? r.errors.join('；') : (r ? r.error : '送出訂票失敗');
            thsrSetMsg(4, errorMsg);
            return;
        }
        
        thsrRenderResult(r.ticket, r.message);
        thsrShowStep(5);
    } catch (e) {
        thsrSetMsg(4, '連線失敗，請稍後再試');
        console.error(e);
    }
}

function thsrRenderResult(ticket, message) {
    const el = document.getElementById('thsr-result-detail');
    if (!el) return;
    el.innerHTML = `
      訂位代號：<b>${ticket.booking_id}</b><br>
      車次：${ticket.train_id}（${ticket.start_station} → ${ticket.dest_station}）<br>
      日期／時間：${ticket.date} ${ticket.depart_time} → ${ticket.arrival_time}<br>
      車廂／座位：${ticket.seat}
    `;
}