// ── Backtest ─────────────────────────────────────────────────
let btAbort = null;
async function runBacktest(){
  const code  = document.getElementById('bt-code').value.trim();
  const strat = document.getElementById('bt-strat').value;
  const period= document.getElementById('bt-period').value;
  const score = parseInt(document.getElementById('bt-score').value);
  if(!code){ toast('請輸入代號','err'); return; }

  const btn = document.getElementById('bt-run-btn');
  const stopBtn = document.getElementById('bt-stop-btn');
  btn.disabled=true; btn.textContent='回測中...';
  stopBtn.classList.remove('d-none');
  document.getElementById('bt-result').style.display='none';
  document.getElementById('bt-empty').style.display='block';
  document.getElementById('bt-empty').innerHTML=`<div class="loader"><div class="spinner"></div>抓取歷史資料並逐根 K 棒計算中，請稍候（約 5-20 秒）...</div>`;
  btAbort = new AbortController();

  try{
    const commission_pct = parseFloat(document.getElementById('bt-commission').value) || 0.001425;
    const slippage_pct   = parseFloat(document.getElementById('bt-slippage').value)   || 0.0005;
    const r = await api('POST','/api/backtest',{code, strategy:strat, period, min_score:score, commission_pct, slippage_pct}, btAbort.signal);
    if(!r.ok){
      document.getElementById('bt-empty').innerHTML=`<div class="empty"><div class="empty-icon">⚠️</div>${r.error||'回測失敗'}</div>`;
      return;
    }
    if(r.multi){
      renderMultiBacktestResult(r);
    } else {
      renderBacktestResult(r);
    }
    document.getElementById('bt-result').style.display='block';
    document.getElementById('bt-empty').style.display='none';
  }catch(e){
    if(e.name==='AbortError') document.getElementById('bt-empty').innerHTML=`<div class="empty">已停止回測</div>`;
    else document.getElementById('bt-empty').innerHTML=`<div class="empty" style="color:var(--red)">⚠ 回測失敗，請確認伺服器執行中</div>`;
  }finally{
    btAbort=null;
    btn.disabled=false; btn.textContent='▶ 開始回測';
    stopBtn.classList.add('d-none');
  }
}
function stopBacktest(){ if(btAbort){ btAbort.abort(); btAbort=null; } }

// ── Full-market Backtest (SSE) ────────────────────────────────
let fullBtEs = null;
let btTechFilterEnabled = false;
function toggleBtTechFilter(){
  btTechFilterEnabled = !btTechFilterEnabled;
  const btn = document.getElementById('bt-tech-filter-btn');
  if(btTechFilterEnabled){
    btn.classList.remove('btn-outline-secondary');
    btn.classList.add('btn-outline-info');
    btn.textContent = '⚡ 電子股';
  } else {
    btn.classList.remove('btn-outline-info');
    btn.classList.add('btn-outline-secondary');
    btn.textContent = '🌐 全市場';
  }
}
function stopFullBacktest(){
  if(fullBtEs){ fullBtEs.close(); fullBtEs=null; }
  const btn = document.getElementById('bt-full-btn');
  const stopBtn = document.getElementById('bt-full-stop-btn');
  btn.disabled=false; btn.textContent='🌐 全市場';
  stopBtn.classList.add('d-none');
  document.getElementById('bt-empty').innerHTML=`<div class="empty">已停止全市場回測</div>`;
}

