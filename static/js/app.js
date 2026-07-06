// ── Helpers ─────────────────────────────────────────────────
function getApiKey(){ return localStorage.getItem('trading_api_key')||''; }

async function api(method, path, body, signal){
  const headers = { 'Content-Type':'application/json' };
  const apiKey = getApiKey();
  const token  = localStorage.getItem('jwt_token');
  if(apiKey) headers['X-API-Key'] = apiKey;
  if(token)  headers['Authorization'] = 'Bearer ' + token;

  const opts = { method, headers };
  if (body) opts.body = JSON.stringify(body);
  if (signal) opts.signal = signal;

  const r = await fetch(path, opts);
  if(r.status===401){
    // 多人登入模式下，Token 無效或過期，清除並導回登入頁
    if(token){
      localStorage.removeItem('jwt_token');
      localStorage.removeItem('trade_sys_jwt');
      localStorage.removeItem('username');
      localStorage.removeItem('display_name');
      if(!location.pathname.startsWith('/login')){
        window.location.href = '/login';
      }
    }
    throw new Error('Unauthorized，請重新登入');
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
  const clockEl = document.getElementById('clock');
  if (clockEl) {
    clockEl.textContent = new Intl.DateTimeFormat('zh-TW',{
      timeZone:'Asia/Taipei',hour:'2-digit',minute:'2-digit',second:'2-digit',
      year:'numeric',month:'2-digit',day:'2-digit',hour12:false
    }).format(new Date()) + ' TST';
  }
}
setInterval(tick,1000); tick();

// ── Tabs ─────────────────────────────────────────────────────
document.querySelectorAll('.tab').forEach(tab=>{
  tab.addEventListener('click',(e)=>{
    if (e && typeof e.stopPropagation === 'function') e.stopPropagation();
    const targetId = 'tab-' + tab.dataset.tab;
    const targetPanel = document.getElementById(targetId);
    document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
    tab.classList.add('active');
    document.querySelectorAll('.panel').forEach(p=>{
      p.classList.remove('active');
      p.style.setProperty('display', '', 'important');
    });
    if (targetPanel) {
      targetPanel.classList.add('active');
      targetPanel.style.setProperty('display', 'block', 'important');
    }
    try {
      if(tab.dataset.tab==='holdings') loadMarket?.();
      if(tab.dataset.tab==='watchlist') loadWatchlist?.();
      if(tab.dataset.tab==='news') loadNews?.();
      if(tab.dataset.tab==='ai'){ loadXIntel?.(); loadDailySummary?.(); }
      if(tab.dataset.tab==='topic') loadCoverageKeywords?.();
      if(tab.dataset.tab==='predict') loadPredictionHistoryTable?.();
    } catch(error) {
      console.error("[安全熔斷] Tab 載入異常：", error);
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
    if(!r.cached) _mktRetry=setTimeout(loadMarket,10000);
  }catch(e){
    _mktRetry=setTimeout(loadMarket,15000);
  }
}
