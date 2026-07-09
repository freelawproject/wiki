/**
 * Code block enhancements: syntax highlighting, copy buttons, and tabbed
 * code groups ({% tabs %} markup, rendered as <div class="code-tabs">).
 *
 * Loaded after highlight.js on detail views and editor forms. Runs on DOM
 * ready for each .wiki-content container, and is exposed as
 * window.enhanceCodeBlocks(root) so the editor preview can enhance
 * HTML it injects after the fact.
 *
 * Tab selection is shared: picking a language activates it in every tab
 * group on the page that offers it, and persists across pages via
 * localStorage.
 */
(function () {
  var STORAGE_KEY = 'wiki-code-tab';

  var LANG_LABELS = {
    bash: 'Bash',
    cpp: 'C++',
    csharp: 'C#',
    css: 'CSS',
    curl: 'cURL',
    go: 'Go',
    html: 'HTML',
    java: 'Java',
    javascript: 'JavaScript',
    js: 'JavaScript',
    json: 'JSON',
    php: 'PHP',
    plaintext: 'Text',
    py: 'Python',
    python: 'Python',
    ruby: 'Ruby',
    rust: 'Rust',
    sh: 'Shell',
    shell: 'Shell',
    sql: 'SQL',
    ts: 'TypeScript',
    typescript: 'TypeScript',
    xml: 'XML',
    yaml: 'YAML',
    yml: 'YAML',
  };

  // ```curl fences keep their language-curl class (and cURL tab label) but
  // highlight with bash rules.
  if (typeof hljs !== 'undefined') {
    hljs.registerAliases('curl', { languageName: 'bash' });
  }

  function langOf(code) {
    var match = code.className.match(/language-([\w+-]+)/);
    return match ? match[1].toLowerCase() : '';
  }

  function labelFor(lang) {
    if (!lang) return 'Text';
    if (LANG_LABELS[lang]) return LANG_LABELS[lang];
    return lang.charAt(0).toUpperCase() + lang.slice(1);
  }

  function storedLang() {
    try {
      return localStorage.getItem(STORAGE_KEY);
    } catch (e) {
      return null;
    }
  }

  function rememberLang(lang) {
    try {
      localStorage.setItem(STORAGE_KEY, lang);
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

  // ── Tabbed code groups ─────────────────────────────────────────────

  function groupPanels(group) {
    return [].slice.call(group.children).filter(function (el) {
      return el.classList.contains('code-block-wrapper');
    });
  }

  function activateGroup(group, lang) {
    var tabs = group.querySelectorAll('[role="tab"]');
    var panels = groupPanels(group);
    var index = 0;
    if (lang) {
      for (var i = 0; i < tabs.length; i++) {
        if (tabs[i].dataset.lang === lang) {
          index = i;
          break;
        }
      }
    }
    tabs.forEach(function (tab, i) {
      var active = i === index;
      tab.setAttribute('aria-selected', active ? 'true' : 'false');
      tab.tabIndex = active ? 0 : -1;
      tab.classList.toggle('active', active);
      if (panels[i]) panels[i].hidden = !active;
    });
  }

  function groupHasLang(group, lang) {
    return !!group.querySelector('[role="tab"][data-lang="' + lang + '"]');
  }

  function selectLang(lang) {
    document.querySelectorAll('.code-tabs').forEach(function (group) {
      if (groupHasLang(group, lang)) activateGroup(group, lang);
    });
  }

  function buildTabGroup(group) {
    if (group.querySelector('.code-tabs-bar')) return;
    var panels = groupPanels(group);
    if (!panels.length) return;

    var bar = document.createElement('div');
    bar.className = 'code-tabs-bar';
    bar.setAttribute('role', 'tablist');
    bar.setAttribute('aria-label', 'Code examples');

    panels.forEach(function (panel) {
      var code = panel.querySelector('pre code');
      var lang = code ? langOf(code) : '';
      var tab = document.createElement('button');
      tab.type = 'button';
      tab.setAttribute('role', 'tab');
      tab.dataset.lang = lang;
      tab.textContent = labelFor(lang);
      tab.addEventListener('click', function () {
        if (lang) {
          rememberLang(lang);
          selectLang(lang);
        } else {
          activateGroup(group, lang);
        }
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

    var remembered = storedLang();
    activateGroup(group, remembered && groupHasLang(group, remembered) ? remembered : null);
  }

  // ── Entry point ────────────────────────────────────────────────────

  function enhanceCodeBlocks(root) {
    root.querySelectorAll('pre code').forEach(enhanceBlock);
    root.querySelectorAll('.code-tabs').forEach(buildTabGroup);
  }

  window.enhanceCodeBlocks = enhanceCodeBlocks;

  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('.wiki-content').forEach(enhanceCodeBlocks);
  });
})();
