/**
 * Code block enhancements: syntax highlighting, copy buttons, and tabbed
 * content groups ({% tabs %} markup, rendered as <div class="content-tabs">
 * of labeled panels).
 *
 * Loaded after highlight.js on detail views and editor forms. Runs on DOM
 * ready for each .wiki-content container, and is exposed as
 * window.enhanceCodeBlocks(root) so the editor preview can enhance
 * HTML it injects after the fact.
 *
 * Tab selection is shared: picking a tab activates every same-named tab
 * on the page, and persists across pages via localStorage.
 */
(function () {
  var STORAGE_KEY = 'wiki-content-tab';

  function storedTab() {
    try {
      return localStorage.getItem(STORAGE_KEY);
    } catch (e) {
      return null;
    }
  }

  function rememberTab(label) {
    try {
      localStorage.setItem(STORAGE_KEY, label);
    } catch (e) {
      /* storage unavailable — selection just won't persist */
    }
  }

  // ── Highlighting + copy button ─────────────────────────────────────

  function enhanceBlock(code) {
    if (code.dataset.enhanced) return;
    code.dataset.enhanced = 'true';

    if (typeof hljs !== 'undefined') {
      hljs.highlightElement(code);
    }

    // Wrap <pre> in a relative container for the copy button
    var pre = code.parentElement;
    var wrapper = document.createElement('div');
    wrapper.className = 'code-block-wrapper';
    pre.parentNode.insertBefore(wrapper, pre);
    wrapper.appendChild(pre);

    // Create copy button
    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'copy-code-btn';
    btn.setAttribute('aria-label', 'Copy code');
    btn.innerHTML =
      '<svg class="copy-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
        '<rect x="9" y="9" width="13" height="13" rx="2" ry="2"/>' +
        '<path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>' +
      '</svg>' +
      '<svg class="check-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
        '<polyline points="20 6 9 17 4 12"/>' +
      '</svg>';

    btn.addEventListener('click', function () {
      var text = code.textContent;
      navigator.clipboard.writeText(text).then(function () {
        btn.classList.add('copied');
        setTimeout(function () {
          btn.classList.remove('copied');
        }, 2000);
      });
    });

    wrapper.appendChild(btn);
  }

  // ── Tabbed content groups ──────────────────────────────────────────

  var groupCount = 0;

  function groupPanels(group) {
    return [].slice.call(group.children).filter(function (el) {
      return el.classList.contains('content-tab-panel');
    });
  }

  function tabIndexForLabel(group, label) {
    var tabs = group.querySelectorAll('[role="tab"]');
    for (var i = 0; i < tabs.length; i++) {
      if (tabs[i].dataset.label === label) return i;
    }
    return -1;
  }

  function activateGroup(group, index) {
    var tabs = group.querySelectorAll('[role="tab"]');
    var panels = groupPanels(group);
    tabs.forEach(function (tab, i) {
      var active = i === index;
      tab.setAttribute('aria-selected', active ? 'true' : 'false');
      tab.tabIndex = active ? 0 : -1;
      tab.classList.toggle('active', active);
      if (panels[i]) panels[i].hidden = !active;
    });
  }

  function selectTab(label) {
    document.querySelectorAll('.content-tabs').forEach(function (group) {
      var index = tabIndexForLabel(group, label);
      if (index !== -1) activateGroup(group, index);
    });
  }

  function buildTabGroup(group) {
    if (group.querySelector('.content-tabs-bar')) return;
    var panels = groupPanels(group);
    if (!panels.length) return;
    var groupId = ++groupCount;

    var bar = document.createElement('div');
    bar.className = 'content-tabs-bar';
    bar.setAttribute('role', 'tablist');
    bar.setAttribute('aria-label', 'Tabs');

    panels.forEach(function (panel, i) {
      var label = panel.dataset.label || 'Tab ' + (i + 1);
      var tab = document.createElement('button');
      tab.type = 'button';
      tab.id = 'content-tab-' + groupId + '-' + i;
      tab.setAttribute('role', 'tab');
      tab.setAttribute('aria-controls', 'content-tabpanel-' + groupId + '-' + i);
      tab.dataset.label = label;
      tab.textContent = label;
      panel.id = 'content-tabpanel-' + groupId + '-' + i;
      panel.setAttribute('role', 'tabpanel');
      panel.setAttribute('aria-labelledby', tab.id);
      tab.addEventListener('click', function () {
        rememberTab(label);
        selectTab(label);
      });
      bar.appendChild(tab);
    });

    bar.addEventListener('keydown', function (e) {
      if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
      var tabs = [].slice.call(bar.querySelectorAll('[role="tab"]'));
      var current = tabs.indexOf(document.activeElement);
      if (current === -1) return;
      e.preventDefault();
      var step = e.key === 'ArrowLeft' ? -1 : 1;
      var next = tabs[(current + step + tabs.length) % tabs.length];
      next.focus();
      next.click();
    });

    group.insertBefore(bar, group.firstChild);

    var remembered = storedTab();
    var index = remembered ? tabIndexForLabel(group, remembered) : -1;
    activateGroup(group, index === -1 ? 0 : index);
  }

  // ── Entry point ────────────────────────────────────────────────────

  function enhanceCodeBlocks(root) {
    root.querySelectorAll('pre code').forEach(enhanceBlock);
    root.querySelectorAll('.content-tabs').forEach(buildTabGroup);
  }

  window.enhanceCodeBlocks = enhanceCodeBlocks;

  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('.wiki-content').forEach(enhanceCodeBlocks);
  });
})();
