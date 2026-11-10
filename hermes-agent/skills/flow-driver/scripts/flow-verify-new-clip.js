#!/usr/bin/env node
// Positive-ID check for a finished Flow clip: attach to the project tab,
// reload (the SPA stops pushing updates to an idle tab), click the sidebar
// `Videos` leaf, open the FIRST tile, then run the two-sided text check:
//   expected phrase (only you wrote it) must be PRESENT,
//   forbidden phrase (the previous clip's product) must be ABSENT.
// Tile COUNTS are never a verdict — this script never reads them as one.
//
// Usage:
//   node flow-verify-new-clip.js <project-id> "<expected>" "<forbidden>"
// Example:
//   node flow-verify-new-clip.js b618e7a8-2661-4b51-be99-e4bb79df2758 \
//        "LEGO Batman" "God of War"
//
// Prints one JSON line:
//   {"ok":true, "editId":"...", "url":"...", "expected":true, "forbidden":false}
// ok:true means you opened a NEW /edit/<id> holding your text and no trace of
// the old clip -> that is the finished clip. Non-zero exit otherwise.
const http = require('http');
const PROJECT = process.argv[2] || null;
const EXPECTED = process.argv[3] || null;
const FORBIDDEN = process.argv[4] || null;
if (!PROJECT || !EXPECTED) {
  console.log(JSON.stringify({ error: 'usage: node flow-verify-new-clip.js <project-id> "<expected>" ["<forbidden>"]' }));
  process.exit(64);
}

const get = (p) => new Promise(r => {
  http.get('http://127.0.0.1:9222' + p, res => {
    let d = ''; res.on('data', c => d += c);
    res.on('end', () => { try { r(JSON.parse(d)); } catch (e) { r(null); } });
  }).on('error', () => r(null));
});
const openWs = (url) => new Promise((res, rej) => {
  const ws = new WebSocket(url); ws.onopen = () => res(ws); ws.onerror = rej;
});
const sleep = (ms) => new Promise(r => setTimeout(r, ms));

const CLICK_VIDEOS = `(()=>{const sp=[...document.querySelectorAll('span')].find(e=>(e.textContent||'').trim()==='Videos'&&e.getBoundingClientRect().width>0);
  if(!sp) return 'no-videos-leaf';
  const r=sp.getBoundingClientRect(); const cx=r.x+r.width/2, cy=r.y+r.height/2;
  const o={bubbles:true,cancelable:true,view:window,clientX:cx,clientY:cy,pointerId:1,isPrimary:true,button:0,buttons:1};
  sp.dispatchEvent(new PointerEvent('pointerdown',o)); sp.dispatchEvent(new MouseEvent('mousedown',o));
  sp.dispatchEvent(new PointerEvent('pointerup',Object.assign({},o,{buttons:0}))); sp.dispatchEvent(new MouseEvent('mouseup',Object.assign({},o,{buttons:0})));
  sp.dispatchEvent(new MouseEvent('click',Object.assign({},o,{buttons:0})));
  return 'clicked';})()`;

const FIRST_TILE = `(()=>{const im=[...document.querySelectorAll('img[alt="Generated video thumbnail"]')][0];
  if(!im) return JSON.stringify({err:'no-poster'});
  const r=im.getBoundingClientRect(); const cx=Math.round(r.x+r.width/2), cy=Math.round(r.y+r.height/2);
  const el=document.elementFromPoint(cx,cy);
  if(!el) return JSON.stringify({err:'null-hit'});
  const o={bubbles:true,cancelable:true,view:window,clientX:cx,clientY:cy,pointerId:1,isPrimary:true,button:0,buttons:1};
  el.dispatchEvent(new PointerEvent('pointerdown',o)); el.dispatchEvent(new MouseEvent('mousedown',o));
  el.dispatchEvent(new PointerEvent('pointerup',Object.assign({},o,{buttons:0}))); el.dispatchEvent(new MouseEvent('mouseup',Object.assign({},o,{buttons:0})));
  el.dispatchEvent(new MouseEvent('click',Object.assign({},o,{buttons:0})));
  el.dispatchEvent(new MouseEvent('dblclick',Object.assign({},o,{buttons:0})));
  return JSON.stringify({hit:el.tagName});})()`;

