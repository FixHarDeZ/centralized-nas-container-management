let allNews = [];
let _sentIds = new Set();
let _newsSortNewest = true;
let _newsStatus = 'all';
let _sentIdsAvailable = true;
let _newsRequest = 0;
let _currentTab = 'news-timeline';
let _digestTimes = null;
let _overviewPromise = null;
let _overviewVersion = 0;
let _drawerOpener;
let allPrices = [];
let _shownPrices = [];
let _priceZoneFilter = '';
let _freeModels = [];
let _lbPrices = [];
const UI = window.NewsFeedUI;
let _watchlist = new Set();
try { _watchlist = new Set(UI.readWatchlist(localStorage.getItem('nf_watchlist'))); } catch (_) {}

function cacheWatchlist() {
  try { localStorage.setItem('nf_watchlist', JSON.stringify([..._watchlist])); } catch (_) {}
}

function updateWatchlistCount() {
  for (const id of ['stat-watchlist', 'activity-watchlist']) {
    const el = document.getElementById(id);
    if (el) el.textContent = id === 'activity-watchlist' ? `ติดตาม ${_watchlist.size.toLocaleString('th-TH')} โมเดลใน Watchlist` : _watchlist.size.toLocaleString('th-TH');
  }
}

async function _syncWatchlistFromServer() {
  try {
    const data = await api('/api/watchlist');
    const serverIds = data.model_ids || [];
    if (serverIds.length > 0) {
      _watchlist = new Set(serverIds);
      cacheWatchlist();
    } else {
      const localIds = [..._watchlist];
      if (localIds.length > 0) {
        const response = await fetch('/api/watchlist', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({model_ids: localIds}),
        });
        if (!response.ok) throw new Error(response.status);
      }
    }
    renderLeaderboard();
    renderPriceWatchlist();
    const hint = document.getElementById('watchlist-sync-status');
    if (hint) { hint.textContent = 'ซิงก์ข้ามอุปกรณ์แล้ว'; hint.dataset.state = 'synced'; }
  } catch (_) {
    const hint = document.getElementById('watchlist-sync-status');
    if (hint) { hint.textContent = 'ใช้รายการในเครื่องนี้ · ซิงก์ไม่ได้'; hint.dataset.state = 'error'; }
  }
  updateWatchlistCount();
}
let _customSources = []; // [{key, name, url}]
let _priceCharts = {}; // idx → Chart instance

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
  return UI.escapeText(s);
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
  if (c) {
    c.classList.toggle('collapsed');
    c.querySelector('.lb-head')?.setAttribute('aria-expanded', String(!c.classList.contains('collapsed')));
  }
}

function jumpToCard(id) {
  const el = document.getElementById(id);
  if (!el) return;
  el.classList.remove('collapsed');
  el.querySelector('.lb-head')?.setAttribute('aria-expanded', 'true');
  el.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function toggleBookmark(modelId) {
  if (_watchlist.has(modelId)) _watchlist.delete(modelId);
  else _watchlist.add(modelId);
  cacheWatchlist();
  updateWatchlistCount();
  fetch(`/api/watchlist/${encodeURIComponent(modelId)}`, {method: 'PATCH'})
    .then(response => { if (!response.ok) throw new Error(response.status); })
    .catch(() => {
      const hint = document.getElementById('watchlist-sync-status');
      if (hint) { hint.textContent = 'บันทึกในเครื่องแล้ว · ซิงก์ไม่ได้'; hint.dataset.state = 'error'; }
    });
  // Update star buttons in price table in-place (not re-rendered by renderLeaderboard)
  document.querySelectorAll('#price-table .star-btn').forEach(btn => {
    if (btn.dataset.model === modelId) {
      const on = _watchlist.has(modelId);
      btn.classList.toggle('on', on);
      btn.textContent = on ? '★' : '☆';
      btn.title = on ? 'นำออกจาก watchlist' : 'เก็บเข้า watchlist';
    }
  });
  renderLeaderboard();
  renderPriceWatchlist();
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
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 15000);
  try {
    const r = await fetch(path, { signal: controller.signal });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    return await r.json();
  } finally {
    clearTimeout(timeout);
  }
}

const PAGE_META = {
  'news-timeline': ['YOUR DAILY SIGNAL', 'ข่าวล่าสุด', 'เรื่องที่น่ารู้ในโลก AI และเทคโนโลยี พร้อมสรุปภาษาไทย'],
  'price-tracker': ['MODEL EXPLORER', 'ราคาโมเดล AI', 'ค้นหา เปรียบเทียบราคา และติดตามโมเดลที่คุณสนใจ'],
  'ai-leaderboard': ['MODEL DISCOVERY', 'สำรวจโมเดล', 'โมเดลยอดนิยม ราคาคุ้มค่า และตัวเลือกที่ใช้งานฟรี'],
  'digest-history': ['YOUR BRIEFINGS', 'ประวัติ Digest', 'ย้อนดูข่าวที่ส่งให้คุณทาง LINE และ Telegram'],
  'source-health': ['FEED ACTIVITY', 'แหล่งข่าว', 'ดูความเคลื่อนไหวของแต่ละแหล่งในช่วง 24 ชั่วโมง'],
  'schedule-config': ['WORKSPACE SETTINGS', 'ตั้งค่าระบบ', 'จัดเวลาส่งข่าว เลือกแหล่งข่าว และตั้งค่าโมเดลสรุป'],
};

