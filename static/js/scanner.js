// ── Scanner ──────────────────────────────────────────────────
let currentStrat='trend';
let fullScanResults=[];
let fullScanEs=null;
let techFilterEnabled=true;

function toggleTechFilter(){
  techFilterEnabled=!techFilterEnabled;
  const btn=document.getElementById('tech-filter-btn');
  if(techFilterEnabled){
    btn.classList.remove('btn-outline-secondary');
    btn.classList.add('btn-outline-info');
    btn.textContent='⚡ 電子股';
  } else {
    btn.classList.remove('btn-outline-info');
    btn.classList.add('btn-outline-secondary');
    btn.textContent='🌐 全市場';
  }
}

function setStrat(s){ currentStrat=s; document.getElementById('strend').classList.toggle('active',s==='trend'); document.getElementById('sict').classList.toggle('active',s==='ict'); document.getElementById('sfundamental').classList.toggle('active',s==='fundamental'); }

let scanAbort = null;
async function runScan(){
  const btn = document.getElementById('scan-btn');
  const stopBtn = document.getElementById('scan-stop-btn');
  btn.disabled=true; btn.classList.add('spin-btn'); btn.textContent='掃描中...';
  stopBtn.classList.remove('d-none');
  document.getElementById('scan-result').innerHTML=`<div class="loader"><div class="spinner"></div>抓取 yfinance 資料並計算 EMA / ADX / ATR / MACD，約 30-60 秒...</div>`;
  scanAbort = new AbortController();
  try{
    const r = await api('POST','/api/scan',{strategy:currentStrat}, scanAbort.signal);
    renderScan(r);
  }catch(e){
    if(e.name==='AbortError') document.getElementById('scan-result').innerHTML=`<div class="empty">已停止掃描</div>`;
    else document.getElementById('scan-result').innerHTML=`<div class="empty" style="color:var(--red)">⚠ 掃描失敗，請確認伺服器執行中</div>`;
  }
  scanAbort=null;
  btn.disabled=false; btn.classList.remove('spin-btn'); btn.textContent='▶ 自訂清單';
  stopBtn.classList.add('d-none');
}
function stopScan(){ if(scanAbort){ scanAbort.abort(); scanAbort=null; } }

function stopFullScan(){
  if(fullScanEs){ fullScanEs.close(); fullScanEs=null; }
  const btn = document.getElementById('full-scan-btn');
  const stopBtn = document.getElementById('full-scan-stop-btn');
  btn.disabled=false; btn.textContent='🌐 全台股';
  stopBtn.classList.add('d-none');
  document.getElementById('full-scan-progress').style.display='none';
  document.getElementById('fsb-label').textContent='已停止';
}

