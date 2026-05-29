let allNews = [];
let _sentIds = new Set();
let _newsSortNewest = true;
let allPrices = [];
let _shownPrices = [];
let _priceZoneFilter = '';
let _freeModels = [];
let _lbPrices = [];
let _watchlist = new Set(JSON.parse(localStorage.getItem('nf_watchlist') || '[]'));

const PROVIDER_ZONES = {
  'openai':       { zone: 'US', flag: '🇺🇸', label: 'US' },
  'anthropic':    { zone: 'US', flag: '🇺🇸', label: 'US' },
  'google':       { zone: 'US', flag: '🇺🇸', label: 'US' },
  'meta-llama':   { zone: 'US', flag: '🇺🇸', label: 'US' },
  'x-ai':         { zone: 'US', flag: '🇺🇸', label: 'US' },
  'amazon':       { zone: 'US', flag: '🇺🇸', label: 'US' },
  'microsoft':    { zone: 'US', flag: '🇺🇸', label: 'US' },
  'nvidia':       { zone: 'US', flag: '🇺🇸', label: 'US' },
  'perplexity':   { zone: 'US', flag: '🇺🇸', label: 'US' },
  'writer':       { zone: 'US', flag: '🇺🇸', label: 'US' },
  'deepseek':     { zone: 'CN', flag: '🇨🇳', label: 'CN' },
  'qwen':         { zone: 'CN', flag: '🇨🇳', label: 'CN' },
  'alibaba':      { zone: 'CN', flag: '🇨🇳', label: 'CN' },
  'baidu':        { zone: 'CN', flag: '🇨🇳', label: 'CN' },
  'ernie':        { zone: 'CN', flag: '🇨🇳', label: 'CN' },
  '01-ai':        { zone: 'CN', flag: '🇨🇳', label: 'CN' },
  'yi':           { zone: 'CN', flag: '🇨🇳', label: 'CN' },
  'minimax':      { zone: 'CN', flag: '🇨🇳', label: 'CN' },
  'moonshot':     { zone: 'CN', flag: '🇨🇳', label: 'CN' },
  'moonshotai':   { zone: 'CN', flag: '🇨🇳', label: 'CN' },
  'kimi':         { zone: 'CN', flag: '🇨🇳', label: 'CN' },
  'zhipuai':      { zone: 'CN', flag: '🇨🇳', label: 'CN' },
  'z-ai':         { zone: 'CN', flag: '🇨🇳', label: 'CN' },
  'thudm':        { zone: 'CN', flag: '🇨🇳', label: 'CN' },
  'glm':          { zone: 'CN', flag: '🇨🇳', label: 'CN' },
  'baichuan':     { zone: 'CN', flag: '🇨🇳', label: 'CN' },
  'iflytek':      { zone: 'CN', flag: '🇨🇳', label: 'CN' },
  'bytedance':    { zone: 'CN', flag: '🇨🇳', label: 'CN' },
  'tencent':      { zone: 'CN', flag: '🇨🇳', label: 'CN' },
  'xiaomi':       { zone: 'CN', flag: '🇨🇳', label: 'CN' },
  'stepfun':      { zone: 'CN', flag: '🇨🇳', label: 'CN' },
  'internlm':     { zone: 'CN', flag: '🇨🇳', label: 'CN' },
  'opengvlab':    { zone: 'CN', flag: '🇨🇳', label: 'CN' },
  'mistralai':    { zone: 'EU', flag: '🇪🇺', label: 'EU' },
  'aleph-alpha':  { zone: 'EU', flag: '🇪🇺', label: 'EU' },
  'silo':         { zone: 'EU', flag: '🇪🇺', label: 'EU' },
};

const TOP_HIT_MODELS = [
  'gpt-4.1', 'gpt-4o-mini', 'gpt-4o', 'o4-mini', 'o3',
  'claude-opus-4', 'claude-sonnet-4', 'claude-3-7-sonnet', 'claude-3-5-sonnet',
  'gemini-2.5-pro', 'gemini-2.0-flash',
  'deepseek-r1', 'deepseek-v3',
  'llama-4', 'llama-3.3-70b',
  'mistral-large',
  'grok-3',
];