const _tabRequests = {};
let _configSaving = false;
let _configSaveDone = null;
let _configReloadPromise = null;
function sectionFeedback(id, message = '', retry = false) {
  const section = document.getElementById(id);
  let el = document.getElementById(`feedback-${id}`);
  if (!el) {
    el = document.createElement('div');
    el.id = `feedback-${id}`;
    el.className = 'section-feedback';
    el.setAttribute('role', 'status');
    section.prepend(el);
  }
  el.hidden = !message;
  el.classList.toggle('error-state', retry);
  el.replaceChildren();
  if (message) {
    const text = document.createElement('span');
    text.textContent = message;
    el.append(text);
    if (retry) {
      const button = document.createElement('button');
      button.className = 'btn btn-sm';
      button.textContent = 'ลองอีกครั้ง';
      button.onclick = () => loadTab(id, true);
      el.append(button);
    }
  }
}

async function loadTab(id, force = false) {
  if (id === 'schedule-config' && _configSaving) {
    // Reload once after the POST settles; never populate the form from pre-save data.
    if (!_configReloadPromise) {
      _configReloadPromise = _configSaveDone.then(() => loadTab(id, true))
        .finally(() => { _configReloadPromise = null; });
    }
    return _configReloadPromise;
  }
  const loaders = {
    'news-timeline': loadNews, 'price-tracker': loadPrices, 'ai-leaderboard': loadLeaderboard,
    'digest-history': loadDigestHistory, 'source-health': loadSourceHealth, 'schedule-config': loadScheduleConfig,
  };
  if (id === 'source-health' && _sourceHealthLoaded && !force) return;
  const request = (_tabRequests[id] || 0) + 1;
  _tabRequests[id] = request;
  const isCurrent = () => _tabRequests[id] === request;
  sectionFeedback(id, 'กำลังโหลดข้อมูล…');
  document.getElementById(id).setAttribute('aria-busy', 'true');
  const saveButton = document.getElementById('save-config-btn');
  if (id === 'schedule-config' && saveButton) saveButton.disabled = true;
  try {
    await loaders[id](isCurrent);
    if (_tabRequests[id] === request) sectionFeedback(id);
    if (id === 'schedule-config' && saveButton && _tabRequests[id] === request) saveButton.disabled = _configSaving;
  } catch (error) {
    if (_tabRequests[id] === request) {
      sectionFeedback(id, 'โหลดข้อมูลไม่สำเร็จ กรุณาลองอีกครั้ง', true);
      if (id === 'news-timeline' && !allNews.length) {
        document.getElementById('news-list').innerHTML = '<div class="empty-state"><strong>ยังโหลดข่าวไม่ได้</strong><p>ใช้ปุ่มลองอีกครั้งด้านบนเพื่อเชื่อมต่อใหม่</p></div>';
      }
    }
    console.error(`load ${id}:`, error);
  } finally {
    if (_tabRequests[id] === request) document.getElementById(id).setAttribute('aria-busy', 'false');
  }
}

function showTab(id) {
  if (!PAGE_META[id]) return;
  _currentTab = id;
  document.querySelectorAll('.section').forEach(section => section.classList.toggle('active', section.id === id));
  document.querySelectorAll('[data-tab]').forEach(button => {
    button.classList.toggle('active', button.dataset.tab === id);
    if (button.dataset.tab === id) button.setAttribute('aria-current', 'page');
    else button.removeAttribute('aria-current');
  });
  const more = document.getElementById('mob-more');
  if (more) more.classList.toggle('active', !['news-timeline', 'price-tracker', 'ai-leaderboard'].includes(id));
  const [eyebrow, title, description] = PAGE_META[id];
  document.getElementById('page-eyebrow').textContent = eyebrow;
  document.getElementById('page-title').textContent = title;
  document.getElementById('page-description').textContent = description;
  document.title = `${title} · News Feed`;
  loadTab(id);
}

function refreshCurrentTab() {
  loadTab(_currentTab, true);
  loadOverview();
}

function openMobileDrawer() {
  _drawerOpener = document.activeElement;
  const overlay = document.getElementById('mobile-drawer-overlay');
  overlay.classList.add('open');
  overlay.setAttribute('aria-hidden', 'false');
  document.getElementById('mob-more')?.setAttribute('aria-expanded', 'true');
  document.body.style.overflow = 'hidden';
  overlay.querySelector('button')?.focus();
}

function closeMobileDrawer() {
  const overlay = document.getElementById('mobile-drawer-overlay');
  if (!overlay.classList.contains('open')) return;
  overlay.classList.remove('open');
  overlay.setAttribute('aria-hidden', 'true');
  document.getElementById('mob-more')?.setAttribute('aria-expanded', 'false');
  document.body.style.overflow = '';
  _drawerOpener?.focus();
}

