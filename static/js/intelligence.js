// ── AI Sentiment (Groq) ───────────────────────────────────────
async function loadAiSentiment(){
  const btn = document.getElementById('ai-sentiment-btn');
  btn.disabled = true; btn.textContent = '分析中...';
  document.getElementById('ai-sentiment-box').innerHTML = `<div class="loader"><div class="spinner"></div>Groq AI 分析中...</div>`;
  try{
    const r = await api('GET', '/api/intelligence/ai_sentiment');
    if(!r.ok){
      const msg = r.groq_available===false
        ? `<div class="empty" style="color:var(--yellow);font-size:11px">⚙️ ${esc(r.error||'Groq 未設定')}<br><span style="color:var(--text-secondary)">請在 <code>.env</code> 加入 <code>GROQ_API_KEY=...</code> 並重啟</span></div>`
        : `<div class="empty" style="color:var(--red)">${esc(r.error||'分析失敗')}</div>`;
      document.getElementById('ai-sentiment-box').innerHTML=msg; return;
    }
    const moodIcon = {bullish:'📈',bearish:'📉',neutral:'➡️'}[r.mood]||'❓';
    const moodTw   = {bullish:'多頭',bearish:'空頭',neutral:'中性'}[r.mood]||r.mood;
    const moodColor= {bullish:'var(--green)',bearish:'var(--red)',neutral:'var(--text-secondary)'}[r.mood]||'';
    const themes   = (r.themes||[]).map(t=>`<span class="badge bg-secondary-lt" style="font-size:10px;margin:1px">${esc(t)}</span>`).join('');
    document.getElementById('ai-sentiment-box').innerHTML=`
      <div style="padding:8px 0">
        <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:6px">
          <span style="font-size:18px">${moodIcon}</span>
          <span style="font-family:var(--mono);font-weight:700;color:${moodColor}">${esc(moodTw)}</span>
          <span style="font-size:11px;color:var(--text-secondary)">信心 ${r.confidence||'?'}/10</span>
        </div>
        <div style="margin-bottom:6px">${themes}</div>
        <div style="font-size:12px;line-height:1.6">${esc(r.summary||'')}</div>
      </div>`;
  }catch(e){
    document.getElementById('ai-sentiment-box').innerHTML=`<div class="empty" style="color:var(--red)">請求失敗</div>`;
  }finally{
    btn.disabled=false; btn.textContent='⚡ 分析';
  }
}

// ── X / Twitter Intel ─────────────────────────────────────────
async function loadXIntel(collect=false){
  const btn = document.getElementById('x-intel-btn');
  btn.disabled = true;
  document.getElementById('x-intel-box').innerHTML=`<div class="loader"><div class="spinner"></div>載入 X 情報...</div>`;
  if(collect){
    btn.textContent = '收集中...';
    try{ await api('POST', '/api/intelligence/collect'); } catch(e){}
  } else {
    btn.textContent = '讀取中...';
  }
  try{
    const r = await api('GET', '/api/intelligence/x');
    const stats = r.stats||{};
    const posts = r.posts||[];
    const total   = stats.total||0;
    const bullish = stats.bullish||0;
    const bearish = stats.bearish||0;
    const neutral = stats.neutral||0;
    const mood    = stats.mood||'neutral';
    const moodTw  = {bullish:'多頭',bearish:'空頭',neutral:'中性'}[mood]||'中性';
    const moodColor = {bullish:'var(--green)',bearish:'var(--red)',neutral:'var(--text-secondary)'}[mood];
    const moodBg    = {bullish:'rgba(var(--tbs-success-rgb),.12)',bearish:'rgba(var(--tbs-danger-rgb),.12)',neutral:'rgba(128,128,128,.08)'}[mood];
    const src = posts.length && posts[0].source==='grok' ? 'Grok API' : 'Google News RSS';
    const fallback = r.fallback || false;

    // 情緒比例條
    const bPct = total ? Math.round(bullish/total*100) : 0;
    const rPct = total ? Math.round(bearish/total*100) : 0;
    const nPct = 100 - bPct - rPct;
    const bar = total ? `
      <div style="display:flex;height:5px;border-radius:3px;overflow:hidden;margin:8px 0 4px;gap:1px">
        <div style="width:${bPct}%;background:var(--green);border-radius:3px 0 0 3px"></div>
        <div style="width:${nPct}%;background:var(--border)"></div>
        <div style="width:${rPct}%;background:var(--red);border-radius:0 3px 3px 0"></div>
      </div>
      <div style="display:flex;justify-content:space-between;font-size:9px;color:var(--text-secondary);margin-bottom:10px">
        <span style="color:var(--green)">📈 多頭 ${bPct}%</span>
        <span>中性 ${nPct}%</span>
        <span style="color:var(--red)">空頭 ${rPct}% 📉</span>
      </div>` : '';

    let html = `<div style="padding:4px 0">
      <div style="display:flex;align-items:center;gap:10px;padding:10px 12px;border-radius:8px;background:${moodBg};margin-bottom:8px">
        <div style="display:flex;flex-direction:column;gap:2px;flex:1;min-width:0">
          <div style="display:flex;align-items:center;gap:6px">
            <span style="font-size:13px;font-weight:700;color:${moodColor}">${moodTw}</span>
            <span style="font-size:9px;color:var(--text-secondary);padding:1px 5px;border:1px solid var(--border);border-radius:10px">${esc(src)}</span>
          </div>
          <div style="font-size:10px;color:var(--text-secondary)">${fallback ? `最近可用資料 · ${total} 則` : `過去 24 小時 · ${total} 則討論`}</div>
        </div>
        <div style="display:flex;gap:10px;font-size:11px;white-space:nowrap">
          <span style="color:var(--green)">▲ ${bullish}</span>
          <span style="color:var(--text-secondary)">— ${neutral}</span>
          <span style="color:var(--red)">▼ ${bearish}</span>
        </div>
      </div>
      ${bar}`;

    if(posts.length){
      const sentColor = {bullish:'var(--green)',bearish:'var(--red)',neutral:'var(--text-secondary)'};
      const sentLabel = {bullish:'多頭',bearish:'空頭',neutral:'中性'};
      html += posts.slice(0,6).map(p=>{
        const sc = sentColor[p.sentiment]||sentColor.neutral;
        const sl = sentLabel[p.sentiment]||'中性';
        const ts = p.collected_at ? `<span style="font-size:9px;color:var(--text-secondary)">${esc(p.collected_at.slice(11,16))}</span>` : '';
        return `<div style="display:flex;align-items:flex-start;gap:8px;padding:7px 0;border-bottom:1px solid var(--border)">
          <span style="font-size:9px;font-weight:600;color:${sc};padding:1px 5px;border:1px solid ${sc};border-radius:10px;white-space:nowrap;margin-top:1px">${sl}</span>
          <span style="font-size:11px;line-height:1.5;flex:1;min-width:0;word-break:break-all">${esc((p.content||'').slice(0,100))}</span>
          ${ts}
        </div>`;
      }).join('');
    } else {
      html += `<div class="empty" style="font-size:11px">尚無資料，點擊更新收集最新資料</div>`;
    }
    html += '</div>';
    document.getElementById('x-intel-box').innerHTML = html;
  }catch(e){
    document.getElementById('x-intel-box').innerHTML=`<div class="empty" style="color:var(--red)">讀取失敗</div>`;
  }finally{
    btn.disabled=false; btn.textContent='↻ 更新';
  }
}

