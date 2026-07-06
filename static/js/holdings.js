// ── Positions ────────────────────────────────────────────────
let _reportMap = {};
let positions = [];

async function loadPositions(){
  const [d, rpt] = await Promise.all([
    api('GET','/api/positions'),
    api('GET','/api/report').catch(()=>({analyses:[]})),
  ]);
  positions = d.positions||[];
  _reportMap = {};
  (rpt.analyses||[]).forEach(a => { if(a.code) _reportMap[a.code] = a; });
  renderPositions();
  renderRisk(d.summary, d.config);
  loadPrices();
}

async function loadPrices(){
  try {
    const r = await api('GET', '/api/prices');
    const prices = r.prices || {};
    positions.forEach(p => {
      const pr = prices[String(p.id)];
      if(!pr || pr.current == null) return;
      p.current    = pr.current;
      p.change_pct = pr.change_pct;
      p.pnl        = pr.pnl;
      p.pnl_pct    = pr.pnl_pct;
      const card = document.querySelector(`[data-pid="${p.id}"]`);
      if(!card) return;
      const chgCls  = pr.change_pct >= 0 ? 'up' : 'dn';
      const chgSign = pr.change_pct >= 0 ? '+' : '';
      const pnlCls  = pr.pnl >= 0 ? 'g' : 'r';
      const pnlSign = pr.pnl >= 0 ? '+' : '';
      card.querySelector('.price-row').innerHTML = `
        <div>
          <div style="font-family:'JetBrains Mono',monospace;font-size:9px;color:var(--text-tertiary);letter-spacing:1px;margin-bottom:2px">現價</div>
          <span class="cur-price">${pr.current}</span>
          <span class="cur-chg ${chgCls}" style="margin-left:6px">${chgSign}${pr.change_pct?.toFixed(2)}%</span>
        </div>
        <div style="text-align:right">
          <div style="font-family:'JetBrains Mono',monospace;font-size:9px;color:var(--text-tertiary);letter-spacing:1px;margin-bottom:2px">未實現損益</div>
          <div class="pval ${pnlCls}" style="font-size:14px">${pnlSign}${pr.pnl?.toLocaleString()} 元</div>
          <div style="font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--text-tertiary)">${pnlSign}${pr.pnl_pct?.toFixed(2)}%</div>
        </div>`;
    });
    renderPnlChart();
    renderInlineCharts();
  } catch(e) {
    console.warn('報價更新失敗', e);
  }
}

let _posPage = 0;
const POS_PAGE_SIZE = 10;