function formatBangkok(value, options = {}) {
  const date = new Date(value);
  if (!value || !Number.isFinite(date.getTime())) return 'ยังไม่มีข้อมูล';
  return date.toLocaleString('th-TH', { timeZone: 'Asia/Bangkok', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', ...options });
}

function renderNextDigest() {
  const next = _digestTimes === null ? null : UI.nextDigest(_digestTimes);
  document.getElementById('stat-next-digest').textContent = _digestTimes === null ? '—' : next ? next.toLocaleTimeString('th-TH', { timeZone: 'Asia/Bangkok', hour: '2-digit', minute: '2-digit' }) : 'ไม่ได้ตั้ง';
  document.getElementById('stat-next-note').textContent = next ? `${next.toLocaleDateString('th-TH', { timeZone: 'Asia/Bangkok', day: 'numeric', month: 'short' })} · เวลาไทย` : 'เวลาประเทศไทย';
  document.getElementById('activity-next').textContent = _digestTimes === null ? 'โหลดตารางส่งไม่ได้' : next ? `${formatBangkok(next)} น. · เวลาไทย` : 'ยังไม่ได้ตั้งเวลาส่ง';
}

function renderHealth(health) {
  const badge = document.getElementById('health-badge');
  badge.textContent = health.status === 'ok' ? 'เชื่อมต่อแล้ว' : 'ตรวจสอบสถานะ';
  badge.dataset.state = health.status === 'ok' ? 'online' : 'error';
  const last = health.last_fetch ? formatBangkok(health.last_fetch) : 'ยังไม่เคยดึงข่าว';
  document.getElementById('footer-info').textContent = `ดึงข่าวล่าสุด ${last}`;
  document.getElementById('activity-fetch').textContent = last;
}

async function loadHealth() {
  try { renderHealth(await api('/api/health')); }
  catch (_) {
    document.getElementById('health-badge').textContent = 'เชื่อมต่อไม่ได้';
    document.getElementById('health-badge').dataset.state = 'error';
    document.getElementById('activity-fetch').textContent = 'โหลดสถานะไม่ได้';
    document.getElementById('footer-info').textContent = 'โหลดสถานะไม่ได้';
  }
}

function loadOverview() {
  ++_overviewVersion;
  if (_overviewPromise) return _overviewPromise;
  const status = document.getElementById('overview-status');
  status.textContent = 'กำลังอัปเดตภาพรวม…';
  document.getElementById('overview-retry').hidden = true;
  _overviewPromise = (async () => {
    try {
      let version;
      do {
        version = _overviewVersion;
        const results = await Promise.allSettled([
          api('/api/health'), api('/api/news/sources?hours=24'), api('/api/schedule'), api('/api/digest/history'),
        ]);
        // A refresh requested during this batch invalidates it and queues a new batch.
        if (version !== _overviewVersion) continue;
        const [health, sources, schedule, history] = results;
        if (health.status === 'fulfilled') renderHealth(health.value);
        else {
          document.getElementById('health-badge').textContent = 'เชื่อมต่อไม่ได้';
          document.getElementById('health-badge').dataset.state = 'error';
          document.getElementById('activity-fetch').textContent = 'โหลดสถานะไม่ได้';
          document.getElementById('footer-info').textContent = 'โหลดสถานะไม่ได้';
        }
        if (sources.status === 'fulfilled') {
          document.getElementById('stat-articles').textContent = sources.value.reduce((sum, source) => sum + source.count, 0).toLocaleString('th-TH');
          document.getElementById('stat-sources').textContent = sources.value.filter(source => source.count > 0).length.toLocaleString('th-TH');
        } else {
          document.getElementById('stat-articles').textContent = '—';
          document.getElementById('stat-sources').textContent = '—';
        }
        _digestTimes = schedule.status === 'fulfilled' ? schedule.value.digest_times || [] : null;
        renderNextDigest();
        document.getElementById('activity-digest').textContent = history.status === 'fulfilled'
          ? history.value.length ? formatBangkok(history.value[0].sent_at) : 'ยังไม่มีประวัติการส่ง'
          : 'โหลดประวัติไม่ได้';
        updateWatchlistCount();
        const failed = results.filter(result => result.status === 'rejected').length;
        status.textContent = failed ? `ข้อมูลบางส่วนโหลดไม่ได้ (${failed}/4) · ลองอัปเดตอีกครั้ง` : 'ข้อมูล 24 ชั่วโมงล่าสุด · เวลาไทย (GMT+7)';
        document.getElementById('overview-retry').hidden = !failed;
      } while (version !== _overviewVersion);
    } finally {
      _overviewPromise = null;
    }
  })();
  return _overviewPromise;
}

let sourceChart;
let _sourceHealthLoaded = false;

async function loadSourceHealth(isCurrent = () => true) {
    const sources = await api('/api/news/sources?hours=24');
    if (!isCurrent()) return;
    const labels = sources.map(s => sourceName(s.source));
    const data = sources.map(s => s.count);
    if (sourceChart) sourceChart.destroy();
    const canvas = document.getElementById('sourceChart');
    canvas.hidden = typeof Chart === 'undefined' || !sources.length;
    if (typeof Chart !== 'undefined' && sources.length) sourceChart = new Chart(canvas, {
      type: 'bar',
      data: { labels, datasets: [{ label: 'ข่าวใน 24h', data, backgroundColor: '#158579', borderRadius: 5, maxBarThickness: 42 }] },
      options: { responsive: true, plugins: { legend: { display: false } }, scales: { x: { grid: { display: false }, ticks: { color: '#65766f' } }, y: { beginAtZero: true, ticks: { color: '#65766f', precision: 0 }, grid: { color: '#edf0ee' } } } },
    });
    let chartHint = document.getElementById('source-chart-hint');
    if (!chartHint) { chartHint = document.createElement('p'); chartHint.id = 'source-chart-hint'; canvas.after(chartHint); }
    chartHint.hidden = typeof Chart !== 'undefined' && sources.length > 0;
    chartHint.textContent = !sources.length ? 'ยังไม่มีข่าวในช่วง 24 ชั่วโมงล่าสุด' : 'กราฟโหลดไม่ได้ · ดูจำนวนข่าวของแต่ละแหล่งด้านล่าง';
    const statusEl = document.getElementById('source-status-list');
    statusEl.innerHTML = '<h2>ความเคลื่อนไหวใน 24 ชั่วโมง</h2><p class="section-note">จำนวนข่าวที่ดึงมาได้ ไม่ใช่ผลตรวจการเชื่อมต่อ RSS</p>' + (sources.length
      ? sources.map(s =>
          `<div class="source-status-row"><span>${escapeHtml(sourceName(s.source))}</span><strong>${s.count} <small>ข่าว</small></strong></div>`
        ).join('')
      : '<p style="color:#64748b;padding:.5rem 0;font-size:.85rem">No articles fetched yet</p>'
    );
    _sourceHealthLoaded = true;
}

function refreshSourceHealth() {
  _sourceHealthLoaded = false;
  loadTab('source-health', true);
}

async function loadNews(isCurrent = () => true) {
  const request = ++_newsRequest;
  if (!allNews.length) document.getElementById('news-list').innerHTML = '<div class="loading-state" aria-label="กำลังโหลดข่าว">' + '<div class="skeleton"></div>'.repeat(3) + '</div>';
  let sentAvailable = true;
  const [articles, sentData] = await Promise.all([
    api('/api/news?limit=100'),
    api('/api/news/sent-ids').catch(() => { sentAvailable = false; return { sent_ids: [] }; }),
  ]);
  if (request !== _newsRequest || !isCurrent()) return;
  allNews = articles;
  _sentIdsAvailable = sentAvailable;
  _sentIds = new Set(sentData.sent_ids);
  const sel = document.getElementById('news-source-filter');
  const selectedSource = sel.value;
  const sources = [...new Set(allNews.map(a=>a.source))];
  if (selectedSource && !sources.includes(selectedSource)) sources.push(selectedSource);
  sel.innerHTML = '<option value="">ทุกแหล่งข่าว</option>' + sources.map(s=>`<option value="${escapeAttr(s)}">${escapeHtml(sourceName(s))}</option>`).join('');
  sel.value = selectedSource;
  const sentFilter = document.querySelector('[data-news-status="sent"]');
  if (sentFilter) sentFilter.disabled = !_sentIdsAvailable;
  _updateSortBtn();
  filterNews();
}

function sourceName(source) {
  return SOURCE_META[source]?.name || source;
}

function setNewsStatus(status) {
  if (!['all', 'summarized', 'sent'].includes(status)) return;
  _newsStatus = status;
  document.querySelectorAll('[data-news-status]').forEach(button => {
    button.classList.toggle('active', button.dataset.newsStatus === status);
    button.setAttribute('aria-pressed', String(button.dataset.newsStatus === status));
  });
  filterNews();
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
  if (btn) btn.textContent = _newsSortNewest ? '↓ ใหม่ล่าสุด' : '↑ เก่าสุดก่อน';
}

function toggleNewsSort() {
  _newsSortNewest = !_newsSortNewest;
  _updateSortBtn();
  filterNews();
}

function _digestBadge(a) {
  if (!_sentIdsAvailable) return '<span class="digest-badge badge-expired">โหลดสถานะส่งไม่ได้</span>';
  if (_sentIds.has(a.id)) return '<span class="digest-badge badge-sent">ส่งแล้ว</span>';
  if (!a.summary_th) return '';
  // 36h is the outer bound of the adaptive digest window. Beyond that, an article
  // very likely missed its slot and won't be picked up.
  const inWindow = new Date(a.fetched_at) >= new Date(Date.now() - 36 * 60 * 60 * 1000);
  if (inWindow) return '<span class="digest-badge badge-pending">ยังไม่ส่ง</span>';
  return '<span class="digest-badge badge-expired">เกิน 36 ชม.</span>';
}

function renderNews(articles) {
  const sorted = _sortedNews(articles);
  const el = document.getElementById('news-list');
  const openIds = new Set([...el.querySelectorAll('details[open]')].map(article => article.dataset.articleId));
  if (!sorted.length) {
    el.innerHTML = `<div class="empty-state"><span class="empty-icon">⌕</span><strong>${allNews.length ? 'ไม่พบข่าวที่ตรงกับตัวกรอง' : 'ยังไม่มีข่าวในฟีด'}</strong><p>${allNews.length ? 'ลองเปลี่ยนคำค้น แหล่งข่าว หรือสถานะข่าว' : 'ข่าวใหม่จะปรากฏที่นี่หลังระบบดึงข้อมูล หรือกดดึงข่าวทันที'}</p></div>`;
    return;
  }
  el.innerHTML = sorted.map(article => {
    const url = UI.safeArticleUrl(article.url);
    const summary = article.summary_th?.trim() || 'ยังไม่มีสรุปภาษาไทย';
    return `<details class="article-card" data-article-id="${escapeAttr(article.id)}" ${openIds.has(article.id) ? 'open' : ''}>
      <summary class="article-toggle">
        <div class="article-meta"><span class="source-badge">${escapeHtml(sourceName(article.source))}</span><time>${escapeHtml(formatBangkok(article.published))}</time>${_digestBadge(article)}</div>
        <h3 class="article-title">${escapeHtml(article.title)}</h3>
        <p class="article-preview">${escapeHtml(summary)}</p>
        <span class="article-toggle-label">อ่านสรุป <span aria-hidden="true">↗</span></span>
      </summary>
      <div class="article-summary">${escapeHtml(summary)}</div>
      ${url ? `<a class="article-link" href="${escapeAttr(url)}" target="_blank" rel="noopener noreferrer">อ่านจากต้นฉบับ <span aria-hidden="true">↗</span></a>` : '<span class="article-link">ไม่มีลิงก์ต้นฉบับที่ใช้งานได้</span>'}
    </details>`;
  }).join('');
}

function filterNews() {
  const filtered = UI.filterArticles(allNews, {
    query: document.getElementById('news-search').value,
    source: document.getElementById('news-source-filter').value,
    status: _newsStatus,
  }, _sentIds);
  document.getElementById('news-results').textContent = _newsStatus === 'sent' && !_sentIdsAvailable
    ? 'โหลดประวัติส่งไม่ได้ · ลองอัปเดตอีกครั้ง'
    : `${filtered.length} จาก ${allNews.length} ข่าว · ค้นหาใน 100 ข่าวล่าสุด`;
  if (_newsStatus === 'sent' && !_sentIdsAvailable) {
    document.getElementById('news-list').innerHTML = '<div class="empty-state"><strong>ยังตรวจสอบสถานะส่งไม่ได้</strong><p>ลองกดอัปเดตใหม่ หรือเลือกดูข่าวทั้งหมด</p></div>';
    return;
  }
  renderNews(filtered);
}

function togglePriceExpand(idx) {
  const row = document.getElementById(`price-expand-${idx}`);
  if (!row) return;
  row.classList.toggle('open');
  document.getElementById(`price-row-${idx}`)?.setAttribute('aria-expanded', String(row.classList.contains('open')));
  if (row.classList.contains('open') && !_priceCharts[idx]) {
    const model = _shownPrices[idx];
    if (model) _loadPriceChart(idx, model.model_id);
  }
}

async function _loadPriceChart(idx, modelId) {
  const wrap = document.getElementById(`price-hist-wrap-${idx}`);
  const canvas = document.getElementById(`price-hist-${idx}`);
  if (!wrap || !canvas) return;
  try {
    const history = await api(`/api/prices/${encodeURIComponent(modelId)}/history?days=30`);
    if (!history.length) {
      wrap.innerHTML = '<p style="color:#64748b;font-size:.74rem;margin:.2rem 0">ยังไม่มีข้อมูลประวัติราคา — จะเริ่มเก็บหลัง price job รอบถัดไป</p>';
      return;
    }
    const labels = history.map(h => h.date.slice(5)); // MM-DD
    const combined = history.map(h => +((( h.prompt_price||0) + (h.complete_price||0)).toFixed(4)));
    const isFree = combined.every(v => v === 0);
    if (isFree) {
      wrap.innerHTML = '<p style="color:#22c55e;font-size:.74rem;margin:.2rem 0">FREE — ไม่มีประวัติราคา</p>';
      return;
    }
    if (typeof Chart === 'undefined') {
      wrap.innerHTML = '<p class="section-note">กราฟโหลดไม่ได้ กรุณารีเฟรชหน้าเพื่อลองโหลดอีกครั้ง</p>';
      return;
    }
    _priceCharts[idx] = new Chart(canvas, {
      type: 'line',
      data: {
        labels,
        datasets: [{
          label: 'Combined $/1M',
          data: combined,
          borderColor: '#158579',
          backgroundColor: 'rgba(21,133,121,.08)',
          fill: true,
          tension: 0.3,
          pointRadius: combined.length <= 7 ? 3 : 1,
          pointHoverRadius: 4,
        }],
      },
      options: {
        responsive: true,
        plugins: { legend: { display: false }, tooltip: { callbacks: {
          label: ctx => `$${ctx.parsed.y.toFixed(4)}/1M`,
        }}},
        scales: {
          x: { ticks: { color: '#94a3b8', font: { size: 10 }, maxTicksLimit: 10 }, grid: { color: 'rgba(148,163,184,.1)' } },
          y: { ticks: { color: '#94a3b8', font: { size: 10 } }, beginAtZero: true, grid: { color: 'rgba(148,163,184,.1)' } },
        },
      },
    });
  } catch(_) {
    wrap.innerHTML = '<p style="color:#64748b;font-size:.74rem;margin:.2rem 0">ไม่สามารถโหลดประวัติราคา</p>';
  }
}

function renderPriceTable(prices) {
  Object.values(_priceCharts).forEach(c => { try { c.destroy(); } catch(_) {} });
  _priceCharts = {};
  _shownPrices = prices;
  const tbody = document.querySelector('#price-table tbody');
  if (!prices.length) {
    tbody.innerHTML = '<tr><td colspan="8"><div class="empty-state"><strong>ไม่พบโมเดล</strong><p>ลองเปลี่ยนคำค้นหาหรือตัวกรอง</p></div></td></tr>';
    return;
  }
  tbody.innerHTML = prices.map((p, i) => {
    const z = getZone(p.model_id);
    const ctx = p.context_length ? p.context_length.toLocaleString() + ' tokens' : '–';
    const updated = p.updated_at ? new Date(p.updated_at).toLocaleString('th-TH') : '–';
    return `<tr id="price-row-${i}" tabindex="0" aria-expanded="false" aria-controls="price-expand-${i}" onclick="if(!event.target.closest('button,a,input'))togglePriceExpand(${i})" onkeydown="if(event.target===this && (event.key==='Enter' || event.key===' ')){event.preventDefault();togglePriceExpand(${i})}">
    <td style="padding:.4rem .3rem;width:2rem;text-align:center">${_starBtn(p.model_id)}</td>
    <td>
      <span class="price-model-name">${escapeHtml(p.name)}</span> <span class="zone-badge">${z.flag} ${z.label}</span>
      <span class="price-cell-provider">${escapeHtml(p.provider)}</span>
    </td>
    <td><span class="model-id">${escapeHtml(p.model_id)}</span> <button class="copy-btn" data-idx="${i}" title="Copy model ID">📋</button></td>
    <td>${escapeHtml(p.provider)}</td>
    <td class="price-value">$${(p.prompt_price||0).toFixed(3)}</td>
    <td class="price-value">$${(p.complete_price||0).toFixed(3)}</td>
    <td>${p.context_length ? p.context_length.toLocaleString() : '–'}</td>
    <td>${p.updated_at ? formatBangkok(p.updated_at) : '–'}</td>
  </tr>
  <tr class="price-expand-row" id="price-expand-${i}">
    <td colspan="8">
      <div class="price-expand-detail">
        <div><span class="lbl">Model ID</span><code>${escapeHtml(p.model_id)}</code></div>
        <div><span class="lbl">Context</span><span>${ctx}</span></div>
        <div><span class="lbl">Updated</span><span>${updated}</span></div>
      </div>
      <div id="price-hist-wrap-${i}" style="margin-top:.5rem;min-height:1.5rem">
        <canvas id="price-hist-${i}" height="70"></canvas>
      </div>
    </td>
  </tr>`;
  }).join('');
}

async function loadPrices(isCurrent = () => true) {
  const provider = document.getElementById('price-provider-filter').value;
  const sort = document.getElementById('price-sort').value;
  const params = new URLSearchParams({ sort });
  if (provider) params.set('provider', provider);
  const [prices, updatedData] = await Promise.all([
    api('/api/prices?' + params),
    api('/api/prices/updated'),
  ]);
  if (!isCurrent()) return;
  allPrices = prices.filter(p => (p.prompt_price||0) >= 0 && (p.complete_price||0) >= 0);
  const updatedEl = document.getElementById('price-updated');
  if (updatedData.updated_at) {
    updatedEl.textContent = `อัปเดตราคาล่าสุด ${formatBangkok(updatedData.updated_at)} · USD ต่อ 1 ล้าน tokens`;
  } else {
    updatedEl.textContent = '🕐 Not yet updated';
  }
  if (document.getElementById('price-provider-filter').options.length <= 1) {
    const providers = [...new Set(allPrices.map(p=>p.provider))];
    const sel = document.getElementById('price-provider-filter');
    sel.innerHTML = '<option value="">ทุกผู้ให้บริการ</option>' + providers.map(p=>`<option value="${escapeAttr(p)}">${escapeHtml(p)}</option>`).join('');
  }
  filterPrices();
  renderPriceWatchlist();
}

function renderPriceWatchlist() {
  const el = document.getElementById('pt-watchlist-body');
  if (!el) return;
  const countEl = document.getElementById('pt-watchlist-count');
  const watch = allPrices.filter(p => _watchlist.has(p.model_id));
  if (countEl) countEl.textContent = watch.length ? `(${watch.length})` : '';
  el.innerHTML = watch.length
    ? watch.map(p => _rankRow(p, null, _priceHtml(p))).join('')
    : '<p style="color:#64748b;font-size:.85rem">ยังไม่มีโมเดลใน watchlist — กด ☆ ที่แถวโมเดลใดก็ได้เพื่อเก็บ</p>';
}

function filterPrices() {
  const q = document.getElementById('price-search').value.toLowerCase();
  let filtered = allPrices;
  if (q) filtered = filtered.filter(p => p.name.toLowerCase().includes(q) || p.model_id.toLowerCase().includes(q));
  if (_priceZoneFilter) filtered = filtered.filter(p => getZone(p.model_id).zone === _priceZoneFilter);
  renderPriceTable(filtered);
}

async function loadLeaderboard(isCurrent = () => true) {
  const [prices, updatedData] = await Promise.all([
    api('/api/prices?sort=combined_asc'),
    api('/api/prices/updated'),
  ]);
  if (!isCurrent()) return;
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

  // Watchlist (server-synced with a local cache/fallback)
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

async function loadDigestHistory(isCurrent = () => true) {
  const history = await api('/api/digest/history');
  if (!isCurrent()) return;
  const el = document.getElementById('digest-list');
  if (!history.length) { el.innerHTML = '<div class="empty-state"><strong>ยังไม่มีประวัติ Digest</strong><p>ข่าวที่ระบบส่งให้คุณจะปรากฏที่นี่</p></div>'; return; }
  el.innerHTML = history.map(d => `
    <details class="digest-entry">
      <summary><span class="digest-date">${escapeHtml(formatBangkok(d.sent_at))}</span><span class="digest-info">${escapeHtml(Array.isArray(d.channels) ? d.channels.join(' · ') : d.channels)} · ${d.article_ids.length} ข่าว</span><span class="digest-caret" aria-hidden="true">⌄</span></summary>
      <div class="digest-detail">${d.article_ids.map(id=>`<div class="model-id">${escapeHtml(id)}</div>`).join('')}</div>
    </details>`).join('');
}

async function testDigest() {
  if (!confirm('ส่ง Test Digest ไปยัง LINE / Telegram ที่ตั้งไว้ตอนนี้?')) return;
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
      statusEl.textContent = `✓ ส่งสำเร็จ → ${data.sent_to.join(', ')} (${data.article_count} บทความ, window: ${data.window_computed_hours}h, candidates: ${data.candidates_in_window})`;
      statusEl.style.color = 'var(--success)';
    } else {
      statusEl.textContent = `⚠ ไม่มีบทความใหม่ (window: ${data.window_computed_hours}h, candidates: ${data.candidates_in_window}, sent already: ${data.already_sent_ids})`;
      statusEl.style.color = 'var(--warn)';
    }
    loadTab('digest-history', true);
    loadOverview();
    loadNews().catch(() => {});
  } catch(e) {
    statusEl.textContent = `✗ Error: ${e.message}`;
    statusEl.style.color = 'var(--danger)';
  } finally {
    btn.disabled = false;
    btn.textContent = 'ส่ง Test Digest · LINE / Telegram';
  }
}

function _renderDigestTimeInputs(times) {
  const timesEl = document.getElementById('digest-times-inputs');
  timesEl.innerHTML = times.map((t, i) =>
    `<span style="display:inline-flex;align-items:center;gap:.3rem;margin:0 .75rem .4rem 0">
      <label>Digest ${i+1}: <input type="time" value="${t}" data-idx="${i}" class="digest-time-input"></label>
      ${times.length > 1 ? `<button type="button" class="btn btn-sm" onclick="removeDigestTime(${i})" title="ลบเวลานี้" style="padding:.15rem .45rem;line-height:1.2">×</button>` : ''}
    </span>`
  ).join('') +
  `<span style="display:inline-flex;align-items:center;margin:.4rem 0">
    <button type="button" class="btn btn-sm" onclick="addDigestTime()">+ Add Time</button>
  </span>`;
}

function _renderFallbackChain(fallbacks) {
  const el = document.getElementById('fallback-chain-inputs');
  if (!el) return;
  const providerOpts = ['anthropic','openrouter','mimo'].map(p => `<option value="${p}">${p}</option>`).join('');
  el.innerHTML = (fallbacks.length ? fallbacks : []).map((fb, i) =>
    `<span style="display:flex;align-items:center;gap:.4rem;margin-bottom:.4rem">
      <span style="color:#64748b;font-size:.78rem;min-width:.8rem">${i+1}.</span>
      <select class="fallback-provider" data-idx="${i}">${providerOpts.replace(`value="${fb.provider}"`, `value="${fb.provider}" selected`)}</select>
      <input type="text" class="fallback-model" data-idx="${i}" value="${escapeAttr(fb.model)}" placeholder="model id" style="width:200px">
      <button type="button" class="btn btn-sm" onclick="removeFallback(${i})" style="padding:.15rem .45rem;line-height:1.2">×</button>
    </span>`
  ).join('') +
  `<div style="margin-top:.3rem"><button type="button" class="btn btn-sm" onclick="addFallback()">+ Add Fallback</button></div>`;
}

function addFallback() {
  const current = _readFallbackChain();
  current.push({provider: 'openrouter', model: ''});
  _renderFallbackChain(current);
}

function removeFallback(idx) {
  const current = _readFallbackChain();
  current.splice(idx, 1);
  _renderFallbackChain(current);
}

function _readFallbackChain() {
  const providers = [...document.querySelectorAll('.fallback-provider')].map(el => el.value);
  const models = [...document.querySelectorAll('.fallback-model')].map(el => el.value);
  return providers.map((p, i) => ({provider: p, model: models[i] || ''}));
}

function addDigestTime() {
  const times = [...document.querySelectorAll('.digest-time-input')].map(el => el.value || '09:00');
  times.push('09:00');
  _renderDigestTimeInputs(times);
}

function removeDigestTime(idx) {
  const times = [...document.querySelectorAll('.digest-time-input')].map(el => el.value);
  times.splice(idx, 1);
  _renderDigestTimeInputs(times);
}

function _slugify(name) {
  return 'custom_' + name.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '').substring(0, 24);
}