// ── Daily Summary ─────────────────────────────────────────────
function _renderSummary(s, stats){
  if(!s) return `<div class="empty" style="font-size:11px">尚無每日摘要（每天 08:00 自動生成）</div>`;
  const moodTw    = {bullish:'多頭',bearish:'空頭',neutral:'中性'}[s.mood]||'中性';
  const moodColor = {bullish:'var(--green)',bearish:'var(--red)',neutral:'var(--text-secondary)'}[s.mood]||'var(--text-secondary)';
  const moodBg    = {bullish:'rgba(var(--tbs-success-rgb),.10)',bearish:'rgba(var(--tbs-danger-rgb),.10)',neutral:'rgba(128,128,128,.07)'}[s.mood]||'rgba(128,128,128,.07)';
  const st = stats||{};
  return `<div style="padding:4px 0">
    <div style="display:flex;align-items:center;gap:10px;padding:10px 12px;border-radius:8px;background:${moodBg};margin-bottom:10px">
      <div style="flex:1;min-width:0">
        <div style="font-size:13px;font-weight:700;color:${moodColor}">${moodTw}</div>
        <div style="font-size:10px;color:var(--text-secondary);margin-top:2px">${esc(s.date)} · 新聞${st.total||0}則</div>
      </div>
      <div style="display:flex;gap:8px;font-size:10px">
        <span style="color:var(--green)">▲ ${st.bullish||0}</span>
        <span style="color:var(--text-secondary)">— ${st.neutral||0}</span>
        <span style="color:var(--red)">▼ ${st.bearish||0}</span>
      </div>
    </div>
    <div style="font-size:12px;line-height:1.8;white-space:pre-wrap;padding:0 2px">${esc(s.summary)}</div>
    <div style="font-size:10px;color:var(--text-secondary);margin-top:8px;padding-top:6px;border-top:1px solid var(--border)">生成時間：${esc(s.created_at||'')}</div>
  </div>`;
}

async function loadDailySummary(){
  const btn = document.getElementById('daily-summary-btn');
  btn.disabled=true; btn.textContent='載入中...';
  document.getElementById('daily-summary-box').innerHTML=`<div class="loader"><div class="spinner"></div>載入每日摘要...</div>`;
  try{
    const r = await api('GET', '/api/intelligence/summary');
    document.getElementById('daily-summary-box').innerHTML = _renderSummary(r.summary, r.stats);
  }catch(e){
    document.getElementById('daily-summary-box').innerHTML=`<div class="empty" style="color:var(--red)">讀取失敗</div>`;
  }finally{
    btn.disabled=false; btn.textContent='↻ 載入';
  }
}

async function generateSummary(){
  const btn = document.getElementById('regen-summary-btn');
  btn.disabled=true; btn.textContent='生成中...';
  document.getElementById('daily-summary-box').innerHTML=`<div class="loader"><div class="spinner"></div>Groq AI 生成中，請稍候...</div>`;
  try{
    const r = await api('POST', '/api/intelligence/generate_summary');
    if(r.ok){
      const st = await api('GET', '/api/intelligence/summary');
      document.getElementById('daily-summary-box').innerHTML = _renderSummary(r.summary, st.stats);
    } else {
      const errHtml = r.groq_available===false
        ? `<div class="empty" style="color:var(--yellow);font-size:11px">⚙️ ${esc(r.error||'Groq 未設定')}<br><span style="color:var(--text-secondary)">請在 <code>.env</code> 加入 <code>GROQ_API_KEY=...</code> 並重啟</span></div>`
        : `<div class="empty" style="color:var(--red);font-size:11px">⚠️ ${esc(r.error||'生成失敗')}</div>`;
      document.getElementById('daily-summary-box').innerHTML=errHtml;
    }
  }catch(e){
    document.getElementById('daily-summary-box').innerHTML=`<div class="empty" style="color:var(--red)">生成失敗：${esc(String(e))}</div>`;
  }finally{
    btn.disabled=false; btn.textContent='⚡ 重新生成';
  }
}
