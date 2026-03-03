/**
 * Generic mention/autocomplete dropdown helper.
 *
 * Shared by markdown-editor.js (CodeMirror @-mention) and
 * page-form.js (change-message @-mention).
 */
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