function renderPositions(){
  document.getElementById('pos-count').textContent = positions.length;
  const el = document.getElementById('pos-list');
  const pager = document.getElementById('pos-pagination');
  if(!positions.length){ el.innerHTML=`<div class="empty"><div class="empty-icon">📭</div>無持倉，點擊「新增部位」開始追蹤</div>`; pager.style.display='none'; return; }
  const totalPages = Math.ceil(positions.length / POS_PAGE_SIZE);
  _posPage = Math.min(_posPage, totalPages - 1);
  const page = positions.slice(_posPage * POS_PAGE_SIZE, (_posPage + 1) * POS_PAGE_SIZE);
  // Show pagination only when needed
  if(positions.length > POS_PAGE_SIZE){
    pager.style.display='flex';
    document.getElementById('pos-page-label').textContent = `${_posPage+1} / ${totalPages}`;
  } else {
    pager.style.display='none';
  }
  const badges = { safe:`<span class="badge bs">✅ 無風險</span>`, active:`<span class="badge ba">🔥 持倉中</span>`, alert:`<span class="badge br">⚠ 注意</span>` };
  el.innerHTML = page.map(p=>{
    const sc = p.stop>=p.entry?'g':'r';
    const rc = p.risk_amount===0?'g':'y';
    const tgt = p.target ? p.target+' 元' : '波段抱單';
    let prog='';
    if(p.target && p.status==='active'){
      const pct = Math.min(85, Math.max(5, ((p.entry-p.stop)/(p.target-p.entry))*30));
      prog=`<div class="prog-wrap"><div class="prog-lbl"><span>停損 ${p.stop}</span><span>進場 ${p.entry}</span><span>目標 ${p.target}</span></div><div class="progress" style="height:4px"><div class="progress-bar" style="width:${pct}%;background:linear-gradient(90deg,var(--blue),var(--green))"></div></div></div>`;
    }
    let priceRow = '';
    if(p.current != null){
      const chgCls = p.change_pct>=0 ? 'up' : 'dn';
      const chgSign = p.change_pct>=0 ? '+' : '';
      const pnlCls = p.pnl>=0 ? 'g' : 'r';
      const pnlSign = p.pnl>=0 ? '+' : '';
      priceRow = `<div class="price-row">
        <div>
          <div style="font-family:'JetBrains Mono',monospace;font-size:9px;color:var(--text-tertiary);letter-spacing:1px;margin-bottom:2px">現價</div>
          <span class="cur-price">${p.current}</span>
          <span class="cur-chg ${chgCls}" style="margin-left:6px">${chgSign}${p.change_pct?.toFixed(2)}%</span>
        </div>
        <div style="text-align:right">
          <div style="font-family:'JetBrains Mono',monospace;font-size:9px;color:var(--text-tertiary);letter-spacing:1px;margin-bottom:2px">未實現損益</div>
          <div class="pval ${pnlCls}" style="font-size:14px">${pnlSign}${p.pnl?.toLocaleString()} 元</div>
          <div style="font-family:'JetBrains Mono',monospace;font-size:10px;color:var(--text-tertiary)">${pnlSign}${p.pnl_pct?.toFixed(2)}%</div>
        </div>
      </div>`;
    } else {
      priceRow = `<div class="price-row"><span style="font-family:'JetBrains Mono',monospace;font-size:11px;color:var(--text-tertiary)">⏳ 報價載入中...</span></div>`;
    }
    return `<div class="pcard ${p.status}" data-pid="${p.id}">
      <div class="ph">
        <div class="ph-left"><span class="stkcode">${esc(p.code)}</span><div><div style="font-weight:600;font-size:13px">${esc(p.name)}</div><div class="stksub">進場：${p.date}</div></div></div>
        <div style="display:flex;gap:6px;align-items:center">
          ${badges[p.status]||''}
          <button class="btn-xs" onclick="editPos(${p.id})" title="編輯">✎</button>
          <button class="btn-xs danger" onclick="delPos(${p.id})" title="刪除">🗑</button>
        </div>
      </div>
      <div class="pb">
        ${priceRow}
        <div class="pgrid">
          <div class="pi"><label>進場價</label><div class="pval">${p.entry} 元</div></div>
          <div class="pi"><label>持股數</label><div class="pval b">${(p.shares/1000).toFixed(1)} 張</div></div>
          <div class="pi"><label>停損價</label><div class="pval ${sc}">${p.stop} 元</div></div>
          <div class="pi"><label>目標價</label><div class="pval g">${tgt}</div></div>
          <div class="pi" style="grid-column:span 2"><label>總曝險</label><div class="pval ${rc}">${p.risk_amount===0?'0 元（已無風險）':p.risk_amount.toLocaleString()+' 元'}</div></div>
        </div>
        ${prog}
        ${(()=>{const rpt=_reportMap[p.code];return rpt?`<div class="ptech">
          <span>${rpt.ema20?'EMA20: '+rpt.ema20:''} ${rpt.below_ema20?'<span class="r">▼ 跌破</span>':'<span class="g">▲ 站上</span>'}</span>
          ${rpt.pct_to_target!=null?'<span>目標距: '+(rpt.pct_to_target>0?'+':'')+rpt.pct_to_target+'%</span>':''}
          ${(rpt.alerts||[]).map(a=>'<span class="r" style="font-size:10px">'+esc(a)+'</span>').join('')}
        </div>`:''})()}
        ${p.note?`<div class="pnote">📋 ${esc(p.note)}</div>`:''}
      </div>
      <div class="pcard-chart" id="chart-${p.code}"></div>
    </div>`;
  }).join('');
}