function runFullScan(){
  if(fullScanEs){ fullScanEs.close(); fullScanEs=null; }

  const btn = document.getElementById('full-scan-btn');
  const stopBtn = document.getElementById('full-scan-stop-btn');
  btn.disabled=true; btn.textContent='掃描中...';
  stopBtn.classList.remove('d-none');
  fullScanResults=[];

  document.getElementById('full-scan-progress').style.display='block';
  document.getElementById('scan-result').innerHTML='';
  document.getElementById('scan-live-results').innerHTML='';
  document.getElementById('fsb-label').textContent='正在從證交所取得股票清單...';
  document.getElementById('fsb-count').textContent='0 / ?';
  document.getElementById('fsb-fill').style.width='0%';

  const sc=v=>v>=5?'var(--green)':v>=3?'var(--yellow)':'var(--red)';

  if(typeof NProgress!=='undefined') NProgress.start();

  const filterParam = techFilterEnabled ? '&filter=tech' : '';
  const _scanKey = localStorage.getItem('trading_api_key') || '';
  const _scanToken = localStorage.getItem('jwt_token') || '';
  fullScanEs = new EventSource('/api/scan/full?strategy='+currentStrat+filterParam+'&key='+encodeURIComponent(_scanKey)+'&token='+encodeURIComponent(_scanToken));

  fullScanEs.onmessage = (e)=>{
    const d = JSON.parse(e.data);

    if(d.type==='start'){
      document.getElementById('fsb-label').textContent=`掃描中（共 ${d.total} 檔）...`;
      document.getElementById('fsb-count').textContent=`0 / ${d.total}`;
    }
    else if(d.type==='result' || d.type==='progress'){
      const pct = Math.round(d.done/d.total*100);
      if(typeof NProgress!=='undefined') NProgress.set(d.done/d.total*0.95);
      document.getElementById('fsb-fill').style.width=pct+'%';
      document.getElementById('fsb-count').textContent=`${d.done} / ${d.total}`;
      document.getElementById('fsb-label').textContent=`掃描中... ${pct}%`;

      if(d.type==='result'){
        fullScanResults.push(d.item);
        if(d.item.score>=4){
          const dots=Object.entries(d.item.signals).map(([k,v])=>`<span class="dot ${v.pass?'pass':'fail'}">${v.label}</span>`).join('');
          const card=`<div class="scard" onclick='quickAdd(${JSON.stringify({code:d.item.code,name:d.item.name||'',entry:d.item.entry,stop:d.item.stop,target:d.item.target})})'>
            <div class="scard-hdr">
              <div><div class="sc-code">${d.item.code} <span style="font-size:11px;font-weight:400;color:var(--text-secondary)">${d.item.name||''}</span></div><div class="sc-sub">收 ${d.item.close}${d.item.adx!=null?' ｜ ADX '+d.item.adx:d.item.pe!=null?' ｜ PE '+d.item.pe:''}</div></div>
              <div><div class="sc-score" style="color:${sc(d.item.score)}">${d.item.score}/6</div><div style="font-size:9px;color:var(--text-tertiary)">得分</div></div>
            </div>
            <div class="dots">${dots}</div>
            <div class="sc-params">停損 ${d.item.stop} ｜ 目標 ${d.item.target}</div>
          </div>`;
          const liveEl = document.getElementById('scan-live-results');
          if(!liveEl.querySelector('.scan-grid')){
            liveEl.innerHTML=`<div style="font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--text-secondary);margin-bottom:8px">🔴 即時高分（≥4分）</div><div class="scan-grid" id="live-grid"></div>`;
          }
          document.getElementById('live-grid').insertAdjacentHTML('beforeend',card);
        }
      }
    }
    else if(d.type==='done'){
      if(typeof NProgress!=='undefined') NProgress.done();
      fullScanEs.close(); fullScanEs=null;
      btn.disabled=false; btn.textContent='🌐 全台股';
      stopBtn.classList.add('d-none');
      document.getElementById('fsb-label').textContent=`✅ 掃描完成，共 ${d.total} 檔`;
      document.getElementById('fsb-fill').style.width='100%';
      renderScan({results:d.results, scanned:d.total, risk_pct:d.risk_pct, strategy:d.strategy});
      document.getElementById('full-scan-progress').style.display='none';
    }
  };

  fullScanEs.onerror = ()=>{
    if(typeof NProgress!=='undefined') NProgress.done();
    if(fullScanEs){ fullScanEs.close(); fullScanEs=null; }
    btn.disabled=false; btn.textContent='🌐 全台股';
    stopBtn.classList.add('d-none');
    document.getElementById('fsb-label').textContent='⚠ 連線中斷';
    document.getElementById('scan-result').innerHTML=`<div class="empty" style="color:var(--red)">⚠ 掃描中斷，請重試</div>`;
  };
}