const MODEL_ELO_SCORES = {
  'o3': 1420, 'o4-mini': 1395,
  'gpt-4.1': 1370, 'gpt-4o': 1330, 'gpt-4o-mini': 1270,
  'claude-opus-4': 1415, 'claude-sonnet-4': 1380, 'claude-3-7-sonnet': 1360, 'claude-3-5-sonnet': 1310,
  'gemini-2.5-pro': 1410, 'gemini-2.0-flash': 1295,
  'deepseek-r1': 1360, 'deepseek-v3': 1320,
  'grok-3': 1350,
  'llama-4': 1310, 'llama-3.3-70b': 1250,
  'mistral-large': 1240,
  'qwen-2.5-72b': 1230, 'qwen3': 1330,
  'gemma-3-27b': 1210,
};

function freeExpiryStatus(expires_at) {
  if (!expires_at) return { label: '–', className: '' };
  const todayMidnight = new Date();
  todayMidnight.setHours(0, 0, 0, 0);
  const expiryDate = new Date(expires_at + 'T00:00:00');
  if (isNaN(expiryDate.getTime())) return { label: '⚠️ Invalid', className: 'expiry-urgent' };
  const daysLeft = Math.ceil((expiryDate - todayMidnight) / 86400000);
  if (daysLeft <= 0) return { label: '⚠️ Expired', className: 'expiry-urgent' };
  if (daysLeft <= 3) return { label: `⚠️ ${daysLeft}d left`, className: 'expiry-urgent' };
  if (daysLeft <= 7) return { label: `${daysLeft}d left`, className: 'expiry-warn' };
  const label = expiryDate.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });
  return { label, className: 'expiry-ok' };
}

function escapeHtml(s) {
  const d = document.createElement('div');
  d.textContent = String(s ?? '');
  return d.innerHTML;
}

