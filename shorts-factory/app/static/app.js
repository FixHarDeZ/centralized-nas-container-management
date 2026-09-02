// Two behaviours, no dependencies: remember the theme, and hide rows client
// side. Filtering stays in the browser so no route has to grow a query
// parameter — docs/adr/0007 keeps this app to plain GET pages.

document.getElementById('theme')?.addEventListener('click', () => {
  const next = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark';
  document.documentElement.dataset.theme = next;
  localStorage.setItem('theme', next);
});

const filters = document.querySelector('.filters');
if (filters) {
  const rows = [...document.querySelectorAll('tr[data-outcome]')];
  filters.addEventListener('click', (event) => {
    const button = event.target.closest('button');
    if (!button) return;
    const want = button.dataset.outcome;
    for (const b of filters.querySelectorAll('button')) b.classList.toggle('on', b === button);
    for (const row of rows) row.hidden = want !== '' && row.dataset.outcome !== want;
  });
}
