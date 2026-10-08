const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const helpersPath = path.join(__dirname, '../app/static/dashboard-utils.js');
const ui = fs.existsSync(helpersPath) ? require(helpersPath) : {};

test('next digest uses Bangkok time and rolls across midnight', () => {
  assert.equal(typeof ui.nextDigest, 'function');
  assert.equal(ui.nextDigest(['18:00', '07:00', '12:00'], new Date('2026-10-08T16:50:00Z')).toISOString(), '2026-10-09T00:00:00.000Z');
  assert.equal(ui.nextDigest(['07:00', '12:00'], new Date('2026-10-08T00:00:00Z')).toISOString(), '2026-10-08T05:00:00.000Z');
  assert.equal(ui.nextDigest(['00:15'], new Date('2026-10-08T17:05:00Z')).toISOString(), '2026-10-08T17:15:00.000Z');
});

test('empty or invalid schedules have no next digest', () => {
  assert.equal(typeof ui.nextDigest, 'function');
  assert.equal(ui.nextDigest([], new Date()), null);
  assert.equal(ui.nextDigest(['25:00', '12:99', 'bad', null], new Date()), null);
});

test('external article text is escaped for HTML and attributes', () => {
  assert.equal(typeof ui.escapeText, 'function');
  assert.equal(ui.escapeText('<img src=x onerror="alert(1)"> & \'ไทย\''), '&lt;img src=x onerror=&quot;alert(1)&quot;&gt; &amp; &#39;ไทย&#39;');
  assert.equal(ui.escapeText(null), '');
});

test('article links accept only absolute HTTP or HTTPS URLs', () => {
  assert.equal(typeof ui.safeArticleUrl, 'function');
  for (const value of ['javascript:alert(1)', 'data:text/html,hi', '//example.com', '/relative', 'not a URL', 'https://exa\nmple.com']) {
    assert.equal(ui.safeArticleUrl(value), null, value);
  }
  assert.equal(ui.safeArticleUrl('https://example.com/news?q=ไทย'), 'https://example.com/news?q=%E0%B9%84%E0%B8%97%E0%B8%A2');
  assert.equal(ui.safeArticleUrl('http://example.com/'), 'http://example.com/');
});

test('query, source and digest status compose without mutating articles', () => {
  assert.equal(typeof ui.filterArticles, 'function');
  const articles = [
    { id: 'a', source: 'tech', title: 'AI Tool', summary_th: 'สรุปข่าวไทย' },
    { id: 'b', source: 'tech', title: 'Device', summary_th: null },
    { id: 'c', source: 'other', title: 'AI Launch', summary_th: 'พร้อมใช้' },
  ];
  const sent = new Set(['a']);
  assert.deepEqual(ui.filterArticles(articles, { query: 'ไทย', source: 'tech', status: 'sent' }, sent).map(a => a.id), ['a']);
  assert.deepEqual(ui.filterArticles(articles, { query: ' AI ', status: 'summarized' }, sent).map(a => a.id), ['a', 'c']);
  assert.equal(ui.filterArticles(articles, { status: 'all' }, sent).length, 3);
  assert.equal(articles.length, 3);
});

test('invalid cached watchlist data never prevents the dashboard loading', () => {
  assert.equal(typeof ui.readWatchlist, 'function');
  for (const value of [null, 'broken', '{}', 'null', '42']) assert.deepEqual(ui.readWatchlist(value), []);
  assert.deepEqual(ui.readWatchlist('["openai/model", 7, null, "", "openai/model"]'), ['openai/model']);
});

