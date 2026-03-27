(function() {
  var config = JSON.parse(
    document.getElementById('page-config').textContent
  );
  var csrfToken = config.csrfToken;
  var isEditing = config.isEditing;
  var pageSlug = config.pageSlug;
  var pageForm = document.getElementById('page-form');

  // ── Dynamic HTML title ─────────────────────────────────────
  var titleInput = document.getElementById('id_title');
  var titlePrefix = isEditing ? 'Edit' : 'New Page';
  var titleDefault = isEditing ? 'Edit Page - FLP Wiki' : 'New Page - FLP Wiki';
  titleInput.addEventListener('input', function() {
    var val = titleInput.value.trim().replace(/`([^`]+)`/g, '$1');
    document.title = val ? titlePrefix + ' - ' + val + ' - FLP Wiki' : titleDefault;
  });

  // ── Location Picker ─────────────────────────────────────
  var locationInput = document.getElementById('location-input');
  var locationChips = document.getElementById('location-chips');
  var dirDropdown = document.getElementById('dir-dropdown');
  var dirPathInput = document.getElementById('directory-path-input');
  var dirTitlesInput = document.getElementById('directory-titles-input');

  var segments = config.dirSegments;
  var searchTimeout = null;

  function escapeHtml(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function fetchInheritMeta(dirPath) {
    if (!dirPath) return;
    fetch(config.urls.dirInherit + '?path=' + encodeURIComponent(dirPath))
      .then(function(r) { return r.ok ? r.json() : null; })
      .then(function(meta) {
        if (!meta) return;
        _upgradeSelectsToInherit(meta);
        document.dispatchEvent(new CustomEvent('dir-inherit-update', { detail: meta }));
      })
      .catch(function() {});
  }

  // Replace plain <select> widgets with inherit-select Alpine components
  // when a directory is first selected on the new-page form.
  var FIELD_NAMES = ['visibility', 'editability', 'in_sitemap', 'in_llms_txt'];

  function _upgradeSelectsToInherit(meta) {
    FIELD_NAMES.forEach(function(fieldName) {
      var fieldMeta = meta[fieldName];
      if (!fieldMeta) return;
      // Skip if already upgraded to inherit-select
      if (document.querySelector('[data-field="' + fieldName + '"]')) return;
      var sel = document.getElementById('id_' + fieldName);
      if (!sel || sel.tagName !== 'SELECT') return;

      // Collect explicit choices from the existing <select>
      var choices = [];
      for (var i = 0; i < sel.options.length; i++) {
        var opt = sel.options[i];
        if (opt.value !== 'inherit') {
          choices.push({ value: opt.value, label: opt.textContent.trim() });
        }
      }

      // Build the inherit-select component markup
      var wrapper = document.createElement('div');
      wrapper.setAttribute('data-field', fieldName);
      wrapper.setAttribute('data-inherit-value', fieldMeta.value);
      wrapper.setAttribute('data-inherit-display', fieldMeta.display);
      wrapper.setAttribute('data-inherit-source', fieldMeta.source);
      wrapper.className = 'relative';

      var hidden = document.createElement('input');
      hidden.type = 'hidden';
      hidden.name = fieldName;
      hidden.value = 'inherit';
      wrapper.appendChild(hidden);

      // Button
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.id = 'id_' + fieldName;
      btn.setAttribute('role', 'combobox');
      btn.className = 'input-text w-full text-left flex items-center justify-between gap-2';
      btn.innerHTML =
        '<div class="min-w-0">' +
          '<span class="block"></span>' +
          '<span class="block text-xs text-gray-400 dark:text-gray-500 truncate" aria-hidden="true"></span>' +
        '</div>' +
        '<svg class="w-4 h-4 text-gray-400 shrink-0" aria-hidden="true" fill="none" viewBox="0 0 24 24" stroke="currentColor">' +
          '<path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/>' +
        '</svg>';
      wrapper.appendChild(btn);

      // Listbox
      var listbox = document.createElement('div');
      listbox.id = 'listbox_' + fieldName;
      listbox.setAttribute('role', 'listbox');
      listbox.style.display = 'none';
      listbox.className = 'absolute z-50 mt-1 w-full bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded-lg shadow-lg overflow-hidden';

      // Inherit option
      var inheritOpt = document.createElement('div');
      inheritOpt.setAttribute('role', 'option');
      inheritOpt.setAttribute('data-value', 'inherit');
      inheritOpt.setAttribute('tabindex', '-1');
      inheritOpt.className = 'px-3 py-2 cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-700 focus:bg-gray-100 dark:focus:bg-gray-700 outline-none';
      var titleEl = document.createElement('div');
      titleEl.className = 'text-sm font-medium';
      titleEl.textContent = fieldMeta.display;
      inheritOpt.appendChild(titleEl);
      var sourceEl = document.createElement('div');
      sourceEl.className = 'text-xs text-gray-400 dark:text-gray-500';
      sourceEl.setAttribute('aria-hidden', 'true');
      sourceEl.textContent = 'Provided by ' + fieldMeta.source;
      inheritOpt.appendChild(sourceEl);
      listbox.appendChild(inheritOpt);

      // Explicit options (skip the one matching the inherited value)
      choices.forEach(function(c) {
        if (c.value === fieldMeta.value) return;
        var opt = document.createElement('div');
        opt.setAttribute('role', 'option');
        opt.setAttribute('data-value', c.value);
        opt.setAttribute('data-option-value', c.value);
        opt.setAttribute('tabindex', '-1');
        opt.className = 'px-3 py-2 cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-700 focus:bg-gray-100 dark:focus:bg-gray-700 outline-none text-sm';
        opt.textContent = c.label;
        listbox.appendChild(opt);
      });

      wrapper.appendChild(listbox);

      // Set Alpine directives (use x-on:/x-bind: syntax for setAttribute)
      wrapper.setAttribute('x-data', 'inheritSelect');
      wrapper.setAttribute('x-on:click.outside', 'close');
      wrapper.setAttribute('x-on:keydown', 'onKeydown');
      btn.setAttribute('x-on:click', 'toggle');
      btn.setAttribute('x-bind:aria-expanded', 'open');
      btn.setAttribute('aria-controls', 'listbox_' + fieldName);
      btn.setAttribute('aria-haspopup', 'listbox');
      var spans = btn.querySelectorAll('span');
      spans[0].setAttribute('x-text', 'selectedLabel');
      spans[1].setAttribute('x-show', 'showInheritSub');
      spans[1].setAttribute('x-text', 'inheritSubLabel');
      listbox.setAttribute('x-show', 'open');
      inheritOpt.setAttribute('x-on:click', 'pick');
      listbox.querySelectorAll('[data-option-value]').forEach(function(el) {
        el.setAttribute('x-on:click', 'pick');
      });

      // Replace the <select> and let Alpine initialize the component
      sel.parentNode.replaceChild(wrapper, sel);
      Alpine.initTree(wrapper);
    });
  }

  function renderChips() {
    locationChips.innerHTML = '';
    var titles = {};
    segments.forEach(function(seg) {
      var chip = document.createElement('span');
      chip.className = 'inline-flex items-center gap-1 px-2 py-0.5 rounded bg-primary-100 dark:bg-primary-900 text-primary-800 dark:text-primary-200 text-sm';
      chip.textContent = seg.title;
      locationChips.appendChild(chip);
      var sep = document.createElement('span');
      sep.className = 'text-gray-400 text-sm select-none';
      sep.textContent = '/';
      locationChips.appendChild(sep);
      if (seg.isNew) {
        titles[seg.path] = seg.title;
      }
    });
    var newPath = segments.length > 0 ? segments[segments.length - 1].path : '';
    dirPathInput.value = newPath;
    dirTitlesInput.value = JSON.stringify(titles);
    if (newPath) fetchInheritMeta(newPath);
  }

  function currentParentPath() {
    return segments.length > 0 ? segments[segments.length - 1].path : '';
  }

  var dirDdIndex = -1;

  function getDirItems() {
    return dirDropdown.querySelectorAll('[data-path], [data-new]');
  }

  function highlightDirItem() {
    var items = getDirItems();
    items.forEach(function(el, i) {
      if (i === dirDdIndex) {
        el.classList.add('bg-gray-100', 'dark:bg-gray-700');
      } else {
        el.classList.remove('bg-gray-100', 'dark:bg-gray-700');
      }
    });
    if (items[dirDdIndex]) {
      items[dirDdIndex].scrollIntoView({ block: 'nearest' });
    }
  }

  function selectDirItem(el) {
    if (el.dataset.path) {
      segments.push({path: el.dataset.path, title: el.dataset.title});
      renderChips(); locationInput.value = ''; fetchSuggestions('');
    } else if (el.dataset.new) {
      var parentPath = currentParentPath();
      var slug = el.dataset.title.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '');
      var newPath = parentPath ? parentPath + '/' + slug : slug;
      segments.push({path: newPath, title: el.dataset.title, isNew: true});
      renderChips(); locationInput.value = ''; dirDropdown.classList.add('hidden'); locationInput.focus();
    }
  }

  function fetchSuggestions(query) {
    var parent = currentParentPath();
    var url = config.urls.dirSearch + '?parent=' + encodeURIComponent(parent);
    if (query) url += '&q=' + encodeURIComponent(query);
    fetch(url).then(function(r) { return r.ok ? r.json() : Promise.resolve([]); }).then(function(dirs) {
      if (!dirs.length && !query) { dirDropdown.classList.add('hidden'); return; }
      var html = '';
      dirs.forEach(function(d) {
        html += '<div class="px-3 py-2 cursor-pointer text-sm" data-path="' + escapeHtml(d.path) + '" data-title="' + escapeHtml(d.title) + '">' + escapeHtml(d.title) + '</div>';
      });
      if (query && !dirs.some(function(d) { return d.title.toLowerCase() === query.toLowerCase(); })) {
        html += '<div class="px-3 py-2 cursor-pointer text-sm text-primary-600 dark:text-primary-400" data-new="true" data-title="' + escapeHtml(query) + '">Create "' + escapeHtml(query) + '"</div>';
      }
      dirDropdown.innerHTML = html;
      dirDropdown.classList.remove('hidden');
      dirDdIndex = 0;
      highlightDirItem();
      var allItems = getDirItems();
      allItems.forEach(function(el, i) {
        el.addEventListener('mousedown', function(e) {
          e.preventDefault();
          selectDirItem(el);
        });
        el.addEventListener('mouseenter', function() {
          dirDdIndex = i;
          highlightDirItem();
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
    if (e.key === 'Backspace' && locationInput.value === '' && segments.length > 0) { segments.pop(); renderChips(); fetchSuggestions(''); return; }
    if (e.key === 'Escape') { dirDropdown.classList.add('hidden'); return; }

    var isOpen = !dirDropdown.classList.contains('hidden');
    if (!isOpen) return;
    var items = getDirItems();
    if (!items.length) return;

    if (e.key === 'ArrowDown') {
      e.preventDefault();
      if (dirDdIndex < items.length - 1) dirDdIndex++;
      highlightDirItem();
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      if (dirDdIndex > 0) dirDdIndex--;
      highlightDirItem();
    } else if (e.key === 'Enter') {
      e.preventDefault();
      if (dirDdIndex >= 0 && dirDdIndex < items.length) {
        selectDirItem(items[dirDdIndex]);
      }
    } else if (e.key === 'Tab' || e.key === '/') {
      e.preventDefault();
      if (dirDdIndex >= 0 && dirDdIndex < items.length) {
        selectDirItem(items[dirDdIndex]);
      }
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
    fetchUrl: config.urls.userSearch + '?q=',
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
    fetch(config.urls.checkPagePerms, {
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