function posPagePrev(){ if(_posPage > 0){ _posPage--; renderPositions(); } }
function posPageNext(){
  const totalPages = Math.ceil(positions.length / POS_PAGE_SIZE);
  if(_posPage < totalPages - 1){ _posPage++; renderPositions(); }
}

function renderRisk(s, cfg){
  if(!s) return;
  const total = s.total_capital || 3000000;

  // Summary cards with CountUp animation
  const elTotal = document.getElementById('summary-total');
  if(elTotal){
    elTotal.textContent = '$0';
    try {
      new countUp.CountUp(elTotal, total, { duration: 1.2, separator: ',', prefix: '$' }).start();
    } catch(e) { elTotal.textContent = '$' + total.toLocaleString(); }
  }

  const pnlEl = document.getElementById('summary-pnl');
  if(pnlEl) pnlEl.textContent = '';

  const wlEl = document.getElementById('summary-wl');
  if(wlEl) wlEl.textContent = `${positions.filter(p=>p.status==='active').length} 活躍`;

  // Risk display with CountUp
  const riskPct = document.getElementById('risk-pct');
  if(riskPct){
    const rVal = s.risk_pct||0;
    try {
      new countUp.CountUp(riskPct, rVal, { duration: 1.2, decimalPlaces: 1, suffix: '%' }).start();
    } catch(e) { riskPct.textContent = rVal+'%'; }
  }

  const riskMode = document.getElementById('risk-mode');
  const c = cfg?.consecutive_losses||0;
  const slow = c>=3;
  if(riskMode){
    riskMode.textContent = slow?'⚠ 1% 降速模式':'正常 2%';
    riskMode.style.color = slow?'var(--yellow)':'var(--green)';
  }

  // Keep old hidden elements working
  const rv = document.getElementById('risk-val');
  if(rv) rv.textContent = `${(s.total_risk||0).toLocaleString()} / ${total.toLocaleString()}`;
  const rf = document.getElementById('risk-fill');
  if(rf) rf.style.width = Math.min(100,(s.risk_pct||0)*5)+'%';
  const cc = document.getElementById('consec');
  if(cc) cc.textContent = c+' 次';
}

async function delPos(id){
  const pos = positions.find(p=>p.id===id);
  const label = pos ? `${pos.code} ${pos.name}` : `#${id}`;
  if(typeof Swal!=='undefined'){
    const res = await Swal.fire({
      title: '確認刪除？',
      text: `「${label}」將被永久移除`,
      icon: 'warning',
      showCancelButton: true,
      confirmButtonColor: '#ef4444',
      cancelButtonColor: '#6b7280',
      confirmButtonText: '確認刪除',
      cancelButtonText: '取消',
    });
    if(!res.isConfirmed) return;
  } else {
    if(!confirm(`確認刪除「${label}」？\n此操作無法復原。`)) return;
  }
  const r = await api('DELETE',`/api/positions/${id}`);
  if(r.ok){ toast('✓ 已刪除','ok'); loadPositions(); }
  else toast(r.error||'刪除失敗','err');
}

function editPos(id){
  const p = positions.find(p=>p.id===id);
  if(!p) return;
  document.getElementById('f-edit-id').value  = id;
  document.getElementById('f-code').value     = p.code;
  document.getElementById('f-name').value     = p.name;
  document.getElementById('f-date').value     = p.date;
  document.getElementById('f-entry').value    = p.entry;
  document.getElementById('f-shares').value   = p.shares;
  document.getElementById('f-stop').value     = p.stop;
  document.getElementById('f-target').value   = p.target||'';
  document.getElementById('f-note').value     = p.note||'';
  document.getElementById('f-status').value   = p.status;
  document.getElementById('f-name-tag').textContent = p.name||'--';
  document.getElementById('f-name-tag').style.color = 'var(--green)';
  document.getElementById('modal-title').textContent = `✎ 編輯持倉 ${p.code} ${p.name}`;
  document.getElementById('add-modal').classList.add('open');
}

