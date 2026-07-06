/**
 * static/js/intraday.js — 即時監控頁簽前端邏輯
 *
 * 後端 IntradayMonitorDaemon（trading/services/intraday_monitor.py）為完全獨立的
 * 背景常駐執行緒，盤中 09:00–13:30 每 FETCH_INTERVAL 秒自動抓取，不論是否有人
 * 開著這個分頁都會持續運作。本檔案只負責：
 *   1. 讀取/管理使用者個人監控清單
 *   2. 依目前系統 FETCH_INTERVAL 定時輪詢快照與 K 線，更新畫面
 *   3. 讓使用者即時調整 FETCH_INTERVAL 與策略權重（呼叫 API 後立即套用）
 */

let idPollTimer = null;
let idIntervalSeconds = 5;
let idWatchlist = [];          // [{code, name}]
let idSelectedCode = null;
let idChart = null;
let idActualSeries = null;
let idPredictedSeries = null;
let idStrategies = [];         // [{name, label}]

// ── 分頁進入時初始化 ─────────────────────────────────────────────

async function initIntradayTab() {
    await idLoadStatus();
    await idLoadWatchlist();
    await idLoadStrategiesAndWeights();
    idStartPolling();
}

function stopIntradayPolling() {
    if (idPollTimer) {
        clearInterval(idPollTimer);
        idPollTimer = null;
    }
}

function idStartPolling() {
    stopIntradayPolling();
    idRefreshAll();
    idPollTimer = setInterval(idRefreshAll, Math.max(3, idIntervalSeconds) * 1000);
}

async function idRefreshAll() {
    await idLoadStatus();
    await idLoadSnapshot();
    if (idSelectedCode) {
        await idLoadKline(idSelectedCode);
        await idLoadNews(idSelectedCode);
    }
}

// ── 系統狀態／FETCH_INTERVAL ─────────────────────────────────────

async function idLoadStatus() {
    try {
        const r = await api('GET', '/api/intraday/status');
        if (!r.ok) return;
        const marketBadge = document.getElementById('id-market-badge');
        const channelBadge = document.getElementById('id-channel-badge');
        if (marketBadge) {
            marketBadge.textContent = r.market_open ? '🟢 盤中監控中' : '⚪ 非盤中（09:00-13:30 自動啟動）';
        }
        if (channelBadge) {
            channelBadge.textContent = `來源: ${r.channel}`;
        }
        idIntervalSeconds = r.interval || idIntervalSeconds;
        const intervalInput = document.getElementById('id-interval-input');
        if (intervalInput && document.activeElement !== intervalInput) {
            intervalInput.value = idIntervalSeconds;
        }
    } catch (e) {
        console.error('讀取即時監控狀態失敗', e);
    }
}

async function idApplyInterval() {
    const input = document.getElementById('id-interval-input');
    const seconds = parseInt(input.value, 10);
    if (!seconds || seconds < 3) {
        if (typeof Swal !== 'undefined') {
            Swal.fire({ icon: 'warning', title: 'FETCH_INTERVAL 最短需 3 秒', timer: 1800, showConfirmButton: false });
        }
        return;
    }
    try {
        const r = await api('POST', '/api/intraday/interval', { seconds });
        if (r.ok) {
            idIntervalSeconds = r.interval;
            idStartPolling(); // 立即以新頻率重新排程輪詢
            if (typeof Swal !== 'undefined') {
                Swal.fire({ icon: 'success', title: `FETCH_INTERVAL 已套用為 ${r.interval} 秒`, timer: 1500, showConfirmButton: false });
            }
        }
    } catch (e) {
        console.error('套用 FETCH_INTERVAL 失敗', e);
    }
}

// ── 監控清單 CRUD ───────────────────────────────────────────────