function renderScan(r){
  const results=r.results||[];
  if(!results.length){ document.getElementById('scan-result').innerHTML=`<div class="empty">無符合條件股票</div>`; return; }
  const strat=r.strategy||currentStrat||'trend';
  const sc=(v,total)=>v>=total-1?'var(--green)':v>=Math.floor(total/2)?'var(--yellow)':'var(--red)';
  const cards=results.map(s=>{
    const total=s.total_enabled||(strat==='ict'?7:strat==='fundamental'?5:6);
    const dots=Object.entries(s.signals).map(([k,v])=>`<span class="dot ${v.enabled===false?'disabled':v.pass?'pass':'fail'}">${v.label}</span>`).join('');
    const sub=strat==='ict'
      ? `收 ${s.close} ｜ 均衡 ${s.equilibrium||'--'} ｜ OB ${s.ob_low||'--'}~${s.ob_high||'--'}`
      : strat==='fundamental'
        ? `收 ${s.close} ｜ PE ${s.pe??'--'} ｜ PB ${s.pb??'--'}`
        : `收 ${s.close} ｜ ADX ${s.adx} ｜ ATR ${s.atr}`;
    const extra=strat==='ict'
      ? `<div class="sc-w52">區間 L:${s.range_low||'--'} H:${s.range_high||'--'}${s.mss_level?' ｜ MSS:'+s.mss_level:''}</div>`
      : strat==='fundamental'
        ? `<div class="sc-w52">EPS ${s.eps??'--'} → ${s.forward_eps??'--'} ｜ 營收成長 ${s.revenue_growth!=null?s.revenue_growth+'%':'--'}</div>`
        : `<div class="sc-w52">52週 L:${s.w52_low} H:${s.w52_high}</div>`;
    const safeName=encodeURIComponent(s.name||'');

    // ──【新增】自適應 AI 綜合研判前端 HTML 區塊 ──
    let adaptiveHtml = '';
    if (s.adaptive_analysis) {
        const aa = s.adaptive_analysis;
        const badgeColor = aa.composite_score >= 68 ? '#dcfce7' : '#f1f5f9';
        const textColor = aa.composite_score >= 68 ? '#166534' : '#475569';
        adaptiveHtml = `
        <div style="border-left: 4px solid #3b82f6; background: rgba(59, 130, 246, 0.04); padding: 10px; margin-top: 10px; border-radius: 4px; text-align: left;">
            <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px;">
                <span style="font-weight: bold; font-size: 12px; color: var(--text-primary); display: flex; align-items: center; gap: 4px;">🧠 自適應 AI 綜合研判</span>
                <span style="font-size: 10px; font-weight: 600; padding: 1px 6px; border-radius: 8px; background: ${badgeColor}; color: ${textColor};">${aa.recommendation}</span>
            </div>
            <div style="display: flex; gap: 12px; align-items: center;">
                <!-- 分數圓圈 -->
                <div style="width: 42px; height: 42px; border-radius: 50%; background: rgba(59, 130, 246, 0.08); border: 2px solid #3b82f6; display: flex; flex-direction: column; align-items: center; justify-content: center; flex-shrink: 0; box-sizing: border-box;">
                    <span style="font-size: 13px; font-weight: bold; color: #3b82f6; line-height: 1;">${aa.composite_score}</span>
                    <span style="font-size: 8px; color: #3b82f6; margin-top: 1px;">分</span>
                </div>
                <!-- 雙色進度條 -->
                <div style="flex: 1;">
                    <div style="display: flex; justify-content: space-between; font-size: 10px; color: var(--text-secondary); margin-bottom: 3px;">
                        <span>📊 量化指標: ${aa.quant_weight_pct}%</span>
                        <span>🤖 AI 決策: ${aa.ai_weight_pct}%</span>
                    </div>
                    <div style="width: 100%; height: 5px; background: rgba(0,0,0,0.08); border-radius: 3px; overflow: hidden; display: flex;">
                        <div style="width: ${aa.quant_weight_pct}%; background: #10b981; height: 100%;"></div>
                        <div style="width: ${aa.ai_weight_pct}%; background: #3b82f6; height: 100%;"></div>
                    </div>
                    <p style="margin: 3px 0 0 0; font-size: 9px; color: var(--text-tertiary);">*指標衝突度 ${aa.conflict_degree}，自動動態切換權重</p>
                </div>
            </div>
        </div>`;
    }

    // ──【新增】次日開盤價預測前端 HTML 區塊 ──
    let openPredictHtml = '';
    if (s.open_prediction) {
        const op = s.open_prediction;
        openPredictHtml = `
        <div style="background: rgba(16, 185, 129, 0.04); border-left: 4px solid #10b981; padding: 10px; margin-top: 8px; border-radius: 4px; font-size: 11px; text-align: left;">
            <div style="display: flex; justify-content: space-between; margin-bottom: 4px;">
                <span style="font-weight: bold; color: var(--text-primary);">🔮 次日開盤價預測</span>
                <span style="color: #10b981; font-weight: 600; font-size: 10px;">${op.type} (${op.probability})</span>
            </div>
            <div style="display: flex; justify-content: space-between; align-items: center; color: var(--text-secondary);">
                <div>預估開盤: <strong style="font-size: 13px; color: #10b981;">${op.predicted_open}</strong> 元</div>
                <div style="font-size: 10px;">震盪合理區間: <span style="font-family: monospace; background: rgba(0,0,0,0.05); padding: 1px 4px; border-radius: 3px;">${op.range_low} ~ ${op.range_high}</span></div>
            </div>
        </div>`;
    }

    return `<div class="scard" onclick='quickAdd(${JSON.stringify({code:s.code,name:s.name||'',entry:s.entry,stop:s.stop,target:s.target})})'>
      <div class="scard-hdr">
        <div><div class="sc-code">${s.code} <span style="font-size:11px;font-weight:400;color:var(--text-secondary)">${s.name||''}</span></div><div class="sc-sub">${sub}</div></div>
        <div><div class="sc-score" style="color:${sc(s.score,total)}">${s.score}/${total}</div><div style="font-size:9px;color:var(--text-tertiary)">得分</div></div>
      </div>
      <div class="dots">${dots}</div>
      <div class="sc-params">停損 ${s.stop} ｜ 目標 ${s.target} ｜ 建議 ${s.shares} 股</div>
      ${extra}
      ${adaptiveHtml}
      ${openPredictHtml}
      <div style="margin-top:6px;text-align:right">
        <button class="btn-xs" onclick="event.stopPropagation();showCoverage('${s.code}',decodeURIComponent('${safeName}'))">研究</button>
      </div>
    </div>`;
  }).join('');
  document.getElementById('scan-result').innerHTML=`<div class="scan-grid">${cards}</div><div class="scan-note">⚠ 技術指標篩選，非投資建議。進場前請對照策略 SOP 人工確認。已掃描 ${r.scanned||0} 檔，曝險模式：${r.risk_pct}%</div>`;
}
//function renderScan(r){
//  const results=r.results||[];
//  if(!results.length){ document.getElementById('scan-result').innerHTML=`<div class="empty">無符合條件股票</div>`; return; }
//  const strat=r.strategy||currentStrat||'trend';
//  const sc=(v,total)=>v>=total-1?'var(--green)':v>=Math.floor(total/2)?'var(--yellow)':'var(--red)';
//  const cards=results.map(s=>{
//    const total=s.total_enabled||(strat==='ict'?7:strat==='fundamental'?5:6);
//    const dots=Object.entries(s.signals).map(([k,v])=>`<span class="dot ${v.enabled===false?'disabled':v.pass?'pass':'fail'}">${v.label}</span>`).join('');
//    const sub=strat==='ict'
//      ? `收 ${s.close} ｜ 均衡 ${s.equilibrium||'--'} ｜ OB ${s.ob_low||'--'}~${s.ob_high||'--'}`
//      : strat==='fundamental'
//        ? `收 ${s.close} ｜ PE ${s.pe??'--'} ｜ PB ${s.pb??'--'}`
//        : `收 ${s.close} ｜ ADX ${s.adx} ｜ ATR ${s.atr}`;
//    const extra=strat==='ict'
//      ? `<div class="sc-w52">區間 L:${s.range_low||'--'} H:${s.range_high||'--'}${s.mss_level?' ｜ MSS:'+s.mss_level:''}</div>`
//      : strat==='fundamental'
//        ? `<div class="sc-w52">EPS ${s.eps??'--'} → ${s.forward_eps??'--'} ｜ 營收成長 ${s.revenue_growth!=null?s.revenue_growth+'%':'--'}</div>`
//        : `<div class="sc-w52">52週 L:${s.w52_low} H:${s.w52_high}</div>`;
//    const safeName=encodeURIComponent(s.name||'');
//
//    // ──【新增】自適應 AI 綜合研判前端 HTML 區塊 ──
//    let adaptiveHtml = '';
//    if (s.adaptive_analysis) {
//        const aa = s.adaptive_analysis;
//        const badgeColor = aa.composite_score >= 68 ? '#dcfce7' : '#f1f5f9';
//        const textColor = aa.composite_score >= 68 ? '#166534' : '#475569';
//        adaptiveHtml = `
//        <div style="border-left: 4px solid #3b82f6; background: rgba(59, 130, 246, 0.04); padding: 10px; margin-top: 10px; border-radius: 4px; text-align: left;">
//            <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px;">
//                <span style="font-weight: bold; font-size: 12px; color: var(--text-primary); display: flex; align-items: center; gap: 4px;">🧠 自適應 AI 綜合研判</span>
//                <span style="font-size: 10px; font-weight: 600; padding: 1px 6px; border-radius: 8px; background: ${badgeColor}; color: ${textColor};">${aa.recommendation}</span>
//            </div>
//            <div style="display: flex; gap: 12px; align-items: center;">
//                <!-- 分數圓圈 -->
//                <div style="width: 42px; height: 42px; border-radius: 50%; background: rgba(59, 130, 246, 0.08); border: 2px solid #3b82f6; display: flex; flex-direction: column; align-items: center; justify-content: center; flex-shrink: 0; box-sizing: border-box;">
//                    <span style="font-size: 13px; font-weight: bold; color: #3b82f6; line-height: 1;">${aa.composite_score}</span>
//                    <span style="font-size: 8px; color: #3b82f6; margin-top: 1px;">分</span>
//                </div>
//                <!-- 雙色進度條 -->
//                <div style="flex: 1;">
//                    <div style="display: flex; justify-content: space-between; font-size: 10px; color: var(--text-secondary); margin-bottom: 3px;">
//                        <span>📊 量化指標: ${aa.quant_weight_pct}%</span>
//                        <span>🤖 AI 決策: ${aa.ai_weight_pct}%</span>
//                    </div>
//                    <div style="width: 100%; height: 5px; background: rgba(0,0,0,0.08); border-radius: 3px; overflow: hidden; display: flex;">
//                        <div style="width: ${aa.quant_weight_pct}%; background: #10b981; height: 100%;"></div>
//                        <div style="width: ${aa.ai_weight_pct}%; background: #3b82f6; height: 100%;"></div>
//                    </div>
//                    <p style="margin: 3px 0 0 0; font-size: 9px; color: var(--text-tertiary);">*指標衝突度 ${aa.conflict_degree}，自動動態切換權重</p>
//                </div>
//            </div>
//        </div>`;
//    }
//
//    return `<div class="scard" onclick='quickAdd(${JSON.stringify({code:s.code,name:s.name||'',entry:s.entry,stop:s.stop,target:s.target})})'>
//      <div class="scard-hdr">
//        <div><div class="sc-code">${s.code} <span style="font-size:11px;font-weight:400;color:var(--text-secondary)">${s.name||''}</span></div><div class="sc-sub">${sub}</div></div>
//        <div><div class="sc-score" style="color:${sc(s.score,total)}">${s.score}/${total}</div><div style="font-size:9px;color:var(--text-tertiary)">得分</div></div>
//      </div>
//      <div class="dots">${dots}</div>
//      <div class="sc-params">停損 ${s.stop} ｜ 目標 ${s.target} ｜ 建議 ${s.shares} 股</div>
//      ${extra}
//      ${adaptiveHtml}
//      <div style="margin-top:6px;text-align:right">
//        <button class="btn-xs" onclick="event.stopPropagation();showCoverage('${s.code}',decodeURIComponent('${safeName}'))">研究</button>
//      </div>
//    </div>`;
//  }).join('');
//  document.getElementById('scan-result').innerHTML=`<div class="scan-grid">${cards}</div><div class="scan-note">⚠ 技術指標篩選，非投資建議。進場前請對照策略 SOP 人工確認。已掃描 ${r.scanned||0} 檔，曝險模式：${r.risk_pct}%</div>`;
//}