// ── Add Modal ────────────────────────────────────────────────
function openAddModal(pre){
  document.getElementById('f-edit-id').value = '';
  document.getElementById('modal-title').textContent = '+ 新增持股部位';
  document.getElementById('f-name-tag').textContent='輸入代號自動查詢';
  document.getElementById('f-name-tag').style.color='var(--text-tertiary)';
  if(pre){
    document.getElementById('f-code').value=pre.code||'';
    document.getElementById('f-entry').value=pre.entry||'';
    document.getElementById('f-stop').value=pre.stop||'';
    document.getElementById('f-target').value=pre.target||'';
    if(pre.name){
      document.getElementById('f-name').value=pre.name;
      document.getElementById('f-name-tag').textContent=pre.name;
      document.getElementById('f-name-tag').style.color='var(--green)';
    } else if(pre.code){
      autoFetchName(pre.code);
    }
  }
  document.getElementById('f-date').value = new Date().toISOString().split('T')[0];
  document.getElementById('add-modal').classList.add('open');
}

async function savePos(){
  const editId = document.getElementById('f-edit-id').value;
  const b = {
    code:   document.getElementById('f-code').value.trim(),
    name:   document.getElementById('f-name').value.trim(),
    date:   document.getElementById('f-date').value,
    entry:  parseFloat(document.getElementById('f-entry').value),
    shares: parseInt(document.getElementById('f-shares').value),
    stop:   parseFloat(document.getElementById('f-stop').value),
    target: document.getElementById('f-target').value ? parseFloat(document.getElementById('f-target').value) : null,
    status: document.getElementById('f-status').value,
    note:   document.getElementById('f-note').value,
  };
  if(!b.code){ toast('請輸入代號','err'); return; }
  if(!b.name){ toast('請輸入名稱','err'); return; }
  if(isNaN(b.entry)||isNaN(b.shares)||isNaN(b.stop)){ toast('請填入進場價、持股數、停損價','err'); return; }

  let r;
  if(editId){
    r = await api('PUT', `/api/positions/${editId}`, b);
    if(r.ok){ toast('✓ 已更新','ok'); }
    else { toast(r.error||'更新失敗','err'); return; }
  } else {
    r = await api('POST', '/api/positions', b);
    if(r.ok){ toast('✓ 新增成功','ok'); }
    else { toast(r.error||'新增失敗','err'); return; }
  }

  closeModal('add-modal');
  ['f-code','f-name','f-entry','f-shares','f-stop','f-target','f-note'].forEach(id=>document.getElementById(id).value='');
  document.getElementById('f-edit-id').value = '';
  document.getElementById('modal-title').textContent = '+ 新增持股部位';
  document.getElementById('f-name-tag').textContent='輸入代號自動查詢';
  document.getElementById('f-name-tag').style.color='var(--text-tertiary)';
  loadPositions();
}

// ── P&L Bar Chart ────────────────────────────────────────────
function renderPnlChart(){
  const wrap = document.getElementById('pnl-chart-wrap');
  const withPrices = positions.filter(p => p.pnl_pct != null);
  if(!withPrices.length){ wrap.style.display='none'; return; }

  const labels  = withPrices.map(p => p.code);
  const data    = withPrices.map(p => +p.pnl_pct.toFixed(2));
  const colors  = data.map(v => v >= 0 ? 'rgba(16,185,129,0.75)' : 'rgba(239,68,68,0.75)');
  const borders = data.map(v => v >= 0 ? '#10b981' : '#ef4444');

  const ctx = document.getElementById('pnl-chart').getContext('2d');
  if(window._pnlChart) window._pnlChart.destroy();
  window._pnlChart = new Chart(ctx, {
    type: 'bar',
    data: { labels, datasets: [{ data, backgroundColor: colors, borderColor: borders, borderWidth: 1 }] },
    options: {
      indexAxis: 'y',
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: c => `${c.raw >= 0 ? '+' : ''}${c.raw}%` } },
      },
      scales: {
        x: {
          grid: { color: 'rgba(0,0,0,0.04)' },
          ticks: { color: '#6b7280', font: { family: 'JetBrains Mono', size: 10 },
                   callback: v => (v > 0 ? '+' : '') + v + '%' },
        },
        y: {
          grid: { display: false },
          ticks: { color: '#374151', font: { family: 'JetBrains Mono', size: 11, weight: '700' } },
        },
      },
    },
  });
  const h = Math.max(60, Math.min(200, withPrices.length * 36));
  document.getElementById('pnl-chart-box').style.height = h + 'px';
  wrap.style.display = 'block';
}

