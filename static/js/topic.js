// ── 主題搜尋 ─────────────────────────────────────────────────
async function searchTopic() {
  const q = document.getElementById('scan-topic-q').value.trim();
  if (!q) return;
  const container = document.getElementById('scan-topic-result');
  container.innerHTML = '<div class="empty">搜尋中...</div>';
  try {
    const d = await api('GET', `/api/coverage/search?q=${encodeURIComponent(q)}&limit=20`);
    if (!d.ok) { container.innerHTML = `<div class="empty" style="color:var(--red)">${d.error}</div>`; return; }
    if (!d.results.length) { container.innerHTML = `<div class="empty">找不到與「${q}」相關的台股</div>`; return; }
    const cards = d.results.map(r => {
      const safeName = encodeURIComponent(r.name||'');
      const tagHtml = r.matched_links.length
        ? `<div class="cov-tags" style="margin-top:4px">${r.matched_links.map(l=>`<span class="cov-tag">${l}</span>`).join('')}</div>`
        : '';
      return `<div class="scard" onclick="showCoverage('${r.code}',decodeURIComponent('${safeName}'))" style="cursor:pointer">
        <div class="scard-hdr">
          <div>
            <div class="sc-code">${r.code} <span style="font-size:11px;font-weight:400;color:var(--text-secondary)">${r.name||''}</span></div>
            <div class="sc-sub">${r.sector||''}</div>
          </div>
        </div>
        ${tagHtml}
      </div>`;
    }).join('');
    container.innerHTML = `<div style="font-size:11px;color:var(--text-tertiary);margin-bottom:6px">主題「${q}」：${d.results.length} 筆相關台股（點擊查看研究摘要）</div><div class="scan-grid">${cards}</div>`;
  } catch(e) {
    container.innerHTML = `<div class="empty" style="color:var(--red)">搜尋失敗，請確認伺服器執行中</div>`;
  }
}

function runTopicSearch(keyword) {
  closeCoverageModal();
  document.getElementById('scan-topic-q').value = keyword;
  searchTopic();
  // 切換到主題搜尋 Tab（若尚未在此 Tab）
  const topicTabBtn = document.querySelector('[data-tab="topic"]');
  if (topicTabBtn) topicTabBtn.click();
}
