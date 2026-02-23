/**
 * Shared markdown editor initialization (EasyMDE + preview + file upload +
 * @-mention + #wiki-link autocomplete).
 *
 * Reads config from a <script type="application/json" id="editor-config">
 * block with: { csrfToken, pageSlug? }
 *
 * Expects these DOM elements (optional ones are gracefully skipped):
 *   #markdown-editor  — textarea (required)
 *   #preview-btn      — button to trigger server-side preview
 *   #preview-area     — container shown when preview is active
 *   #preview-content  — inner div where preview HTML is injected
 *   #mention-dropdown — dropdown for @-mention autocomplete
 *   #slug-dropdown    — dropdown for #wiki-link autocomplete
 *
 * Returns the EasyMDE editor instance.
 */
var initMarkdownEditor = (function() {
  // ── Generic mention/autocomplete helper ─────────────────
  function setupMentionDropdown(dropdown, opts) {
    var timer = null;
    return {
      check: function(text, cursorPos) {
        var match = opts.getMatch(text, cursorPos);
        if (!match || match.query.length < 1) { dropdown.classList.add('hidden'); return null; }
        clearTimeout(timer);
        timer = setTimeout(function() {
          fetch(opts.fetchUrl + encodeURIComponent(match.query))
            .then(function(r) { return r.json(); }).then(function(results) {
              if (!results.length) { dropdown.classList.add('hidden'); return; }
              dropdown.innerHTML = '';
              results.forEach(function(r) {
                var el = document.createElement('div');
                el.className = 'px-3 py-2 hover:bg-gray-100 dark:hover:bg-gray-700 cursor-pointer text-sm flex items-center gap-2';
                var inner = '';
                if (r.gravatar_url) inner += '<img src="' + r.gravatar_url + '" class="w-5 h-5 rounded-full" alt="">';
                inner += '<span>' + r.display_name + '</span>';
                inner += '<span class="text-gray-400 text-xs">@' + r.username + '</span>';
                el.innerHTML = inner;
                el.dataset.username = r.username;
                el.addEventListener('mousedown', function(e) {
                  e.preventDefault();
                  opts.onSelect(r.username, match);
                  dropdown.classList.add('hidden');
                });
                dropdown.appendChild(el);
              });
              dropdown.classList.remove('hidden');
            });
        }, 150);
        return match;
      },
      selectFirst: function(match) {
        var first = dropdown.querySelector('[data-username]');
        if (first) {
          opts.onSelect(first.dataset.username, match);
          dropdown.classList.add('hidden');
          return true;
        }
        return false;
      },
      hide: function() { dropdown.classList.add('hidden'); }
    };
  }

  return function initMarkdownEditor(config) {
    var csrfToken = config.csrfToken;
    var pageSlug = config.pageSlug || '';

    // ── File upload (defined early so toolbar action can reference it) ──
    var editor; // forward declaration
    function handleFileUpload(file) {
      if (file.size > 1024 * 1024 * 1024) {
        alert('File too large. Maximum size is 1 GB.');
        return;
      }
      var fd = new FormData(); fd.append('file', file);
      fetch('/api/upload/', { method: 'POST', headers: { 'X-CSRFToken': csrfToken }, body: fd })
        .then(function(r) { return r.json(); }).then(function(data) {
          if (data.error) { alert(data.error); return; }
          if (data.markdown) { var cm = editor.codemirror; cm.replaceRange(data.markdown + '\n', cm.getCursor()); }
        });
    }

    // ── EasyMDE Editor ──────────────────────────────────────
    editor = new EasyMDE({
      element: document.getElementById('markdown-editor'),
      spellChecker: false,
      autosave: { enabled: false },
      status: ['lines', 'words'],
      uploadImage: false,
      toolbar: ['bold', 'italic', 'heading', '|', 'quote', 'unordered-list', 'ordered-list', '|', 'link', 'image', {
        name: 'upload',
        action: function() {
          var input = document.createElement('input');
          input.type = 'file';
          input.onchange = function() {
            if (input.files.length) handleFileUpload(input.files[0]);
          };
          input.click();
        },
        className: 'fa fa-upload',
        title: 'Upload File',
      }, 'table', '|', 'guide'],
    });

    // ── Write / Preview tabs ──────────────────────────────────
    var editorContainer = editor.codemirror.getWrapperElement().closest('.EasyMDEContainer');
    if (editorContainer) {
      // Wrap the EasyMDEContainer so we can reliably hide/show it
      var editorWrapper = document.createElement('div');
      editorContainer.parentNode.insertBefore(editorWrapper, editorContainer);
      editorWrapper.appendChild(editorContainer);

      // Create tab bar
      var tabBar = document.createElement('div');
      tabBar.className = 'flex border-b border-gray-200 dark:border-gray-700 mb-0';
      tabBar.innerHTML =
        '<button type="button" class="editor-tab px-4 py-2 text-sm font-medium border-b-2 border-primary-500 text-primary-600 dark:text-primary-400" data-tab="write">Write</button>' +
        '<button type="button" class="editor-tab px-4 py-2 text-sm font-medium border-b-2 border-transparent text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-300" data-tab="preview">Preview</button>';
      editorWrapper.parentNode.insertBefore(tabBar, editorWrapper);

      // Create preview container (hidden by default), in place of editor
      var previewPane = document.createElement('div');
      previewPane.id = 'tab-preview-content';
      previewPane.className = 'hidden wiki-content card min-h-[200px] p-4';
      editorWrapper.parentNode.insertBefore(previewPane, editorWrapper.nextSibling);

      var writeTab = tabBar.querySelector('[data-tab="write"]');
      var previewTab = tabBar.querySelector('[data-tab="preview"]');

      function activateTab(tab) {
        var tabs = tabBar.querySelectorAll('.editor-tab');
        tabs.forEach(function(t) {
          t.classList.remove('border-primary-500', 'text-primary-600', 'dark:text-primary-400');
          t.classList.add('border-transparent', 'text-gray-500', 'dark:text-gray-400');
        });
        tab.classList.remove('border-transparent', 'text-gray-500', 'dark:text-gray-400');
        tab.classList.add('border-primary-500', 'text-primary-600', 'dark:text-primary-400');
      }

      writeTab.addEventListener('click', function() {
        activateTab(writeTab);
        editorWrapper.style.display = '';
        previewPane.classList.add('hidden');
      });

      previewTab.addEventListener('click', function() {
        activateTab(previewTab);
        editorWrapper.style.display = 'none';
        previewPane.classList.remove('hidden');
        previewPane.innerHTML = '<p class="text-gray-400">Loading preview...</p>';
        fetch('/api/preview/', {
          method: 'POST',
          headers: { 'X-CSRFToken': csrfToken, 'Content-Type': 'application/x-www-form-urlencoded' },
          body: 'content=' + encodeURIComponent(editor.value()),
        }).then(function(r) { return r.text(); }).then(function(html) {
          previewPane.innerHTML = html;
        });
      });
    }

    // ── File upload: paste & drop handlers ────────────────
    editor.codemirror.on('paste', function(cm, e) {
      var items = e.clipboardData && e.clipboardData.items; if (!items) return;
      for (var i = 0; i < items.length; i++) { if (items[i].type.startsWith('image/')) { e.preventDefault(); handleFileUpload(items[i].getAsFile()); break; } }
    });
    editor.codemirror.on('drop', function(cm, e) {
      var files = e.dataTransfer && e.dataTransfer.files; if (!files || !files.length) return;
      e.preventDefault(); for (var i = 0; i < files.length; i++) handleFileUpload(files[i]);
    });

    // ── @-mention in CodeMirror editor ──────────────────────
    var mentionDrop = document.getElementById('mention-dropdown');
    var activeCmMatch = null;

    if (mentionDrop) {
      var cmMention = setupMentionDropdown(mentionDrop, {
        getMatch: function(text, pos) {
          var before = text.slice(0, pos);
          var m = before.match(/@([a-zA-Z][a-zA-Z0-9._-]*)$/);
          if (!m) return null;
          return { query: m[1], start: pos - m[0].length, end: pos };
        },
        fetchUrl: '/api/user-search/?q=',
        onSelect: function(username, match) {
          var cm = editor.codemirror;
          var cursor = cm.getCursor();
          var line = cm.getLine(cursor.line);
          var before = line.slice(0, cursor.ch);
          var atPos = before.lastIndexOf('@');
          cm.replaceRange('@' + username, { line: cursor.line, ch: atPos }, cursor);
        }
      });

      editor.codemirror.on('inputRead', function(cm, change) {
        var cursor = cm.getCursor();
        var line = cm.getLine(cursor.line);
        var before = line.slice(0, cursor.ch);

        // Check @mention first
        var atMatch = before.match(/@([a-zA-Z][a-zA-Z0-9._-]*)$/);
        if (atMatch) {
          activeCmMatch = cmMention.check(before, cursor.ch);
          var coords = cm.cursorCoords(true, 'page');
          mentionDrop.style.left = coords.left + 'px';
          mentionDrop.style.top = (coords.bottom + 4) + 'px';
          var slugDd = document.getElementById('slug-dropdown');
          if (slugDd) slugDd.classList.add('hidden');
          return;
        }
        mentionDrop.classList.add('hidden');
        activeCmMatch = null;

        // Check #wiki-link
        var slugDd = document.getElementById('slug-dropdown');
        if (!slugDd) return;
        var hashMatch = before.match(/#([a-z0-9-]*)$/);
        if (!hashMatch || hashMatch[1].length < 2) {
          slugDd.classList.add('hidden');
          return;
        }
        clearTimeout(window._wikiTimer);
        window._wikiTimer = setTimeout(function() {
          var searchUrl = '/api/page-search/?q=' + encodeURIComponent(hashMatch[1]);
          if (pageSlug) searchUrl += '&exclude=' + encodeURIComponent(pageSlug);
          fetch(searchUrl)
            .then(function(r) { return r.text(); }).then(function(html) {
              if (!html.trim()) { slugDd.classList.add('hidden'); return; }
              slugDd.innerHTML = html; slugDd.classList.remove('hidden');
              var coords = cm.cursorCoords(true, 'page');
              slugDd.style.left = coords.left + 'px'; slugDd.style.top = (coords.bottom + 4) + 'px';
              slugDd.querySelectorAll('[data-slug]').forEach(function(el) {
                el.addEventListener('mousedown', function(e) {
                  e.preventDefault();
                  var cur = cm.getCursor(); var ln = cm.getLine(cur.line);
                  var hp = ln.slice(0, cur.ch).lastIndexOf('#');
                  cm.replaceRange('#' + el.dataset.slug, { line: cur.line, ch: hp }, cur);
                  slugDd.classList.add('hidden');
                });
              });
            });
        }, 200);
      });

      editor.codemirror.on('keydown', function(cm, e) {
        if (e.key === 'Escape') {
          mentionDrop.classList.add('hidden');
          var slugDd = document.getElementById('slug-dropdown');
          if (slugDd) slugDd.classList.add('hidden');
        }
        if (e.key === 'Tab' && !mentionDrop.classList.contains('hidden') && activeCmMatch) {
          e.preventDefault();
          cmMention.selectFirst(activeCmMatch);
        }
      });

      // Hide dropdowns on outside click
      document.addEventListener('click', function(e) {
        if (!mentionDrop.contains(e.target)) mentionDrop.classList.add('hidden');
        var slugDd = document.getElementById('slug-dropdown');
        if (slugDd && !slugDd.contains(e.target)) slugDd.classList.add('hidden');
      });
    }

    return editor;
  };
})();

// Auto-initialize when loaded standalone (no page-form.js following).
// If page-form.js is present, it will call initMarkdownEditor itself.
(function() {
  var editorConfig = document.getElementById('editor-config');
  var pageConfig = document.getElementById('page-config');
  if (editorConfig && !pageConfig) {
    var config = JSON.parse(editorConfig.textContent);
    initMarkdownEditor(config);
  }
})();