function escapeAttr(s) {
  return escapeHtml(s).replace(/"/g, '&quot;');
}

function _combined(p) {
  return (p.prompt_price || 0) + (p.complete_price || 0);
}

function _isPopular(modelId) {
  const mid = (modelId || '').toLowerCase();
  return TOP_HIT_MODELS.some(sub => mid.includes(sub));
}

function _starBtn(modelId) {
  const on = _watchlist.has(modelId);
  return `<button class="star-btn ${on ? 'on' : ''}" data-model="${escapeAttr(modelId)}" title="${on ? 'นำออกจาก watchlist' : 'เก็บเข้า watchlist'}">${on ? '★' : '☆'}</button>`;
}

function _rankRow(p, num, priceHtml) {
  const z = getZone(p.model_id);
  return `<div class="rank-row">
    ${num != null ? `<span class="rank-num">${num}</span>` : ''}
    ${_starBtn(p.model_id)}
    <span class="rank-name">${escapeHtml(p.name)} <span class="zone-badge">${z.flag} ${z.label}</span><br><small style="color:#64748b">${escapeHtml(p.model_id)}</small></span>
    <span class="rank-price">${priceHtml}</span>
  </div>`;
}

function _priceHtml(p) {
  const c = _combined(p);
  return c > 0 ? `$${c.toFixed(3)}/1M` : '<span class="free-tag">FREE</span>';
}

function toggleLbCard(id) {
  const c = document.getElementById(id);
  if (c) c.classList.toggle('collapsed');
}

function jumpToCard(id) {
  const el = document.getElementById(id);
  if (!el) return;
  el.classList.remove('collapsed');
  el.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function toggleBookmark(modelId) {
  if (_watchlist.has(modelId)) _watchlist.delete(modelId);
  else _watchlist.add(modelId);
  localStorage.setItem('nf_watchlist', JSON.stringify([..._watchlist]));
  renderLeaderboard();
}

function getZone(modelId) {
  const prefix = (modelId || '').split('/')[0].toLowerCase();
  return PROVIDER_ZONES[prefix] || { zone: 'Others', flag: '🌍', label: 'Others' };
}

function setZoneFilter(zone) {
  _priceZoneFilter = zone;
  document.querySelectorAll('.zone-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.zone === zone);
  });
  filterPrices();
}

async function api(path) {
  const r = await fetch(path);
  if (!r.ok) throw new Error(r.status);
  return r.json();
}

function showTab(id) {
  document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
  document.querySelectorAll('nav button').forEach(b => b.classList.remove('active'));
  document.getElementById(id).classList.add('active');
  const tabs = ['source-health','news-timeline','price-tracker','ai-leaderboard','digest-history','schedule-config'];
  document.querySelectorAll('nav button')[tabs.indexOf(id)].classList.add('active');
  // sync mobile bottom nav
  const mobTabMap = { 'news-timeline': 'mob-news', 'ai-leaderboard': 'mob-board', 'price-tracker': 'mob-prices' };
  document.querySelectorAll('.mob-nav-item').forEach(b => b.classList.remove('active'));
  const mobBtn = document.getElementById(mobTabMap[id]);
  if (mobBtn) mobBtn.classList.add('active');
  if (id === 'source-health') { if (!_sourceHealthLoaded) loadSourceHealth(); }
  if (id === 'news-timeline') loadNews();
  if (id === 'price-tracker') loadPrices();
  if (id === 'ai-leaderboard') loadLeaderboard();
  if (id === 'digest-history') loadDigestHistory();
  if (id === 'schedule-config') loadScheduleConfig();
}

function openMobileDrawer() {
  document.getElementById('mobile-drawer-overlay').classList.add('open');
}

function closeMobileDrawer() {
  document.getElementById('mobile-drawer-overlay').classList.remove('open');
}

async function loadHealth() {
  try {
    const h = await api('/api/health');
    const badge = document.getElementById('health-badge');
    badge.textContent = `${h.article_count} articles`;
    document.getElementById('footer-info').textContent =
      `Last fetch: ${h.last_fetch ? new Date(h.last_fetch).toLocaleString('th-TH') : 'never'}`;
  } catch(e) { document.getElementById('health-badge').textContent = 'error'; }
}

let sourceChart;
let _sourceHealthLoaded = false;

async function loadSourceHealth() {
  try {
    const sources = await api('/api/news/sources?hours=24');
    const labels = sources.map(s => s.source);
    const data = sources.map(s => s.count);
    if (sourceChart) sourceChart.destroy();
    sourceChart = new Chart(document.getElementById('sourceChart'), {
      type: 'bar',
      data: { labels, datasets: [{ label: 'Articles', data, backgroundColor: '#3b82f6' }] },
      options: { plugins: { legend: { display: false } }, scales: { x: { ticks: { color: '#94a3b8' } }, y: { ticks: { color: '#94a3b8' } } } },
    });
    const statusEl = document.getElementById('source-status-list');
    statusEl.innerHTML = '<h2>Source Status</h2>' + (sources.length
      ? sources.map(s =>
          `<div style="padding:.35rem 0"><span class="dot green"></span>${s.source} <small style="color:#64748b">(${s.count} articles in last 24h)</small></div>`
        ).join('')
      : '<p style="color:#64748b;padding:.5rem 0;font-size:.85rem">No articles fetched yet</p>'
    );
    _sourceHealthLoaded = true;
  } catch(e) { console.error('loadSourceHealth error:', e); }
}

function refreshSourceHealth() {
  _sourceHealthLoaded = false;
  loadSourceHealth();
}

async function loadNews() {
  const [articles, sentData] = await Promise.all([
    api('/api/news?limit=100'),
    api('/api/news/sent-ids').catch(() => ({ sent_ids: [] })),
  ]);
  allNews = articles;
  _sentIds = new Set(sentData.sent_ids);
  const sel = document.getElementById('news-source-filter');
  const sources = [...new Set(allNews.map(a=>a.source))];
  sel.innerHTML = '<option value="">All sources</option>' + sources.map(s=>`<option value="${s}">${s}</option>`).join('');
  _newsSortNewest = true;
  _updateSortBtn();
  renderNews(allNews);
}

function _sortedNews(articles) {
  // Sort explicitly by published date so the toggle is correct regardless of API order
  const byNewest = [...articles].sort((a, b) => {
    const ta = new Date(a.published).getTime() || 0;
    const tb = new Date(b.published).getTime() || 0;
    return tb - ta;
  });
  return _newsSortNewest ? byNewest : byNewest.reverse();
}

function _updateSortBtn() {
  const btn = document.getElementById('news-sort-btn');
  if (btn) btn.textContent = _newsSortNewest ? '🕐 Newest first' : '🕐 Oldest first';
}

function toggleNewsSort() {
  _newsSortNewest = !_newsSortNewest;
  _updateSortBtn();
  filterNews();
}

function _digestBadge(a) {
  if (_sentIds.has(a.id)) return '<span class="digest-badge badge-sent">ส่งแล้ว</span>';
  if (a.summary_th) return '<span class="digest-badge badge-pending">รอส่ง</span>';
  return '';
}

function renderNews(articles) {
  const sorted = _sortedNews(articles);
  const el = document.getElementById('news-list');
  if (!sorted.length) { el.innerHTML = '<h2>News Timeline</h2><p style="color:#64748b;padding:.5rem 0">No articles</p>'; return; }
  el.innerHTML = '<h2>News Timeline</h2>' + sorted.map(a => `
    <div class="article-card" onclick="this.classList.toggle('open')">
      <div class="article-title">${a.title}</div>
      <div class="article-meta">${_digestBadge(a)}<span class="source-badge">${a.source}</span>${new Date(a.published).toLocaleString('th-TH')}</div>
      <div class="article-summary">${a.summary_th || '<em>Summarizing…</em>'}</div>
      <div style="margin-top:.25rem"><a href="${a.url}" target="_blank" style="color:#3b82f6;font-size:.75rem" onclick="event.stopPropagation()">อ่านต่อ ↗</a></div>
    </div>`).join('');
}

function filterNews() {
  const q = document.getElementById('news-search').value.toLowerCase();
  const src = document.getElementById('news-source-filter').value;
  renderNews(allNews.filter(a =>
    (!src || a.source === src) &&
    (!q || a.title.toLowerCase().includes(q) || (a.summary_th||'').toLowerCase().includes(q))
  ));
}

function togglePriceExpand(idx) {
  const row = document.getElementById(`price-expand-${idx}`);
  if (row) row.classList.toggle('open');
}

function renderPriceTable(prices) {
  _shownPrices = prices;
  const tbody = document.querySelector('#price-table tbody');
  tbody.innerHTML = prices.map((p, i) => {
    const z = getZone(p.model_id);
    const ctx = p.context_length ? p.context_length.toLocaleString() + ' tokens' : '–';
    const updated = p.updated_at ? new Date(p.updated_at).toLocaleString('th-TH') : '–';
    return `<tr onclick="togglePriceExpand(${i})">
    <td>
      ${escapeHtml(p.name)} <span class="zone-badge">${z.flag} ${z.label}</span>
      <span class="price-cell-provider">${escapeHtml(p.provider)}</span>
    </td>
    <td><span class="model-id">${escapeHtml(p.model_id)}</span> <button class="copy-btn" data-idx="${i}" title="Copy model ID">📋</button></td>
    <td>${escapeHtml(p.provider)}</td>
    <td>$${(p.prompt_price||0).toFixed(3)}</td>
    <td>$${(p.complete_price||0).toFixed(3)}</td>
    <td>${p.context_length ? p.context_length.toLocaleString() : '–'}</td>
    <td>${p.updated_at ? new Date(p.updated_at).toLocaleString('th-TH') : '–'}</td>
  </tr>
  <tr class="price-expand-row" id="price-expand-${i}">
    <td colspan="7">
      <div class="price-expand-detail">
        <div><span class="lbl">Model ID</span><code>${escapeHtml(p.model_id)}</code></div>
        <div><span class="lbl">Context</span><span>${ctx}</span></div>
        <div><span class="lbl">Updated</span><span>${updated}</span></div>
      </div>
    </td>
  </tr>`;
  }).join('');
}

async function loadPrices() {
  const provider = document.getElementById('price-provider-filter').value;
  const sort = document.getElementById('price-sort').value;
  const params = new URLSearchParams({ sort });
  if (provider) params.set('provider', provider);
  const [prices, updatedData] = await Promise.all([
    api('/api/prices?' + params),
    api('/api/prices/updated'),
  ]);
  allPrices = prices.filter(p => (p.prompt_price||0) >= 0 && (p.complete_price||0) >= 0);
  const searchEl = document.getElementById('price-search');
  if (searchEl) searchEl.value = '';
  const updatedEl = document.getElementById('price-updated');
  if (updatedData.updated_at) {
    updatedEl.textContent = `🕐 Last updated: ${new Date(updatedData.updated_at).toLocaleString('th-TH')}`;
  } else {
    updatedEl.textContent = '🕐 Not yet updated';
  }
  if (document.getElementById('price-provider-filter').options.length <= 1) {
    const providers = [...new Set(allPrices.map(p=>p.provider))];
    const sel = document.getElementById('price-provider-filter');
    sel.innerHTML = '<option value="">All providers</option>' + providers.map(p=>`<option value="${p}">${p}</option>`).join('');
  }
  renderPriceTable(allPrices);
}

function filterPrices() {
  const q = document.getElementById('price-search').value.toLowerCase();
  let filtered = allPrices;
  if (q) filtered = filtered.filter(p => p.name.toLowerCase().includes(q) || p.model_id.toLowerCase().includes(q));
  if (_priceZoneFilter) filtered = filtered.filter(p => getZone(p.model_id).zone === _priceZoneFilter);
  renderPriceTable(filtered);
}

async function loadLeaderboard() {
  const [prices, updatedData] = await Promise.all([
    api('/api/prices?sort=combined_asc'),
    api('/api/prices/updated'),
  ]);
  _lbPrices = prices;
  const updatedEl = document.getElementById('leaderboard-updated');
  updatedEl.textContent = updatedData.updated_at
    ? `🕐 Last updated: ${new Date(updatedData.updated_at).toLocaleString('th-TH')}`
    : '🕐 Not yet updated';
  renderLeaderboard();
}

function renderLeaderboard() {
  const empty = '<p style="color:#64748b;font-size:.85rem">No data available</p>';
  // Categorize: free = both prices === 0, paid = combined > 0 (includes mixed-price models)
  const validPrices = _lbPrices.filter(p => (p.prompt_price||0) >= 0 && (p.complete_price||0) >= 0);
  const freeModels = validPrices.filter(p => (p.prompt_price||0) === 0 && (p.complete_price||0) === 0);
  const paidPositive = validPrices.filter(p => _combined(p) > 0);
  const popular = validPrices.filter(p => _isPopular(p.model_id));

  // Watchlist (bookmarked models, persisted in localStorage)
  const watch = validPrices.filter(p => _watchlist.has(p.model_id));
  document.getElementById('lb-watchlist-count').textContent = watch.length ? `(${watch.length})` : '';
  document.getElementById('leaderboard-watchlist').innerHTML = watch.length
    ? watch.map(p => _rankRow(p, null, _priceHtml(p))).join('')
    : '<p style="color:#64748b;font-size:.85rem">ยังไม่มีโมเดลใน watchlist — กด ☆ ที่โมเดลใดก็ได้เพื่อเก็บ</p>';

  // Top Hit: match validPrices against TOP_HIT_MODELS in order (first substring match wins per entry)
  const topHitMatched = [];
  for (const sub of TOP_HIT_MODELS) {
    const found = validPrices.find(p => p.model_id.toLowerCase().includes(sub) && !topHitMatched.includes(p));
    if (found) topHitMatched.push(found);
    if (topHitMatched.length >= 10) break;
  }
  document.getElementById('leaderboard-top-hit').innerHTML = topHitMatched.length
    ? topHitMatched.map((p, i) => _rankRow(p, i+1, _priceHtml(p))).join('') : empty;

  // Top Hit Cheapest: popular paid models, cheapest first (validPrices already combined_asc)
  const hitCheap = popular.filter(p => _combined(p) > 0).slice(0, 10);
  document.getElementById('leaderboard-tophit-cheap').innerHTML = hitCheap.length
    ? hitCheap.map((p, i) => _rankRow(p, i+1, `$${_combined(p).toFixed(3)}/1M`)).join('')
    : '<p style="color:#64748b;font-size:.85rem">No popular paid models available</p>';

  // Top Hit Free: popular models priced at $0
  const hitFree = popular.filter(p => _combined(p) === 0).slice(0, 10);
  document.getElementById('leaderboard-tophit-free').innerHTML = hitFree.length
    ? hitFree.map((p, i) => _rankRow(p, i+1, '<span class="free-tag">FREE</span>')).join('')
    : '<p style="color:#64748b;font-size:.85rem">No popular free models available</p>';

  // Top Intelligence: match validPrices against MODEL_ELO_SCORES, sort desc by ELO, top 10
  const eloMatched = [];
  const sortedEloEntries = Object.entries(MODEL_ELO_SCORES).sort((a, b) => b[0].length - a[0].length);
  for (const p of validPrices) {
    const mid = p.model_id.toLowerCase();
    for (const [sub, elo] of sortedEloEntries) {
      if (mid.includes(sub) && !eloMatched.find(e => e.p === p)) {
        eloMatched.push({ p, elo });
        break;
      }
    }
  }
  eloMatched.sort((a, b) => b.elo - a.elo);
  document.getElementById('leaderboard-intelligence').innerHTML = eloMatched.length
    ? eloMatched.slice(0, 10).map(({ p, elo }, i) =>
        _rankRow(p, i+1, `<span style="color:#a78bfa;font-size:.78rem">ELO ${elo}</span> ${_combined(p) > 0 ? '· $' + _combined(p).toFixed(3) + '/1M' : '· <span class="free-tag">FREE</span>'}`)
      ).join('') : empty;

  // Top 10 Cheapest: paid positive only (already sorted combined_asc)
  const cheapList = paidPositive.slice(0, 10);
  document.getElementById('leaderboard-cheap').innerHTML = cheapList.length
    ? cheapList.map((p, i) => _rankRow(p, i+1, `$${_combined(p).toFixed(3)}/1M`)).join('')
    : '<p style="color:#64748b;font-size:.85rem">No paid models available</p>';

  // Free Models: all free models (no rank numbers, with expiry editing)
  _freeModels = freeModels;
  const freeEl = document.getElementById('leaderboard-free');
  if (!freeModels.length) {
    freeEl.innerHTML = '<p style="color:#64748b;font-size:.85rem">No free models found</p>';
  } else {
    freeEl.innerHTML = freeModels.map((p, i) => {
      const z = getZone(p.model_id);
      const expiryStatus = freeExpiryStatus(p.free_expires_at);
      return `<div class="rank-row" data-idx="${i}">
        ${_starBtn(p.model_id)}
        <span class="rank-name">${escapeHtml(p.name)} <span class="zone-badge">${z.flag} ${z.label}</span>
          <br><small style="color:#64748b">${escapeHtml(p.model_id)}</small>
        </span>
        <span style="display:flex;align-items:center;gap:.4rem">
          ${expiryStatus.className
            ? `<span class="expiry-badge ${expiryStatus.className}">${expiryStatus.label}</span>`
            : `<span style="color:#475569;font-size:.75rem">–</span>`
          }
          <button class="copy-btn set-expiry-btn" data-idx="${i}" title="Set expiry date">📅</button>
        </span>
      </div>`;
    }).join('');
  }

  // Top 5 Most Expensive: paid positive only, sorted reverse
  const expensiveList = [...paidPositive].reverse().slice(0, 5);
  document.getElementById('leaderboard-expensive').innerHTML = expensiveList.length
    ? expensiveList.map((p, i) => _rankRow(p, i+1, `<span style="color:#ef4444">$${_combined(p).toFixed(3)}/1M</span>`)).join('')
    : '<p style="color:#64748b;font-size:.85rem">No paid models available</p>';
}

async function loadDigestHistory() {
  const history = await api('/api/digest/history');
  const el = document.getElementById('digest-list');
  if (!history.length) { el.innerHTML = '<p style="color:#64748b">No digests sent yet</p>'; return; }
  el.innerHTML = history.map(d => `
    <div class="digest-entry" onclick="this.classList.toggle('open')">
      <span>${new Date(d.sent_at).toLocaleString('th-TH')}</span>
      <span style="color:#64748b;font-size:.75rem;margin-left:.5rem">${d.channels} · ${d.article_ids.length} articles</span>
      <div class="digest-detail">${d.article_ids.map(id=>`<div style="font-size:.8rem;color:#94a3b8">• ${id}</div>`).join('')}</div>
    </div>`).join('');
}

async function testDigest() {
  const btn = document.getElementById('test-digest-btn');
  const statusEl = document.getElementById('test-digest-status');
  btn.disabled = true;
  btn.textContent = '⏳ Sending…';
  statusEl.textContent = '';
  statusEl.style.color = '';
  try {
    const r = await fetch('/api/digest/test', { method: 'POST' });
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || r.status);
    if (data.sent_to && data.sent_to.length > 0) {
      statusEl.textContent = `✓ ส่งสำเร็จ → ${data.sent_to.join(', ')} (${data.article_count} บทความ, window: ${data.window_used})`;
      statusEl.style.color = 'var(--success)';
    } else {
      statusEl.textContent = `⚠ ไม่มีบทความใหม่ (6h: ${data.available_6h}, 24h: ${data.available_24h}, sent already: ${data.already_sent_ids})`;
      statusEl.style.color = 'var(--warn)';
    }
    loadDigestHistory();
  } catch(e) {
    statusEl.textContent = `✗ Error: ${e.message}`;
    statusEl.style.color = 'var(--danger)';
  } finally {
    btn.disabled = false;
    btn.textContent = '📤 ส่ง Test Digest';
  }
}

