// ── Theme Toggle ─────────────────────────────────────────────
function toggleTheme(theme) {
  document.documentElement.setAttribute('data-bs-theme', theme);
  document.body.setAttribute('data-theme', theme);
  localStorage.setItem('trading_theme', theme);
}

function initTheme() {
  const saved = localStorage.getItem('trading_theme') || 'light';
  toggleTheme(saved);
  const sel = document.getElementById('s-theme');
  if (sel) sel.value = saved;
}

// Apply saved theme on load
initTheme();


// ── 💡 關鍵新增：模擬當前登入的使用者身份 ──────────────────────
// 未來若做好了真正的註冊登入，直接動態將此變數換成登入者的 user_id 即可
let CURRENT_USER_ID = "jack"; 
let CURRENT_MODULE_ID = "settings_page"; // 標記這個網頁模組的固定識別碼


// ── Settings ─────────────────────────────────────────────────
async function openSettings(){
  // // 🟢 修正點：將原本的 /api/config 改成呼叫我們新架設的 /api/user_config
  // // 並且在網址後面用 query 參數帶上目前的 user_id 與 module_id
  // const url = `/api/user_config?user_id=${encodeURIComponent(CURRENT_USER_ID)}&module_id=${encodeURIComponent(CURRENT_MODULE_ID)}`;
  // const response = await api('GET', url);
  // 
  // // 💡 注意：依照後端 API 的設計格式，成功的資料會包在 response.data 裡面
  // const r = response.ok ? response.data : {};
  // 
  // // 如果資料庫中還沒有設定，給予預設值保底
  // document.getElementById('s-capital').value = r.total_capital || 3000000;
  // document.getElementById('s-consec').value = r.consecutive_losses || 0;
  // document.getElementById('s-theme').value = localStorage.getItem('trading_theme') || 'light';
  // document.getElementById('settings-modal').classList.add('open');
  const url = `/api/user_page_config?user_id=${CURRENT_WEB_USER}&module_id=${SETTINGS_MODULE_ID}`;
  const response = await api('GET', url);
  
  // 💡 安全解包：如果 response 本身就是資料，或者包在 response.data 裡，進行安全相容性保底
  const r = response.data ? response.data : (response.ok ? response : response);
  
  document.getElementById('s-capital').value = r.total_capital || 3000000;
  document.getElementById('s-consec').value = r.consecutive_losses || 0;
  document.getElementById('s-theme').value = localStorage.getItem('trading_theme') || 'light';
  document.getElementById('settings-modal').classList.add('open');
}

async function saveSettings(){
  const updatedConfigs = {
    total_capital: parseInt(document.getElementById('s-capital').value),
    consecutive_losses: parseInt(document.getElementById('s-consec').value)
  };

  const payload = {
    user_id: CURRENT_WEB_USER,
    module_id: SETTINGS_MODULE_ID,
    configs: updatedConfigs
  };

  // 🟢 修正點：對齊全新獨立儲存路徑 /api/user_page_config/save
  const r = await api('POST', '/api/user_page_config/save', payload);
  
  if(r.ok || r.message === "儲存成功"){ 
    toast('✓ 設定已儲存','ok'); 
    closeModal('settings-modal'); 
    if (typeof loadPositions === 'function') loadPositions(); 
  }
  else {
    toast('儲存失敗','err');
  }
}

// ── Strategy Settings ────────────────────────────────────────
let _stratParams = null;

const STRAT_META = {
  trend: {
    ema_arrangement: { label: "均線多頭排列（收>EMA5>EMA20>EMA60）" },
    slopes_up:       { label: "三線齊揚（EMA5/20/60同步上揚）" },
    adx_above_25:    { label: "ADX 趨勢強度門檻", field: "threshold", unit: "(值)" },
    macd_positive:   { label: "MACD 紅柱（直方圖>0）" },
    volume_spike:    { label: "成交量爆量倍數（倍於20日均量）", field: "threshold", unit: "x" },
    ema_crossover:   { label: "EMA5 穿越 EMA20（近3日黃金交叉）" },
  },
  ict: {
    bullish_ob:      { label: "多頭 Order Block" },
    fvg_present:     { label: "Fair Value Gap（不平衡區）" },
    bos:             { label: "Break of Structure（結構突破）" },
    liquidity_sweep: { label: "流動性掃除後反轉" },
    discount_zone:   { label: "折扣區（低於均衡價）" },
    ote_zone:        { label: "OTE 回檔 Fib 下限 / 上限", field: ["fib_low","fib_high"], unit: ["低","高"] },
    mss:             { label: "市場結構轉換（MSS）" },
  },
  fundamental: {
    pe_reasonable:   { label: "本益比合理（PE <）", field: "threshold", unit: "" },
    eps_positive:    { label: "EPS 為正" },
    eps_growth:      { label: "EPS 成長（forward > trailing）" },
    pb_reasonable:   { label: "股價淨值比合理（PB <）", field: "threshold", unit: "" },
    revenue_growth:  { label: "營收成長率 > 0" },
  },
};