// ── Inline K-Line Charts ─────────────────────────────────────
async function renderInlineCharts() {
  for (const p of positions) {
    const container = document.getElementById(`chart-${p.code}`);
    if (!container || container.dataset.loaded) continue;

    try {
      const r = await api('GET', `/api/ohlcv/${encodeURIComponent(p.code)}`);
      if (!r.ok || !r.candles || !r.candles.length) {
        container.innerHTML = '<div style="padding:12px;color:var(--text-tertiary);font-size:11px;text-align:center">K 線資料不足</div>';
        continue;
      }

      container.innerHTML = '';
      const isDark = document.body.getAttribute('data-theme') === 'dark';
      const chart = LightweightCharts.createChart(container, {
        layout: {
          background: { type: 'solid', color: isDark ? '#0d1117' : '#ffffff' },
          textColor: isDark ? '#8b949e' : '#6b7280',
          fontFamily: 'JetBrains Mono',
          fontSize: 11
        },
        grid: {
          vertLines: { color: isDark ? '#21262d' : '#f3f4f6' },
          horzLines: { color: isDark ? '#21262d' : '#f3f4f6' }
        },
        crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
        rightPriceScale: { borderColor: isDark ? '#30363d' : '#e5e7eb' },
        timeScale: { borderColor: isDark ? '#30363d' : '#e5e7eb', timeVisible: true },
        width: container.clientWidth,
        height: 360,
      });

      const candles = chart.addCandlestickSeries({
        upColor: '#10b981', downColor: '#ef4444',
        borderVisible: false,
        wickUpColor: '#10b981', wickDownColor: '#ef4444',
      });
      candles.setData(r.candles);

      // EMA5 (orange), EMA20 (blue), EMA60 (purple)
      if (r.ema5)  chart.addLineSeries({ color: '#f59e0b', lineWidth: 1,   title: 'EMA5',  priceLineVisible: false, lastValueVisible: false }).setData(r.ema5);
      if (r.ema20) chart.addLineSeries({ color: '#3b82f6', lineWidth: 1.5, title: 'EMA20', priceLineVisible: false, lastValueVisible: false }).setData(r.ema20);
      if (r.ema60) chart.addLineSeries({ color: '#a855f7', lineWidth: 1,   title: 'EMA60', priceLineVisible: false, lastValueVisible: false }).setData(r.ema60);

      // Price lines: entry, stop, target
      if (p.entry)  candles.createPriceLine({ price: p.entry,  color: '#9ca3af', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: '進場' });
      if (p.stop)   candles.createPriceLine({ price: p.stop,   color: '#ef4444', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: '停損' });
      if (p.target) candles.createPriceLine({ price: p.target, color: '#10b981', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: '目標' });

      // Swing Low — minimum of last 20 bars
      if (r.candles.length >= 5) {
        const last20  = r.candles.slice(-20);
        const swingLow = Math.min(...last20.map(c => c.low));
        candles.createPriceLine({ price: swingLow, color: '#6366f1', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: 'Swing Low' });
      }

      chart.timeScale().fitContent();
      container.dataset.loaded = 'true';

      // ResizeObserver
      const ro = new ResizeObserver(() => chart.applyOptions({ width: container.clientWidth }));
      ro.observe(container);

    } catch (e) {
      container.innerHTML = '<div style="padding:12px;color:var(--text-tertiary);font-size:11px;text-align:center">圖表載入失敗</div>';
    }
  }
}

