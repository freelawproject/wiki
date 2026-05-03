/**
 * Records a page-view tally on load and refreshes the displayed count.
 *
 * The page itself is served by a CDN with a long TTL, so the count
 * rendered into the HTML can be very stale. This script:
 *   1. POSTs to /api/page-view/ with the page id (CSRF-exempt endpoint).
 *   2. Replaces the rendered count with the value returned by the server.
 *
 * Reads config from <script type="application/json" id="view-tally-config">:
 *   { pageId: <int>, url: "<endpoint>" }
 * Updates the element with id="page-view-count" if present.
 */
(function () {
  var configEl = document.getElementById('view-tally-config');
  if (!configEl) return;

  var config;
  try {
    config = JSON.parse(configEl.textContent);
  } catch (e) {
    return;
  }
  if (!config.pageId || !config.url) return;

  fetch(config.url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ page_id: config.pageId }),
    credentials: 'same-origin',
    keepalive: true,
  })
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (data) {
      if (!data || typeof data.count !== 'number') return;
      var el = document.getElementById('page-view-count');
      if (!el) return;
      var formatted = data.count.toLocaleString();
      var label = data.count === 1 ? 'view' : 'views';
      el.textContent = formatted + ' ' + label;
    })
    .catch(function () { /* network errors are not actionable here */ });
})();
