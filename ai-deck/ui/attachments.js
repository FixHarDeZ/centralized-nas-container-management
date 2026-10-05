/* Browser file objects stay here; the chat request carries only server-issued IDs. */
(function () {
  'use strict';
  // The extension travels in X-Upload-Ext, not the URL; upload.py and
  // chat_attachments.py put it back, so the file lands under its real name
  // and nothing in between can route or filter on it. Same shape rule as
  // their EXT; anything else (no dot, leading dot, odd extension) goes as
  // the whole name. Shared with the drawer in app.js.
  window.DeskUploadTarget = function (name) {
    const dot = name.lastIndexOf('.');
    if (dot <= 0 || !/^\.[^./\\\x00-\x1f\x7f]{1,15}$/.test(name.slice(dot))) {
      return {path: encodeURIComponent(name), headers: {}};
    }
    return {
      path: encodeURIComponent(name.slice(0, dot)),
      headers: {'X-Upload-Ext': encodeURIComponent(name.slice(dot))},
    };
  };
  window.DeskAttachments = function ({enabled, url, note}) {
    const button = document.getElementById('chat-attach');
    const picker = document.getElementById('chat-files');
    const list = document.getElementById('chat-attachments');
    const form = document.getElementById('chat-form');
    const input = document.getElementById('chat-input');
    const maxBytes = 20 * 1024 * 1024, maxFiles = 10;
    let items = [], locked = false;
    button.hidden = !enabled;

    function render() {
      list.replaceChildren();
      list.hidden = !items.length;
      button.disabled = locked;
      for (const item of items) {
        const chip = document.createElement('div');
        chip.className = 'chat-attachment';
        if (item.preview) {
          const image = document.createElement('img');
          image.src = item.preview; image.alt = item.name;
          chip.append(image);
        }
        const label = document.createElement('span');
        label.className = 'attachment-label';
        const name = document.createElement('strong'); name.textContent = item.name;
        const status = document.createElement('small');
        status.textContent = item.error || (item.id ? 'Ready' : 'Uploading…');
        label.append(name, status); chip.append(label);
        if (item.error) {
          const retry = document.createElement('button');
          retry.type = 'button'; retry.textContent = 'Retry'; retry.disabled = locked;
          retry.setAttribute('aria-label', 'Retry ' + item.name);
          retry.addEventListener('click', () => upload(item)); chip.append(retry);
        }
        const remove = document.createElement('button');
        remove.type = 'button'; remove.textContent = '×'; remove.disabled = locked;
        remove.setAttribute('aria-label', 'Remove ' + item.name);
        remove.addEventListener('click', () => {
          dispose(item); items = items.filter(i => i !== item); render();
        });
        chip.append(remove); list.append(chip);
      }
    }

    function dispose(item) {
      if (item.controller) item.controller.abort();
      if (item.preview) URL.revokeObjectURL(item.preview);
    }
    async function upload(item) {
      item.error = ''; item.controller = new AbortController(); render();
      try {
        const target = window.DeskUploadTarget(item.name);
        const response = await fetch(url('chat/attachments/' + target.path), {
          method: 'PUT', body: item.file, signal: item.controller.signal,
          headers: {...target.headers, 'Content-Type': 'application/octet-stream'},
        });
        if (!response.ok) {
          // Proxy errors may be HTML; do not put a proxy page in a file chip.
          const reason = await response.text();
          throw Error(response.status === 413 ? 'Maximum file size is 20 MiB'
            : reason && !reason.includes('<') ? reason.slice(0, 160) : 'Upload failed; try again');
        }
        const result = await response.json();
        if (typeof result.id !== 'string' || !result.id) throw Error('Invalid upload response');
        item.id = result.id;
      } catch (error) {
        if (error.name !== 'AbortError') item.error = error.message || 'Upload failed; try again';
      } finally {
        if (items.includes(item)) render();
      }
    }
    function add(files) {
      if (!enabled || locked) return;
      note('');
      for (const file of files) {
        if (items.length >= maxFiles) { note('Attach at most 10 files per message.'); break; }
        if (file.size > maxBytes) { note(file.name + ': maximum file size is 20 MiB.'); continue; }
        const item = {name: file.name || 'clipboard.png', file, id: '', error: ''};
        if (/^image\/(png|jpeg|gif|webp)$/.test(file.type)) item.preview = URL.createObjectURL(file);
        items.push(item); upload(item);
      }
      render();
    }
    function clear() { items.forEach(dispose); items = []; render(); }
    if (enabled) {
      button.addEventListener('click', () => picker.click());
      picker.addEventListener('change', () => { add(Array.from(picker.files)); picker.value = ''; });
      input.addEventListener('paste', event => {
        const files = Array.from(event.clipboardData?.files || []);
        if (!files.length) return; // Preserve normal text paste and IME behavior.
        event.preventDefault(); add(files);
      });
      form.addEventListener('dragover', event => {
        if (!Array.from(event.dataTransfer?.types || []).includes('Files')) return;
        event.preventDefault(); form.classList.add('attachment-drop');
        event.dataTransfer.dropEffect = locked ? 'none' : 'copy';
      });
      form.addEventListener('dragleave', event => {
        if (!form.contains(event.relatedTarget)) form.classList.remove('attachment-drop');
      });
      form.addEventListener('drop', event => {
        form.classList.remove('attachment-drop');
        const files = Array.from(event.dataTransfer?.files || []);
        if (!files.length) return;
        event.preventDefault(); add(files);
      });
    }
    return {
      ready() {
        if (items.some(i => !i.id)) {
          note(items.some(i => i.error) ? 'Retry or remove failed uploads before sending.' : 'Wait for files to finish uploading.');
          return false;
        }
        return true;
      },
      snapshot: () => items.map(i => ({id: i.id, name: i.name})),
      lock(value) { locked = value; render(); },
      clear,
      restore(saved) {
        if (items.length) { note('Send or remove the current attachments before retrying this message.'); return false; }
        items = saved.map(i => ({...i})); render(); return true;
      },
    };
  };
})();