(async () => {
  const v = await get('/json/version');
  if (!v) { console.log(JSON.stringify({ error: 'CDP-DOWN' })); process.exit(2); }
  const ws = await openWs(v.webSocketDebuggerUrl);
  let id = 0; const pending = new Map();
  ws.onmessage = e => {
    const m = JSON.parse(e.data);
    if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); }
  };
  const send = (sid, method, params) => new Promise(r => {
    const i = ++id; pending.set(i, r);
    ws.send(JSON.stringify(Object.assign({ id: i, method, params: params || {} }, sid ? { sessionId: sid } : {})));
  });
  const timed = (sid, method, params, ms) => new Promise(r => {
    const p = send(sid, method, params);
    const t = setTimeout(() => r({ __: 'TIMEOUT' }), ms);
    p.then(m => { clearTimeout(t); r(m); });
  });
  const ev = async (sid, expr, ms) => {
    const r = await timed(sid, 'Runtime.evaluate', { expression: expr, returnByValue: true }, ms || 8000);
    return r.result && r.result.result ? r.result.result.value : null;
  };

  let tabs = (await get('/json/list') || []).filter(t => t.type === 'page' && /flow\.google\.com/.test(t.url || ''));
  if (PROJECT) tabs = tabs.filter(t => (t.url || '').includes(PROJECT));
  if (!tabs.length) { console.log(JSON.stringify({ error: 'no matching flow tab', wanted: PROJECT })); process.exit(3); }

  let sess = null, tab = null;
  for (const t of tabs) {
    const a = await send(null, 'Target.attachToTarget', { targetId: t.id, flatten: true });
    if (!a.result) continue;
    const s = a.result.sessionId;
    if (await ev(s, '1+1', 5000)) { sess = s; tab = t; break; }
  }
  if (!sess) { console.log(JSON.stringify({ error: 'NO-RESPONSIVE-FLOW-TAB' })); process.exit(4); }

  await timed(sess, 'Page.navigate', { url: 'https://flow.google.com/project/' + PROJECT }, 10000);
  await sleep(9000);
  let raw = await ev(sess, 'JSON.stringify({url:location.href, body:document.body.innerText.length})', 8000);
  if (!raw) { console.log(JSON.stringify({ error: 'unresponsive after navigate' })); process.exit(5); }

  const clicked = await ev(sess, CLICK_VIDEOS, 6000);
  await sleep(6000);
  const tile = await ev(sess, FIRST_TILE, 6000);
  await sleep(5000);

  const verdict = await ev(sess, `JSON.stringify((function(){
    var body=document.body.innerText;
    return {url:location.href,
            expected:${JSON.stringify(EXPECTED)}? body.indexOf(${JSON.stringify(EXPECTED)})>=0 : null,
            forbidden:${JSON.stringify(FORBIDDEN)}? body.indexOf(${JSON.stringify(FORBIDDEN)})>=0 : null};
  })())`, 8000);
  if (!verdict) { console.log(JSON.stringify({ error: 'unresponsive after open', clicked, tile })); process.exit(6); }

  const v2 = JSON.parse(verdict);
  const editId = ((v2.url || '').match(/\/edit\/([0-9a-f-]{36})/) || [])[1] || null;
  const isNew = !!editId && !!v2.expected && v2.forbidden === false;
  console.log(JSON.stringify({
    ok: isNew, editId, url: v2.url, expected: v2.expected, forbidden: v2.forbidden,
    tile, clicked, tab: tab.id.slice(0, 8),
    note: isNew ? 'opened a new /edit id holding your phrase, old clip absent' : 'not confirmed - inspect manually'
  }));
  process.exit(isNew ? 0 : 7);
})();