async function loadScheduleConfig() {
  const cfg = await api('/api/schedule');
  const timesEl = document.getElementById('digest-times-inputs');
  timesEl.innerHTML = (cfg.digest_times||[]).map((t,i) =>
    `<label style="margin-right:.75rem">Digest ${i+1}: <input type="time" value="${t}" data-idx="${i}" class="digest-time-input"></label>`
  ).join('');
  const allSources = ['techcrunch_ai','venturebeat','theverge','arstechnica','gsmarena','9to5mac','android_authority'];
  document.getElementById('source-toggles').innerHTML = allSources.map(s =>
    `<label style="display:inline-block;margin:.25rem .5rem">
      <input type="checkbox" value="${s}" ${(cfg.enabled_sources||[]).includes(s)?'checked':''}> ${s}
    </label>`).join('');
  document.getElementById('cfg-provider').value = cfg.summarizer_provider || 'anthropic';
  document.getElementById('cfg-model').value = cfg.summarizer_model || '';
  document.getElementById('cfg-retention').value = cfg.retention_days || 30;
}

async function saveSchedule() {
  const times = [...document.querySelectorAll('.digest-time-input')].map(i=>i.value).filter(Boolean);
  const sources = [...document.querySelectorAll('#source-toggles input:checked')].map(i=>i.value);
  const provider = document.getElementById('cfg-provider').value;
  const model = document.getElementById('cfg-model').value;
  const retention = parseInt(document.getElementById('cfg-retention').value, 10) || 30;
  try {
    const r = await fetch('/api/schedule', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ digest_times: times, enabled_sources: sources, summarizer_provider: provider, summarizer_model: model, retention_days: retention }),
    });
    if (!r.ok) throw new Error(r.status);
    document.getElementById('save-status').textContent = '✓ Saved';
    document.getElementById('save-status').style.color = '#22c55e';
  } catch(e) {
    document.getElementById('save-status').textContent = '✗ Save failed';
    document.getElementById('save-status').style.color = '#ef4444';
  }
  setTimeout(()=>document.getElementById('save-status').textContent='', 3000);
}