async function openStratSettings(){
  if(!_stratParams){
    const r = await api('GET','/api/strategy_params');
    _stratParams = r.params;
  }
  renderStratSettingsModal(_stratParams);
  document.getElementById('strat-settings-modal').classList.add('open');
}

function renderStratSettingsModal(params){
  ['trend','ict','fundamental'].forEach(strat=>{
    const meta   = STRAT_META[strat];
    const sParam = params[strat] || {};
    const el     = document.getElementById('ss-'+strat);
    if (!el) return; // 💡 確保安全，防止找不到 DOM 元素
    el.innerHTML = Object.entries(meta).map(([key, m])=>{
      const sp      = sParam[key] || {};
      const enabled = sp.enabled !== false;
      if(Array.isArray(m.field)){
        // dual input (OTE fib)
        return `<div class="sig-row${enabled?'':' disabled'}">
          <input type="checkbox" id="ss-${strat}-${key}" ${enabled?'checked':''} onchange="ssToggle('${strat}','${key}',this.checked)">
          <label for="ss-${strat}-${key}">${m.label}</label>
          ${m.field.map((f,i)=>`<input class="form-control form-control-sm" type="number" step="0.001"
            id="ss-${strat}-${key}-${f}" value="${sp[f]??''}" style="width:64px" title="${m.unit[i]}">`).join('')}
        </div>`;
      } else if(m.field){
        return `<div class="sig-row${enabled?'':' disabled'}">
          <input type="checkbox" id="ss-${strat}-${key}" ${enabled?'checked':''} onchange="ssToggle('${strat}','${key}',this.checked)">
          <label for="ss-${strat}-${key}">${m.label}</label>
          <input class="form-control form-control-sm" type="number" step="0.1"
            id="ss-${strat}-${key}-${m.field}" value="${sp[m.field]??''}" style="width:72px" title="${m.unit}">
        </div>`;
      } else {
        return `<div class="sig-row${enabled?'':' disabled'}">
          <input type="checkbox" id="ss-${strat}-${key}" ${enabled?'checked':''} onchange="ssToggle('${strat}','${key}',this.checked)">
          <label for="ss-${strat}-${key}">${m.label}</label>
        </div>`;
      }
    }).join('');
  });
}

function ssToggle(strat, key, checked){
  const el = document.getElementById('ss-'+strat+'-'+key);
  if (!el) return;
  const row = el.closest('.sig-row');
  if (row) row.classList.toggle('disabled', !checked);
}

function collectStratParams(){
  const params = {};
  ['trend','ict','fundamental'].forEach(strat=>{
    params[strat] = {};
    Object.entries(STRAT_META[strat]).forEach(([key, m])=>{
      const cb = document.getElementById('ss-'+strat+'-'+key);
      const sp = { enabled: cb ? cb.checked : true };
      if(Array.isArray(m.field)){
        m.field.forEach(f=>{
          const inp = document.getElementById(`ss-${strat}-${key}-${f}`);
          if(inp && inp.value !== '') sp[f] = parseFloat(inp.value);
        });
      } else if(m.field){
        const inp = document.getElementById(`ss-${strat}-${key}-${m.field}`);
        if(inp && inp.value !== '') sp[m.field] = parseFloat(inp.value);
      }
      params[strat][key] = sp;
    });
  });
  return params;
}

async function saveStratSettings(){
  const params = collectStratParams();
  const r = await api('POST','/api/strategy_params',{params});
  if(r.ok){
    _stratParams = params;
    toast('✓ 策略設定已儲存','ok');
    closeModal('strat-settings-modal');
  } else {
    toast('儲存失敗','err');
  }
}

async function resetStratSettings(){
  if(typeof Swal!=='undefined'){
    const res = await Swal.fire({
      title: '重置所有策略設定？',
      text: '將恢復為系統預設值',
      icon: 'question',
      showCancelButton: true,
      confirmButtonColor: '#ef4444',
      cancelButtonColor: '#6b7280',
      confirmButtonText: '確認重置',
      cancelButtonText: '取消',
    });
    if(!res.isConfirmed) return;
  }
  const r = await api('POST','/api/strategy_params',{params: {}});
  if(r.ok){
    const r2 = await api('GET','/api/strategy_params');
    _stratParams = r2.params;
    renderStratSettingsModal(_stratParams);
    toast('已重置為預設值','ok');
  }
}