function _renderCustomSources(enabledKeys) {
  const el = document.getElementById('custom-sources-list');
  if (!el) return;
  if (!_customSources.length) {
    el.innerHTML = '<p style="color:#64748b;font-size:.82rem;margin:.2rem 0 .4rem">ยังไม่มี custom source</p>';
    return;
  }
  el.innerHTML = _customSources.map((s, i) =>
    `<div style="display:flex;align-items:center;gap:.5rem;flex-wrap:wrap;margin-bottom:.3rem">
      <input type="checkbox" value="${escapeAttr(s.key)}" class="custom-src-check" ${enabledKeys.includes(s.key) ? 'checked' : ''}>
      <span style="font-weight:600;font-size:.88rem">${escapeHtml(s.name)}</span>
      <span style="color:#64748b;font-size:.75rem;word-break:break-all;flex:1;min-width:0">${escapeHtml(s.url)}</span>
      <button type="button" class="btn btn-sm" onclick="removeCustomSource(${i})" style="padding:.15rem .45rem;line-height:1.2;flex-shrink:0">×</button>
    </div>`
  ).join('');
}

function addCustomSource() {
  const nameEl = document.getElementById('new-source-name');
  const urlEl = document.getElementById('new-source-url');
  const errEl = document.getElementById('add-source-error');
  const name = nameEl.value.trim();
  const url = urlEl.value.trim();
  errEl.textContent = '';
  if (!name) { errEl.textContent = 'ต้องกรอก Name'; return; }
  if (!url.startsWith('http')) { errEl.textContent = 'URL ต้องขึ้นต้นด้วย http'; return; }
  const key = _slugify(name);
  if (_customSources.find(s => s.key === key)) { errEl.textContent = `Key "${key}" ซ้ำ — เปลี่ยนชื่อ`; return; }
  // Read current enabled state before mutating
  const enabledKeys = [
    ...[...document.querySelectorAll('#source-toggles input[type=checkbox]:checked')].map(i => i.value),
    ...[...document.querySelectorAll('.custom-src-check:checked')].map(i => i.value),
    key, // new source auto-enabled
  ];
  _customSources.push({key, name, url});
  _renderCustomSources(enabledKeys);
  nameEl.value = '';
  urlEl.value = '';
}