// ── K-Line Chart (Modal) ──────────────────────────────────────
function openChartById(id){
  const p = positions.find(p => p.id === id);
  if(!p) return;
  openChart(p.code, { entry: p.entry, stop: p.stop, target: p.target || null, name: p.name });
}

async function openChart(code, pos){
  document.getElementById('chart-modal-title').textContent = `${code}  ${pos.name || ''} · K 線圖`;
  document.getElementById('chart-modal').classList.add('open');
  const container = document.getElementById('chart-container');
  container.innerHTML = '<div class="loader"><div class="spinner"></div>載入 K 線資料中...</div>';

  // Clean up previous chart
  if(window._chartInst){ window._chartInst.remove(); window._chartInst = null; }
  if(window._chartRO){   window._chartRO.disconnect(); window._chartRO = null; }

  try{
    const r = await api('GET', `/api/ohlcv/${encodeURIComponent(code)}`);
    if(!r.ok){ container.innerHTML = '<div class="empty" style="color:var(--red)">⚠ 資料載入失敗</div>'; return; }

    container.innerHTML = '';
    const chart = LightweightCharts.createChart(container, {
      layout: { background: { type: 'solid', color: document.body.getAttribute('data-theme')==='dark' ? '#0d1117' : '#ffffff' }, textColor: '#6b7280',
                fontFamily: 'JetBrains Mono' },
      grid:   { vertLines: { color: '#f3f4f6' }, horzLines: { color: '#f3f4f6' } },
      crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
      rightPriceScale: { borderColor: '#e5e7eb' },
      timeScale: { borderColor: '#e5e7eb', timeVisible: false },
      width: container.clientWidth, height: 420,
    });

    const candles = chart.addCandlestickSeries({
      upColor: '#10b981', downColor: '#ef4444',
      borderVisible: false,
      wickUpColor: '#10b981', wickDownColor: '#ef4444',
    });
    candles.setData(r.candles);

    chart.addLineSeries({ color: '#f59e0b', lineWidth: 1, title: 'EMA5',  priceLineVisible: false, lastValueVisible: false }).setData(r.ema5);
    chart.addLineSeries({ color: '#3b82f6', lineWidth: 2, title: 'EMA20', priceLineVisible: false, lastValueVisible: false }).setData(r.ema20);

    if(pos.entry)  candles.createPriceLine({ price: pos.entry,  color: '#9ca3af', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: '進場' });
    if(pos.stop)   candles.createPriceLine({ price: pos.stop,   color: '#ef4444', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: '停損' });
    if(pos.target) candles.createPriceLine({ price: pos.target, color: '#10b981', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: '目標' });

    chart.timeScale().fitContent();
    window._chartInst = chart;

    const ro = new ResizeObserver(() => {
      if(window._chartInst) window._chartInst.applyOptions({ width: container.clientWidth });
    });
    ro.observe(container);
    window._chartRO = ro;

  }catch(e){
    container.innerHTML = '<div class="empty" style="color:var(--red)">⚠ 載入失敗，請確認伺服器執行中</div>';
  }
}

function closeChartModal(){
  document.getElementById('chart-modal').classList.remove('open');
  if(window._chartInst){ window._chartInst.remove(); window._chartInst = null; }
  if(window._chartRO){   window._chartRO.disconnect(); window._chartRO = null; }
}

// ── PNG 匯出（K線圖）─────────────────────────────────────────
function exportChartPng(){
  if(!window._chartInst){ toast('圖表尚未載入','err'); return; }
  try {
    const img = window._chartInst.takeScreenshot();
    const a = document.createElement('a');
    a.href = URL.createObjectURL(img);
    a.download = `kline_${Date.now()}.png`;
    a.click();
  } catch(e) { toast('截圖失敗: ' + e.message, 'err'); }
}