async function idLoadWatchlist() {
    try {
        const r = await api('GET', '/api/intraday/watchlist');
        if (!r.ok) return;
        idWatchlist = r.items || [];
        idRenderWatchlistChips();
        if (!idSelectedCode && idWatchlist.length > 0) {
            idSelectCode(idWatchlist[0].code);
        }
    } catch (e) {
        console.error('讀取監控清單失敗', e);
    }
}

function idRenderWatchlistChips() {
    const wrap = document.getElementById('id-wl-chips');
    const countEl = document.getElementById('id-wl-count');
    if (countEl) countEl.textContent = idWatchlist.length;
    if (!wrap) return;

    if (idWatchlist.length === 0) {
        wrap.innerHTML = '<div class="empty" style="width:100%"><div class="empty-icon">📡</div>尚無監控股票，請於上方輸入股號新增</div>';
        return;
    }

    wrap.innerHTML = idWatchlist.map(item => {
        const active = item.code === idSelectedCode;
        return `
      <div class="badge" style="display:flex;align-items:center;gap:6px;padding:6px 10px;cursor:pointer;font-family:var(--mono);font-size:12px;
                  background:${active ? 'var(--tblr-primary, #3b82f6)' : 'var(--bs-tertiary-bg, #21262d)'};
                  color:${active ? '#fff' : 'inherit'};border-radius:6px;"
           onclick="idSelectCode('${item.code}')">
        <span>${item.code} ${item.name || ''}</span>
        <span onclick="event.stopPropagation(); idRemoveCode('${item.code}')" style="opacity:0.7;padding-left:4px;" title="移除監控">✕</span>
      </div>`;
    }).join('');
}

async function idAddCode() {
    const input = document.getElementById('id-add-code');
    const code = (input.value || '').trim();
    if (!code) return;
    try {
        const r = await api('POST', '/api/intraday/watchlist', { code });
        if (r.ok) {
            input.value = '';
            await idLoadWatchlist();
            idSelectCode(code);
        } else if (typeof Swal !== 'undefined') {
            Swal.fire({ icon: 'error', title: r.error || '新增失敗', timer: 2000, showConfirmButton: false });
        }
    } catch (e) {
        console.error('新增監控股票失敗', e);
    }
}

async function idRemoveCode(code) {
    try {
        const r = await api('DELETE', `/api/intraday/watchlist/${encodeURIComponent(code)}`);
        if (r.ok) {
            if (idSelectedCode === code) idSelectedCode = null;
            await idLoadWatchlist();
        }
    } catch (e) {
        console.error('移除監控股票失敗', e);
    }
}

function idSelectCode(code) {
    idSelectedCode = code;
    idRenderWatchlistChips();
    const label = document.getElementById('id-chart-code-label');
    const item = idWatchlist.find(w => w.code === code);
    if (label) label.textContent = item ? `${item.code} ${item.name || ''}` : code;
    idLoadKline(code);
    idLoadNews(code);
}

// ── 即時快照表格（現價、五檔、法人外資） ──────────────────────────

async function idLoadSnapshot() {
    if (idWatchlist.length === 0) return;
    try {
        const r = await api('GET', '/api/intraday/snapshot');
        if (!r.ok) return;
        idRenderSnapshotTable(r.items || {});
    } catch (e) {
        console.error('讀取即時快照失敗', e);
    }
}

function idFmtInst(buyVal, sellVal) {
    if (buyVal === undefined || buyVal === null || sellVal === undefined || sellVal === null) return '--';
    const net = buyVal - sellVal;
    const sign = net > 0 ? '+' : '';
    const color = net > 0 ? '#10b981' : (net < 0 ? '#ef4444' : 'inherit');
    return `<span style="color:${color}">${sign}${net.toLocaleString()}</span>`;
}

