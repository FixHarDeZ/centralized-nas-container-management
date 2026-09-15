// claude-desk browser client.
//
// Talks ttyd's websocket protocol directly (the same one ttyd's own page
// uses): first frame is a JSON handshake, then '0'+bytes for input,
// '1'+JSON for resize; server sends '0'+bytes output, '1'+title, '2'+prefs.
// Touch scrolling, sticky-Ctrl and the iOS keyboard dance are adapted from
// pawprint0706/ttyd-wrapper (MIT — see vendor/LICENSE.ttyd-wrapper).
(function () {
  'use strict';

  const encoder = new TextEncoder();
  const decoder = new TextDecoder();

  const CMD_INPUT = 0x30;   // '0'
  const CMD_RESIZE = '1';
  const SVR_OUTPUT = 0x30;
  const SVR_TITLE = 0x31;
  const SVR_PREFS = 0x32;

  // ?demo=1 renders a canned session with no server (design preview);
  // ?mobile=1 forces the phone layout so a desktop screenshot shows it.
  const PARAMS = new URLSearchParams(location.search);
  const DEMO = PARAMS.has('demo');

  const IS_MOBILE = PARAMS.has('mobile')
    || /Android|iPhone|iPod|iPad/i.test(navigator.userAgent)
    || (/Mac/i.test(navigator.userAgent) && navigator.maxTouchPoints > 1);

  // ── Font size ─────────────────────────────────────────
  const FONT_SIZES = [11, 12, 13, 14, 15, 16, 18, 20, 22];
  const FONT_KEY = 'claude-desk.fontSize';
  let fontSize = IS_MOBILE ? 13 : 14;
  try {
    const saved = parseInt(localStorage.getItem(FONT_KEY), 10);
    if (FONT_SIZES.includes(saved)) fontSize = saved;
  } catch (_) { /* no storage */ }

  // ── Terminal ──────────────────────────────────────────
  const term = new Terminal({
    fontSize: fontSize,
    fontFamily: '"JetBrains Mono", ui-monospace, Menlo, monospace',
    fontWeight: '400',
    fontWeightBold: '700',
    lineHeight: 1.2,
    cursorBlink: true,
    cursorStyle: 'bar',
    scrollback: 8000,
    allowProposedApi: true,
    theme: {
      background: '#0b0f19',
      foreground: '#e5e7eb',
      cursor: '#f59e0b',
      cursorAccent: '#0b0f19',
      selectionBackground: 'rgba(245, 158, 11, 0.28)',
      black: '#111827',
      red: '#f87171',
      green: '#34d399',
      yellow: '#fbbf24',
      blue: '#60a5fa',
      magenta: '#c084fc',
      cyan: '#22d3ee',
      white: '#d1d5db',
      brightBlack: '#4b5563',
      brightRed: '#fca5a5',
      brightGreen: '#6ee7b7',
      brightYellow: '#fde68a',
      brightBlue: '#93c5fd',
      brightMagenta: '#d8b4fe',
      brightCyan: '#67e8f9',
      brightWhite: '#f9fafb',
    },
  });
  const fit = new FitAddon.FitAddon();
  term.loadAddon(fit);
  term.loadAddon(new WebLinksAddon.WebLinksAddon());

  const container = document.getElementById('terminal');
  term.open(container);
  if (!IS_MOBILE) term.focus();

  function refit() {
    fit.fit();
    sendResize();
  }
  requestAnimationFrame(refit);
  setTimeout(refit, 60);
  window.addEventListener('load', refit);
  if (document.fonts && document.fonts.load) {
    document.fonts.load(fontSize + 'px "JetBrains Mono"').then(() => requestAnimationFrame(refit)).catch(() => {});
  }
  new ResizeObserver(() => requestAnimationFrame(refit)).observe(container);
  window.addEventListener('resize', refit);

  // ── Connection ────────────────────────────────────────
  const statusText = document.getElementById('status-text');
  let socket = null;
  let token = '';
  let reconnectTimer = null;
  let reconnectDelay = 1000;

  function setState(state, label) {
    document.body.classList.remove('connected', 'reconnecting');
    if (state) document.body.classList.add(state);
    statusText.textContent = label;
  }

  async function refreshToken() {
    try {
      const r = await fetch('token', { cache: 'no-store' });
      if (r.ok) token = (await r.json()).token || '';
    } catch (_) { /* ttyd without -c: no token */ }
  }

  async function connect() {
    if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) return;
    setState('reconnecting', 'connecting');
    await refreshToken();
    const url = (location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host
      + location.pathname.replace(/[^/]*$/, '') + 'ws';
    try {
      socket = new WebSocket(url, ['tty']);
      socket.binaryType = 'arraybuffer';
      socket.onopen = () => {
        setState('connected', 'live');
        reconnectDelay = 1000;
        socket.send(encoder.encode(JSON.stringify({ AuthToken: token, columns: term.cols, rows: term.rows })));
        term.reset();
        if (!IS_MOBILE) term.focus();
      };
      socket.onmessage = (ev) => {
        if (!(ev.data instanceof ArrayBuffer)) return;
        const bytes = new Uint8Array(ev.data);
        if (!bytes.length) return;
        const payload = bytes.subarray(1);
        switch (bytes[0]) {
          case SVR_OUTPUT: term.write(payload); break;
          case SVR_TITLE: document.title = decoder.decode(payload) || 'claude-desk'; break;
          case SVR_PREFS: break; // our own page decides fonts
          default: break;
        }
      };
      socket.onclose = () => { setState('reconnecting', 'reconnecting'); scheduleReconnect(); };
      socket.onerror = () => {};
    } catch (_) {
      scheduleReconnect();
    }
  }

  function scheduleReconnect() {
    if (reconnectTimer) return;
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null;
      reconnectDelay = Math.min(reconnectDelay * 1.5, 10000);
      connect();
    }, reconnectDelay);
  }

  function sendInput(data) {
    if (DEMO) { term.write(data === '\r' ? '\r\n' : data); return; }
    if (!socket || socket.readyState !== WebSocket.OPEN) return;
    const bytes = typeof data === 'string' ? encoder.encode(data) : data;
    const msg = new Uint8Array(1 + bytes.length);
    msg[0] = CMD_INPUT;
    msg.set(bytes, 1);
    socket.send(msg);
  }

  function sendResize() {
    if (!socket || socket.readyState !== WebSocket.OPEN) return;
    socket.send(encoder.encode(CMD_RESIZE + JSON.stringify({ columns: term.cols, rows: term.rows })));
  }

  // ── Sticky Ctrl ───────────────────────────────────────
  // One-shot: tap Ctrl, then the next typed character becomes a control
  // byte. Multi-char input (IME composition, paste) passes through untouched
  // and keeps Ctrl armed, so a Thai keyboard never eats it by accident.
  let ctrlArmed = false;
  const ctrlBtn = document.querySelector('button[data-mod="ctrl"]');
  function setCtrl(on) {
    ctrlArmed = on;
    ctrlBtn.classList.toggle('armed', on);
  }
  function ctrlify(ch) {
    const u = ch.toUpperCase().charCodeAt(0);
    if (ch === ' ') return '\x00';
    if (u >= 0x3f && u <= 0x7e) return String.fromCharCode(u & 0x1f);
    return ch;
  }

  term.onData((data) => {
    if (ctrlArmed && data.length === 1 && data.charCodeAt(0) < 0x80) {
      setCtrl(false);
      sendInput(ctrlify(data));
      return;
    }
    sendInput(data);
  });

  // ── Toolbar keys ──────────────────────────────────────
  const KEYS = {
    esc: '\x1b',
    tab: '\x09',
    shifttab: '\x1b[Z',
    up: '\x1b[A',
    down: '\x1b[B',
    right: '\x1b[C',
    left: '\x1b[D',
    // Alt+Enter: Claude Code inserts a newline without submitting.
    newline: '\x1b\r',
    slash: '/',
    ctrlc: '\x03',
  };

  const toolbar = document.getElementById('toolbar');
  // pointerdown preventDefault keeps focus in xterm's textarea so the soft
  // keyboard stays open while tapping the bar.
  toolbar.addEventListener('pointerdown', (e) => {
    const btn = e.target.closest('button');
    if (!btn) return;
    e.preventDefault();
    btn.classList.add('pressed');
  });
  ['pointerup', 'pointercancel', 'pointerleave'].forEach((ev) => {
    toolbar.addEventListener(ev, (e) => {
      const btn = e.target.closest('button');
      if (btn) btn.classList.remove('pressed');
    }, true);
  });
  toolbar.addEventListener('click', (e) => {
    const btn = e.target.closest('button');
    if (!btn) return;
    e.preventDefault();
    if (btn.dataset.key) {
      let seq = KEYS[btn.dataset.key];
      if (ctrlArmed && seq.length === 1) { seq = ctrlify(seq); setCtrl(false); }
      sendInput(seq);
    } else if (btn.dataset.mod === 'ctrl') {
      setCtrl(!ctrlArmed);
    }
  });

  // ── Font buttons ──────────────────────────────────────
  function setFont(size) {
    fontSize = size;
    term.options.fontSize = size;
    try { localStorage.setItem(FONT_KEY, size); } catch (_) {}
    requestAnimationFrame(refit);
  }
  document.getElementById('font-minus').addEventListener('click', () => {
    const i = FONT_SIZES.indexOf(fontSize);
    if (i > 0) setFont(FONT_SIZES[i - 1]);
  });
  document.getElementById('font-plus').addEventListener('click', () => {
    const i = FONT_SIZES.indexOf(fontSize);
    if (i < FONT_SIZES.length - 1) setFont(FONT_SIZES[i + 1]);
  });

  // ── Paste ─────────────────────────────────────────────
  document.getElementById('paste-btn').addEventListener('click', async () => {
    try {
      const text = await navigator.clipboard.readText();
      if (text) sendInput(text);
    } catch (_) { /* denied or unsupported */ }
  });

  // ── Keyboard toggle + iOS viewport ────────────────────
  const kbBtn = document.getElementById('kb-btn');
  kbBtn.addEventListener('click', () => {
    const ta = term.textarea;
    if (!ta) return;
    if (document.activeElement === ta) ta.blur(); else term.focus();
  });
  if (window.visualViewport) {
    const vv = window.visualViewport;
    const onVV = () => {
      const open = vv.height < window.innerHeight - 1;
      document.body.classList.toggle('kb-open', open);
      kbBtn.classList.toggle('on', open);
      document.body.style.height = open ? vv.height + 'px' : '';
      window.scrollTo(0, 0);
      requestAnimationFrame(refit);
    };
    vv.addEventListener('resize', onVV);
    vv.addEventListener('scroll', onVV);
  }

  // ── Toolbar visibility ────────────────────────────────
  const toolbarBtn = document.getElementById('toolbar-btn');
  let toolbarOn = IS_MOBILE;
  function applyToolbar() {
    document.body.classList.toggle('toolbar-hidden', !toolbarOn);
    toolbarBtn.classList.toggle('on', toolbarOn);
    requestAnimationFrame(refit);
  }
  toolbarBtn.addEventListener('click', () => { toolbarOn = !toolbarOn; applyToolbar(); });
  applyToolbar();

  // ── Touch: drag to scroll, tap to focus ───────────────
  // xterm's own touch scrolling fights the browser on the DOM renderer, and
  // full-screen TUIs (Claude Code) live in the alt buffer where scrollLines
  // is a no-op — feed a synthetic wheel event there instead.
  let gesture = null;
  function screenRect() {
    const s = container.querySelector('.xterm-screen');
    return (s || container).getBoundingClientRect();
  }
  container.addEventListener('pointerdown', (e) => {
    if (e.pointerType === 'mouse') return;
    if (gesture) return;
    e.preventDefault();
    gesture = { id: e.pointerId, lastY: e.clientY, acc: 0, cellH: screenRect().height / term.rows,
      x0: e.clientX, y0: e.clientY, t0: Date.now() };
    try { container.setPointerCapture(e.pointerId); } catch (_) {}
  }, true);
  container.addEventListener('pointermove', (e) => {
    if (!gesture || e.pointerId !== gesture.id) return;
    gesture.acc += gesture.lastY - e.clientY;
    const lines = Math.trunc(gesture.acc / gesture.cellH);
    if (lines !== 0) {
      gesture.acc -= lines * gesture.cellH;
      if (term.modes.mouseTrackingMode !== 'none' || term.buffer.active.type === 'alternate') {
        const s = container.querySelector('.xterm-screen');
        (s || container).dispatchEvent(new WheelEvent('wheel', {
          bubbles: true, cancelable: true, deltaMode: WheelEvent.DOM_DELTA_LINE,
          deltaY: lines, clientX: e.clientX, clientY: e.clientY,
        }));
      } else {
        term.scrollLines(lines);
      }
    }
    gesture.lastY = e.clientY;
  }, true);
  function endGesture(e) {
    if (!gesture || e.pointerId !== gesture.id) return;
    const tap = Math.abs(e.clientX - gesture.x0) < 10 && Math.abs(e.clientY - gesture.y0) < 10 && Date.now() - gesture.t0 < 350;
    gesture = null;
    if (tap) term.focus();
  }
  container.addEventListener('pointerup', endGesture, true);
  container.addEventListener('pointercancel', endGesture, true);
  ['touchstart', 'touchmove'].forEach((ev) => {
    container.addEventListener(ev, (e) => { e.stopPropagation(); if (e.cancelable) e.preventDefault(); },
      { capture: true, passive: false });
  });

  // ── Files drawer ──────────────────────────────────────
  // Two folders on the share: in/ (yours → Claude, with upload + delete)
  // and out/ (Claude → you, tap to open, ⬇ to save). Listing comes from
  // nginx's JSON autoindex; uploads go to upload.py in the desk container.
  const drawer = document.getElementById('drawer');
  const list = document.getElementById('file-list');
  const empty = document.getElementById('file-empty');
  const sub = document.getElementById('drawer-sub');
  const inActions = document.getElementById('in-actions');
  const fileInput = document.getElementById('file-input');
  const upStatus = document.getElementById('upload-status');
  let dir = 'out';

  const ICON_DL = '<svg viewBox="0 0 24 24"><path d="M12 4v11M7 10l5 5 5-5M5 20h14"/></svg>';
  const ICON_DEL = '<svg viewBox="0 0 24 24"><path d="M5 7h14M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/></svg>';

  function fmtSize(n) {
    if (n < 1024) return n + ' B';
    if (n < 1048576) return (n / 1024).toFixed(0) + ' KB';
    return (n / 1048576).toFixed(1) + ' MB';
  }
  function fmtTime(s) {
    const d = new Date(s);
    if (isNaN(d)) return '';
    const same = d.toDateString() === new Date().toDateString();
    return same ? d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
      : d.toLocaleDateString([], { day: 'numeric', month: 'short' });
  }
  function render(files) {
    list.innerHTML = '';
    files = files.filter((f) => f.type === 'file' && !f.name.startsWith('.') && !f.name.endsWith('.part'))
      .sort((a, b) => new Date(b.mtime) - new Date(a.mtime));
    empty.hidden = files.length > 0;
    empty.innerHTML = dir === 'out' ? 'Nothing in <code>out/</code> yet.' : 'Nothing in <code>in/</code>. Add a file for Claude to work on.';
    for (const f of files) {
      const ext = (f.name.split('.').pop() || '').toLowerCase();
      const href = 'files/' + dir + '/' + encodeURIComponent(f.name);
      const li = document.createElement('li');
      const a = document.createElement('a');
      a.href = href; a.target = '_blank'; a.rel = 'noopener';
      a.innerHTML = '<span class="file-ico"></span><span class="file-name"></span><span class="file-meta"></span>';
      a.querySelector('.file-ico').textContent = ext.slice(0, 4).toUpperCase();
      a.querySelector('.file-ico').classList.add(ext);
      a.querySelector('.file-name').textContent = f.name;
      a.querySelector('.file-meta').textContent = fmtSize(f.size) + ' · ' + fmtTime(f.mtime);
      li.appendChild(a);
      const act = document.createElement('button');
      act.className = 'file-act' + (dir === 'in' ? ' del' : '');
      act.innerHTML = dir === 'in' ? ICON_DEL : ICON_DL;
      act.title = dir === 'in' ? 'Delete' : 'Download';
      act.addEventListener('click', () => (dir === 'in' ? removeFile(f.name) : saveFile(href, f.name)));
      li.appendChild(act);
      list.appendChild(li);
    }
  }
  function saveFile(href, name) {
    const a = document.createElement('a');
    a.href = href; a.download = name;
    document.body.appendChild(a); a.click(); a.remove();
  }
  async function loadFiles() {
    if (DEMO) {
      render(dir === 'out' ? [
        { name: '2026-09-15-q3-review.pptx', type: 'file', size: 2411520, mtime: new Date().toISOString() },
        { name: '2026-09-15-budget.xlsx', type: 'file', size: 88123, mtime: new Date(Date.now() - 3.6e6).toISOString() },
        { name: '2026-09-14-proposal.docx', type: 'file', size: 421000, mtime: new Date(Date.now() - 9e7).toISOString() },
        { name: 'slide-03.png', type: 'file', size: 310000, mtime: new Date(Date.now() - 9.1e7).toISOString() },
      ] : [
        { name: 'sales-q3.xlsx', type: 'file', size: 150000, mtime: new Date().toISOString() },
        { name: 'brand-template.pptx', type: 'file', size: 3900000, mtime: new Date(Date.now() - 2e8).toISOString() },
      ]);
      return;
    }
    try {
      const r = await fetch('files/' + dir + '/', { cache: 'no-store', headers: { Accept: 'application/json' } });
      render(r.ok ? await r.json() : []);
    } catch (_) {
      render([]);
    }
  }
  function setDir(next) {
    dir = next;
    drawer.querySelectorAll('.tab').forEach((t) => t.classList.toggle('on', t.dataset.dir === dir));
    inActions.hidden = dir !== 'in';
    sub.textContent = dir === 'out' ? 'finished files · tap to open, ⬇ to save' : 'source files for Claude · tap to open, 🗑 to remove';
    loadFiles();
  }
  drawer.querySelectorAll('.tab').forEach((t) => t.addEventListener('click', () => setDir(t.dataset.dir)));

  // Upload: one PUT per file, sequential, with a progress bar. XHR rather
  // than fetch because fetch has no upload progress.
  function putFile(file) {
    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open('PUT', 'upload/' + encodeURIComponent(file.name));
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) setProgress(file.name, e.loaded / e.total);
      };
      xhr.onload = () => (xhr.status === 201 ? resolve() : reject(new Error(xhr.status + ' ' + xhr.responseText)));
      xhr.onerror = () => reject(new Error('network'));
      xhr.send(file);
    });
  }
  function setProgress(name, frac, err) {
    upStatus.hidden = false;
    upStatus.innerHTML = '<span></span><div class="bar"><i></i></div>';
    upStatus.querySelector('span').textContent = err ? ('✕ ' + name + ' — ' + err) : ((frac >= 1 ? '✓ ' : '↑ ') + name + ' ' + Math.round(frac * 100) + '%');
    upStatus.querySelector('i').style.width = Math.round(frac * 100) + '%';
  }
  document.getElementById('add-btn').addEventListener('click', () => fileInput.click());
  fileInput.addEventListener('change', async () => {
    const files = Array.from(fileInput.files || []);
    fileInput.value = '';
    for (const f of files) {
      try {
        setProgress(f.name, 0);
        if (DEMO) { await new Promise((r) => setTimeout(r, 400)); setProgress(f.name, 1); }
        else await putFile(f);
        setProgress(f.name, 1);
      } catch (e) {
        setProgress(f.name, 0, e.message);
        break;
      }
    }
    loadFiles();
    setTimeout(() => { upStatus.hidden = true; }, 2500);
  });
  async function removeFile(name) {
    if (DEMO) return;
    try {
      await fetch('upload/' + encodeURIComponent(name), { method: 'DELETE' });
    } catch (_) { /* listing refresh shows the truth */ }
    loadFiles();
  }

  function openDrawer() {
    document.body.classList.add('drawer-open');
    drawer.setAttribute('aria-hidden', 'false');
    setDir(dir);
  }
  function closeDrawer() {
    document.body.classList.remove('drawer-open');
    drawer.setAttribute('aria-hidden', 'true');
  }
  document.getElementById('files-btn').addEventListener('click', openDrawer);
  document.getElementById('drawer-close').addEventListener('click', closeDrawer);
  document.getElementById('scrim').addEventListener('click', closeDrawer);

  // ── Go ────────────────────────────────────────────────
  if (DEMO) {
    setState('connected', 'live');
    term.writeln('\x1b[38;5;214m▌\x1b[0m claude-desk — 2.1.272 (Claude Code)');
    term.writeln('\x1b[38;5;245m  in/  ← drop source files here (DS File)');
    term.writeln('  out/ → finished pptx/docx/xlsx land here');
    term.writeln('  type: claude  |  r = resume last\x1b[0m');
    term.writeln('');
    term.writeln('\x1b[38;5;214mdesk\x1b[0m \x1b[38;5;245m/work\x1b[0m › claude');
    term.writeln('');
    term.writeln('\x1b[1m ✻ Welcome to Claude Code\x1b[0m');
    term.writeln('');
    term.writeln('\x1b[38;5;245m > \x1b[0mทำ slide สรุปยอดขาย Q3 จาก in/sales-q3.xlsx 8 หน้า');
    term.writeln('');
    term.writeln('\x1b[38;5;214m●\x1b[0m Reading in/sales-q3.xlsx…');
    term.writeln('\x1b[38;5;214m●\x1b[0m Building deck with pptxgenjs');
    term.writeln('\x1b[38;5;214m●\x1b[0m Rendering slides to check layout');
    term.writeln('');
    term.writeln('  out/2026-09-15-q3-review.pptx — 8 slides, Thai fonts OK');
    term.writeln('');
    term.write('\x1b[38;5;245m > \x1b[0m');
    if (PARAMS.has('drawer')) { openDrawer(); if (PARAMS.get('drawer') === 'in') setDir('in'); }
  } else {
    connect();
  }

  window._term = term;
})();