// Minimal DOM seam for data/rendering behavior, not a browser or layout test.
function dashboard(fetchImpl) {
  const nodes = new Map();
  function element(id = '') {
    const classes = new Set();
    const node = {
      value: '', textContent: '', dataset: {}, style: {}, children: [], hidden: false, disabled: false,
      classList: { add: value => classes.add(value), remove: value => classes.delete(value), contains: value => classes.has(value), toggle(value, force) { const enabled = force ?? !classes.has(value); enabled ? classes.add(value) : classes.delete(value); return enabled; } },
      setAttribute(key, value) { this[key] = value; }, removeAttribute(key) { delete this[key]; },
      append(...children) { this.children.push(...children); }, prepend(child) { this.children.unshift(child); },
      replaceChildren(...children) { this.children = children; }, after() {}, focus() {},
      querySelectorAll() { return []; }, querySelector() { return null; },
    };
    let html = '';
    Object.defineProperty(node, 'innerHTML', { get: () => html, set(value) {
      html = value;
      // Replacing a select's options resets its selection in a real DOM.
      if (id === 'news-source-filter') node.value = html.match(/<option value="([^"]*)"/)?.[1] || '';
    } });
    Object.defineProperty(node, 'id', { get: () => id, set(value) { id = value; nodes.set(id, node); } });
    Object.defineProperty(node, 'options', { get: () => [...node.innerHTML.matchAll(/<option/g)] });
    if (id) nodes.set(id, node);
    return node;
  }
  const markup = fs.readFileSync(path.join(__dirname, '../app/static/index.html'), 'utf8');
  for (const match of markup.matchAll(/\bid="([^"]+)"/g)) element(match[1]);
  const sentButton = element();
  sentButton.dataset.newsStatus = 'sent';
  const selectors = { '.digest-time-input': [{ value: '07:00' }] };
  const context = vm.createContext({
    window: { NewsFeedUI: ui, matchMedia: () => ({ addEventListener() {} }) },
    document: {
      getElementById: id => nodes.get(id) || null, createElement: () => element(),
      querySelectorAll: selector => selectors[selector] || [],
      querySelector: selector => selector === '[data-news-status="sent"]' ? sentButton : null,
      addEventListener() {}, body: { style: {} },
    },
    localStorage: { getItem: () => null, setItem() {} },
    fetch: fetchImpl, console: { error() {} }, URL, URLSearchParams, AbortController,
    setTimeout: () => 0, clearTimeout() {}, setInterval() {},
  });
  const source = fs.readFileSync(path.join(__dirname, '../app/static/app.js'), 'utf8');
  const bootstrap = source.indexOf('// Init: the same reading-first view on every device.');
  assert.ok(bootstrap > 0, 'isolate functions from automatic startup requests');
  vm.runInContext(source.slice(0, bootstrap), context);
  return { context, nodes, sentButton, evaluate: code => vm.runInContext(code, context) };
}

const response = data => ({ ok: true, json: async () => data });
const deferred = () => {
  let resolve, reject;
  const promise = new Promise((done, fail) => { resolve = done; reject = fail; });
  return { promise, resolve, reject };
};
const flushRequests = () => new Promise(resolve => setImmediate(resolve));

test('news refresh retains source, query and sort and renders escaped content', async () => {
  const articles = [{ id: 'a', source: 'techcrunch_ai', title: '<img src=x onerror="alert(1)"> AI', summary_th: 'ไทย <script>x()</script>', url: 'javascript:alert(1)', published: '2026-10-08T00:00:00Z' }];
  const app = dashboard(async route => response(route.includes('sent-ids') ? { sent_ids: [] } : articles));
  app.nodes.get('news-search').value = 'ไทย';
  app.nodes.get('news-source-filter').value = 'techcrunch_ai';
  app.evaluate('_newsSortNewest = false');
  await app.context.loadNews();
  assert.equal(app.nodes.get('news-search').value, 'ไทย');
  assert.equal(app.nodes.get('news-source-filter').value, 'techcrunch_ai');
  assert.equal(app.evaluate('_newsSortNewest'), false);
  const rendered = app.nodes.get('news-list').innerHTML;
  assert.ok(rendered.includes('&lt;img'));
  assert.ok(rendered.includes('&lt;script&gt;'));
  assert.ok(!rendered.includes('href="javascript:'));
  assert.ok(rendered.includes('<details'));
});

test('news refresh retains a selected source absent from the latest articles', async () => {
  const app = dashboard(async route => response(route.includes('sent-ids') ? { sent_ids: [] } : [{ id: 'a', source: 'theverge', title: 'Other news' }]));
  app.nodes.get('news-source-filter').value = 'techcrunch_ai';
  await app.context.loadNews();
  assert.equal(app.nodes.get('news-source-filter').value, 'techcrunch_ai');
  assert.ok(app.nodes.get('news-source-filter').innerHTML.includes('value="techcrunch_ai"'));
  assert.ok(app.nodes.get('news-results').textContent.startsWith('0 จาก 1'));
  assert.ok(app.nodes.get('news-list').innerHTML.includes('ไม่พบข่าวที่ตรงกับตัวกรอง'));
});

test('sent status failure is shown as unknown rather than pending', async () => {
  const app = dashboard(async route => {
    if (route.includes('sent-ids')) throw new Error('offline');
    return response([{ id: 'a', source: 'theverge', title: 'News', summary_th: 'สรุป', published: '2026-10-08T00:00:00Z', fetched_at: new Date().toISOString() }]);
  });
  await app.context.loadNews();
  assert.equal(app.sentButton.disabled, true);
  assert.ok(app.nodes.get('news-list').innerHTML.includes('โหลดสถานะส่งไม่ได้'));
  assert.ok(!app.nodes.get('news-list').innerHTML.includes('badge-pending'));
});

