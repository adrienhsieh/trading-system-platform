// ── Helpers ─────────────────────────────────────────────────
function getApiKey(){ return localStorage.getItem('trading_api_key')||''; }

async function api(method, path, body, signal){
  const sentKey = getApiKey();
  const opts = { method, headers:{'Content-Type':'application/json','X-API-Key':sentKey} };
  if (body) opts.body = JSON.stringify(body);
  if (signal) opts.signal = signal;
  const r = await fetch(path, opts);
  if(r.status===401){
    if(getApiKey() !== sentKey && getApiKey() !== '') return api(method,path,body,signal);
    const k = prompt('請輸入 API Key（從伺服器啟動訊息取得）：');
    if(k){ localStorage.setItem('trading_api_key',k); return api(method,path,body,signal); }
    throw new Error('Unauthorized');
  }
  return r.json();
}
function esc(s){ return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#x27;'); }
function toast(msg, type='ok'){
  const el = document.getElementById('toast');
  el.textContent = msg; el.className = `toast ${type} show`;
  setTimeout(()=>el.classList.remove('show'), 3000);
}
function fmtChg(pct){
  if(pct==null) return '<span class="chg">--</span>';
  const cls = pct>=0?'up':'dn';
  const sign = pct>=0?'+':'';
  return `<span class="chg ${cls}">${sign}${pct.toFixed(2)}%</span>`;
}

// ── Clock ────────────────────────────────────────────────────
function tick(){
  document.getElementById('clock').textContent = new Intl.DateTimeFormat('zh-TW',{
    timeZone:'Asia/Taipei',hour:'2-digit',minute:'2-digit',second:'2-digit',
    year:'numeric',month:'2-digit',day:'2-digit',hour12:false
  }).format(new Date()) + ' TST';
}
setInterval(tick,1000); tick();

// ── Tabs ─────────────────────────────────────────────────────
document.querySelectorAll('.tab').forEach(tab => {
  tab.addEventListener('click', (e) => {
    
    // 🟢 核心修正 1：防止點擊事件被台股預測功能 (predict.js) 的全域捕獲干擾阻斷
    if (e && typeof e.stopPropagation === 'function') {
      e.stopPropagation();
    }

    // 🟢 核心修正 2：切換頁簽時，強制且精準清除監控定時器，避免背景無限跳動耗電
    if (typeof monitorTimer !== 'undefined' && monitorTimer) {
      clearInterval(monitorTimer);
      monitorTimer = null;
      console.log('已自動熔斷盤中監控定時器。');
    }
    if (typeof monitorIntervalId !== 'undefined' && monitorIntervalId) {
      clearInterval(monitorIntervalId);
      monitorIntervalId = null;
    }

    // 1. 先確認要切換的目標 ID 面板是否存在，避免找不到元件導致 JS 卡死
    const targetId = 'tab-' + tab.dataset.tab;
    const targetPanel = document.getElementById(targetId);
    
    if (!targetPanel) {
      console.warn(`[Tabs Error] 找不到對應的網頁面板: #${targetId}`);
    }

    // 2. 切換導覽列按鈕的 active 狀態
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    tab.classList.add('active');

    // 3. 切換內容面板的 active 狀態（有找到面板才做切換）
    document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
    if (targetPanel) {
      targetPanel.classList.add('active');
    }
    
    // 4. 使用 try...catch 沙盒隔離各別分頁的資料載入邏輯，一處出錯，絕不卡死全網頁
    try {
      if (tab.dataset.tab === 'holdings') {
        if (typeof loadMarket === 'function') loadMarket();
      }
      
      if (tab.dataset.tab === 'watchlist') {
        loadWatchlist();
      }
      
      if (tab.dataset.tab === 'scanner') {
        // 如果台股掃描有載入函式請補在這邊，例如：if(typeof loadScanner==='function') loadScanner();
      }
      
      if (tab.dataset.tab === 'predict') {
        console.log('進入台股預測分頁');
        if (typeof loadPredictionHistoryTable === 'function') {
          loadPredictionHistoryTable();
        }
      }
      
      if (tab.dataset.tab === 'backtest') {
        // 如果回測有初始化邏輯請補在這邊
      }
      
      if (tab.dataset.tab === 'news') {
        loadNews();
      }
      
      if (tab.dataset.tab === 'ai') { 
        loadXIntel(); 
        loadDailySummary(); 
      }
      
      if (tab.dataset.tab === 'topic') {
        loadCoverageKeywords();
      }

      // 🟢 核心修正 3：補齊開盤監控分頁的返回重繪邏輯
      if (tab.dataset.tab === 'live-monitor') {
        console.log('進入台股開盤監控分頁，狀態機完全對齊！');
        if (typeof drawLiveMonitorKline === 'function' && 
            typeof liveMonitorHistoryData !== 'undefined' && liveMonitorHistoryData) {
          if (document.getElementById('liveKlineCanvas')) {
            drawLiveMonitorKline();
          }
        }
      }
    } catch (error) {
      console.error("[防禦熔斷] 偵測到分頁載入函式崩潰，已自動安全隔離：", error);
    }
  });
});
function closeModal(id){ document.getElementById(id).classList.remove('open'); }

// ── Market ───────────────────────────────────────────────────
let _mktRetry = null;
async function loadMarket(){
  clearTimeout(_mktRetry);
  try{
    const r = await api('GET', '/api/market');
    const m = r.market||{};
    const setMkt=(id,chgId,d)=>{
      if(d?.price){
        document.getElementById(id).textContent=d.price.toLocaleString();
        document.getElementById(chgId).outerHTML=`<span id="${chgId}">${fmtChg(d.change_pct)}</span>`;
      }
    };
    setMkt('m-tw','m-tw-chg',m.taiex);
    setMkt('m-nd','m-nd-chg',m.nasdaq);
    setMkt('m-sp','m-sp-chg',m.sp500);
    if(m.usd_twd?.price) document.getElementById('m-fx').textContent=m.usd_twd.price.toFixed(2);
    if(m.market_above_ema20!=null){
      const el=document.getElementById('m-filter');
      if(el){ el.textContent=m.market_above_ema20?'✅ 站上 20EMA':'❌ 跌破 20EMA'; el.style.color=m.market_above_ema20?'var(--green)':'var(--red)'; }
      // 摘要卡片
      const sub=document.getElementById('m-filter-sub');
      if(sub){ sub.textContent=m.market_above_ema20?'✅ 站上 20EMA':'❌ 跌破 20EMA'; sub.style.color=m.market_above_ema20?'var(--green)':'var(--red)'; }
    }
    if(m.ema20_tw){
      const el=document.getElementById('m-ema'); if(el) el.textContent=m.ema20_tw.toLocaleString();
      const se=document.getElementById('summary-ema'); if(se) se.textContent='EMA20: '+m.ema20_tw.toLocaleString();
    }
    if(!r.cached) _mktRetry=setTimeout(loadMarket,10000);
  }catch(e){
    _mktRetry=setTimeout(loadMarket,15000);
  }
}

// ── Init（由 index.html 底部的 inline script 呼叫） ──────────

// ── 代號自動查名稱 ───────────────────────────────────────────
let _nameTimer = null;
function autoFetchName(code){
  code = (code||'').trim();
  const tag = document.getElementById('f-name-tag');
  const inp = document.getElementById('f-name');
  if(!code){ tag.textContent='輸入代號自動查詢'; tag.style.color='var(--text-tertiary)'; return; }
  if(code.length < 4){ tag.textContent='...'; tag.style.color='var(--text-tertiary)'; return; }
  clearTimeout(_nameTimer);
  _nameTimer = setTimeout(async ()=>{
    tag.textContent = '查詢中...'; tag.style.color='var(--text-secondary)';
    try{
      const d = await api('GET', `/api/stock_info/${encodeURIComponent(code)}`);
      if(d.ok && d.name){
        tag.textContent = d.name;
        tag.style.color = 'var(--green)';
        if(!inp.value) inp.value = d.name;
        if(d.group) tag.title = `${d.market} ｜ ${d.group}`;
      } else {
        tag.textContent = '找不到此代號';
        tag.style.color = 'var(--red)';
      }
    }catch(e){
      tag.textContent = '查詢失敗'; tag.style.color='var(--red)';
    }
  }, 400);
}
