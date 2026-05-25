let allNews = [];
let allPrices = [];

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
  if (id === 'source-health') loadSourceHealth();
  if (id === 'news-timeline') loadNews();
  if (id === 'price-tracker') loadPrices();
  if (id === 'ai-leaderboard') loadLeaderboard();
  if (id === 'digest-history') loadDigestHistory();
  if (id === 'schedule-config') loadScheduleConfig();
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
async function loadSourceHealth() {
  try {
    const news = await api('/api/news?limit=500');
    const counts = {};
    news.forEach(a => { counts[a.source] = (counts[a.source]||0)+1; });
    const labels = Object.keys(counts);
    const data = labels.map(k => counts[k]);
    if (sourceChart) sourceChart.destroy();
    sourceChart = new Chart(document.getElementById('sourceChart'), {
      type: 'bar',
      data: { labels, datasets: [{ label: 'Articles', data, backgroundColor: '#3b82f6' }] },
      options: { plugins: { legend: { display: false } }, scales: { x: { ticks: { color: '#94a3b8' } }, y: { ticks: { color: '#94a3b8' } } } },
    });
    const statusEl = document.getElementById('source-status-list');
    statusEl.innerHTML = '<h2>Source Status</h2>' + labels.map(s =>
      `<div style="padding:.35rem 0"><span class="dot green"></span>${s} <small style="color:#64748b">(${counts[s]} articles)</small></div>`
    ).join('');
  } catch(e) { console.error(e); }
}

async function loadNews() {
  allNews = await api('/api/news?limit=100');
  const sel = document.getElementById('news-source-filter');
  const sources = [...new Set(allNews.map(a=>a.source))];
  sel.innerHTML = '<option value="">All sources</option>' + sources.map(s=>`<option value="${s}">${s}</option>`).join('');
  renderNews(allNews);
}

function renderNews(articles) {
  const el = document.getElementById('news-list');
  if (!articles.length) { el.innerHTML = '<h2>News Timeline</h2><p style="color:#64748b;padding:.5rem 0">No articles</p>'; return; }
  el.innerHTML = '<h2>News Timeline</h2>' + articles.map(a => `
    <div class="article-card" onclick="this.classList.toggle('open')">
      <div class="article-title">${a.title}</div>
      <div class="article-meta"><span class="source-badge">${a.source}</span>${new Date(a.published).toLocaleString('th-TH')}</div>
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

async function loadPrices() {
  const provider = document.getElementById('price-provider-filter').value;
  const sort = document.getElementById('price-sort').value;
  const params = new URLSearchParams({ sort });
  if (provider) params.set('provider', provider);
  const [prices, updatedData] = await Promise.all([
    api('/api/prices?' + params),
    api('/api/prices/updated'),
  ]);
  allPrices = prices;
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
  const tbody = document.querySelector('#price-table tbody');
  tbody.innerHTML = allPrices.map((p, i) => `<tr>
    <td>${p.name}</td><td><span class="model-id">${p.model_id}</span> <button class="copy-btn" data-idx="${i}" title="Copy model ID">📋</button></td><td>${p.provider}</td>
    <td>$${(p.prompt_price||0).toFixed(3)}</td>
    <td>$${(p.complete_price||0).toFixed(3)}</td>
    <td>${p.context_length ? p.context_length.toLocaleString() : '–'}</td>
    <td>${p.updated_at ? new Date(p.updated_at).toLocaleString('th-TH') : '–'}</td>
  </tr>`).join('');
}

async function loadLeaderboard() {
  const [prices, updatedData] = await Promise.all([
    api('/api/prices?sort=combined_asc'),
    api('/api/prices/updated'),
  ]);
  const updatedEl = document.getElementById('leaderboard-updated');
  if (updatedData.updated_at) {
    updatedEl.textContent = `🕐 Last updated: ${new Date(updatedData.updated_at).toLocaleString('th-TH')}`;
  } else {
    updatedEl.textContent = '🕐 Not yet updated';
  }
  const cheapEl = document.getElementById('leaderboard-cheap');
  cheapEl.innerHTML = prices.slice(0,10).map((p,i) => `
    <div class="rank-row">
      <span class="rank-num">${i+1}</span>
      <span class="rank-name">${p.name}<br><small style="color:#64748b">${p.model_id}</small></span>
      <span class="rank-price">$${((p.prompt_price||0)+(p.complete_price||0)).toFixed(3)}/1M</span>
    </div>`).join('');
  const expensive = [...prices].reverse().slice(0,5);
  const expEl = document.getElementById('leaderboard-expensive');
  expEl.innerHTML = expensive.map((p,i) => `
    <div class="rank-row">
      <span class="rank-num">${i+1}</span>
      <span class="rank-name">${p.name}<br><small style="color:#64748b">${p.model_id}</small></span>
      <span class="rank-price" style="color:#ef4444">$${((p.prompt_price||0)+(p.complete_price||0)).toFixed(3)}/1M</span>
    </div>`).join('');
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
}

async function saveSchedule() {
  const times = [...document.querySelectorAll('.digest-time-input')].map(i=>i.value).filter(Boolean);
  const sources = [...document.querySelectorAll('#source-toggles input:checked')].map(i=>i.value);
  const provider = document.getElementById('cfg-provider').value;
  const model = document.getElementById('cfg-model').value;
  try {
    const r = await fetch('/api/schedule', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ digest_times: times, enabled_sources: sources, summarizer_provider: provider, summarizer_model: model }),
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

// Copy button handler (delegated)
const _copyTimers = new WeakMap();
document.addEventListener('click', e => {
  const btn = e.target.closest('.copy-btn');
  if (!btn) return;
  const idx = parseInt(btn.dataset.idx, 10);
  const modelId = allPrices[idx]?.model_id;
  if (!modelId) return;
  navigator.clipboard.writeText(modelId).then(() => {
    clearTimeout(_copyTimers.get(btn));
    btn.textContent = '✓';
    _copyTimers.set(btn, setTimeout(() => { btn.textContent = '📋'; }, 1500));
  }).catch(err => console.error('Copy failed:', err));
});

// Init
loadHealth();
loadSourceHealth();