function idRenderSnapshotTable(items) {
    const tbody = document.getElementById('id-snapshot-body');
    if (!tbody) return;

    if (idWatchlist.length === 0) {
        tbody.innerHTML = '<tr><td colspan="11" class="text-muted py-3">尚無監控股票</td></tr>';
        return;
    }

    tbody.innerHTML = idWatchlist.map(w => {
        const row = items[w.code] || {};
        const price = row.price != null ? row.price : '--';
        const chg = row.change_pct;
        const chgColor = chg > 0 ? '#10b981' : (chg < 0 ? '#ef4444' : 'inherit');
        const chgText = chg != null ? `${chg > 0 ? '+' : ''}${chg}%` : '--';
        const vol = row.volume != null ? row.volume.toLocaleString() : '--';
        const bid1 = row.bids && row.bids[0] ? `${row.bids[0].price} / ${row.bids[0].volume}` : '--';
        const ask1 = row.asks && row.asks[0] ? `${row.asks[0].price} / ${row.asks[0].volume}` : '--';
        const inst = row.institutional || {};
        const foreignTxt = idFmtInst(inst.foreign_buy, inst.foreign_sell);
        const trustTxt = idFmtInst(inst.trust_buy, inst.trust_sell);
        const dealerTxt = idFmtInst(inst.dealer_buy, inst.dealer_sell);
        const instDate = inst.trade_date || '--';
        const source = row.data_source || '--';

        return `<tr style="cursor:pointer;" onclick="idSelectCode('${w.code}')">
      <td>${w.code} ${w.name || ''}</td>
      <td>${price}</td>
      <td style="color:${chgColor}">${chgText}</td>
      <td>${vol}</td>
      <td>${bid1}</td>
      <td>${ask1}</td>
      <td>${foreignTxt}</td>
      <td>${trustTxt}</td>
      <td>${dealerTxt}</td>
      <td>${instDate}</td>
      <td>${source}</td>
    </tr>`;
    }).join('');
}

// ── 策略權重 ────────────────────────────────────────────────────

async function idLoadStrategiesAndWeights() {
    try {
        const [stratRes, weightRes] = await Promise.all([
            api('GET', '/api/intraday/strategies'),
            api('GET', '/api/intraday/weights'),
        ]);
        idStrategies = (stratRes.ok && stratRes.strategies) || [];
        const weights = (weightRes.ok && weightRes.weights) || {};
        idRenderWeightsPanel(weights);
    } catch (e) {
        console.error('讀取策略/權重失敗', e);
    }
}

function idRenderWeightsPanel(weights) {
    const panel = document.getElementById('id-weights-panel');
    if (!panel) return;
    if (idStrategies.length === 0) {
        panel.innerHTML = '<div class="empty" style="width:100%">尚無可用策略</div>';
        return;
    }
    panel.innerHTML = idStrategies.map(s => {
        const w = weights[s.name] != null ? weights[s.name] : 0;
        return `
      <div style="display:flex;flex-direction:column;gap:4px;min-width:160px;">
        <label>${s.label}（${s.name}）</label>
        <div style="display:flex;align-items:center;gap:8px;">
          <input type="range" min="0" max="100" value="${w}" id="id-weight-${s.name}"
                 oninput="document.getElementById('id-weight-val-${s.name}').textContent=this.value"
                 style="width:120px;">
          <span id="id-weight-val-${s.name}" style="width:28px;text-align:right;">${w}</span>
        </div>
      </div>`;
    }).join('');
}

async function idApplyWeights() {
    const weights = {};
    idStrategies.forEach(s => {
        const el = document.getElementById(`id-weight-${s.name}`);
        if (el) weights[s.name] = parseInt(el.value, 10);
    });
    try {
        const r = await api('POST', '/api/intraday/weights', { weights });
        if (r.ok && typeof Swal !== 'undefined') {
            Swal.fire({ icon: 'success', title: '策略權重已套用', timer: 1500, showConfirmButton: false });
        }
    } catch (e) {
        console.error('套用策略權重失敗', e);
    }
}

// ── K 線圖：實際 vs 預測 ─────────────────────────────────────────

function idBarsToSeries(bars, tradeDate) {
    return (bars || []).map(b => {
        const iso = `${tradeDate}T${b.bar_time}:00`;
        const t = Math.floor(new Date(iso).getTime() / 1000);
        return { time: t, open: b.open, high: b.high, low: b.low, close: b.close };
    }).sort((a, b) => a.time - b.time);
}