function runFullBacktest(){
  const strat  = document.getElementById('bt-strat').value;
  const period = document.getElementById('bt-period').value;
  const score  = parseInt(document.getElementById('bt-score').value);
  if(fullBtEs){ fullBtEs.close(); fullBtEs=null; }

  const btn = document.getElementById('bt-full-btn');
  const stopBtn = document.getElementById('bt-full-stop-btn');
  btn.disabled = true; btn.textContent = '掃描中...';
  stopBtn.classList.remove('d-none');
  document.getElementById('bt-result').style.display = 'none';
  document.getElementById('bt-empty').style.display = 'block';
  document.getElementById('bt-empty').innerHTML = `<div class="loader"><div class="spinner"></div>全市場掃描中，請稍候...</div>`;

  const btFilterParam = btTechFilterEnabled ? '&filter=tech' : '';
  const _btKey = localStorage.getItem('trading_api_key') || '';
  const _btToken = localStorage.getItem('jwt_token') || '';
  if(typeof NProgress!=='undefined') NProgress.start();
  fullBtEs = new EventSource(`/api/backtest/full?strategy=${strat}&period=${period}&min_score=${score}${btFilterParam}&key=${encodeURIComponent(_btKey)}&token=${encodeURIComponent(_btToken)}`);
  fullBtEs.onmessage = ev => {
    const d = JSON.parse(ev.data);
    if(d.type === 'scan_progress'){
      document.getElementById('bt-empty').innerHTML = `<div class="loader"><div class="spinner"></div>掃描中 ${d.done}/${d.total}，通過 ${d.passed} 檔...</div>`;
    } else if(d.type === 'bt_start'){
      document.getElementById('bt-empty').innerHTML = `<div class="loader"><div class="spinner"></div>回測 ${d.total} 檔中...</div>`;
    } else if(d.type === 'bt_result'){
      const it = d.item;
      document.getElementById('bt-empty').innerHTML = `<div class="loader"><div class="spinner"></div>回測 ${d.done}/${d.total}：${it.code} ${it.total_return>=0?'+':''}${it.total_return}%</div>`;
    } else if(d.type === 'done'){
      if(typeof NProgress!=='undefined') NProgress.done();
      fullBtEs.close(); fullBtEs = null;
      btn.disabled = false; btn.textContent = '🌐 全市場';
      stopBtn.classList.add('d-none');
      renderFullBtResult(d);
    }
  };
  fullBtEs.onerror = () => {
    if(typeof NProgress!=='undefined') NProgress.done();
    fullBtEs.close(); fullBtEs = null;
    btn.disabled = false; btn.textContent = '🌐 全市場';
    stopBtn.classList.add('d-none');
    document.getElementById('bt-empty').innerHTML = `<div class="empty" style="color:var(--red)">⚠ 全市場回測失敗，請確認伺服器執行中</div>`;
  };
}

function renderFullBtResult(d){
  const rows = d.summary || [];
  if(!rows.length){
    document.getElementById('bt-empty').innerHTML = `<div class="empty">無符合條件的股票</div>`;
    return;
  }
  const stLabel = {'trend':'趨勢策略','ict':'ICT 策略','fundamental':'基本面策略'}[d.strategy] || d.strategy;
  const tbody = rows.map(r=>`
    <tr>
      <td style="font-family:var(--mono)">${esc(r.code)}</td>
      <td>${esc(r.name||'')}</td>
      <td style="text-align:right;color:${r.total_return>=0?'var(--green)':'var(--red)'}">
        ${r.total_return>=0?'+':''}${r.total_return}%</td>
      <td style="text-align:right">${r.win_rate}%</td>
      <td style="text-align:right">${r.total_trades}</td>
      <td style="text-align:right">${r.profit_factor>=999?'∞':r.profit_factor}</td>
      <td style="text-align:right;color:var(--red)">${r.max_drawdown}%</td>
    </tr>`).join('');
  document.getElementById('bt-empty').style.display = 'none';
  document.getElementById('bt-result').style.display = 'block';
  document.getElementById('bt-single-trades').style.display = 'none';
  document.getElementById('bt-detail-section').style.display = 'block';
  document.getElementById('bt-stats').innerHTML = `
    <div class="col-12"><div class="card card-sm"><div class="card-body p-2" style="font-size:11px;color:var(--text-secondary)">
      全市場回測 · ${stLabel} · ${d.period} · 共 ${rows.length} 檔
    </div></div></div>`;
  // No equity chart for full scan
  document.getElementById('bt-equity-card').style.display = 'none';
  document.getElementById('bt-detail-section').innerHTML = `
    <div class="card mt-2">
      <div class="card-header"><h3 class="card-title" style="font-family:var(--mono);font-size:11px;letter-spacing:1.5px;text-transform:uppercase">全市場回測排行</h3></div>
      <div class="card-body p-0">
        <div style="overflow-x:auto;max-height:420px;overflow-y:auto">
          <table class="table table-sm table-hover mb-0" style="font-family:var(--mono);font-size:11px">
            <thead style="position:sticky;top:0;background:var(--card-bg)">
              <tr><th>代號</th><th>名稱</th><th style="text-align:right">總報酬</th><th style="text-align:right">勝率</th><th style="text-align:right">交易數</th><th style="text-align:right">盈虧比</th><th style="text-align:right">最大回撤</th></tr>
            </thead>
            <tbody>${tbody}</tbody>
          </table>
        </div>
      </div>
    </div>`;
}