//function renderScan(r){
//  const results=r.results||[];
//  if(!results.length){ document.getElementById('scan-result').innerHTML=`<div class="empty">無符合條件股票</div>`; return; }
//  const strat=r.strategy||currentStrat||'trend';
//  const sc=(v,total)=>v>=total-1?'var(--green)':v>=Math.floor(total/2)?'var(--yellow)':'var(--red)';
//  const cards=results.map(s=>{
//    const total=s.total_enabled||(strat==='ict'?7:strat==='fundamental'?5:6);
//    const dots=Object.entries(s.signals).map(([k,v])=>`<span class="dot ${v.enabled===false?'disabled':v.pass?'pass':'fail'}">${v.label}</span>`).join('');
//    const sub=strat==='ict'
//      ? `收 ${s.close} ｜ 均衡 ${s.equilibrium||'--'} ｜ OB ${s.ob_low||'--'}~${s.ob_high||'--'}`
//      : strat==='fundamental'
//        ? `收 ${s.close} ｜ PE ${s.pe??'--'} ｜ PB ${s.pb??'--'}`
//        : `收 ${s.close} ｜ ADX ${s.adx} ｜ ATR ${s.atr}`;
//    const extra=strat==='ict'
//      ? `<div class="sc-w52">區間 L:${s.range_low||'--'} H:${s.range_high||'--'}${s.mss_level?' ｜ MSS:'+s.mss_level:''}</div>`
//      : strat==='fundamental'
//        ? `<div class="sc-w52">EPS ${s.eps??'--'} → ${s.forward_eps??'--'} ｜ 營收成長 ${s.revenue_growth!=null?s.revenue_growth+'%':'--'}</div>`
//        : `<div class="sc-w52">52週 L:${s.w52_low} H:${s.w52_high}</div>`;
//    const safeName=encodeURIComponent(s.name||'');
//    return `<div class="scard" onclick='quickAdd(${JSON.stringify({code:s.code,name:s.name||'',entry:s.entry,stop:s.stop,target:s.target})})'>
//      <div class="scard-hdr">
//        <div><div class="sc-code">${s.code} <span style="font-size:11px;font-weight:400;color:var(--text-secondary)">${s.name||''}</span></div><div class="sc-sub">${sub}</div></div>
//        <div><div class="sc-score" style="color:${sc(s.score,total)}">${s.score}/${total}</div><div style="font-size:9px;color:var(--text-tertiary)">得分</div></div>
//      </div>
//      <div class="dots">${dots}</div>
//      <div class="sc-params">停損 ${s.stop} ｜ 目標 ${s.target} ｜ 建議 ${s.shares} 股</div>
//      ${extra}
//      <div style="margin-top:6px;text-align:right">
//        <button class="btn-xs" onclick="event.stopPropagation();showCoverage('${s.code}',decodeURIComponent('${safeName}'))">研究</button>
//      </div>
//    </div>`;
//  }).join('');
//  document.getElementById('scan-result').innerHTML=`<div class="scan-grid">${cards}</div><div class="scan-note">⚠ 技術指標篩選，非投資建議。進場前請對照策略 SOP 人工確認。已掃描 ${r.scanned||0} 檔，曝險模式：${r.risk_pct}%</div>`;
//}

