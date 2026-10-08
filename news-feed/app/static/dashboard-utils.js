/* Pure dashboard helpers: shared by the browser and Node's built-in tests. */
(function (root) {
  'use strict';

  function escapeText(value) {
    const entities = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
    return String(value ?? '').replace(/[&<>"']/g, char => entities[char]);
  }

  function safeArticleUrl(value) {
    if (typeof value !== 'string' || /[\x00-\x1f\x7f]/.test(value)) return null;
    try {
      const url = new URL(value);
      return ['http:', 'https:'].includes(url.protocol) ? url.href : null;
    } catch (_) {
      return null;
    }
  }

  function nextDigest(times, now = new Date()) {
    if (!Array.isArray(times) || !Number.isFinite(now.getTime())) return null;
    const parts = new Intl.DateTimeFormat('en-CA', {
      timeZone: 'Asia/Bangkok', year: 'numeric', month: '2-digit', day: '2-digit',
    }).formatToParts(now);
    const values = Object.fromEntries(parts.map(part => [part.type, part.value]));
    const day = `${values.year}-${values.month}-${values.day}`;
    const candidates = times.filter(time => typeof time === 'string' && /^(?:[01]\d|2[0-3]):[0-5]\d$/.test(time)).map(time => {
      // Bangkok is UTC+07:00 year-round; do not use the browser's local date.
      let tick = new Date(`${day}T${time}:00+07:00`).getTime();
      if (tick <= now.getTime()) tick += 86400000;
      return tick;
    });
    return candidates.length ? new Date(Math.min(...candidates)) : null;
  }

  function filterArticles(articles, { query = '', source = '', status = 'all' } = {}, sentIds = new Set()) {
    const search = query.trim().toLowerCase();
    return articles.filter(article =>
      (!source || article.source === source) &&
      (!search || `${article.title ?? ''} ${article.summary_th ?? ''}`.toLowerCase().includes(search)) &&
      (status !== 'summarized' || Boolean(article.summary_th?.trim())) &&
      (status !== 'sent' || sentIds.has(article.id))
    );
  }

  function readWatchlist(value) {
    try {
      const parsed = JSON.parse(value);
      return Array.isArray(parsed) ? [...new Set(parsed.filter(id => typeof id === 'string' && id.trim()))] : [];
    } catch (_) {
      return [];
    }
  }

  const helpers = { escapeText, safeArticleUrl, nextDigest, filterArticles, readWatchlist };
  if (typeof module !== 'undefined' && module.exports) module.exports = helpers;
  else root.NewsFeedUI = helpers;
})(typeof window !== 'undefined' ? window : globalThis);
