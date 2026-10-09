// Progressive enhancements only: server-rendered records stay readable without JS.
(() => {
  'use strict';
  const root = document.documentElement;
  const readStorage = (kind, key) => {
    try { return window[kind].getItem(key); } catch (_) { return null; }
  };
  const saveStorage = (kind, key, value) => {
    try { window[kind].setItem(key, value); } catch (_) { /* Storage is optional. */ }
  };
  const themeButton = document.getElementById('theme');
  let explicitTheme = ['dark', 'light'].includes(readStorage('localStorage', 'theme'));
  const updateThemeLabel = () => {
    const label = root.dataset.theme === 'dark' ? 'ใช้ธีมสว่าง' : 'ใช้ธีมมืด';
    if (themeButton) {
      themeButton.setAttribute('aria-label', label);
      themeButton.title = label;
    }
  };
  if (themeButton) {
    themeButton.hidden = false;
    updateThemeLabel();
    themeButton.addEventListener('click', () => {
      root.dataset.theme = root.dataset.theme === 'dark' ? 'light' : 'dark';
      explicitTheme = true;
      saveStorage('localStorage', 'theme', root.dataset.theme);
      updateThemeLabel();
    });
    const preferredScheme = window.matchMedia?.('(prefers-color-scheme: light)');
    preferredScheme?.addEventListener?.('change', (event) => {
      if (!explicitTheme) {
        root.dataset.theme = event.matches ? 'light' : 'dark';
        updateThemeLabel();
      }
    });
  }

  const channelButtons = [...document.querySelectorAll('[data-channel]')];
  const panels = [...document.querySelectorAll('[data-channel-panel]')];
  const search = document.getElementById('search');
  const status = document.getElementById('status-filter');
  const count = document.getElementById('row-count');
  const noResults = document.getElementById('no-results');
  const reset = document.getElementById('reset-filters');
  if (channelButtons.length && search && status && count && noResults) {
    const rows = [...document.querySelectorAll('tr[data-locale][data-status]')];
    const remembered = readStorage('sessionStorage', 'shorts-channel');
    let selectedChannel = channelButtons.some((button) => button.dataset.channel === remembered)
      ? remembered : channelButtons[0].dataset.channel;
    const render = () => {
      const query = search.value.toLocaleLowerCase().trim();
      let matching = 0;
      let channelTotal = 0;
      for (const row of rows) {
        const inChannel = row.dataset.locale === selectedChannel;
        if (inChannel) channelTotal += 1;
        const matches = inChannel && (!status.value || row.dataset.status === status.value) &&
          (row.dataset.search || '').toLocaleLowerCase().includes(query);
        row.hidden = !matches;
        if (matches) matching += 1;
      }
      for (const panel of panels) panel.hidden = panel.dataset.channelPanel !== selectedChannel;
      for (const button of channelButtons) {
        const active = button.dataset.channel === selectedChannel;
        button.classList.toggle('active', active);
        button.setAttribute('aria-pressed', String(active));
      }
      noResults.hidden = matching !== 0 || rows.length === 0;
      count.textContent = `แสดง ${matching.toLocaleString()} จาก ${channelTotal.toLocaleString()} คลิป · ${selectedChannel.toUpperCase()}`;
    };
    for (const control of document.querySelectorAll('[data-library-controls]')) control.hidden = false;
    for (const button of channelButtons) {
      button.addEventListener('click', () => {
        selectedChannel = button.dataset.channel;
        saveStorage('sessionStorage', 'shorts-channel', selectedChannel);
        render();
      });
    }
    search.addEventListener('input', render);
    status.addEventListener('change', render);
    reset?.addEventListener('click', () => {
      search.value = '';
      status.value = '';
      render();
      search.focus();
    });
    render();
  }

  for (const button of document.querySelectorAll('[data-copy]')) {
    const source = document.getElementById(button.dataset.copy);
    const feedback = document.getElementById(button.dataset.feedback);
    if (!source || !feedback) continue;
    button.hidden = false;
    button.addEventListener('click', async () => {
      button.disabled = true;
      try {
        if (!navigator.clipboard?.writeText) throw new Error('Clipboard unavailable');
        await navigator.clipboard.writeText(source.innerText);
        feedback.textContent = 'คัดลอกสคริปต์แล้ว';
      } catch (_) {
        feedback.textContent = 'คัดลอกอัตโนมัติไม่ได้ กรุณาเลือกข้อความสคริปต์แล้วคัดลอกด้วยตัวเอง';
      } finally {
        button.disabled = false;
      }
    });
  }
})();
