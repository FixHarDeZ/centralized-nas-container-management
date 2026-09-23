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
  function label(item) { return item.url.replace('https://github.com/', '').replace(/\.git$/, '') + ' · ' + item.branch; }
  async function load() {
    try {
      projects = demo ? (workspace ? [{id: workspace, url: 'https://github.com/example/project', branch: 'desk/' + workspace, path: '/workspaces/tasks/demo/' + workspace}] : []) : (await request('code/projects')).items;
      select.replaceChildren(new Option('Documents', ''));
      projects.forEach(item => select.add(new Option(label(item), item.id)));
      current = projects.find(item => item.id === workspace);
      if (workspace && !current) {
        select.add(new Option('Workspace unavailable', workspace));
        message.textContent = 'This workspace is missing or belongs to another user.';
      }
      select.value = workspace;
      details.hidden = !current;
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
    panel.showModal();
    if (current) refreshStatus();
  });
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
  let poll = null;
  async function loadDeploy() {
    try {
      const data = await request('deploy/profiles');
      deployProfiles.replaceChildren(new Option('Select deployment', ''));
      data.items.forEach(item => deployProfiles.add(new Option(item.id, item.id)));
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
    finally { button.disabled = false; }
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