function removeCustomSource(idx) {
  const enabledKeys = [...document.querySelectorAll('.custom-src-check:checked')].map(i => i.value);
  _customSources.splice(idx, 1);
  _renderCustomSources(enabledKeys);
}

const SOURCE_META = {
  techcrunch_ai:     { name: 'TechCrunch AI',       desc: 'AI startup, funding, product launch — Silicon Valley focus' },
  venturebeat:       { name: 'VentureBeat',          desc: 'AI enterprise & business applications, research breakthroughs' },
  theverge:          { name: 'The Verge',            desc: 'Consumer tech, gadgets, big tech (Apple / Google / Meta)' },
  arstechnica:       { name: 'Ars Technica',         desc: 'เชิงลึก: security, hardware, science — วิเคราะห์มากกว่ารายงาน' },
  gsmarena:          { name: 'GSMArena',             desc: 'Smartphone spec, review, launch ทุกแบรนด์ทั่วโลก' },
  '9to5mac':         { name: '9to5Mac',              desc: 'Apple ecosystem เฉพาะทาง (iPhone / Mac / iOS / watchOS)' },
  android_authority: { name: 'Android Authority',   desc: 'Android ecosystem, Google, Samsung, mid-range phones' },
};

async function loadScheduleConfig(isCurrent = () => true) {
  const cfg = await api('/api/schedule');
  if (!isCurrent()) return;
  _renderDigestTimeInputs(cfg.digest_times || ['07:00', '12:00', '18:00']);
  const allSources = Object.keys(SOURCE_META);
  document.getElementById('source-toggles').innerHTML = allSources.map(s => {
    const m = SOURCE_META[s];
    return `<label style="display:flex;align-items:flex-start;gap:.5rem;margin:.3rem 0;cursor:pointer">
      <input type="checkbox" value="${s}" ${(cfg.enabled_sources||[]).includes(s)?'checked':''} style="margin-top:.15rem;flex-shrink:0">
      <span>
        <span style="font-weight:600">${escapeHtml(m.name)}</span>
        <span style="color:#64748b;font-size:.78rem;display:block;margin-top:.1rem">${escapeHtml(m.desc)}</span>
      </span>
    </label>`;
  }).join('');
  document.getElementById('cfg-provider').value = cfg.summarizer_provider || 'anthropic';
  document.getElementById('cfg-model').value = cfg.summarizer_model || '';
  document.getElementById('cfg-retention').value = cfg.retention_days || 30;
  document.getElementById('cfg-window-buffer').value = cfg.digest_window_buffer_hours ?? 1.0;
  document.getElementById('cfg-size-base').value = cfg.digest_size_base ?? 5;
  document.getElementById('cfg-size-max').value = cfg.digest_size_max ?? 10;
  document.getElementById('cfg-max-per-source').value = cfg.digest_max_per_source ?? 2;
  _renderFallbackChain(cfg.summarizer_fallback || []);
  _customSources = (cfg.custom_sources || []).map(s => ({key: s.key, name: s.name, url: s.url}));
  _renderCustomSources(cfg.enabled_sources || []);
}