let _btTrades = [];
function renderBacktestResult(r){
  _btTrades = r.trades || [];
  document.getElementById('bt-single-trades').style.display = 'block';
  document.getElementById('bt-detail-section').style.display = 'none';
  const s  = r.stats;
  const stratLabel = {'trend':'趨勢策略','ict':'ICT 策略','fundamental':'基本面策略'}[r.strategy] || r.strategy;
  const netPnl     = r.final_equity - r.capital;
  const netColor   = s.total_return >= 0 ? 'var(--green)' : 'var(--red)';
  const pfDisplay  = s.profit_factor >= 999 ? '∞' : s.profit_factor;

  // ── 績效指標卡 ───────────────────────────────────────────
  document.getElementById('bt-stats').innerHTML = `
    <div class="col-6 col-md-2">
      <div class="card card-sm text-center"><div class="card-body p-2">
        <div style="font-family:var(--mono);font-size:9px;color:var(--text-secondary);letter-spacing:1px;margin-bottom:4px">總交易</div>
        <div id="bt-cu-trades" style="font-family:var(--mono);font-size:24px;font-weight:700">0</div>
        <div style="font-size:10px;color:var(--text-secondary)">${s.wins}W / ${s.losses}L</div>
      </div></div>
    </div>
    <div class="col-6 col-md-2">
      <div class="card card-sm text-center"><div class="card-body p-2">
        <div style="font-family:var(--mono);font-size:9px;color:var(--text-secondary);letter-spacing:1px;margin-bottom:4px">勝率</div>
        <div id="bt-cu-winrate" style="font-family:var(--mono);font-size:24px;font-weight:700">0</div>
        <div style="font-size:10px;color:var(--text-secondary)">均贏 +${s.avg_win_pct}%</div>
      </div></div>
    </div>
    <div class="col-6 col-md-2">
      <div class="card card-sm text-center"><div class="card-body p-2">
        <div style="font-family:var(--mono);font-size:9px;color:var(--text-secondary);letter-spacing:1px;margin-bottom:4px">盈虧比</div>
        <div id="bt-cu-pf" style="font-family:var(--mono);font-size:24px;font-weight:700">0</div>
        <div style="font-size:10px;color:var(--text-secondary)">均虧 ${s.avg_loss_pct}%</div>
      </div></div>
    </div>
    <div class="col-6 col-md-2">
      <div class="card card-sm text-center"><div class="card-body p-2">
        <div style="font-family:var(--mono);font-size:9px;color:var(--text-secondary);letter-spacing:1px;margin-bottom:4px">最大回撤</div>
        <div id="bt-cu-dd" style="font-family:var(--mono);font-size:24px;font-weight:700;color:var(--red)">0</div>
        <div style="font-size:10px;color:var(--text-secondary)">峰谷回撤</div>
      </div></div>
    </div>
    <div class="col-12 col-md-4">
      <div class="card card-sm text-center"><div class="card-body p-2">
        <div style="font-family:var(--mono);font-size:9px;color:var(--text-secondary);letter-spacing:1px;margin-bottom:4px">總報酬 · ${stratLabel} · ${r.code}</div>
        <div id="bt-cu-return" style="font-family:var(--mono);font-size:24px;font-weight:700;color:${netColor}">0</div>
        <div style="font-size:10px;color:var(--text-secondary)">${netPnl >= 0 ? '+' : ''}${netPnl.toLocaleString()} 元</div>
      </div></div>
    </div>`;

  // CountUp animations for backtest stats
  try {
    new countUp.CountUp('bt-cu-trades', s.total_trades, { duration: 1 }).start();
    new countUp.CountUp('bt-cu-winrate', s.win_rate, { duration: 1, decimalPlaces: 1, suffix: '%' }).start();
    new countUp.CountUp('bt-cu-pf', parseFloat(pfDisplay) || 0, { duration: 1, decimalPlaces: 2 }).start();
    new countUp.CountUp('bt-cu-dd', s.max_drawdown, { duration: 1, decimalPlaces: 1, suffix: '%' }).start();
    new countUp.CountUp('bt-cu-return', s.total_return, { duration: 1.2, decimalPlaces: 1, prefix: s.total_return >= 0 ? '+' : '', suffix: '%' }).start();
  } catch(e) {
    // Fallback: just set text
    document.getElementById('bt-cu-trades').textContent = s.total_trades;
    document.getElementById('bt-cu-winrate').textContent = s.win_rate + '%';
    document.getElementById('bt-cu-pf').textContent = pfDisplay;
    document.getElementById('bt-cu-dd').textContent = s.max_drawdown + '%';
    document.getElementById('bt-cu-return').textContent = (s.total_return >= 0 ? '+' : '') + s.total_return + '%';
  }

  // ── 資產曲線 ──────────────────────────────────────────────
  document.getElementById('bt-equity-card').style.display = '';
  const ctx = document.getElementById('bt-equity-chart').getContext('2d');
  if(window._btChart){ window._btChart.destroy(); window._btChart=null; }

  const curve = r.equity_curve;
  const step  = Math.max(1, Math.floor(curve.length / 300));
  const pts   = curve.filter((_,i) => i % step === 0 || i === curve.length - 1);

  // Draw initial capital baseline
  const initLine = pts.map(() => r.capital);

  // Monte Carlo confidence band (if available)
  const mcDatasets = [];
  if(r.monte_carlo && r.monte_carlo.p5 && r.monte_carlo.p5.length > 0){
    const mc = r.monte_carlo;
    // Map Monte Carlo points to same downsampled labels
    // MC has len(trades)+1 points; we use sparse indices to align
    const mcStep = Math.max(1, Math.floor(mc.p5.length / pts.length));
    const mcPts5  = mc.p5.filter((_,i) => i % mcStep === 0 || i === mc.p5.length-1).slice(0, pts.length);
    const mcPts95 = mc.p95.filter((_,i) => i % mcStep === 0 || i === mc.p95.length-1).slice(0, pts.length);
    mcDatasets.push({
      label: 'MC p95',
      data: mcPts95,
      borderColor: 'rgba(88,166,255,0.25)',
      backgroundColor: 'rgba(88,166,255,0.07)',
      borderWidth: 1, pointRadius: 0, fill: '+1', tension: 0.2, order: 3,
    });
    mcDatasets.push({
      label: 'MC p5',
      data: mcPts5,
      borderColor: 'rgba(88,166,255,0.25)',
      backgroundColor: 'transparent',
      borderWidth: 1, pointRadius: 0, fill: false, tension: 0.2, order: 4,
    });
  }

  window._btChart = new Chart(ctx, {
    type: 'line',
    data: {
      labels: pts.map(d => d.date),
      datasets: [
        {
          label: '資產',
          data: pts.map(d => d.equity),
          borderColor: s.total_return >= 0 ? '#10b981' : '#ef4444',
          backgroundColor: s.total_return >= 0 ? 'rgba(16,185,129,0.07)' : 'rgba(239,68,68,0.07)',
          borderWidth: 2, fill: true, pointRadius: 0, tension: 0.2, order: 1,
        },
        {
          label: '初始資金',
          data: initLine,
          borderColor: 'rgba(0,0,0,0.15)',
          borderWidth: 1, borderDash: [4,4], pointRadius: 0, fill: false, order: 2,
        },
        ...mcDatasets,
      ],
    },
    options: {
      responsive: true, maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: c => c.dataset.label + ': ' + c.raw.toLocaleString() + ' 元',
          },
        },
      },
      scales: {
        x: {
          grid: { color: 'rgba(0,0,0,0.04)' },
          ticks: { color: '#6b7280', font: { family: 'JetBrains Mono', size: 9 }, maxTicksLimit: 8 },
        },
        y: {
          grid: { color: 'rgba(0,0,0,0.04)' },
          ticks: {
            color: '#6b7280', font: { family: 'JetBrains Mono', size: 9 },
            callback: v => (v / 10000).toFixed(0) + '萬',
          },
        },
      },
    },
  });

  // ── 交易記錄表 ────────────────────────────────────────────
  const tbody = document.getElementById('bt-trade-list');
  if(!r.trades.length){
    tbody.innerHTML='<tr><td colspan="8" style="text-align:center;padding:20px;color:var(--text-tertiary)">無交易記錄（訊號未達最低分數）</td></tr>';
    return;
  }
  tbody.innerHTML = r.trades.map(t=>{
    const c   = t.pnl >= 0 ? 'var(--green)' : 'var(--red)';
    const sgn = t.pnl >= 0 ? '+' : '';
    const rc  = t.reason==='停損'?'var(--red)':t.reason==='目標'?'var(--green)':'var(--yellow)';
    return `<tr>
      <td>${t.entry_date}</td><td>${t.exit_date}</td>
      <td style="text-align:right">${t.entry}</td>
      <td style="text-align:right">${t.exit}</td>
      <td style="text-align:right">${(t.shares||0).toLocaleString()}</td>
      <td style="text-align:right;color:${c}">${sgn}${t.pnl.toLocaleString()}</td>
      <td style="text-align:right;color:${c}">${sgn}${t.pnl_pct}%</td>
      <td style="color:${rc}">${t.reason}</td>
    </tr>`;
  }).join('');
}

