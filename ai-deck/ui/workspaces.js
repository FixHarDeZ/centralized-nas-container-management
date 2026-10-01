/* Project navigation is URL-scoped so reload/back/provider changes keep cwd. */
(function () {
  'use strict';
  const params = new URLSearchParams(location.search);
  const workspace = params.get('workspace') || '';
  const coding = !!workspace || params.get('coding') === '1';
  const demo = params.has('demo');
  window.DeskWorkspace = {
    id: workspace, coding,
    url(path) {
      if (!coding) return path;
      if (path.startsWith('chat/') || path.startsWith('api/')) {
        return 'code/' + path + (path.includes('?') ? '&' : '?') + 'workspace=' + encodeURIComponent(workspace);
      }
      return path;
    },
  };
  const select = document.getElementById('project-select');
  const panel = document.getElementById('project-dialog');
  const form = document.getElementById('project-form');
  const message = document.getElementById('project-message');
  const details = document.getElementById('project-details');
  const statusText = document.getElementById('project-status');
  const diff = document.getElementById('project-diff');
  let projects = [], current = null;
  const tabs = [...panel.querySelectorAll('[role="tab"]')];
  function showTab(tab) {
    tabs.forEach(item => {
      const active = item === tab;
      item.setAttribute('aria-selected', String(active));
      item.tabIndex = active ? 0 : -1;
      document.getElementById(item.getAttribute('aria-controls')).hidden = !active;
    });
  }
  tabs.forEach((tab, index) => {
    tab.addEventListener('click', () => showTab(tab));
    tab.addEventListener('keydown', event => {
      if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault();
      const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1
        : (index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
      showTab(tabs[next]);
      tabs[next].focus();
    });
  });

  function navigate(id, terminal = false) {
    window.dispatchEvent(new Event('desk:save-draft'));
    const url = new URL(location.href);
    url.searchParams.delete('workspace');
    url.searchParams.delete('coding');
    if (id) url.searchParams.set('workspace', id);
    if (terminal) url.searchParams.set('coding', '1');
    try { localStorage.setItem('claude-desk.view', terminal ? 'terminal' : 'chat'); } catch (_) {}
    location.assign(url);
  }
  async function request(path, body) {
    const response = await fetch(path, body ? {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body),
    } : {cache: 'no-store'});
    if (!response.ok) {
      const text = (await response.text()).trim();
      throw new Error(text && !text.startsWith('<') ? text.slice(0, 300)
        : response.status >= 500 ? 'Coding service is unavailable. Enable the coding worker and try again.' : 'Request failed');
    }
    return response.json();
  }
  const isBundle = item => item && item.source === 'bundle';
  function label(item) {
    if (isBundle(item)) return item.url.slice('local:'.length) + ' (local) · ' + item.branch;
    return item.url.replace('https://github.com/', '').replace(/\.git$/, '') + ' · ' + item.branch;
  }
  async function load() {
    try {
      const demoBundle = params.get('source') === 'bundle';
      projects = demo ? (workspace ? [{id: workspace, url: demoBundle ? 'local:demo-app' : 'https://github.com/example/project', source: demoBundle ? 'bundle' : 'github', branch: 'desk/' + workspace, path: '/workspaces/tasks/demo/' + workspace}] : []) : (await request('code/projects')).items;
      select.replaceChildren(new Option('Documents', ''));
      projects.forEach(item => select.add(new Option(label(item), item.id)));
      current = projects.find(item => item.id === workspace);
      if (workspace && !current) {
        select.add(new Option('Workspace unavailable', workspace));
        message.textContent = 'This workspace is missing or belongs to another user.';
      }
      select.value = workspace;
      details.hidden = !current;
      document.getElementById('project-connect').open = !current;
      showBundleTask(isBundle(current));
      const slugs = document.getElementById('bundle-slugs');
      slugs.replaceChildren(...[...new Set(projects.filter(isBundle).map(item => item.url.slice(6)))].map(slug => new Option(slug)));
      try {
        const pending = JSON.parse(sessionStorage.getItem('ai-deck.bundle-warnings') || 'null');
        if (pending && pending.id === workspace) {
          message.textContent = 'Imported. Files that may hold credentials: ' + pending.warnings.join(', ');
        }
        sessionStorage.removeItem('ai-deck.bundle-warnings');
      } catch (_) {}
    } catch (error) {
      message.textContent = error.message;
      if (workspace) {
        select.add(new Option('Workspace unavailable', workspace));
        select.value = workspace;
      }
    }
  }
  select.addEventListener('change', () => navigate(select.value));
  document.getElementById('project-manage').addEventListener('click', () => {
    showTab(tabs[0]);
    panel.showModal();
    if (current) refreshStatus();
  });
  // Signed-in gh account's repos; the URL field stays for anything else.
  const repoWrap = document.getElementById('project-repo-wrap');
  const repoSelect = document.getElementById('project-repo');
  const urlInput = document.getElementById('project-url');
  let reposLoaded = false;
  async function loadRepositories() {
    if (reposLoaded || demo) return;
    try {
      const data = await request('code/projects/repositories');
      if (!data.signed_in || !data.items.length) return;
      repoSelect.replaceChildren(new Option('Choose a repository…', ''));
      data.items.forEach(item => repoSelect.add(new Option(item.name + (item.private ? ' · private' : ''), item.url)));
      repoSelect.value = data.items.some(item => item.url === urlInput.value.trim()) ? urlInput.value.trim() : '';
      repoWrap.hidden = false;
      reposLoaded = true;
    } catch (_) { /* Manual URL entry still works. */ }
  }
  repoSelect.addEventListener('change', () => { if (repoSelect.value) urlInput.value = repoSelect.value; });
  urlInput.addEventListener('input', () => { if (repoSelect.value !== urlInput.value.trim()) repoSelect.value = ''; });
  document.getElementById('project-manage').addEventListener('click', loadRepositories);
  document.getElementById('project-close').addEventListener('click', () => panel.close());
  document.getElementById('coding-terminal').addEventListener('click', () => navigate(workspace, true));
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const button = document.getElementById('project-create');
    button.disabled = true;
    message.textContent = 'Cloning repository and preparing a new task branch…';
    try {
      const item = await request('code/projects', {
        url: document.getElementById('project-url').value.trim(),
        branch: document.getElementById('project-base').value.trim(),
      });
      navigate(item.id);
    } catch (error) { message.textContent = error.message; }
    finally { button.disabled = false; }
  });
  // Local bundle: repositories the worker cannot reach (behind a VPN).
  // The browser carries git bundles both ways; desk-sync does it from a shell.
  const githubForm = form, bundleForm = document.getElementById('bundle-form');
  const sourceHint = document.getElementById('project-source-hint');
  function showSource(bundle) {
    document.getElementById('source-github').setAttribute('aria-pressed', String(!bundle));
    document.getElementById('source-bundle').setAttribute('aria-pressed', String(bundle));
    githubForm.hidden = bundle;
    bundleForm.hidden = !bundle;
    sourceHint.textContent = bundle
      ? 'Upload a git bundle from your computer (or run desk-sync up). Each task gets its own branch.'
      : 'Start from GitHub. Each task gets its own branch.';
  }
  document.getElementById('source-github').addEventListener('click', () => showSource(false));
  document.getElementById('source-bundle').addEventListener('click', () => showSource(true));
  function showBundleTask(bundle) {
    document.getElementById('bundle-actions').hidden = !bundle;
    document.getElementById('project-push').hidden = bundle;
    document.getElementById('deploy-tab').hidden = bundle;
  }
  function megabytes(bytes) { return (bytes / 1048576).toFixed(1) + ' MB'; }
  async function putBundle(query, file) {
    const response = await fetch('code/projects/bundle?' + query, {method: 'PUT', body: file});
    const text = (await response.text()).trim();
    if (!response.ok) throw new Error(text && !text.startsWith('<') ? text.slice(0, 300) : 'Upload failed (' + response.status + ')');
    return JSON.parse(text);
  }
  bundleForm.addEventListener('submit', async event => {
    event.preventDefault();
    const file = document.getElementById('bundle-file').files[0];
    if (!file) return;
    const button = document.getElementById('bundle-create');
    button.disabled = true;
    message.textContent = 'Uploading ' + megabytes(file.size) + ' and preparing a new task branch…';
    const query = new URLSearchParams({slug: document.getElementById('bundle-slug').value.trim()});
    for (const [key, id] of [['branch', 'bundle-base'], ['name', 'bundle-name'], ['email', 'bundle-email']]) {
      const value = document.getElementById(id).value.trim();
      if (value) query.set(key, value);
    }
    try {
      const item = await putBundle(query.toString(), file);
      if (item.warnings && item.warnings.length) {
        try { sessionStorage.setItem('ai-deck.bundle-warnings', JSON.stringify({id: item.id, warnings: item.warnings})); } catch (_) {}
      }
      navigate(item.id);
    } catch (error) { message.textContent = error.message; }
    finally { button.disabled = false; }
  });
  document.getElementById('bundle-update').addEventListener('change', async event => {
    const file = event.target.files[0];
    if (!file) return;
    statusText.textContent = 'Uploading update (' + megabytes(file.size) + ')…';
    try {
      const data = await putBundle('workspace=' + encodeURIComponent(workspace), file);
      statusText.textContent = 'Updated origin/' + data.updated.join(', origin/') + '. Ask the agent to rebase onto it if needed.';
    } catch (error) { statusText.textContent = error.message; }
    event.target.value = '';
  });
  // 409 with uncommitted files arms "Download commits only" (force=1).
  const downloadButton = document.getElementById('bundle-download');
  let downloadForce = false;
  downloadButton.addEventListener('click', async () => {
    downloadButton.disabled = true;
    try {
      const response = await fetch('code/projects/export?workspace=' + encodeURIComponent(workspace) + (downloadForce ? '&force=1' : ''), {cache: 'no-store'});
      if (!response.ok) {
        const text = (await response.text()).trim().slice(0, 300);
        if (response.status === 409 && text.includes('uncommitted') && !downloadForce) {
          downloadForce = true;
          downloadButton.textContent = 'Download commits only';
        }
        throw new Error(text || 'Download failed');
      }
      const disposition = response.headers.get('Content-Disposition') || '';
      const name = (disposition.match(/filename="([^"]+)"/) || [])[1] || 'changes.bundle';
      const link = document.createElement('a');
      link.href = URL.createObjectURL(await response.blob());
      link.download = name;
      document.body.append(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(link.href), 60000);
      statusText.textContent = 'Downloaded ' + name + '. On your computer: desk-sync down ' + name;
      downloadForce = false;
      downloadButton.textContent = 'Download changes';
    } catch (error) { statusText.textContent = error.message; }
    finally { downloadButton.disabled = false; }
  });
  async function refreshStatus() {
    statusText.textContent = 'Reading Git status…';
    try {
      const data = await request('code/projects/status?workspace=' + encodeURIComponent(workspace));
      statusText.textContent = [data.branch, data.head, current?.path,
        typeof data.changes === 'string' ? data.changes || 'Working tree clean' : JSON.stringify(data.changes)].filter(Boolean).join('\n');
      diff.textContent = data.diff || 'No tracked diff. New files appear in Git status above.';
      document.getElementById('deploy-sha').value = data.head || '';
    } catch (error) { statusText.textContent = error.message; }
  }
  document.getElementById('project-refresh').addEventListener('click', refreshStatus);
  // First tap arms, second deletes. The server refuses (409) while work is
  // uncommitted or unpushed; the button then re-arms as "Delete anyway".
  const deleteButton = document.getElementById('project-delete');
  let deleteArmed = false, deleteForce = false, deleteTimer = null;
  function resetDelete() {
    deleteArmed = deleteForce = false;
    deleteButton.classList.remove('armed');
    deleteButton.textContent = 'Delete task';
  }
  function armDelete(text) {
    deleteArmed = true;
    deleteButton.classList.add('armed');
    deleteButton.textContent = text;
    clearTimeout(deleteTimer);
    deleteTimer = setTimeout(resetDelete, 6000);
  }
  deleteButton.addEventListener('click', async () => {
    if (!deleteArmed) { armDelete('Tap again to delete this task'); return; }
    clearTimeout(deleteTimer);
    deleteButton.disabled = true;
    try {
      const response = await fetch('code/projects?workspace=' + encodeURIComponent(workspace) + (deleteForce ? '&force=1' : ''), {method: 'DELETE'});
      if (response.status === 409) {
        statusText.textContent = (await response.text()).trim().slice(0, 300);
        deleteForce = true;
        armDelete('Delete anyway (work is lost)');
        return;
      }
      if (!response.ok) throw new Error((await response.text()).trim().slice(0, 300) || 'Delete failed');
      navigate('');
    } catch (error) { statusText.textContent = error.message; resetDelete(); }
    finally { deleteButton.disabled = false; }
  });
  document.querySelectorAll('[data-code-prompt]').forEach(button => button.addEventListener('click', () => {
    const input = document.getElementById('chat-input');
    if (input.value.trim()) {
      message.textContent = 'Your message draft is still in the composer. Send or clear it first.';
      return;
    }
    input.value = button.dataset.codePrompt;
    input.dispatchEvent(new Event('input', {bubbles: true}));
    document.getElementById('view-chat').click();
    panel.close();
    input.focus();
  }));

  const deployMessage = document.getElementById('deploy-message');
  const deployProfiles = document.getElementById('deploy-profile');
  const deployButton = document.getElementById('deploy-submit');
  let hasDeployProfiles = false;
  let poll = null;
  async function loadDeploy() {
    hasDeployProfiles = false;
    deployButton.disabled = true;
    try {
      const data = await request('deploy/profiles');
      deployProfiles.replaceChildren(new Option('Select deployment', ''));
      data.items.forEach(item => deployProfiles.add(new Option(item.id, item.id)));
      hasDeployProfiles = data.items.length > 0;
      deployButton.disabled = !hasDeployProfiles;
      deployMessage.textContent = data.items.length ? 'Deploy runs separately from your coding workspace.' : 'No deployment profiles are configured for your account.';
    } catch (_) { deployMessage.textContent = 'Deployment runner is not configured or unavailable.'; }
  }
  async function pollJob(id) {
    try {
      const job = await request('deploy/jobs/' + encodeURIComponent(id));
      deployMessage.textContent = job.status + '\n' + (job.log || '');
      if (['queued', 'running'].includes(job.status)) poll = setTimeout(() => pollJob(id), 2500);
      else try { sessionStorage.removeItem('ai-deck.deploy-job'); } catch (_) {}
    } catch (_) {
      deployMessage.textContent = 'Could not read deployment status. Reopen Projects to retry.';
    }
  }
  document.getElementById('deploy-form').addEventListener('submit', async event => {
    event.preventDefault();
    const button = document.getElementById('deploy-submit');
    button.disabled = true;
    try {
      const job = await request('deploy/jobs', {profile: deployProfiles.value, sha: document.getElementById('deploy-sha').value.trim()});
      try { sessionStorage.setItem('ai-deck.deploy-job', job.id); } catch (_) {}
      clearTimeout(poll); pollJob(job.id);
    } catch (error) { deployMessage.textContent = error.message; }
    finally { button.disabled = !hasDeployProfiles; }
  });
  document.getElementById('project-manage').addEventListener('click', () => {
    loadDeploy();
    try { const id = sessionStorage.getItem('ai-deck.deploy-job'); if (id) { clearTimeout(poll); pollJob(id); } } catch (_) {}
  });
  if (coding) {
    document.body.classList.add('coding-workspace');
    document.querySelector('.workspace-label strong').textContent = 'Coding workspace';
    document.querySelector('.workspace-label div > span').textContent = 'Source code, tests and Git';
    document.getElementById('files-btn').hidden = true;
  }
  load();
})();