test('partial overview failure does not masquerade as zero articles', async () => {
  const app = dashboard(async route => {
    if (route.includes('/news/sources')) throw new Error('offline');
    if (route === '/api/health') return response({ status: 'ok', last_fetch: null });
    if (route === '/api/schedule') return response({ digest_times: [] });
    return response([]);
  });
  await app.context.loadOverview();
  assert.equal(app.nodes.get('stat-articles').textContent, '—');
  assert.equal(app.nodes.get('stat-sources').textContent, '—');
  assert.equal(app.nodes.get('overview-retry').hidden, false);
  assert.ok(app.nodes.get('overview-status').textContent.includes('(1/4)'));
});

test('failed settings loading keeps saving disabled until a successful retry', async () => {
  const app = dashboard(async () => { throw new Error('offline'); });
  app.context.loadScheduleConfig = async () => { throw new Error('offline'); };
  await app.context.loadTab('schedule-config', true);
  assert.equal(app.nodes.get('save-config-btn').disabled, true);
  assert.equal(app.nodes.get('feedback-schedule-config').hidden, false);
  app.context.loadScheduleConfig = async () => {};
  await app.context.loadTab('schedule-config', true);
  assert.equal(app.nodes.get('save-config-btn').disabled, false);
});

test('older config responses cannot overwrite edits after the latest load enables saving', async () => {
  const pending = [deferred(), deferred()];
  let requests = 0;
  const app = dashboard(() => pending[requests++].promise);
  const older = app.context.loadTab('schedule-config', true);
  const latest = app.context.loadTab('schedule-config', true);
  pending[1].resolve(response({ summarizer_model: 'latest-model' }));
  await latest;
  assert.equal(app.nodes.get('save-config-btn').disabled, false);
  app.nodes.get('cfg-model').value = 'user-edit';
  pending[0].resolve(response({ summarizer_model: 'old-model' }));
  await older;
  assert.equal(app.nodes.get('cfg-model').value, 'user-edit');
  assert.equal(app.nodes.get('save-config-btn').disabled, false);
});

test('older config success cannot populate settings after the latest load fails', async () => {
  const pending = [deferred(), deferred()];
  let requests = 0;
  const app = dashboard(() => pending[requests++].promise);
  app.nodes.get('cfg-model').value = 'retained-model';
  const older = app.context.loadTab('schedule-config', true);
  const latest = app.context.loadTab('schedule-config', true);
  pending[1].reject(new Error('offline'));
  await latest;
  pending[0].resolve(response({ summarizer_model: 'old-model' }));
  await older;
  assert.equal(app.nodes.get('save-config-btn').disabled, true);
  assert.equal(app.nodes.get('cfg-model').value, 'retained-model');
  assert.equal(app.nodes.get('feedback-schedule-config').hidden, false);
});

test('save completion keeps saving disabled when a newer config refresh fails', async () => {
  const saving = deferred();
  const app = dashboard(async (route, options) => {
    if (options?.method === 'POST') return saving.promise;
    throw new Error('offline');
  });
  app.context.loadOverview = () => {};
  const pendingSave = app.context.saveSchedule();
  const refresh = app.context.loadTab('schedule-config', true);
  await flushRequests();
  assert.equal(app.nodes.get('save-config-btn').disabled, true);
  saving.resolve(response({}));
  await Promise.all([pendingSave, refresh]);
  assert.equal(app.nodes.get('save-config-btn').disabled, true);
});

test('config refresh during a pending save waits and coalesces before reloading settings', async () => {
  const saving = deferred(), reload = deferred();
  let saved = false, configReads = 0;
  const app = dashboard(async (route, options) => {
    if (options?.method === 'POST') { const result = await saving.promise; saved = true; return result; }
    configReads++;
    return saved ? reload.promise : response({ summarizer_model: 'previous-model' });
  });
  app.context.loadOverview = () => {};
  app.nodes.get('cfg-model').value = 'new-model';
  const pendingSave = app.context.saveSchedule();
  const refresh = app.context.loadTab('schedule-config', true);
  const extraRefresh = app.context.loadTab('schedule-config', true);
  await flushRequests();
  assert.equal(app.nodes.get('cfg-model').value, 'new-model');
  assert.equal(app.nodes.get('save-config-btn').disabled, true);
  assert.equal(configReads, 0);
  saving.resolve(response({}));
  await flushRequests();
  assert.equal(configReads, 1);
  assert.equal(app.nodes.get('cfg-model').value, 'new-model');
  assert.equal(app.nodes.get('save-config-btn').disabled, true);
  reload.resolve(response({ summarizer_model: 'new-model' }));
  await Promise.all([pendingSave, refresh, extraRefresh]);
  assert.equal(configReads, 1);
  assert.equal(app.nodes.get('cfg-model').value, 'new-model');
  assert.equal(app.nodes.get('save-config-btn').disabled, false);
  assert.equal(app.nodes.get('save-status').textContent, '✓ Saved');
});