async function fetchNow() {
  const btn = document.getElementById('fetch-now-btn');
  const statusEl = document.getElementById('fetch-now-status');
  btn.disabled = true;
  const orig = btn.textContent;
  btn.textContent = '⏳ Fetching…';
  statusEl.textContent = '';
  statusEl.style.color = '';
  try {
    const r = await fetch('/api/fetch/now', { method: 'POST' });
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || r.status);
    statusEl.textContent = `✓ ดึงข่าวใหม่ ${data.new_articles} รายการ`;
    statusEl.style.color = 'var(--success)';
    loadNews();
    loadHealth();
    refreshSourceHealth();
  } catch (e) {
    statusEl.textContent = `✗ Error: ${e.message}`;
    statusEl.style.color = 'var(--danger)';
  } finally {
    btn.disabled = false;
    btn.textContent = orig;
  }
}

async function clearAllNews() {
  if (!confirm('แน่ใจหรือไม่? ข่าวทั้งหมดจะถูกลบและกู้คืนไม่ได้')) return;
  const statusEl = document.getElementById('clear-status');
  statusEl.textContent = '⏳ กำลังลบ…';
  statusEl.style.color = '';
  try {
    const r = await fetch('/api/news', { method: 'DELETE' });
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || r.status);
    statusEl.textContent = `✓ ลบแล้ว ${data.deleted} ข่าว`;
    statusEl.style.color = 'var(--success)';
    loadHealth();
  } catch (e) {
    statusEl.textContent = `✗ Error: ${e.message}`;
    statusEl.style.color = 'var(--danger)';
  }
}