async function saveSchedule() {
  const button = document.getElementById('save-config-btn');
  if (_configSaving || button?.disabled) return;
  _configSaving = true;
  let finishSave;
  _configSaveDone = new Promise(resolve => { finishSave = resolve; });
  const configRequest = _tabRequests['schedule-config'];
  if (button) button.disabled = true;
  const times = [...document.querySelectorAll('.digest-time-input')].map(i=>i.value).filter(Boolean);
  const sources = [
    ...[...document.querySelectorAll('#source-toggles input[type=checkbox]:checked')].map(i => i.value),
    ...[...document.querySelectorAll('.custom-src-check:checked')].map(i => i.value),
  ];
  const provider = document.getElementById('cfg-provider').value;
  const model = document.getElementById('cfg-model').value;
  const retention = parseInt(document.getElementById('cfg-retention').value, 10) || 30;
  const fallback = _readFallbackChain().filter(fb => fb.model.trim());
  const buffer = parseFloat(document.getElementById('cfg-window-buffer').value);
  try {
    const r = await fetch('/api/schedule', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ digest_times: times, enabled_sources: sources, summarizer_provider: provider, summarizer_model: model, retention_days: retention, summarizer_fallback: fallback, custom_sources: _customSources, digest_window_buffer_hours: Number.isFinite(buffer) ? buffer : 1.0, digest_size_base: parseInt(document.getElementById('cfg-size-base').value, 10) || 5, digest_size_max: parseInt(document.getElementById('cfg-size-max').value, 10) || 10, digest_max_per_source: parseInt(document.getElementById('cfg-max-per-source').value, 10) || 2 }),
    });
    if (!r.ok) throw new Error(r.status);
    _digestTimes = times;
    renderNextDigest();
    loadOverview();
    document.getElementById('save-status').textContent = '✓ Saved';
    document.getElementById('save-status').style.color = '#22c55e';
  } catch(e) {
    document.getElementById('save-status').textContent = '✗ Save failed';
    document.getElementById('save-status').style.color = '#ef4444';
  } finally {
    _configSaving = false;
    finishSave();
    _configSaveDone = null;
    if (_configReloadPromise) await _configReloadPromise;
    else if (button && _tabRequests['schedule-config'] === configRequest) button.disabled = false;
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
    loadTab('news-timeline', true);
    loadOverview();
    _sourceHealthLoaded = false;
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
    loadOverview();
    allNews = [];
    _sourceHealthLoaded = false;
    loadTab('news-timeline', true);
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
  // Prevent row expand when clicking star in price table
  if (btn.closest('#price-table')) e.stopPropagation();
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
      loadTab('ai-leaderboard', true);
    } catch (err) {
      console.error('Failed to update expiry:', err);
    }
  });
});

// Keep keyboard focus inside the mobile dialog and return it to the opener.
document.addEventListener('keydown', event => {
  const overlay = document.getElementById('mobile-drawer-overlay');
  if (!overlay.classList.contains('open')) return;
  if (event.key === 'Escape') { closeMobileDrawer(); return; }
  if (event.key !== 'Tab') return;
  const buttons = [...overlay.querySelectorAll('button:not([disabled])')];
  const first = buttons[0];
  const last = buttons[buttons.length - 1];
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
});
window.matchMedia('(min-width:761px)').addEventListener('change', event => { if (event.matches) closeMobileDrawer(); });

// Init: the same reading-first view on every device.
showTab('news-timeline');
loadOverview();
_syncWatchlistFromServer();
setInterval(renderNextDigest, 60000);