function quickAdd(pre){ document.querySelectorAll('.tab')[0].click(); setTimeout(()=>openAddModal(pre),100); }

// ── Markdown-lite 格式化 ──────────────────────────────────────
function fmtCovText(raw) {
  if (!raw) return '';
  let s = esc(raw);
  // **bold** → <strong>
  s = s.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
  // [[Link]] → 可點擊的搜尋標籤
  s = s.replace(/\[\[(.+?)\]\]/g, '<span class="cov-inline-link" onclick="runTopicSearch(\'$1\')">$1</span>');
  // 行首 - 轉為列表項
  s = s.replace(/^- /gm, '• ');
  // 換行保留
  s = s.replace(/\n/g, '<br>');
  return s;
}

// ── Coverage Modal ───────────────────────────────────────────
async function showCoverage(code, name) {
  const modal = document.getElementById('coverage-modal');
  const body  = document.getElementById('cov-modal-body');
  const title = document.getElementById('cov-modal-title').querySelector('span');
  title.textContent = `研究摘要 · ${code} ${name}`;
  body.innerHTML = '<div class="empty">載入中...</div>';
  modal.classList.add('open');
  try {
    const d = await api('GET', `/api/coverage/${code}`);
    if (!d.ok) { body.innerHTML = `<div class="cov-empty">此股票尚無研究資料</div>`; return; }
    const wikiHtml = d.wikilinks && d.wikilinks.length
      ? d.wikilinks.map(w => `<span class="cov-tag" onclick="runTopicSearch('${esc(w)}')">${esc(w)}</span>`).join('')
      : '<span class="cov-empty">—</span>';
    body.innerHTML = `
      ${d.business ? `<div class="cov-section"><h5>業務概況</h5><div class="cov-body">${fmtCovText(d.business)}</div></div>` : ''}
      ${d.supply_chain ? `<div class="cov-section"><h5>供應鏈位置</h5><div class="cov-body">${fmtCovText(d.supply_chain)}</div></div>` : ''}
      ${d.customers ? `<div class="cov-section"><h5>主要客戶</h5><div class="cov-body">${fmtCovText(d.customers)}</div></div>` : ''}
      ${d.suppliers ? `<div class="cov-section"><h5>主要供應商</h5><div class="cov-body">${fmtCovText(d.suppliers)}</div></div>` : ''}
      <div class="cov-section"><h5>相關標的</h5><div class="cov-tags">${wikiHtml}</div></div>
      <div style="font-size:10px;color:var(--text-tertiary);margin-top:10px">資料來源：My-TW-Coverage · 產業：${esc(d.sector||'—')}</div>`;
  } catch(e) {
    body.innerHTML = `<div class="cov-empty">載入失敗，請確認伺服器執行中</div>`;
  }
}

function closeCoverageModal() {
  document.getElementById('coverage-modal').classList.remove('open');
}

// ── Coverage keywords ─────────────────────────────────────────
let _kwLoaded = false;
async function loadCoverageKeywords() {
  if (_kwLoaded) return;
  const cloud = document.getElementById('scan-kw-cloud');
  if (!cloud) return;
  try {
    const d = await api('GET', '/api/coverage/keywords?limit=200');
    if (!d.ok || !d.keywords.length) { cloud.innerHTML = '<span style="font-size:11px;color:var(--text-tertiary)">無關鍵字資料</span>'; return; }
    cloud.innerHTML = d.keywords.map(k =>
      `<span class="cov-tag" style="font-size:10px" onclick="runTopicSearch('${esc(k.keyword)}')">${k.keyword}</span>`
    ).join('');
    _kwLoaded = true;
  } catch(e) {
    cloud.innerHTML = '<span style="font-size:11px;color:var(--text-tertiary)">關鍵字載入失敗</span>';
  }
}
