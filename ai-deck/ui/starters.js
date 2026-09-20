// Editable starter templates, shared by providers within this browser.
(function () {
  'use strict';
  const KEY = 'ai-deck.starter-prompts.v1';
  const IDS = ['presentation', 'document', 'data'];
  const MAX_LENGTH = 16000;

  function savedPrompts() {
    try {
      const value = JSON.parse(localStorage.getItem(KEY));
      return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
    } catch (_) { return {}; }
  }

  function mount(box, usePrompt) {
    const buttons = Array.from(box.querySelectorAll('[data-prompt]'));
    const saved = savedPrompts();
    buttons.forEach((button, index) => {
      const id = IDS[index];
      if (!id) return;
      const original = button.dataset.prompt;
      if (typeof saved[id] === 'string' && saved[id].trim() && saved[id].length <= MAX_LENGTH) {
        button.dataset.prompt = saved[id];
      }
      button.classList.add('starter-use');
      button.dataset.starterId = id;
      const card = document.createElement('div');
      card.className = 'starter-card';
      button.replaceWith(card);
      card.append(button);
      const edit = document.createElement('button');
      edit.type = 'button';
      edit.className = 'starter-edit';
      edit.dataset.editPrompt = id;
      edit.textContent = 'Edit prompt';
      const title = button.querySelector('strong').textContent;
      edit.setAttribute('aria-label', 'Edit prompt: ' + title);
      card.append(edit);
      button.addEventListener('click', () => usePrompt(button.dataset.prompt));
      edit.addEventListener('click', () => openEditor({button, edit, id, title, original}));
    });
  }

  function openEditor({button, edit, id, title, original}) {
    if (document.getElementById('prompt-editor')) return;
    const dialog = document.createElement('dialog');
    dialog.id = 'prompt-editor';
    dialog.className = 'prompt-editor';
    dialog.setAttribute('aria-labelledby', 'prompt-editor-title');
    dialog.setAttribute('aria-describedby', 'prompt-editor-help');
    dialog.innerHTML = '<form>'
      + '<h2 id="prompt-editor-title"></h2>'
      + '<p id="prompt-editor-help">Save a prompt for this card in this browser. Works with Claude and Codex.</p>'
      + '<label for="prompt-editor-text">Prompt</label>'
      + '<textarea id="prompt-editor-text" rows="8" maxlength="16000" required autofocus></textarea>'
      + '<p id="prompt-editor-error" role="alert" hidden></p>'
      + '<div class="prompt-editor-actions"><button type="button" data-prompt-reset>Restore default</button>'
      + '<button type="button" data-prompt-cancel>Cancel</button>'
      + '<button type="submit" class="prompt-save">Save prompt</button></div></form>';
    dialog.querySelector('h2').textContent = 'Edit prompt · ' + title;
    const text = dialog.querySelector('textarea');
    text.value = button.dataset.prompt;
    const error = dialog.querySelector('[role="alert"]');
    const close = () => {
      dialog.close();
      dialog.remove();
      if (edit.isConnected) edit.focus();
    };
    dialog.addEventListener('cancel', event => {
      event.preventDefault();
      close();
    });
    dialog.querySelector('[data-prompt-cancel]').addEventListener('click', close);
    dialog.querySelector('[data-prompt-reset]').addEventListener('click', () => {
      text.value = original;
      error.hidden = true;
      text.focus();
    });
    dialog.querySelector('form').addEventListener('submit', event => {
      event.preventDefault();
      if (!text.value.trim() || text.value.length > MAX_LENGTH) {
        error.textContent = 'Enter a prompt between 1 and 16,000 characters.';
        error.hidden = false;
        text.focus();
        return;
      }
      const saved = savedPrompts();
      if (text.value === original) delete saved[id];
      else saved[id] = text.value;
      try { localStorage.setItem(KEY, JSON.stringify(saved)); }
      catch (_) {
        error.textContent = 'Could not save in this browser. Your edits are still here; copy them before closing.';
        error.hidden = false;
        return;
      }
      button.dataset.prompt = text.value;
      close();
    });
    document.body.append(dialog);
    dialog.showModal();
  }

  window.DeskStarters = {mount};
})();
