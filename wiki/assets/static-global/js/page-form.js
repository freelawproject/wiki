(function() {
  var config = JSON.parse(
    document.getElementById('page-config').textContent
  );
  var csrfToken = config.csrfToken;
  var isEditing = config.isEditing;
  var pageSlug = config.pageSlug;
  var pageForm = document.getElementById('page-form');

  // ── Location Picker ─────────────────────────────────────
  var locationInput = document.getElementById('location-input');
  var locationChips = document.getElementById('location-chips');
  var dirDropdown = document.getElementById('dir-dropdown');
  var dirPathInput = document.getElementById('directory-path-input');

  var segments = config.dirSegments;
  var searchTimeout = null;

  function renderChips() {
    locationChips.innerHTML = '';
    segments.forEach(function(seg) {
      var chip = document.createElement('span');
      chip.className = 'inline-flex items-center gap-1 px-2 py-0.5 rounded bg-primary-100 dark:bg-primary-900 text-primary-800 dark:text-primary-200 text-sm';
      chip.textContent = seg.title;
      locationChips.appendChild(chip);
      var sep = document.createElement('span');
      sep.className = 'text-gray-400 text-sm select-none';
      sep.textContent = '/';
      locationChips.appendChild(sep);
    });
    dirPathInput.value = segments.length > 0 ? segments[segments.length - 1].path : '';
  }

  function currentParentPath() {
    return segments.length > 0 ? segments[segments.length - 1].path : '';
  }

  function fetchSuggestions(query) {
    var parent = currentParentPath();
    var url = '/api/dir-search/?parent=' + encodeURIComponent(parent);
    if (query) url += '&q=' + encodeURIComponent(query);
    fetch(url).then(function(r) { return r.json(); }).then(function(dirs) {
      if (!dirs.length && !query) { dirDropdown.classList.add('hidden'); return; }
      var html = '';
      dirs.forEach(function(d) {
        html += '<div class="px-3 py-2 hover:bg-gray-100 dark:hover:bg-gray-700 cursor-pointer text-sm" data-path="' + d.path + '" data-title="' + d.title + '">' + d.title + '</div>';
      });
      if (query && !dirs.some(function(d) { return d.title.toLowerCase() === query.toLowerCase(); })) {
        html += '<div class="px-3 py-2 hover:bg-gray-100 dark:hover:bg-gray-700 cursor-pointer text-sm text-primary-600 dark:text-primary-400" data-new="true" data-title="' + query + '">Create "' + query + '"</div>';
      }
      dirDropdown.innerHTML = html;
      dirDropdown.classList.remove('hidden');
      dirDropdown.querySelectorAll('[data-path]').forEach(function(el) {
        el.addEventListener('mousedown', function(e) {
          e.preventDefault();
          segments.push({path: el.dataset.path, title: el.dataset.title});
          renderChips(); locationInput.value = ''; dirDropdown.classList.add('hidden'); locationInput.focus();
        });
      });
      dirDropdown.querySelectorAll('[data-new]').forEach(function(el) {
        el.addEventListener('mousedown', function(e) {
          e.preventDefault();
          var parentPath = currentParentPath();
          var slug = el.dataset.title.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '');
          var newPath = parentPath ? parentPath + '/' + slug : slug;
          segments.push({path: newPath, title: el.dataset.title, isNew: true});
          renderChips(); locationInput.value = ''; dirDropdown.classList.add('hidden'); locationInput.focus();
        });
      });
    });
  }

  locationInput.addEventListener('input', function() {
    clearTimeout(searchTimeout);
    searchTimeout = setTimeout(function() { fetchSuggestions(locationInput.value.trim()); }, 150);
  });
  locationInput.addEventListener('focus', function() { if (!locationInput.value.trim()) fetchSuggestions(''); });
  locationInput.addEventListener('keydown', function(e) {
    if (e.key === 'Backspace' && locationInput.value === '' && segments.length > 0) { segments.pop(); renderChips(); fetchSuggestions(''); }
    if (e.key === 'Escape') dirDropdown.classList.add('hidden');
    if ((e.key === 'Tab' || e.key === '/') && !dirDropdown.classList.contains('hidden')) {
      var first = dirDropdown.querySelector('[data-path], [data-new]');
      if (first) { e.preventDefault(); first.dispatchEvent(new MouseEvent('mousedown', {bubbles: true})); }
    }
  });
  document.getElementById('location-picker').addEventListener('click', function() { locationInput.focus(); });
  document.addEventListener('click', function(e) {
    if (!document.getElementById('location-picker').contains(e.target) && !dirDropdown.contains(e.target)) dirDropdown.classList.add('hidden');
  });
  renderChips();

  // ── Shared markdown editor (EasyMDE + preview + upload + mentions + wiki links)
  var editorConfig = JSON.parse(
    document.getElementById('editor-config').textContent
  );
  editorConfig.pageSlug = pageSlug;
  var editor = initMarkdownEditor(editorConfig);

  // ── Generic mention/autocomplete helper (for change message) ──
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

  // ── @-mention in change message input ───────────────────
  var cmInput = document.getElementById('id_change_message');
  var cmDrop = document.getElementById('cm-mention-dropdown');
  var activeCmInputMatch = null;

  var cmInputMention = setupMentionDropdown(cmDrop, {
    getMatch: function(text, pos) {
      var before = text.slice(0, pos);
      var m = before.match(/@([a-zA-Z][a-zA-Z0-9._-]*)$/);
      if (!m) return null;
      return { query: m[1], start: pos - m[0].length, end: pos };
    },
    fetchUrl: '/api/user-search/?q=',
    onSelect: function(username, match) {
      var val = cmInput.value;
      cmInput.value = val.slice(0, match.start) + '@' + username + val.slice(match.end);
      cmInput.focus();
      var newPos = match.start + username.length + 1;
      cmInput.setSelectionRange(newPos, newPos);
    }
  });

  cmInput.addEventListener('input', function() {
    var pos = cmInput.selectionStart;
    activeCmInputMatch = cmInputMention.check(cmInput.value, pos);
    if (activeCmInputMatch) {
      var rect = cmInput.getBoundingClientRect();
      cmDrop.style.left = rect.left + 'px';
      cmDrop.style.top = (rect.bottom + 4 + window.scrollY) + 'px';
      cmDrop.style.width = rect.width + 'px';
    }
  });

  cmInput.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') cmDrop.classList.add('hidden');
    if (e.key === 'Tab' && !cmDrop.classList.contains('hidden') && activeCmInputMatch) {
      e.preventDefault();
      cmInputMention.selectFirst(activeCmInputMatch);
    }
  });

  // Hide change message dropdown on outside click
  document.addEventListener('click', function(e) {
    if (!cmDrop.contains(e.target) && e.target !== cmInput) cmDrop.classList.add('hidden');
  });

  // ── Permission check modal on form submit ───────────────
  var modal = document.getElementById('perm-modal');
  var modalUsers = document.getElementById('perm-modal-users');
  var modalLinks = document.getElementById('perm-modal-links');
  var mentionsSection = document.getElementById('perm-modal-mentions-section');
  var linksSection = document.getElementById('perm-modal-links-section');
  var pendingSubmit = false;

  function extractAllReferences() {
    var mentionRe = /@([a-zA-Z][a-zA-Z0-9._-]*)/g;
    var linkRe = /#([a-z0-9](?:[a-z0-9-]*[a-z0-9])?)/g;
    var mentions = new Set();
    var linkedSlugs = new Set();
    var m;
    var content = editor.value();
    while ((m = mentionRe.exec(content)) !== null) mentions.add(m[1]);
    mentionRe.lastIndex = 0;
    var msg = cmInput.value;
    while ((m = mentionRe.exec(msg)) !== null) mentions.add(m[1]);
    while ((m = linkRe.exec(content)) !== null) linkedSlugs.add(m[1]);
    linkRe.lastIndex = 0;
    while ((m = linkRe.exec(msg)) !== null) linkedSlugs.add(m[1]);
    return { mentions: Array.from(mentions), linked_slugs: Array.from(linkedSlugs) };
  }

  pageForm.addEventListener('submit', function(e) {
    if (pendingSubmit) return; // Already checked, let it through

    // Only check for non-public pages when editing
    if (!isEditing || !pageSlug) return;

    var refs = extractAllReferences();
    if (!refs.mentions.length && !refs.linked_slugs.length) return;

    e.preventDefault();
    fetch('/api/check-page-perms/', {
      method: 'POST',
      headers: { 'X-CSRFToken': csrfToken, 'Content-Type': 'application/json' },
      body: JSON.stringify({ page_slug: pageSlug, usernames: refs.mentions, linked_slugs: refs.linked_slugs }),
    }).then(function(r) { return r.json(); }).then(function(data) {
      var hasUsers = data.users_without_access && data.users_without_access.length;
      var hasLinks = data.restrictive_links && data.restrictive_links.length;

      if (!hasUsers && !hasLinks) {
        pendingSubmit = true;
        pageForm.submit();
        return;
      }

      // Show mentions section
      if (hasUsers) {
        mentionsSection.classList.remove('hidden');
        modalUsers.innerHTML = '';
        data.users_without_access.forEach(function(u) {
          var row = document.createElement('div');
          row.className = 'flex items-center justify-between gap-2 text-sm';
          row.innerHTML =
            '<div class="flex items-center gap-2">' +
              '<span class="font-medium">' + u.display_name + '</span> ' +
              '<span class="text-gray-400">(@' + u.username + ')</span>' +
            '</div>' +
            '<select class="grant-select input-text text-sm py-1 px-2 w-32" data-username="' + u.username + '">' +
              '<option value="">Don\'t grant</option>' +
              '<option value="view" selected>View</option>' +
              '<option value="edit">Edit</option>' +
            '</select>';
          modalUsers.appendChild(row);
        });
      } else {
        mentionsSection.classList.add('hidden');
      }

      // Show linked pages section
      if (hasLinks) {
        linksSection.classList.remove('hidden');
        modalLinks.innerHTML = '';
        data.restrictive_links.forEach(function(link) {
          var row = document.createElement('div');
          row.className = 'flex items-center justify-between gap-2 text-sm';
          row.innerHTML =
            '<div class="flex items-center gap-2">' +
              '<span class="font-medium">' + link.title + '</span> ' +
              '<span class="inline-flex items-center px-1.5 py-0.5 rounded-full text-xs bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200">' + link.visibility + '</span>' +
            '</div>' +
            '<a href="' + link.permissions_url + '" target="_blank" class="text-primary-600 dark:text-primary-400 hover:underline text-xs">Permissions</a>';
          modalLinks.appendChild(row);
        });
      } else {
        linksSection.classList.add('hidden');
      }

      modal.classList.remove('hidden');
    });
  });

  document.getElementById('perm-grant-btn').addEventListener('click', function() {
    // Add hidden fields for users with a selected access level
    modalUsers.querySelectorAll('.grant-select').forEach(function(sel) {
      if (sel.value) {
        var input = document.createElement('input');
        input.type = 'hidden';
        input.name = 'grant_access_' + sel.dataset.username;
        input.value = sel.value;
        pageForm.appendChild(input);
      }
    });
    modal.classList.add('hidden');
    pendingSubmit = true;
    pageForm.submit();
  });

  document.getElementById('perm-cancel-btn').addEventListener('click', function() {
    modal.classList.add('hidden');
  });
})();