async function idLoadKline(code) {
    try {
        const r = await api('GET', `/api/intraday/kline?code=${encodeURIComponent(code)}`);
        if (!r.ok) return;
        idRenderKlineChart(r);
    } catch (e) {
        console.error('讀取即時 K 線失敗', e);
    }
}

function idRenderKlineChart(data) {
    const container = document.getElementById('id-kline-chart');
    if (!container) return;

    const tradeDate = new Date().toISOString().slice(0, 10);
    const actualData = idBarsToSeries(data.actual, tradeDate);
    const predictedData = idBarsToSeries(data.predicted, tradeDate);

    if (actualData.length === 0 && predictedData.length === 0) {
        container.innerHTML = '<div class="empty"><div class="empty-icon">📉</div>盤中尚無 K 棒資料（開盤後開始累積）</div>';
        idChart = null;
        return;
    }

    if (!idChart) {
        container.innerHTML = '';
        const isDark = document.body.getAttribute('data-theme') === 'dark';
        idChart = LightweightCharts.createChart(container, {
            layout: {
                background: { type: 'solid', color: isDark ? '#0d1117' : '#ffffff' },
                textColor: isDark ? '#8b949e' : '#6b7280',
                fontFamily: 'JetBrains Mono',
                fontSize: 11,
            },
            grid: {
                vertLines: { color: isDark ? '#21262d' : '#f3f4f6' },
                horzLines: { color: isDark ? '#21262d' : '#f3f4f6' },
            },
            crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
            rightPriceScale: { borderColor: isDark ? '#30363d' : '#e5e7eb' },
            timeScale: { borderColor: isDark ? '#30363d' : '#e5e7eb', timeVisible: true, secondsVisible: false },
            width: container.clientWidth,
            height: 380,
        });
        idActualSeries = idChart.addCandlestickSeries({
            upColor: '#10b981', downColor: '#ef4444', borderVisible: false,
            wickUpColor: '#10b981', wickDownColor: '#ef4444',
            title: '實際',
        });
        idPredictedSeries = idChart.addCandlestickSeries({
            upColor: 'rgba(245,158,11,0.5)', downColor: 'rgba(245,158,11,0.25)', borderVisible: true,
            borderUpColor: '#f59e0b', borderDownColor: '#f59e0b',
            wickUpColor: '#f59e0b', wickDownColor: '#f59e0b',
            title: '預測',
        });
        const ro = new ResizeObserver(() => idChart.applyOptions({ width: container.clientWidth }));
        ro.observe(container);
    }

    if (actualData.length)    idActualSeries.setData(actualData);
    if (predictedData.length) idPredictedSeries.setData(predictedData);
    idChart.timeScale().fitContent();
}

// ── 相關新聞 ────────────────────────────────────────────────────

async function idLoadNews(code) {
    try {
        const r = await api('GET', `/api/intraday/news?code=${encodeURIComponent(code)}`);
        const wrap = document.getElementById('id-news-list');
        if (!wrap) return;
        if (!r.ok || !r.items || r.items.length === 0) {
            wrap.innerHTML = '<div class="empty"><div class="empty-icon">📰</div>近期尚無明顯相關新聞</div>';
            return;
        }
        wrap.innerHTML = r.items.map(n => `
      <div style="padding:8px 0;border-bottom:1px solid var(--border,#30363d);font-size:12px;">
        <a href="${n.url}" target="_blank" rel="noopener" style="color:inherit;">${n.title}</a>
        <div style="font-size:10px;color:var(--text-tertiary,#8b949e);margin-top:2px;">
          ${n.source || ''} · ${n.collected_at || ''} · 情緒: ${n.sentiment || '--'}
        </div>
      </div>`).join('');
    } catch (e) {
        console.error('讀取相關新聞失敗', e);
    }
}