test('queued config refresh also runs after a failed save', async () => {
  const saving = deferred();
  let configReads = 0;
  const app = dashboard(async (route, options) => {
    if (options?.method === 'POST') return saving.promise;
    configReads++;
    return response({ summarizer_model: 'server-model' });
  });
  app.nodes.get('cfg-model').value = 'attempted-model';
  const pendingSave = app.context.saveSchedule();
  const refresh = app.context.loadTab('schedule-config', true);
  await flushRequests();
  assert.equal(configReads, 0);
  assert.equal(app.nodes.get('cfg-model').value, 'attempted-model');
  saving.reject(new Error('offline'));
  await Promise.all([pendingSave, refresh]);
  assert.equal(configReads, 1);
  assert.equal(app.nodes.get('cfg-model').value, 'server-model');
  assert.equal(app.nodes.get('save-config-btn').disabled, false);
  assert.equal(app.nodes.get('save-status').textContent, '✗ Save failed');
});

for (const [tab, route, oldData, latestData, state] of [
  ['price-tracker', '/api/prices?', [{ model_id: 'old/model', name: 'Old', provider: 'old' }], [{ model_id: 'latest/model', name: 'Latest', provider: 'latest' }], 'allPrices[0].model_id'],
  ['ai-leaderboard', '/api/prices?', [{ model_id: 'old/model', name: 'Old' }], [{ model_id: 'latest/model', name: 'Latest' }], '_lbPrices[0].model_id'],
  ['digest-history', '/api/digest/history', [{ sent_at: '2026-10-07T00:00:00Z', channels: ['old'], article_ids: ['old-id'] }], [{ sent_at: '2026-10-08T00:00:00Z', channels: ['latest'], article_ids: ['latest-id'] }], 'document.getElementById("digest-list").innerHTML'],
  ['source-health', '/api/news/sources?', [{ source: 'old-source', count: 1 }], [{ source: 'latest-source', count: 2 }], 'document.getElementById("source-status-list").innerHTML'],
]) {
  test(`${tab} ignores stale tab data after a newer refresh completes`, async () => {
    const pending = [deferred(), deferred()];
    let requests = 0;
    const app = dashboard(url => url.startsWith(route) ? pending[requests++].promise : Promise.resolve(response({ updated_at: null })));
    const older = app.context.loadTab(tab, true);
    const latest = app.context.loadTab(tab, true);
    pending[1].resolve(response(latestData));
    await latest;
    const rendered = app.evaluate(state);
    assert.ok(rendered.includes('latest'));
    pending[0].resolve(response(oldData));
    await older;
    assert.equal(app.evaluate(state), rendered);
  });
}

test('saving a schedule queues an overview refresh and discards the older overview data', async () => {
  const oldSchedule = deferred(), latestSchedule = deferred();
  let scheduleReads = 0;
  const app = dashboard(async (route, options) => {
    if (options?.method === 'POST') return response({});
    if (route === '/api/schedule') return (++scheduleReads === 1 ? oldSchedule : latestSchedule).promise;
    if (route === '/api/health') return response({ status: 'ok' });
    return response([]);
  });
  const loading = app.context.loadOverview();
  await app.context.saveSchedule();
  assert.equal(app.evaluate('_digestTimes.join(",")'), '07:00');
  oldSchedule.resolve(response({ digest_times: ['18:00'] }));
  await flushRequests();
  assert.equal(app.evaluate('_digestTimes.join(",")'), '07:00');
  assert.equal(scheduleReads, 2);
  latestSchedule.resolve(response({ digest_times: ['07:00'] }));
  await loading;
  assert.equal(app.evaluate('_digestTimes.join(",")'), '07:00');
});

test('saving config preserves the valid zero-hour digest buffer', async () => {
  let saved;
  const app = dashboard(async (route, options) => { saved = JSON.parse(options.body); return response({}); });
  for (const [id, value] of Object.entries({ 'cfg-provider': 'mimo', 'cfg-model': 'test', 'cfg-retention': '30', 'cfg-window-buffer': '0', 'cfg-size-base': '5', 'cfg-size-max': '10', 'cfg-max-per-source': '2' })) app.nodes.get(id).value = value;
  app.context.loadOverview = () => {};
  app.context.renderNextDigest = () => {};
  await app.context.saveSchedule();
  assert.equal(saved.digest_window_buffer_hours, 0);
});