// ── Multi-stock Backtest ──────────────────────────────────────
const BT_COLORS = ['#3b82f6','#10b981','#f78166','#f59e0b','#bc8cff','#39d353'];

function renderMultiBacktestResult(r){
  if(window._btChart){ window._btChart.destroy(); window._btChart=null; }

  const stratLabel = {'trend':'趨勢策略','ict':'ICT 策略','fundamental':'基本面策略'}[document.getElementById('bt-strat').value] || document.getElementById('bt-strat').value;

  // ── 比較總表 ──────────────────────────────────────────────
  const rows = r.summary.map((row, i) => {
    if(row.error){
      return `<tr><td style="font-family:var(--mono)">${row.code}</td>
        <td colspan="6" style="color:var(--text-secondary)">${row.error}</td></tr>`;
    }
    const retC = row.total_return >= 0 ? 'var(--green)' : 'var(--red)';
    const sgn  = row.total_return >= 0 ? '+' : '';
    const pf   = row.profit_factor >= 999 ? '∞' : row.profit_factor;
    const dot  = `<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${BT_COLORS[i % BT_COLORS.length]};margin-right:5px"></span>`;
    return `<tr>
      <td style="font-family:var(--mono);font-weight:700">${dot}${row.code}</td>
      <td style="text-align:right;color:${retC};font-family:var(--mono)">${sgn}${row.total_return}%</td>
      <td style="text-align:right;font-family:var(--mono)">${row.total_trades}</td>
      <td style="text-align:right;font-family:var(--mono)">${row.win_rate}%</td>
      <td style="text-align:right;font-family:var(--mono)">${pf}</td>
      <td style="text-align:right;color:var(--red);font-family:var(--mono)">${row.max_drawdown}%</td>
      <td style="text-align:right;font-family:var(--mono)">${(row.final_equity||0).toLocaleString()}</td>
    </tr>`;
  }).join('');

  document.getElementById('bt-stats').innerHTML = `
    <div class="col-12">
      <div class="card">
        <div class="card-header">
          <h3 class="card-title" style="font-family:var(--mono);font-size:11px;letter-spacing:1.5px;text-transform:uppercase">比較總表 · ${stratLabel}</h3>
        </div>
        <div class="card-body p-0">
          <div style="overflow-x:auto">
            <table class="table table-sm table-hover mb-0" style="font-size:11px">
              <thead><tr>
                <th>代號</th>
                <th style="text-align:right">總報酬</th>
                <th style="text-align:right">交易次數</th>
                <th style="text-align:right">勝率</th>
                <th style="text-align:right">盈虧比</th>
                <th style="text-align:right">最大回撤</th>
                <th style="text-align:right">期末資產</th>
              </tr></thead>
              <tbody>${rows}</tbody>
            </table>
          </div>
        </div>
      </div>
    </div>`;

  // ── 資產曲線（% 報酬標準化） ───────────────────────────────
  const okResults = r.results.filter(res => res.ok && res.equity_curve && res.equity_curve.length);

  // 以最長的 equity_curve 作為 X 軸標籤
  const longestCurve = okResults.reduce((a, b) =>
    (a.equity_curve.length >= b.equity_curve.length ? a : b), okResults[0] || {equity_curve:[]});
  const refCurve  = longestCurve.equity_curve || [];
  const refStep   = Math.max(1, Math.floor(refCurve.length / 300));
  const xLabels   = refCurve
    .filter((_, j) => j % refStep === 0 || j === refCurve.length - 1)
    .map(p => p.date);

  const datasets = okResults.map((res, i) => {
    const cap  = res.capital;
    const step = Math.max(1, Math.floor(res.equity_curve.length / 300));
    const pts  = res.equity_curve.filter((_, j) => j % step === 0 || j === res.equity_curve.length - 1);
    return {
      label:           res.code,
      data:            pts.map(p => +((p.equity / cap - 1) * 100).toFixed(2)),
      borderColor:     BT_COLORS[i % BT_COLORS.length],
      backgroundColor: 'transparent',
      borderWidth: 2, pointRadius: 0, tension: 0.2,
    };
  });

  document.getElementById('bt-equity-card').style.display = '';
  const ctx = document.getElementById('bt-equity-chart').getContext('2d');
  window._btChart = new Chart(ctx, {
    type: 'line',
    data: { labels: xLabels, datasets },
    options: {
      responsive: true, maintainAspectRatio: false,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: {
          display: true,
          labels: { color: '#374151', font: { family: 'JetBrains Mono', size: 10 }, boxWidth: 12 },
        },
        tooltip: {
          callbacks: { label: c => `${c.dataset.label}: ${c.raw >= 0 ? '+' : ''}${c.raw}%` },
        },
      },
      scales: {
        x: {
          grid: { color: 'rgba(0,0,0,0.04)' },
          ticks: { color: '#6b7280', font: { family: 'JetBrains Mono', size: 9 }, maxTicksLimit: 8 },
        },
        y: {
          grid: { color: 'rgba(0,0,0,0.04)' },
          ticks: {
            color: '#6b7280', font: { family: 'JetBrains Mono', size: 9 },
            callback: v => (v >= 0 ? '+' : '') + v + '%',
          },
        },
      },
    },
  });

  // ── 每檔交易明細（可展開） ────────────────────────────────
  const tradeDetails = okResults.map((res, i) => {
    const color = BT_COLORS[i % BT_COLORS.length];
    const s = res.stats;
    const pf = s.profit_factor >= 999 ? '∞' : s.profit_factor;
    const trRows = res.trades.map(t => {
      const c   = t.pnl >= 0 ? 'var(--green)' : 'var(--red)';
      const sgn = t.pnl >= 0 ? '+' : '';
      const rc  = t.reason==='停損'?'var(--red)':t.reason==='目標'?'var(--green)':'var(--yellow)';
      return `<tr>
        <td>${t.entry_date}</td><td>${t.exit_date}</td>
        <td style="text-align:right">${t.entry}</td><td style="text-align:right">${t.exit}</td>
        <td style="text-align:right">${(t.shares||0).toLocaleString()}</td>
        <td style="text-align:right;color:${c}">${sgn}${t.pnl.toLocaleString()}</td>
        <td style="text-align:right;color:${c}">${sgn}${t.pnl_pct}%</td>
        <td style="color:${rc}">${t.reason}</td>
      </tr>`;
    }).join('');
    const emptyRow = `<tr><td colspan="8" style="text-align:center;padding:12px;color:var(--text-tertiary)">無交易記錄</td></tr>`;
    return `
      <div class="card mb-2">
        <div class="card-header" style="cursor:pointer" onclick="this.nextElementSibling.style.display=this.nextElementSibling.style.display==='none'?'block':'none'">
          <span style="font-family:var(--mono);font-weight:700;color:${color}">${res.code}</span>
          <span style="font-family:var(--mono);font-size:10px;margin-left:12px;color:var(--text-secondary)">
            ${s.total_trades} 筆 &nbsp;|&nbsp; 勝率 ${s.win_rate}% &nbsp;|&nbsp; 盈虧比 ${pf} &nbsp;|&nbsp; 回撤 ${s.max_drawdown}%
          </span>
          <span style="float:right;font-family:var(--mono);font-size:12px;color:${s.total_return>=0?'var(--green)':'var(--red)'}">
            ${s.total_return>=0?'+':''}${s.total_return}%
          </span>
        </div>
        <div style="display:none">
          <div style="overflow-x:auto;max-height:240px;overflow-y:auto">
            <table class="table table-sm table-hover mb-0" style="font-family:var(--mono);font-size:11px">
              <thead style="position:sticky;top:0;background:var(--card-bg)">
                <tr>
                  <th>進場日</th><th>出場日</th>
                  <th style="text-align:right">進場價</th><th style="text-align:right">出場價</th>
                  <th style="text-align:right">股數</th>
                  <th style="text-align:right">損益</th><th style="text-align:right">損益%</th>
                  <th>原因</th>
                </tr>
              </thead>
              <tbody>${res.trades.length ? trRows : emptyRow}</tbody>
            </table>
          </div>
        </div>
      </div>`;
  }).join('');

  document.getElementById('bt-single-trades').style.display = 'none';
  const section = document.getElementById('bt-detail-section');
  section.innerHTML = tradeDetails;
  section.style.display = 'block';
}