// Copy button handler (delegated)
const _copyTimers = new WeakMap();

function _copyText(text) {
  if (navigator.clipboard && navigator.clipboard.writeText) {
    return navigator.clipboard.writeText(text);
  }
  // HTTP fallback: execCommand (works without HTTPS)
  const el = document.createElement('textarea');
  el.value = text;
  el.style.cssText = 'position:fixed;left:-9999px;top:-9999px;opacity:0';
  document.body.appendChild(el);
  el.focus();
  el.select();
  try { document.execCommand('copy'); } catch (_) {}
  document.body.removeChild(el);
  return Promise.resolve();
}

document.addEventListener('click', e => {
  const btn = e.target.closest('.copy-btn');
  if (!btn) return;
  if (btn.classList.contains('set-expiry-btn')) return;
  e.stopPropagation();  // prevent row expand toggle
  const idx = parseInt(btn.dataset.idx, 10);
  const modelId = _shownPrices[idx]?.model_id;
  if (!modelId) return;
  _copyText(modelId).then(() => {
    clearTimeout(_copyTimers.get(btn));
    btn.textContent = '✓';
    _copyTimers.set(btn, setTimeout(() => { btn.textContent = '📋'; }, 1500));
  }).catch(err => console.error('Copy failed:', err));
});

// Watchlist star handler (delegated)
document.addEventListener('click', e => {
  const btn = e.target.closest('.star-btn');
  if (!btn) return;
  const id = btn.dataset.model;
  if (id) toggleBookmark(id);
});

// Set expiry button handler (delegated)
document.addEventListener('click', e => {
  const btn = e.target.closest('.set-expiry-btn');
  if (!btn) return;
  const idx = parseInt(btn.dataset.idx, 10);
  const model = _freeModels[idx];
  if (!model) return;

  const row = btn.closest('.rank-row');
  const existingInput = row.querySelector('.expiry-edit-input');
  if (existingInput) { existingInput.remove(); return; }

  const input = document.createElement('input');
  input.type = 'date';
  input.className = 'expiry-edit-input';
  input.value = model.free_expires_at || '';
  btn.after(input);

  input.addEventListener('change', async () => {
    const expiryValue = input.value;
    const modelId = model.model_id;
    input.remove();
    try {
      const safeId = modelId.split('/').map(encodeURIComponent).join('/');
      const r = await fetch(`/api/prices/${safeId}/expiry`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ expires_at: expiryValue || null }),
      });
      if (!r.ok) throw new Error(r.status);
      loadLeaderboard();
    } catch (err) {
      console.error('Failed to update expiry:', err);
    }
  });
});

// Init
loadHealth();
loadSourceHealth();
if (window.matchMedia('(max-width:640px)').matches) showTab('news-timeline');
