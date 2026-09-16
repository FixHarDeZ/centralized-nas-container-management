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

  // ── Theme ─────────────────────────────────────────────
  // Two palettes, one per CSS [data-theme]. With no stored choice the page
  // follows the system and keeps following it (matchMedia listener below);
  // the first tap on the header button pins a theme for good.
  // Light's ANSI colours are the darker shade of each hue — a light terminal
  // painted with the dark set is unreadable on white.
  const THEME_KEY = 'claude-desk.theme';
  const THEMES = {
    dark: {
      meta: '#0b0f19',
      xterm: {
        background: '#0b0f19', foreground: '#e5e7eb',
        cursor: '#f59e0b', cursorAccent: '#0b0f19',
        selectionBackground: 'rgba(245, 158, 11, 0.28)',
        black: '#111827', red: '#f87171', green: '#34d399', yellow: '#fbbf24',
        blue: '#60a5fa', magenta: '#c084fc', cyan: '#22d3ee', white: '#d1d5db',
        brightBlack: '#4b5563', brightRed: '#fca5a5', brightGreen: '#6ee7b7',
        brightYellow: '#fde68a', brightBlue: '#93c5fd', brightMagenta: '#d8b4fe',
        brightCyan: '#67e8f9', brightWhite: '#f9fafb',
      },
    },
    light: {
      meta: '#f6f7f9',
      xterm: {
        background: '#f6f7f9', foreground: '#0f172a',
        cursor: '#b45309', cursorAccent: '#f6f7f9',
        selectionBackground: 'rgba(180, 83, 9, 0.22)',
        black: '#1e293b', red: '#b91c1c', green: '#047857', yellow: '#a16207',
        blue: '#1d4ed8', magenta: '#7e22ce', cyan: '#0e7490', white: '#475569',
        // On white the "bright" end has to go darker, not lighter: programs
        // use it for emphasis, and brightWhite as #fff would be invisible.
        brightBlack: '#64748b', brightRed: '#dc2626', brightGreen: '#059669',
        brightYellow: '#b45309', brightBlue: '#2563eb', brightMagenta: '#9333ea',
        brightCyan: '#0891b2', brightWhite: '#0f172a',
      },
    },
  };

  const prefersLight = window.matchMedia ? matchMedia('(prefers-color-scheme: light)') : null;
  const forcedTheme = ['dark', 'light'].includes(PARAMS.get('theme')) ? PARAMS.get('theme') : null;

  function storedTheme() {
    try {
      const v = localStorage.getItem(THEME_KEY);
      return v === 'dark' || v === 'light' ? v : null;
    } catch (_) { return null; }
  }
  function resolveTheme() {
    return forcedTheme || storedTheme() || (prefersLight && prefersLight.matches ? 'light' : 'dark');
  }

  let theme = resolveTheme();

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
    theme: THEMES[theme].xterm,
  });
  const fit = new FitAddon.FitAddon();
  term.loadAddon(fit);
  term.loadAddon(new WebLinksAddon.WebLinksAddon());

  const container = document.getElementById('terminal');
  term.open(container);
  if (!IS_MOBILE) term.focus();
  // Demo only: lets a console poke escape sequences at the terminal (the
  // OSC 52 handler below was checked this way). Never exposed on the live page.
  if (DEMO) window.term = term;

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
    // Attaching is what spawns tmux, so a sessions sheet that came up before
    // the socket did has a pane to ask about only now.
    if (state === 'connected' && document.body.classList.contains('sessions-open')) {
      loadSessions();
    }
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

  // ── Theme button ──────────────────────────────────────
  const themeBtn = document.getElementById('theme-btn');

  function applyTheme(next) {
    theme = next;
    document.documentElement.setAttribute('data-theme', theme);
    // xterm paints from its own palette, not CSS: hand it the new one and
    // repaint the rows already on screen (a plain assignment only affects
    // what is written afterwards).
    term.options.theme = THEMES[theme].xterm;
    term.refresh(0, term.rows - 1);
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute('content', THEMES[theme].meta);
    const other = theme === 'dark' ? 'light' : 'dark';
    themeBtn.title = 'Switch to ' + other + ' mode';
    themeBtn.setAttribute('aria-label', themeBtn.title);
  }

  themeBtn.addEventListener('click', () => {
    const next = theme === 'dark' ? 'light' : 'dark';
    try { localStorage.setItem(THEME_KEY, next); } catch (_) { /* not persisted */ }
    applyTheme(next);
  });

  // Until the button is tapped once, track the system (iOS flips it on a
  // schedule, and the desk is used both in daylight and in bed).
  if (prefersLight && prefersLight.addEventListener) {
    prefersLight.addEventListener('change', (e) => {
      if (!forcedTheme && !storedTheme()) applyTheme(e.matches ? 'light' : 'dark');
    });
  }

  applyTheme(theme);

  // ── Copy ──────────────────────────────────────────────
  // Two sources, because there are two kinds of selection on this screen.
  //
  // Claude Code turns mouse tracking on, so a drag inside it never becomes an
  // xterm selection: the app takes the mouse events, keeps the selection
  // itself, and copies via `tmux load-buffer -w`. With set-clipboard on
  // (tmux.conf) tmux then emits OSC 52 to us — xterm.js does not handle that
  // sequence on its own, so it is caught here and written to the clipboard.
  // Safari refuses writeText() outside a tap, which is why the text is also
  // kept for the button: Claude Code copies, the user taps ⧉ Copy, done.
  //
  // A shell prompt has no mouse tracking, so there a drag is a real xterm
  // selection and the button reads that instead.
  const copyBtn = document.getElementById('copy-btn');
  const say = (label) => {
    copyBtn.textContent = label;
    setTimeout(() => { copyBtn.textContent = '⧉ Copy'; }, 1200);
  };
  let oscClip = '';
  term.parser.registerOscHandler(52, (data) => {
    // "c;<base64>" — selection kind, then payload. "?" is a read request;
    // the browser never answers those.
    const sep = data.indexOf(';');
    const b64 = sep < 0 ? data : data.slice(sep + 1);
    if (!b64 || b64 === '?') return true;
    try {
      const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
      oscClip = new TextDecoder().decode(bytes);
    } catch (_) {
      // A truncated payload looks exactly like the bug this fixes — say so
      // rather than failing silently, and drop the stale text so the button
      // cannot paste an older selection instead.
      oscClip = '';
      say('copy failed');
      return true;
    }
    navigator.clipboard.writeText(oscClip).then(
      () => say('✓ copied'),
      () => say('tap to copy'),
    );
    return true;
  });
  copyBtn.addEventListener('click', async () => {
    const text = term.getSelection() || oscClip;
    if (!text) { say('select first'); return; }
    try {
      await navigator.clipboard.writeText(text);
      say('✓ copied');
    } catch (_) {
      say('blocked');
    }
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
  const clearBtn = document.getElementById('clear-btn');
  const clearLabel = document.getElementById('clear-label');
  let dir = 'out';
  let shown = 0;          // files listed in the current tab, for the arm label

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
    shown = files.length;
    disarmClear();
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
  const demoCleared = { in: false, out: false };
  async function loadFiles() {
    if (DEMO) {
      if (demoCleared[dir]) { render([]); return; }
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
      xhr.open('PUT', 'upload/in/' + encodeURIComponent(file.name));
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
      await fetch('upload/' + dir + '/' + encodeURIComponent(name), { method: 'DELETE' });
    } catch (_) { /* listing refresh shows the truth */ }
    loadFiles();
  }

  // Clearing a folder is permanent — the share's recycle bin is a file-service
  // feature and os.unlink in the container walks straight past it. So the
  // button arms on the first tap and only deletes on the second.
  let armTimer = null;

  function disarmClear() {
    clearTimeout(armTimer);
    armTimer = null;
    clearBtn.classList.remove('armed');
    clearBtn.disabled = false;
    clearBtn.hidden = shown === 0;
    clearLabel.textContent = 'Clear ' + dir + '/';
  }

  clearBtn.addEventListener('click', async () => {
    if (!armTimer) {
      clearBtn.classList.add('armed');
      clearLabel.textContent = 'Delete ' + shown + (shown === 1 ? ' file' : ' files') + ' for good?';
      armTimer = setTimeout(disarmClear, 4000);
      return;
    }
    clearTimeout(armTimer);
    armTimer = null;
    clearBtn.disabled = true;
    clearLabel.textContent = 'Clearing…';
    let gone = shown;
    if (DEMO) { demoCleared[dir] = true; } else {
      try {
        const r = await fetch('upload/' + dir + '/', { method: 'DELETE' });
        gone = r.ok ? parseInt(await r.text(), 10) || 0 : 0;
      } catch (_) {
        gone = 0;
      }
    }
    await loadFiles();        // resets the button through disarmClear
    if (gone) {
      clearBtn.hidden = false;
      clearBtn.disabled = true;
      clearLabel.textContent = 'Cleared ' + gone + (gone === 1 ? ' file' : ' files');
      setTimeout(disarmClear, 2000);
    }
  });

  function openDrawer() {
    closeSessions();
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
  document.getElementById('scrim').addEventListener('click', () => { closeDrawer(); closeSessions(); });

  // ── Rate-limit chip ───────────────────────────────────
  // The numbers come from statusline.sh, which is the only thing Claude Code
  // shows them to; upload.py serves its file and tells us how old it is.
  // Nothing is running most of the time, so a reading that has stopped moving
  // is dimmed rather than presented as current.
  const quota = document.getElementById('quota');
  const STALE_AFTER = 20 * 60;   // seconds; longer than a pause for coffee
  let lastQuota = null;          // last answer, redrawn by the ticker below

  function pctClass(pct) {
    return pct >= 95 ? 'full' : pct >= 80 ? 'hot' : '';
  }
  // Same shape as the status line's fmt_reset, so the chip and the rows below
  // it never disagree about how long is left.
  function fmtReset(seconds) {
    if (!(seconds > 0)) return 'now';
    const d = Math.floor(seconds / 86400);
    const h = Math.floor((seconds % 86400) / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    if (d > 0) return d + 'd';
    if (h > 0) return h + 'h' + m + 'm';
    return m + 'm';
  }
  function fillWindow(row, win, label) {
    if (!win || typeof win.pct !== 'number') { row.hidden = true; return ''; }
    const pct = Math.round(win.pct);
    row.hidden = false;
    row.classList.remove('hot', 'full');
    if (pctClass(pct)) row.classList.add(pctClass(pct));
    row.querySelector('.q-pct').textContent = pct + '%';
    // Counted from resets_at here rather than taken from the server, so the
    // number keeps falling between polls (see the ticker below).
    const left = win.resets_at ? fmtReset(win.resets_at - Date.now() / 1000) : '';
    row.querySelector('.q-in').textContent = left ? '↻' + left : '';
    return label + ' ' + pct + '%' + (left ? ' · resets in ' + left : '');
  }
  function renderQuota(data) {
    const five = data && data.five_hour;
    const week = data && data.seven_day;
    if (!five && !week) { quota.hidden = true; return; }
    lastQuota = data;
    const tips = [
      fillWindow(quota.querySelector('.q-5h'), five, '5h'),
      fillWindow(quota.querySelector('.q-wk'), week, 'wk'),
    ].filter(Boolean);
    const stale = (data.age || 0) > STALE_AFTER;
    quota.classList.toggle('stale', stale);
    quota.title = tips.join(' · ') + (stale ? ' (no session running — last seen reading)' : '');
    quota.hidden = false;
  }
  async function loadQuota() {
    if (DEMO) {
      renderQuota({
        five_hour: { pct: 72, resets_at: Date.now() / 1000 + 7560 },
        seven_day: { pct: 58, resets_at: Date.now() / 1000 + 22560 },
        age: 5,
      });
      return;
    }
    try {
      const r = await fetch('api/status', { cache: 'no-store' });
      if (!r.ok) return;
      const data = await r.json();
      renderQuota(data);
      noteFinished(data.done);
    } catch (_) { /* leave the last reading up */ }
  }
  quota.addEventListener('click', loadQuota);
  loadQuota();
  // 15s rather than a minute because the same poll carries the "Claude
  // finished" mark; a browser throttles it while the tab is hidden anyway.
  setInterval(loadQuota, 15000);
  // The countdown is computed from resets_at, so it can keep falling off the
  // last answer without asking the desk again — and it still moves while the
  // desk is idle and the percentages have stopped changing.
  setInterval(() => { if (lastQuota && !document.hidden) renderQuota(lastQuota); }, 20000);
  // Coming back to a phone that slept: the chip is the first thing that is wrong.
  document.addEventListener('visibilitychange', () => { if (!document.hidden) loadQuota(); });

  // ── "Claude finished" ─────────────────────────────────
  // A Stop hook in the desk writes a timestamp (done-hook.sh); the poll above
  // carries it. There is no way to read this off the websocket — it delivers
  // terminal bytes, and the end of a turn is a shape in Claude Code's drawing,
  // not an event.
  //
  // Only useful while this page is still running. A backgrounded PWA on iOS is
  // suspended, so with the phone locked nothing arrives — that is the deal
  // this accepts, and the alternative (real Web Push) is a push service and
  // VAPID keys, not a toggle.
  const NOTIFY_KEY = 'claude-desk.notify';
  const notifyBtn = document.getElementById('notify-btn');
  const notifyLabel = document.getElementById('notify-label');
  const canNotify = 'Notification' in window;
  let lastDone = 0;
  let notifyOn = false;
  try { notifyOn = localStorage.getItem(NOTIFY_KEY) === '1'; } catch (_) { /* no storage */ }

  function paintNotify() {
    const granted = canNotify && Notification.permission === 'granted';
    const on = notifyOn && granted;
    notifyBtn.classList.toggle('armed', on);
    notifyLabel.textContent = !canNotify ? 'Notifications not supported here'
      : Notification.permission === 'denied' ? 'Notifications blocked in settings'
      : on ? 'Notifying when Claude finishes'
      : 'Notify when Claude finishes';
    notifyBtn.disabled = !canNotify || Notification.permission === 'denied';
  }

  notifyBtn.addEventListener('click', async () => {
    if (!canNotify) return;
    if (notifyOn) {
      notifyOn = false;
    } else {
      // Safari grants this only from inside a tap, which is why the toggle is
      // a button in the sheet rather than something applied on load.
      const permission = Notification.permission === 'granted'
        ? 'granted' : await Notification.requestPermission();
      notifyOn = permission === 'granted';
    }
    try { localStorage.setItem(NOTIFY_KEY, notifyOn ? '1' : '0'); } catch (_) { /* not persisted */ }
    paintNotify();
  });
  paintNotify();

  function noteFinished(done) {
    const at = done && done.at;
    if (!at) return;
    // First answer after a reload only establishes where we are: the turn it
    // reports finished before this page existed.
    if (!lastDone) { lastDone = at; return; }
    if (at <= lastDone) return;
    lastDone = at;
    // Looking at the terminal already shows it.
    if (!document.hidden) return;
    if (!notifyOn || !canNotify || Notification.permission !== 'granted') return;
    try {
      // One tag, so a desk left alone all afternoon leaves one notification
      // rather than a column of them.
      new Notification('claude-desk', { body: 'Claude finished.', tag: 'claude-desk-done' });
    } catch (_) { /* some browsers only allow this from a service worker */ }
  }

  // ── Sessions sheet ────────────────────────────────────
  // Resume is typed into the tmux pane by upload.py rather than sent down
  // this websocket: keys on the socket land wherever the pane's focus is, and
  // that is usually Claude Code's prompt box, where `claude --resume <uuid>`
  // would be read as a message instead of run.
  const sessionsSheet = document.getElementById('sessions');
  const sessionList = document.getElementById('session-list');
  const sessionEmpty = document.getElementById('session-empty');
  const sessionsSub = document.getElementById('sessions-sub');
  const quitBtn = document.getElementById('sessions-quit');
  const quitLabel = document.getElementById('quit-label');

  function fmtWhen(epoch) {
    const d = new Date(epoch * 1000);
    if (isNaN(d)) return '';
    const mins = (Date.now() - d) / 60000;
    if (mins < 60) return Math.max(1, Math.round(mins)) + ' min ago';
    if (d.toDateString() === new Date().toDateString()) {
      return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    }
    return d.toLocaleDateString([], { day: 'numeric', month: 'short' })
      + ' ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }

  function renderSessions(data) {
    const list = (data && data.sessions) || [];
    const pane = data && data.pane;
    // No pane at all means tmux has not been spawned yet: ttyd starts it when
    // a browser attaches, so a sheet opened the moment a home-screen PWA wakes
    // can get here before the handshake. Resuming would answer 503 and read as
    // broken, so the rows wait for the socket instead (see connect()).
    const ready = !!pane;
    // A shell means the prompt is free. Anything else (`claude`, `mimo`, an
    // editor, a pager) has the keyboard and must be quit first.
    //
    // None of which applies in chat: resuming there restarts the chat's own
    // agent and never touches the pane, so gating on the terminal would have
    // left every row greyed out for the usual case of Claude Code sitting
    // open in the other view.
    const free = chatOn || (ready && ['bash', 'sh', 'zsh', '-bash', 'dash'].includes(pane));
    sessionsSheet.classList.toggle('blocked', !free);
    sessionsSub.classList.toggle('blocked', !free);
    sessionsSub.innerHTML = chatOn
      ? 'past work in <code>/work</code> · tap to open it here'
      : !ready
        ? 'waiting for the terminal…'
        : free
          ? 'past work in <code>/work</code> · tap to resume'
          : 'the terminal is busy — quit it to use this list';
    // Without a way out from here the sheet is a trap in the terminal view:
    // "New session" leaves Claude Code sitting in the pane, and every later
    // visit is refused until someone quits it by typing in the terminal — the
    // thing this avoids.
    quitBtn.hidden = chatOn || free || !ready;
    quitBtn.disabled = false;
    quitLabel.textContent = pane ? 'Quit “' + pane + '”' : 'Quit it';

    sessionList.innerHTML = '';
    sessionEmpty.hidden = list.length > 0;
    sessionEmpty.innerHTML = 'No past sessions in <code>/work</code> yet.';
    for (const s of list) {
      const li = document.createElement('li');
      const row = document.createElement('button');
      row.className = 'session-row';
      row.type = 'button';
      row.innerHTML = '<div class="s-title"></div><div class="s-meta"></div>';
      const title = row.querySelector('.s-title');
      title.textContent = s.title || 'untitled';
      if (!s.title) title.classList.add('untitled');
      row.querySelector('.s-meta').innerHTML = fmtWhen(s.mtime)
        + ' · <span class="s-id">' + s.id.slice(0, 8) + '</span>';
      row.addEventListener('click', () => resume(s.id, row));
      li.appendChild(row);
      sessionList.appendChild(li);
    }
  }

  async function post(path, body) {
    const r = await fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: body ? JSON.stringify(body) : undefined,
    });
    return { ok: r.ok, text: (await r.text()).trim() };
  }

  function sheetError(text) {
    sessionsSub.classList.add('blocked');
    sessionsSub.textContent = text.startsWith('busy:')
      ? '“' + text.slice(5) + '” is running in the terminal — quit it first'
      : 'could not reach the terminal (' + (text || 'no answer') + ')';
  }

  async function resume(id, row) {
    if (DEMO) { closeSessions(); return; }
    row.disabled = true;
    // The sheet opens over whichever view is showing, so it resumes into that
    // one. Tapping a past conversation while looking at chat used to bring it
    // back in the *terminal*, which reads as the list not working.
    const into = chatOn ? resumeInChat : resumeInTerminal;
    try {
      const r = await into(id);
      if (r.ok) { closeSessions(); return; }
      sheetError(r.text);
    } catch (_) {
      sheetError('');
    }
    row.disabled = false;
  }
  function resumeInTerminal(id) { return post('api/resume', { id: id }); }
  function resumeInChat(id) { return post('chat/new', { id: id }); }

  // The agent replays nothing on --resume — it just knows the context — so
  // the earlier messages come from the transcript Claude Code wrote. Same
  // path repaints the view after a plain reload.
  async function paintHistory(id) {
    if (!id || DEMO) return;
    let items = [];
    try {
      const r = await fetch('chat/history?id=' + encodeURIComponent(id), { cache: 'no-store' });
      if (r.ok) items = (await r.json()).items || [];
    } catch (_) { return; }
    if (!items.length) return;
    chatLog.querySelector('.chat-empty')?.remove();
    for (const item of items) {
      if (item.k === 'you') {
        add(el('div', 'bubble me', item.text));
      } else if (item.k === 'claude') {
        const box = add(el('div', 'bubble them'));
        box.dataset.raw = item.text;
        markdown(box, item.text);
      } else if (item.k === 'tool') {
        onChatEvent({ t: 'tool', name: item.name, detail: item.detail });
      } else if (item.k === 'tool_done') {
        onChatEvent({ t: 'tool_done', ok: item.ok });
      }
    }
    bubble = null;
    chatLog.scrollTop = chatLog.scrollHeight;
  }

  quitBtn.addEventListener('click', async () => {
    quitBtn.disabled = true;
    quitLabel.textContent = 'Quitting…';
    try {
      const r = await post('api/quit');
      if (!r.ok) sheetError(r.text);
    } catch (_) {
      sheetError('');
    }
    // Either way the list is redrawn from what the pane actually reports —
    // guessing at the outcome is how a sheet ends up lying about its state.
    loadSessions();
  });

  document.getElementById('new-session').addEventListener('click', async () => {
    if (DEMO) { closeSessions(); return; }
    try {
      // Same rule as the rows: the sheet acts on the view it opened over.
      const r = chatOn ? await post('chat/new', {}) : await post('api/new');
      if (r.ok) { closeSessions(); return; }
      sheetError(r.text);
    } catch (_) { sheetError(''); }
  });

  async function loadSessions() {
    if (DEMO) {
      renderSessions({ pane: 'bash', sessions: [
        { id: '3bb7d4ca-216a-4893-a150-b2b9aea26b72', title: 'ทำ slide สรุปยอดขาย Q3 จาก in/sales-q3.xlsx 8 หน้า', mtime: Date.now() / 1000 - 900 },
        { id: '7508d99d-ae2d-45c6-9139-269008b26b5e', title: 'แปลง proposal.docx เป็น pdf แล้วใส่หน้าปก', mtime: Date.now() / 1000 - 7200 },
        { id: 'f2cae4c0-0119-4fde-901b-52ff2f7a163a', title: '', mtime: Date.now() / 1000 - 180000 },
      ] });
      return;
    }
    try {
      const r = await fetch('api/sessions', { cache: 'no-store' });
      renderSessions(r.ok ? await r.json() : {});
    } catch (_) {
      renderSessions({});
    }
  }

  function openSessions() {
    closeDrawer();
    document.body.classList.add('sessions-open');
    sessionsSheet.setAttribute('aria-hidden', 'false');
    loadSessions();
  }
  function closeSessions() {
    document.body.classList.remove('sessions-open');
    sessionsSheet.setAttribute('aria-hidden', 'true');
  }
  document.getElementById('sessions-btn').addEventListener('click', openSessions);
  document.getElementById('sessions-close').addEventListener('click', closeSessions);

  // ── Chat view ─────────────────────────────────────────
  // A second view over the same desk, not a wrapper around the terminal: it
  // drives its own Claude Code through chat.py over a documented protocol.
  // Scraping ANSI out of xterm to build bubbles would break every time Claude
  // Code changed how it draws — and would have put the terminal, the thing
  // that works, at risk of a UI change.
  //
  // It exists because a terminal wraps hard at COLUMNS: on a phone that is
  // about 40 columns of Thai, and a long answer is painful to read. Bubbles
  // reflow, and the text is selectable without going near OSC 52.
  const chat = document.getElementById('chat');
  const chatLog = document.getElementById('chat-log');
  const chatForm = document.getElementById('chat-form');
  const chatInput = document.getElementById('chat-input');
  const chatNote = document.getElementById('chat-note');
  const chatState = document.getElementById('chat-state');
  const viewTermBtn = document.getElementById('view-term');
  const viewChatBtn = document.getElementById('view-chat');

  let chatOn = false;
  let chatStream = null;
  let chatBusy = false;
  let bubble = null;        // the assistant bubble currently filling in
  let typing = null;

  function el(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }
  function atBottom() {
    return chatLog.scrollHeight - chatLog.scrollTop - chatLog.clientHeight < 60;
  }
  function follow(was) {
    // Only chase the bottom if that is where the reader already was —
    // yanking the view down while they scroll back through an answer is the
    // single most annoying thing a chat window can do.
    if (was) chatLog.scrollTop = chatLog.scrollHeight;
  }
  function add(node) {
    const was = atBottom();
    if (typing) chatLog.insertBefore(node, typing); else chatLog.appendChild(node);
    follow(was);
    return node;
  }

  // Just enough markdown for what an agent writes: fenced blocks, inline
  // code. Everything else stays literal — a full parser is a dependency and
  // an escaping bug, and the text is already pre-wrapped by CSS.
  function markdown(target, text) {
    target.textContent = '';
    const parts = text.split(/```/);
    parts.forEach((part, i) => {
      if (i % 2) {
        const pre = el('pre');
        // First line of a fence is the language, not content.
        pre.appendChild(el('code', null, part.replace(/^[^\n]*\n/, '')));
        target.appendChild(pre);
        return;
      }
      part.split(/(`[^`\n]+`)/).forEach((piece) => {
        if (piece.startsWith('`') && piece.endsWith('`') && piece.length > 2) {
          target.appendChild(el('code', null, piece.slice(1, -1)));
        } else if (piece) {
          target.appendChild(document.createTextNode(piece));
        }
      });
    });
  }

  // What the turn cost, under the answer. `total` is the session running
  // total the agent reports — measured as never decreasing across turns — so
  // what *this* turn cost is the difference, which the backend works out.
  let spent = 0;
  function money(n) {
    if (typeof n !== 'number') return '';
    return n < 0.01 ? '<$0.01' : '$' + n.toFixed(2);
  }
  function tokens(n) {
    if (!n) return '';
    return n >= 1000 ? (n / 1000).toFixed(n >= 10000 ? 0 : 1) + 'k' : String(n);
  }
  function addMeter(ev) {
    const bits = [];
    if (ev.context) bits.push(tokens(ev.context) + ' ctx');
    if (ev.out) bits.push(tokens(ev.out) + ' out');
    if (money(ev.cost)) bits.push(money(ev.cost));
    if (ev.ms) bits.push(ev.ms >= 60000 ? Math.round(ev.ms / 60000) + 'm' : Math.round(ev.ms / 1000) + 's');
    if (!bits.length) return;
    add(el('div', 'meter', bits.join(' · ')));
  }
  function paintSpent() {
    const label = document.getElementById('chat-spent');
    if (!label) return;
    label.textContent = spent ? money(spent) + ' this session' : '';
  }

  function showTyping(on) {
    if (on && !typing) {
      typing = el('div', 'typing');
      typing.innerHTML = '<i></i><i></i><i></i>';
      const was = atBottom();
      chatLog.appendChild(typing);
      follow(was);
    } else if (!on && typing) {
      typing.remove();
      typing = null;
    }
  }

  function setChatBusy(on) {
    chatBusy = on;
    document.body.classList.toggle('chat-busy', on);
    showTyping(on && !bubble);
  }

  function note(text) {
    chatNote.textContent = text || '';
    chatNote.hidden = !text;
  }

  function emptyState() {
    if (chatLog.children.length) return;
    const box = el('div', 'chat-empty');
    box.innerHTML = 'Ask for a document.<br>Files live in <code>/work/in</code> and <code>/work/out</code>, same as the terminal.';
    chatLog.appendChild(box);
  }

  function clearLog() {
    chatLog.innerHTML = '';
    bubble = null;
    typing = null;
    emptyState();
  }

  function onChatEvent(ev) {
    if (ev.t === 'busy') { setChatBusy(ev.on); return; }
    if (ev.t === 'reset') {
      // The stream is the single place a reset is acted on, so a resume
      // repaints once — whichever page asked for it, and any other that has
      // the view open. Painting in the caller too would double the history.
      clearLog();
      note('');
      spent = 0;
      paintSpent();
      if (ev.session_id) paintHistory(ev.session_id);
      return;
    }
    if (ev.t === 'gone') {
      setChatBusy(false);
      if (bubble) bubble = null;
      return;
    }
    if (ev.t === 'say_start') {
      showTyping(false);
      const first = chatLog.querySelector('.chat-empty');
      if (first) first.remove();
      bubble = add(el('div', 'bubble them'));
      bubble.dataset.raw = '';
      return;
    }
    if (ev.t === 'say') {
      if (!bubble) { onChatEvent({ t: 'say_start' }); }
      const was = atBottom();
      bubble.dataset.raw += ev.text;
      markdown(bubble, bubble.dataset.raw);
      follow(was);
      return;
    }
    if (ev.t === 'say_end') { bubble = null; return; }
    if (ev.t === 'tool') {
      showTyping(false);
      const first = chatLog.querySelector('.chat-empty');
      if (first) first.remove();
      const pill = add(el('div', 'pill'));
      pill.appendChild(el('span', 'p-dot'));
      pill.appendChild(el('span', 'p-name', ev.name));
      pill.appendChild(el('span', 'p-detail', ev.detail || ''));
      pill.dataset.open = '1';
      return;
    }
    if (ev.t === 'tool_done') {
      // Pills finish in order, so the oldest unfinished one is this result's.
      const open = chatLog.querySelector('.pill[data-open]');
      if (open) {
        delete open.dataset.open;
        open.classList.add(ev.ok ? 'ok' : 'bad');
      }
      showTyping(chatBusy && !bubble);
      return;
    }
    if (ev.t === 'turn') {
      bubble = null;
      setChatBusy(false);
      if (ev.status === 'stopped') note('หยุดแล้ว');
      else if (ev.status === 'error') {
        const box = add(el('div', 'bubble them err'));
        box.textContent = ev.text || 'ทำงานไม่สำเร็จ';
      }
      addMeter(ev);
      if (typeof ev.total === 'number') spent = ev.total;
      paintSpent();
    }
  }

  function openChatStream() {
    if (chatStream || DEMO) return;
    chatStream = new EventSource('chat/events');
    chatStream.onmessage = (e) => {
      try { onChatEvent(JSON.parse(e.data)); } catch (_) { /* ignore a bad frame */ }
    };
    // EventSource reconnects on its own; nothing to do but stop pretending
    // the desk is reachable while it is down.
    chatStream.onerror = () => { showTyping(false); };
  }

  async function chatPost(path, body) {
    const r = await fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: body ? JSON.stringify(body) : undefined,
    });
    return { ok: r.ok, text: (await r.text()).trim() };
  }

  async function sendChat() {
    const text = chatInput.value.trim();
    if (!text) return;
    const first = chatLog.querySelector('.chat-empty');
    if (first) first.remove();
    add(el('div', 'bubble me', text));
    chatInput.value = '';
    sizeInput();
    note('');
    setChatBusy(true);            // optimistic: the stream confirms it
    try {
      const r = await chatPost('chat/send', { text: text });
      if (!r.ok) { setChatBusy(false); note(r.text || 'ส่งไม่สำเร็จ'); }
    } catch (_) {
      setChatBusy(false);
      note('ต่อเดสก์ไม่ได้');
    }
  }

  chatForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (chatBusy) {
      try { await chatPost('chat/stop'); } catch (_) { /* the stream will say */ }
      return;
    }
    sendChat();
  });

  document.getElementById('chat-new').addEventListener('click', async () => {
    try { await chatPost('chat/new', {}); } catch (_) { /* nothing to undo */ }
    clearLog();
    spent = 0;
    paintSpent();
  });

  // Enter sends, Shift+Enter is a newline — on a phone the key says "send"
  // (enterkeyhint) and there is no Shift to hold anyway.
  chatInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      if (!chatBusy) sendChat();
    }
  });
  function sizeInput() {
    chatInput.style.height = 'auto';
    chatInput.style.height = Math.min(chatInput.scrollHeight, 140) + 'px';
  }
  chatInput.addEventListener('input', sizeInput);

  async function refreshChatState() {
    if (DEMO) return;
    try {
      const r = await fetch('api/sessions', { cache: 'no-store' });
      if (!r.ok) return;
      const pane = (await r.json()).pane;
      const busyTerminal = pane && !['bash', 'sh', 'zsh', '-bash', 'dash'].includes(pane);
      // Two agents in /work at once is allowed now — it is not prevented,
      // because the pane reports `claude` whenever a session is merely open
      // and refusing on that would block the normal case. Saying so is the
      // honest surface.
      chatState.textContent = busyTerminal
        ? '“' + pane + '” is open in the terminal too — two agents in /work'
        : 'this chat runs its own Claude Code in /work';
      chatState.classList.toggle('warn', !!busyTerminal);
    } catch (_) { /* leave the last line up */ }
  }

  function setView(which) {
    chatOn = which === 'chat';
    document.body.classList.toggle('chat-view', chatOn);
    chat.hidden = !chatOn;
    viewChatBtn.classList.toggle('on', chatOn);
    viewTermBtn.classList.toggle('on', !chatOn);
    try { localStorage.setItem(VIEW_KEY, which); } catch (_) { /* not persisted */ }
    if (chatOn) {
      emptyState();
      openChatStream();
      refreshChatState();
      // A page that comes back to a turn already in progress should show the
      // stop button, not an idle send button that would be refused anyway.
      if (!DEMO) {
        fetch('chat/state', { cache: 'no-store' })
          .then((r) => (r.ok ? r.json() : null))
          .then((s) => {
            if (!s) return;
            setChatBusy(!!s.busy);
            spent = s.spent || 0;
            paintSpent();
            // Nothing is kept in memory on the server; the conversation is
            // repainted from the transcript Claude Code writes. Only when the
            // log is empty — switching views mid-answer must not duplicate it.
            if (s.session_id && !chatLog.querySelector('.bubble')) {
              paintHistory(s.session_id);
            }
          })
          .catch(() => {});
      }
      if (!IS_MOBILE) chatInput.focus();
    } else {
      requestAnimationFrame(refit);
      if (!IS_MOBILE) term.focus();
    }
  }
  const VIEW_KEY = 'claude-desk.view';
  viewTermBtn.addEventListener('click', () => setView('terminal'));
  viewChatBtn.addEventListener('click', () => setView('chat'));

  // ── Go ────────────────────────────────────────────────
  if (DEMO) {
    setState('connected', 'live');
    term.writeln('\x1b[38;5;214m▌\x1b[0m claude-desk — 2.1.272 (Claude Code)');
    term.writeln('\x1b[38;5;245m  in/  ← drop source files here (DS File)');
    term.writeln('  out/ → finished pptx/docx/xlsx land here');
    term.writeln('  claude | r = resume | m = mimo agent');
    term.writeln('  ask <question> = one answer\x1b[0m');
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
    if (PARAMS.has('sessions')) openSessions();
    if (PARAMS.has('chat')) { setView('chat'); demoChat(); }
  } else {
    connect();
  }

  // Whichever view was last used comes back on the next open: the desk is a
  // tool you return to mid-job, and landing on the wrong half of it costs a
  // tap every single time. With no stored choice it opens on chat — that is
  // what the desk is for from a phone, and the terminal is one tap away.
  if (!DEMO) {
    let saved = null;
    try { saved = localStorage.getItem(VIEW_KEY); } catch (_) { /* no storage */ }
    if (saved !== 'terminal') setView('chat');
  }

  function demoChat() {
    clearLog();
    chatLog.querySelector('.chat-empty')?.remove();
    chatState.textContent = 'this chat runs its own Claude Code in /work';
    add(el('div', 'bubble me', 'ทำ slide สรุปยอดขาย Q3 จาก in/sales-q3.xlsx 8 หน้า'));
    onChatEvent({ t: 'tool', name: 'Read', detail: '/work/in/sales-q3.xlsx' });
    onChatEvent({ t: 'tool_done', ok: true });
    onChatEvent({ t: 'tool', name: 'Bash', detail: 'node build-deck.js' });
    onChatEvent({ t: 'tool_done', ok: true });
    onChatEvent({ t: 'say_start' });
    onChatEvent({ t: 'say', text: 'เสร็จแล้วครับ — 8 สไลด์ อยู่ที่ `out/2026-09-15-q3-review.pptx`\n\nสรุปที่ใส่ไว้:\n- ยอดรวม Q3 โตจาก Q2 12%\n- ภาคเหนือเป็นตัวฉุด ติดลบ 4%\n- ฟอนต์ไทยเรนเดอร์ถูกต้องทุกหน้า ตรวจจากภาพแล้ว' });
    onChatEvent({ t: 'say_end' });
    onChatEvent({ t: 'turn', status: 'done', text: '', cost: 0.037, total: 0.11, context: 24100, out: 1180, ms: 48000 });
  }

  window._term = term;
})();