// ── CSV 匯出（交易記錄）──────────────────────────────────────
function exportTradesCsv(){
  if(!_btTrades || !_btTrades.length){ toast('無交易記錄可匯出','err'); return; }
  const header = ['代號','進場日','出場日','進場價','出場價','股數','損益(元)','損益%','原因'];
  const rows   = _btTrades.map(t => [
    t.code || '', t.entry_date, t.exit_date,
    t.entry, t.exit, t.shares, t.pnl, t.pnl_pct, t.reason,
  ]);
  const csv = [header, ...rows].map(r => r.join(',')).join('\n');
  const blob = new Blob(['\uFEFF'+csv], {type:'text/csv;charset=utf-8'});
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `backtest_trades_${Date.now()}.csv`;
  a.click();
}

// ── PNG 匯出（資產曲線）─────────────────────────────────────
function exportEquityPng(){
  if(!window._btChart){ toast('請先執行回測','err'); return; }
  const a = document.createElement('a');
  a.href = window._btChart.toBase64Image('image/png', 1.0);
  a.download = `equity_curve_${Date.now()}.png`;
  a.click();
}

// ── 策略參數掃描 ─────────────────────────────────────────────
let _optEs = null;
function runOptimizer(){
  const code  = document.getElementById('bt-code').value.trim();
  const strat = document.getElementById('bt-strat').value;
  const period= document.getElementById('bt-period').value;
  if(!code){ toast('請先輸入代號','err'); return; }

  const commission_pct = parseFloat(document.getElementById('bt-commission').value) || 0.001425;
  const slippage_pct   = parseFloat(document.getElementById('bt-slippage').value)   || 0.0005;
  const param_grid = { min_score: [3, 4, 5, 6] };

  if(_optEs){ _optEs.close(); _optEs = null; }
  document.getElementById('bt-result').style.display='none';
  document.getElementById('bt-empty').style.display='block';
  document.getElementById('bt-empty').innerHTML=`<div class="loader"><div class="spinner"></div>參數掃描中（${Object.keys(param_grid).join(', ')}）...</div>`;

  const qs = new URLSearchParams({
    code, strategy: strat, period,
    commission_pct, slippage_pct,
    param_grid: JSON.stringify(param_grid),
    key: localStorage.getItem('trading_api_key') || '',
    token: localStorage.getItem('jwt_token') || '',
  });
  _optEs = new EventSource('/api/backtest/optimize?' + qs.toString());

  const results = [];
  _optEs.onmessage = e => {
    const d = JSON.parse(e.data);
    if(d.type === 'start'){
      document.getElementById('bt-empty').innerHTML=`<div class="loader"><div class="spinner"></div>參數掃描：0 / ${d.total} 組合...</div>`;
    } else if(d.type === 'progress'){
      document.getElementById('bt-empty').innerHTML=`<div class="loader"><div class="spinner"></div>參數掃描：${d.done} / ${d.total} 組合...</div>`;
      if(d.item && !d.item.error) results.push(d.item);
    } else if(d.type === 'done'){
      _optEs.close(); _optEs = null;
      renderOptimizerResult(d.results || results);
    }
  };
  _optEs.onerror = () => {
    if(_optEs){ _optEs.close(); _optEs = null; }
    document.getElementById('bt-empty').innerHTML=`<div class="empty" style="color:var(--red)">⚠ 參數掃描失敗</div>`;
  };
}

