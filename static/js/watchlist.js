// ── Watchlist ───────────────────────────────────────────────
let _wlAnalysisCache = null;
let _wlAnalysisTime = 0;
const _WL_CACHE_TTL = 5 * 60_000;  // 5 分鐘

function openWlAddModal() {
  document.getElementById('wl-code').value = '';
  document.getElementById('wl-add-modal').classList.add('open');
  document.getElementById('wl-code').focus();
}

async function saveWlAdd() {
  const code = document.getElementById('wl-code').value.trim();
  if (!code) return;
  try {
    const r = await api('POST', '/api/watchlist', { code });
    if (!r.ok) { toast(r.error || '新增失敗', 'err'); return; }
    closeModal('wl-add-modal');
    toast(`✓ 已新增 ${r.code} ${r.name}`, 'ok');
    _wlAnalysisCache = null;
    loadWatchlist();
  } catch (e) { toast('新增失敗：' + (e.message||'請重啟伺服器'), 'err'); }
}

async function removeWl(code) {
  if(typeof Swal!=='undefined'){
    const res = await Swal.fire({
      title: '移除觀察？',
      text: `確認將 ${code} 從觀察名單移除`,
      icon: 'warning',
      showCancelButton: true,
      confirmButtonColor: '#ef4444',
      cancelButtonColor: '#6b7280',
      confirmButtonText: '確認移除',
      cancelButtonText: '取消',
    });
    if(!res.isConfirmed) return;
  }
  try {
    const r = await api('DELETE', `/api/watchlist/${code}`);
    if (r.ok) { toast(`已移除 ${code}`, 'ok'); _wlAnalysisCache = null; loadWatchlist(); }
  } catch (e) { toast('移除失敗：' + (e.message||''), 'err'); }
}

async function loadWatchlist() {
  const el = document.getElementById('wl-list');
  el.innerHTML = '<div class="loader"><div class="spinner"></div>載入觀察名單...</div>';
  try {
    const r = await api('GET', '/api/watchlist');
    const items = r.items || [];
    document.getElementById('wl-count').textContent = items.length;
    if (!items.length) {
      el.innerHTML = '<div class="empty"><div class="empty-icon">👀</div>尚無觀察股票，點擊「+ 新增」開始追蹤</div>';
      return;
    }
    el.innerHTML = items.map(i => `<div class="wcard" id="wl-${i.code}">
      <div class="wcard-hdr">
        <span><span class="stkcode">${esc(i.code)}</span> <b>${esc(i.name)}</b></span>
        <button class="btn-xs danger" onclick="removeWl('${i.code}')">✕</button>
      </div>
      <div class="wcard-body" style="color:var(--text-secondary);font-size:11px">載入分析中...</div>
    </div>`).join('');
    loadWatchlistAnalysis();
  } catch (e) {
    el.innerHTML = `<div class="empty" style="color:var(--red)">載入失敗：${esc(e.message||'請重啟伺服器')}</div>`;
  }
}

async function loadWatchlistAnalysis() {
  if (_wlAnalysisCache && (Date.now() - _wlAnalysisTime < _WL_CACHE_TTL)) {
    renderWatchlistAnalysis(_wlAnalysisCache);
    return;
  }
  const btn = document.getElementById('wl-refresh-btn');
  if (btn) { btn.disabled = true; btn.textContent = '分析中...'; }
  if(typeof NProgress!=='undefined') NProgress.start();
  try {
    const r = await api('GET', '/api/watchlist/analyze');
    _wlAnalysisCache = r.results || [];
    _wlAnalysisTime = Date.now();
    renderWatchlistAnalysis(_wlAnalysisCache);
  } catch (e) {} finally {
    if(typeof NProgress!=='undefined') NProgress.done();
    if (btn) { btn.disabled = false; btn.textContent = '↻ 分析'; }
  }
}

function _wm(label, value, color) {
  if (value == null) return '';
  return `<div class="wcard-metric"><div class="wcard-metric-label">${label}</div><div class="wcard-metric-value" ${color ? `style="color:${color}"` : ''}>${value}</div></div>`;
}

