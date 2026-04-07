/**
 * Shared markdown editor initialization (EasyMDE + preview + file upload +
 * @-mention + #wiki-link autocomplete).
 *
 * Reads config from a <script type="application/json" id="editor-config">
 * block with: { csrfToken, pageSlug?, urls: { presignUpload, confirmUpload,
 *   fileUpload, markdownGuide, preview, userSearch, pageSearch } }
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
  return function initMarkdownEditor(config) {
    var csrfToken = config.csrfToken;
    var pageSlug = config.pageSlug || '';
    var directUpload = config.directUpload || false;

    // ── File upload (defined early so toolbar action can reference it) ──
    var editor; // forward declaration

    // Shared helpers for placeholder management
    function insertPlaceholder(cm, filename) {
      var cursor = cm.getCursor();
      var text = '⏳ Uploading ' + filename + '...';
      cm.replaceRange(text + '\n', cursor);
      var line = cursor.line;
      var dots = 0;
      var interval = setInterval(function() {
        dots = (dots + 1) % 4;
        var t = '⏳ Uploading ' + filename + '.'.repeat(dots + 1);
        cm.replaceRange(t,
          { line: line, ch: 0 },
          { line: line, ch: cm.getLine(line).length }
        );
      }, 400);
      return { line: line, interval: interval };
    }

    function updatePlaceholderProgress(cm, ph, filename, pct) {
      var text = '⏳ Uploading ' + filename + ' (' + pct + '%)';
      cm.replaceRange(text,
        { line: ph.line, ch: 0 },
        { line: ph.line, ch: cm.getLine(ph.line).length }
      );
    }

    function replacePlaceholder(cm, ph, markdown) {
      clearInterval(ph.interval);
      cm.replaceRange(markdown,
        { line: ph.line, ch: 0 },
        { line: ph.line, ch: cm.getLine(ph.line).length }
      );
    }

    function removePlaceholder(cm, ph) {
      clearInterval(ph.interval);
      cm.replaceRange('',
        { line: ph.line, ch: 0 },
        { line: ph.line + 1, ch: 0 }
      );
    }

    // Upload directly to S3 via presigned POST (production)
    function handleDirectUpload(file) {
      var cm = editor.codemirror;
      var ph = insertPlaceholder(cm, file.name);

      // Step 1: Get presigned POST from Django
      fetch(config.urls.presignUpload, {
        method: 'POST',
        headers: { 'X-CSRFToken': csrfToken, 'Content-Type': 'application/json' },
        body: JSON.stringify({
          filename: file.name,
          content_type: file.type || 'application/octet-stream',
          size: file.size
        })
      }).then(function(r) { return r.json(); }).then(function(data) {
        if (data.error) { removePlaceholder(cm, ph); alert(data.error); return; }

        // Step 2: Upload directly to S3
        var fd = new FormData();
        var fields = data.presigned.fields;
        Object.keys(fields).forEach(function(k) { fd.append(k, fields[k]); });
        fd.append('file', file); // Must be last

        var xhr = new XMLHttpRequest();
        xhr.open('POST', data.presigned.url);

        xhr.upload.addEventListener('progress', function(e) {
          if (!e.lengthComputable) return;
          updatePlaceholderProgress(cm, ph, file.name, Math.round(e.loaded / e.total * 100));
        });

        xhr.addEventListener('load', function() {
          if (xhr.status < 200 || xhr.status >= 300) {
            removePlaceholder(cm, ph);
            alert('Upload to storage failed (status ' + xhr.status + ')');
            return;
          }

          // Step 3: Confirm with Django
          fetch(config.urls.confirmUpload, {
            method: 'POST',
            headers: { 'X-CSRFToken': csrfToken, 'Content-Type': 'application/json' },
            body: JSON.stringify({ pending_id: data.pending_id })
          }).then(function(r) { return r.json(); }).then(function(confirm) {
            if (confirm.error) { removePlaceholder(cm, ph); alert(confirm.error); return; }
            replacePlaceholder(cm, ph, confirm.markdown);
          }).catch(function() {
            removePlaceholder(cm, ph);
            alert('Failed to confirm upload');
          });
        });

        xhr.addEventListener('error', function() {
          removePlaceholder(cm, ph);
          alert('Upload failed — network error');
        });

        xhr.send(fd);
      }).catch(function() {
        removePlaceholder(cm, ph);
        alert('Failed to start upload');
      });
    }

    // Upload through Django (development, local filesystem)
    function handleLocalUpload(file) {
      var cm = editor.codemirror;
      var ph = insertPlaceholder(cm, file.name);

      var xhr = new XMLHttpRequest();
      xhr.open('POST', config.urls.fileUpload);
      xhr.setRequestHeader('X-CSRFToken', csrfToken);

      xhr.upload.addEventListener('progress', function(e) {
        if (!e.lengthComputable) return;
        updatePlaceholderProgress(cm, ph, file.name, Math.round(e.loaded / e.total * 100));
      });

      xhr.addEventListener('load', function() {
        if (xhr.status >= 200 && xhr.status < 300) {
          var data = JSON.parse(xhr.responseText);
          if (data.error) { removePlaceholder(cm, ph); alert(data.error); return; }
          if (data.markdown) { replacePlaceholder(cm, ph, data.markdown); }
        } else {
          removePlaceholder(cm, ph);
          alert('Upload failed (status ' + xhr.status + ')');
        }
      });

      xhr.addEventListener('error', function() {
        removePlaceholder(cm, ph);
        alert('Upload failed — network error');
      });

      var fd = new FormData();
      fd.append('file', file);
      xhr.send(fd);
    }

    var MAX_IMAGE_SIZE = 20 * 1024 * 1024; // 20 MB
    var MAX_FILE_SIZE = 1024 * 1024 * 1024; // 1 GB
    // Types where Canvas API would destroy the format (animation, vector).
    // WebP is included because animated WebP is common and Canvas would
    // silently discard all frames beyond the first.
    var SKIP_STRIP_TYPES = ['image/gif', 'image/svg+xml', 'image/webp'];

    /**
     * Strip image metadata (EXIF, GPS, camera info) using the Canvas API.
     * Draws the image to an offscreen canvas and re-exports it, which
     * produces a clean blob with only pixel data — no metadata survives.
     * Returns a Promise that resolves to a new File (or the original if
     * stripping is not applicable).
     */
    function stripImageMetadata(file) {
      if (!file.type.startsWith('image/') || SKIP_STRIP_TYPES.indexOf(file.type) !== -1) {
        return Promise.resolve(file);
      }
      return new Promise(function(resolve) {
        var url = URL.createObjectURL(file);
        var img = new Image();
        img.onload = function() {
          try {
            var canvas = document.createElement('canvas');
            canvas.width = img.naturalWidth;
            canvas.height = img.naturalHeight;
            var ctx = canvas.getContext('2d');
            if (!ctx) { URL.revokeObjectURL(url); resolve(file); return; }
            ctx.drawImage(img, 0, 0);
            URL.revokeObjectURL(url);
            canvas.toBlob(function(blob) {
              if (!blob) { resolve(file); return; }
              resolve(new File([blob], file.name, { type: file.type }));
            }, file.type, 1.0);
          } catch (e) {
            URL.revokeObjectURL(url);
            resolve(file); // pass through on error
          }
        };
        img.onerror = function() {
          URL.revokeObjectURL(url);
          resolve(file); // pass through on error
        };
        img.src = url;
      });
    }

    function handleFileUpload(file) {
      var isImage = file.type.startsWith('image/');
      if (isImage && file.size > MAX_IMAGE_SIZE) {
        alert('Image too large. Maximum image size is 20 MB.');
        return;
      }
      if (file.size > MAX_FILE_SIZE) {
        alert('File too large. Maximum size is 1 GB.');
        return;
      }
      var upload = directUpload ? handleDirectUpload : handleLocalUpload;
      stripImageMetadata(file).then(upload);
    }

    // ── EasyMDE Editor ──────────────────────────────────────
    editor = new EasyMDE({
      element: document.getElementById('markdown-editor'),
      autoDownloadFontAwesome: false,
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
      }, 'table', '|', {
        name: 'guide',
        action: function() {
          window.open(config.urls.markdownGuide, '_blank');
        },
        className: 'fa fa-question-circle',
        title: 'Markdown Guide',
      }],
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
        fetch(config.urls.preview, {
          method: 'POST',
          headers: { 'X-CSRFToken': csrfToken, 'Content-Type': 'application/x-www-form-urlencoded' },
          body: 'content=' + encodeURIComponent(editor.value()),
        }).then(function(r) { return r.text(); }).then(function(html) {
          previewPane.innerHTML = html;
          if (typeof hljs !== 'undefined') {
            previewPane.querySelectorAll('pre code').forEach(function(block) {
              hljs.highlightElement(block);
            });
          }
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
        fetchUrl: config.urls.userSearch + '?q=',
        onSelect: function(username, match) {
          var cm = editor.codemirror;
          var cursor = cm.getCursor();
          var line = cm.getLine(cursor.line);
          var before = line.slice(0, cursor.ch);
          var atPos = before.lastIndexOf('@');
          cm.replaceRange('@' + username, { line: cursor.line, ch: atPos }, cursor);
        }
      });

      // Helpers for #wiki-link dropdown keyboard navigation
      window._slugDdIndex = -1;

      function highlightSlugItem(dd, index) {
        var items = dd.querySelectorAll('[data-slug]');
        items.forEach(function(el, i) {
          if (i === index) {
            el.classList.add('bg-gray-100', 'dark:bg-gray-700');
          } else {
            el.classList.remove('bg-gray-100', 'dark:bg-gray-700');
          }
        });
        if (items[index]) {
          items[index].scrollIntoView({ block: 'nearest' });
        }
      }

      function selectSlugItem(cm, dd, slug) {
        var cur = cm.getCursor();
        var ln = cm.getLine(cur.line);
        var hp = ln.slice(0, cur.ch).lastIndexOf('#');
        cm.replaceRange('#' + slug, { line: cur.line, ch: hp }, cur);
        dd.classList.add('hidden');
        window._slugDdIndex = -1;
      }

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
          window._slugDdIndex = -1;
          return;
        }
        clearTimeout(window._wikiTimer);
        window._wikiTimer = setTimeout(function() {
          var searchUrl = config.urls.pageSearch + '?q=' + encodeURIComponent(hashMatch[1]);
          if (pageSlug) searchUrl += '&exclude=' + encodeURIComponent(pageSlug);
          fetch(searchUrl)
            .then(function(r) { return r.text(); }).then(function(html) {
              if (!html.trim()) { slugDd.classList.add('hidden'); window._slugDdIndex = -1; return; }
              slugDd.innerHTML = html; slugDd.classList.remove('hidden');
              window._slugDdIndex = 0;
              var coords = cm.cursorCoords(true, 'page');
              slugDd.style.left = coords.left + 'px'; slugDd.style.top = (coords.bottom + 4) + 'px';
              var items = slugDd.querySelectorAll('[data-slug]');
              highlightSlugItem(slugDd, 0);
              items.forEach(function(el) {
                el.addEventListener('mousedown', function(e) {
                  e.preventDefault();
                  selectSlugItem(cm, slugDd, el.dataset.slug);
                });
                el.addEventListener('mouseenter', function() {
                  var allItems = slugDd.querySelectorAll('[data-slug]');
                  for (var j = 0; j < allItems.length; j++) {
                    if (allItems[j] === el) { window._slugDdIndex = j; break; }
                  }
                  highlightSlugItem(slugDd, window._slugDdIndex);
                });
              });
            });
        }, 200);
      });

      editor.codemirror.on('keydown', function(cm, e) {
        var slugDd = document.getElementById('slug-dropdown');
        var slugDdVisible = slugDd && !slugDd.classList.contains('hidden');

        if (e.key === 'Escape') {
          mentionDrop.classList.add('hidden');
          if (slugDd) { slugDd.classList.add('hidden'); window._slugDdIndex = -1; }
        }
        if (e.key === 'Tab' && !mentionDrop.classList.contains('hidden') && activeCmMatch) {
          e.preventDefault();
          cmMention.selectFirst(activeCmMatch);
        }

        // Arrow key navigation and Enter/Tab selection for #wiki-link dropdown
        if (slugDdVisible) {
          var items = slugDd.querySelectorAll('[data-slug]');
          if (!items.length) return;
          if (e.key === 'ArrowDown') {
            e.preventDefault();
            window._slugDdIndex = Math.min((window._slugDdIndex || 0) + 1, items.length - 1);
            highlightSlugItem(slugDd, window._slugDdIndex);
          } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            window._slugDdIndex = Math.max((window._slugDdIndex || 0) - 1, 0);
            highlightSlugItem(slugDd, window._slugDdIndex);
          } else if (e.key === 'Enter' || (e.key === 'Tab' && !e.shiftKey)) {
            e.preventDefault();
            var idx = window._slugDdIndex || 0;
            if (items[idx]) {
              selectSlugItem(cm, slugDd, items[idx].dataset.slug);
            }
          }
        }
      });

      // Hide dropdowns on outside click
      document.addEventListener('click', function(e) {
        if (!mentionDrop.contains(e.target)) mentionDrop.classList.add('hidden');
        var slugDd = document.getElementById('slug-dropdown');
        if (slugDd && !slugDd.contains(e.target)) slugDd.classList.add('hidden');
      });
    }

    // ── Warn before leaving with unsaved changes ────────────
    var initialContent = editor.value();
    window.addEventListener('beforeunload', function(e) {
      if (editor.value() !== initialContent) {
        e.preventDefault();
      }
    });
    // Disable the warning when the form is actually submitted
    var form = document.getElementById('markdown-editor').closest('form');
    if (form) {
      form.addEventListener('submit', function() {
        initialContent = editor.value();
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