function renderOptimizerResult(results){
  document.getElementById('bt-empty').style.display='none';
  document.getElementById('bt-result').style.display='block';
  document.getElementById('bt-single-trades').style.display='none';
  if(window._btChart){ window._btChart.destroy(); window._btChart=null; }
  const ok = results.filter(r => !r.error).sort((a,b) => b.total_return - a.total_return);
  if(!ok.length){
    document.getElementById('bt-stats').innerHTML='<div class="col-12"><div class="empty">無有效結果</div></div>';
    return;
  }
  document.getElementById('bt-stats').innerHTML = `
    <div class="col-12">
      <h4 style="font-family:var(--mono);font-size:11px;letter-spacing:1.5px;text-transform:uppercase;margin-bottom:8px">參數掃描結果（依報酬率排序）</h4>
      <div style="overflow-x:auto">
        <table class="table table-sm table-hover" style="font-family:var(--mono);font-size:11px">
          <thead><tr>
            <th>min_score</th>
            <th style="text-align:right">總報酬%</th>
            <th style="text-align:right">勝率%</th>
            <th style="text-align:right">盈虧比</th>
            <th style="text-align:right">最大回撤%</th>
            <th style="text-align:right">交易次數</th>
          </tr></thead>
          <tbody>
            ${ok.map(r=>{
              const c = r.total_return >= 0 ? 'var(--green)' : 'var(--red)';
              return `<tr>
                <td>${r.params.min_score}</td>
                <td style="text-align:right;color:${c}">${r.total_return >= 0?'+':''}${r.total_return}%</td>
                <td style="text-align:right">${r.win_rate}%</td>
                <td style="text-align:right">${r.profit_factor >= 999 ? '∞' : r.profit_factor}</td>
                <td style="text-align:right;color:var(--red)">${r.max_drawdown}%</td>
                <td style="text-align:right">${r.total_trades}</td>
              </tr>`;
            }).join('')}
          </tbody>
        </table>
      </div>
    </div>`;
}