function renderWatchlistAnalysis(results) {
  results.forEach(r => {
    const el = document.querySelector(`#wl-${r.code} .wcard-body`);
    if (!el) return;
    let html = '';

    // 趨勢策略
    if (r.trend) {
      const t = r.trend;
      const sigs = Object.values(t.signals || {});
      const sc = t.score >= 4 ? 'var(--green)' : t.score >= 2 ? 'var(--yellow)' : 'var(--red)';
      html += `<div class="wcard-section">
        <div class="wcard-section-title">🛡️ 趨勢 <span style="color:${sc}">${t.score}/${t.total}</span></div>
        <div class="wcard-metrics">
          ${_wm('收盤', t.close)}
          ${_wm('ADX', t.adx != null ? t.adx.toFixed(1) : null, t.adx >= 25 ? 'var(--green)' : 'var(--red)')}
          ${_wm('MACD', t.macd_hist != null ? (t.macd_hist >= 0 ? '+' : '') + t.macd_hist.toFixed(3) : null, t.macd_hist >= 0 ? 'var(--green)' : 'var(--red)')}
          ${_wm('EMA20', t.ema20)}
          ${_wm('ATR', t.atr)}
          ${_wm('量/均量', t.volume && t.vol_avg ? (t.volume / t.vol_avg).toFixed(1) + 'x' : null, t.volume > t.vol_avg ? 'var(--green)' : null)}
        </div>
        <div class="wcard-signals">${sigs.map(s =>
          `<span class="sig ${s.pass ? 'pass' : 'fail'}">${s.pass ? '✓' : '✗'} ${esc(s.label)}</span>`
        ).join('')}</div>
      </div>`;
    }

    // 基本面策略
    if (r.fundamental) {
      const f = r.fundamental;
      const sigs = Object.values(f.signals || {});
      const sc = f.score >= 4 ? 'var(--green)' : f.score >= 2 ? 'var(--yellow)' : 'var(--red)';
      html += `<div class="wcard-section">
        <div class="wcard-section-title">📊 基本面 <span style="color:${sc}">${f.score}/${f.total}</span></div>
        <div class="wcard-metrics">
          ${_wm('本益比', f.pe != null ? f.pe.toFixed(1) : null)}
          ${_wm('EPS', f.eps != null ? f.eps.toFixed(2) : null, f.eps > 0 ? 'var(--green)' : 'var(--red)')}
          ${_wm('預估EPS', f.forward_eps != null ? f.forward_eps.toFixed(2) : null)}
          ${_wm('股淨比', f.pb != null ? f.pb.toFixed(2) : null)}
          ${_wm('營收成長', f.revenue_growth != null ? (f.revenue_growth >= 0 ? '+' : '') + f.revenue_growth.toFixed(1) + '%' : null, f.revenue_growth >= 0 ? 'var(--green)' : 'var(--red)')}
        </div>
        <div class="wcard-signals">${sigs.map(s =>
          `<span class="sig ${s.pass ? 'pass' : 'fail'}">${s.pass ? '✓' : '✗'} ${esc(s.label)}</span>`
        ).join('')}</div>
      </div>`;
    }

    // ──【新增】自適應 AI 綜合研判前端渲染區塊 ──
    if (r.adaptive_analysis) {
        const aa = r.adaptive_analysis;
        const badgeColor = aa.composite_score >= 65 ? '#dcfce7' : '#f1f5f9';
        const textColor = aa.composite_score >= 65 ? '#166534' : '#475569';
    
        html += `
        <div class="wcard-section" style="border-left: 5px solid #3b82f6; background: rgba(59, 130, 246, 0.05); padding: 12px; margin-top: 10px; border-radius: 4px;">
            <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
                <span style="font-weight: bold; color: var(--text-primary); display: flex; align-items: center; gap: 4px;">
                    🧠 自適應 AI 綜合研判
                </span>
                <span style="font-size: 11px; font-weight: 600; padding: 2px 8px; border-radius: 10px; background: ${badgeColor}; color: ${textColor};">
                    ${aa.recommendation}
                </span>
            </div>
    
            <div style="display: flex; gap: 15px; align-items: center;">
                <!-- 分數大圓圈 -->
                <div style="width: 50px; height: 50px; border-radius: 50%; background: rgba(59, 130, 246, 0.1); border: 2px solid #3b82f6; display: flex; flex-direction: column; align-items: center; justify-content: center; flex-shrink: 0;">
                    <span style="font-size: 16px; font-weight: bold; color: #3b82f6; line-height: 1;">${aa.composite_score}</span>
                    <span style="font-size: 9px; color: #3b82f6; margin-top: 1px;">分</span>
                </div>
    
                <!-- 權重比例條 -->
                <div style="flex: 1;">
                    <div style="display: flex; justify-content: space-between; font-size: 11px; color: var(--text-secondary); margin-bottom: 4px;">
                        <span>📊 量化指標: ${aa.quant_weight_pct}%</span>
                        <span>🤖 AI 決策: ${aa.ai_weight_pct}%</span>
                    </div>
                    <!-- 進度條 -->
                    <div style="width: 100%; height: 6px; background: rgba(0,0,0,0.1); border-radius: 3px; overflow: hidden; display: flex;">
                        <div style="width: ${aa.quant_weight_pct}%; background: #10b981; height: 100%;"></div>
                        <div style="width: ${aa.ai_weight_pct}%; background: #3b82f6; height: 100%;"></div>
                    </div>
                    <p style="margin: 4px 0 0 0; font-size: 10px; color: var(--text-tertiary);">
                        *指標衝突度 ${aa.conflict_degree}，系統已自適應切換權重。
                    </p>
                </div>
            </div>
        </div>`;
    }

    if (!r.trend && !r.fundamental) {
      html += '<div class="wcard-section" style="color:var(--text-tertiary)">分析資料不足</div>';
    }

    // 新聞
    html += `<div class="wcard-section">`;
    if (r.news && r.news.length) {
      html += '<div class="wcard-news">';
      r.news.forEach(n => {
        html += `<div>· <a href="${esc(n.url)}" target="_blank">${esc(n.title)}</a><span class="wcard-news-date">${esc(n.date)}</span></div>`;
      });
      html += '</div>';
    }
    html += '</div>';

    el.innerHTML = html;
  });
}
