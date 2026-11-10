#!/usr/bin/env node
// Flow status snapshot: attach to a RESPONSIVE PROJECT tab -> reload
// (the SPA stops pushing updates to an idle tab) -> click the left-sidebar
// `Videos` leaf -> count finished-video tiles -> print the session tail.
// One run takes ~25 s and prints one JSON line. Re-run it on a delay instead
// of holding a long foreground poll: a timed-out poll returns no output.
// Usage: node flow-status-probe.js [project-id]
// Tab choice matters: a restored profile carries several flow.google.com tabs,
// commonly the project-less home page, whose tile counts and tail are useless.
// Tabs under /project/ are probed first (only those when [project-id] is given),
// so the reported numbers always come from the project you are driving.
// The counts it prints are still a WINDOW, never a done/stalled verdict: open
// the first Videos tile yourself to identify a finished clip.
const http=require('http');
const WANTED=process.argv[2]||null;
const get=(p)=>new Promise(r=>{http.get('http://127.0.0.1:9222'+p,res=>{let d='';res.on('data',c=>d+=c);res.on('end',()=>{try{r(JSON.parse(d));}catch(e){r(null);}});}).on('error',()=>r(null));});
const openWs=(url)=>new Promise((res,rej)=>{const ws=new WebSocket(url);ws.onopen=()=>res(ws);ws.onerror=rej;});
const sleep=(ms)=>new Promise(r=>setTimeout(r,ms));
const READ=`JSON.stringify({
  url:location.href.slice(-70),
  tiles:document.querySelectorAll('flow-grid-tile-container').length,
  finished:[...document.querySelectorAll('img[alt="Generated video thumbnail"]')].length,
  uploads:[...document.querySelectorAll('img[alt="Tile displaying a user' + String.fromCharCode(39) + 's image"]')].length,
  pct:(document.body.innerText.match(/play_circle \d+%/g)||[]).slice(0,3),
  tail:document.body.innerText.slice(-500)
})`;
const CLICK_VIDEOS=`(()=>{const els=[...document.querySelectorAll('a,button,mat-list-item,[role=menuitem],div')];
  const el=els.find(e=>/^\s*videocam\s*Videos\s*$/.test((e.textContent||'').trim()) && e.children.length<=6 && e.getBoundingClientRect().width>0)
    ||[...document.querySelectorAll('span')].find(e=>(e.textContent||'').trim()==='Videos' && e.getBoundingClientRect().width>0);
  if(!el) return 'no-videos-leaf';
  const r=el.getBoundingClientRect(); const cx=r.x+r.width/2, cy=r.y+r.height/2;
  const o={bubbles:true,cancelable:true,view:window,clientX:cx,clientY:cy,pointerId:1,isPrimary:true,button:0,buttons:1};
  el.dispatchEvent(new PointerEvent('pointerdown',o)); el.dispatchEvent(new MouseEvent('mousedown',o));
  el.dispatchEvent(new PointerEvent('pointerup',Object.assign({},o,{buttons:0}))); el.dispatchEvent(new MouseEvent('mouseup',Object.assign({},o,{buttons:0})));
  el.dispatchEvent(new MouseEvent('click',Object.assign({},o,{buttons:0})));
  return 'clicked:'+el.tagName;})()`;
(async()=>{
  const v=await get('/json/version');
  if(!v){ console.log('CDP-DOWN'); process.exit(2); }
  const ws=await openWs(v.webSocketDebuggerUrl);
  let id=0; const pending=new Map();
  ws.onmessage=e=>{const m=JSON.parse(e.data); if(m.id&&pending.has(m.id)){pending.get(m.id)(m);pending.delete(m.id);}};
  const send=(sid,method,params)=>new Promise(r=>{const i=++id;pending.set(i,r);
    ws.send(JSON.stringify(Object.assign({id:i,method:method,params:params||{}}, sid?{sessionId:sid}:{})));});
  const timed=(sid,method,params,ms)=>new Promise(r=>{const p=send(sid,method,params);
    const t=setTimeout(()=>r({__:'TIMEOUT'}),ms); p.then(m=>{clearTimeout(t);r(m);});});
  const ev=async(sid,expr,ms)=>{const r=await timed(sid,'Runtime.evaluate',{expression:expr,returnByValue:true},ms||8000);
    return r.result? r.result.result && r.result.result.value : null;};
  // Project tabs first, then any responsive Flow tab; skip dead renderers.
  let tabs=(await get('/json/list')||[]).filter(t=>t.type==='page'&&/flow\.google\.com/.test(t.url));
  if(WANTED) tabs=tabs.filter(t=>(t.url||'').includes(WANTED));
  tabs.sort((a,b)=>(b.url.includes('/project/')?1:0)-(a.url.includes('/project/')?1:0));
  if(!tabs.length){ console.log(JSON.stringify({error:'no matching flow tab',wanted:WANTED})); process.exit(3); }
  let sess=null, tab=null;
  for(const t of tabs){
    const a=await send(null,'Target.attachToTarget',{targetId:t.id,flatten:true});
    if(!a.result) continue;
    const s=a.result.sessionId;
    if(await ev(s,'1+1',5000)){ sess=s; tab=t; break; }
  }
  if(!sess){ console.log(JSON.stringify({error:'NO-RESPONSIVE-FLOW-TAB',tried:tabs.map(t=>t.id.slice(0,8))})); process.exit(4); }
  await timed(sess,'Page.reload',{},8000);
  await sleep(9000);
  let raw=await ev(sess,READ,8000);
  if(!raw){ console.log(JSON.stringify({tab:tab.id.slice(0,8),url:tab.url.slice(-60),error:'unresponsive after reload'})); process.exit(5); }
  const media=JSON.parse(raw);
  // Never conclude from the mixed grid: it lags behind, so the filtered
  // Videos list is always the one checked.
  const clicked=await ev(sess,CLICK_VIDEOS,6000);
  await sleep(6000);
  raw=await ev(sess,READ,8000);
  if(!raw){ console.log(JSON.stringify({phase:'videos',clicked:clicked,url:tab.url.slice(-60),error:'unresponsive'})); process.exit(6); }
  const st=JSON.parse(raw);
  console.log(JSON.stringify(Object.assign({phase:'videos',clicked:clicked,tab:tab.id.slice(0,8),projectUrl:tab.url.slice(-60),allMediaFinished:media.finished,allMediaTiles:media.tiles},st)));
  process.exit(0);
})();
