/**
 * Username autocomplete for the permissions "Add Permission" form.
 *
 * Expects:
 *   #id_username  — text input
 *   #username-dropdown — dropdown container (sibling of input)
 */
(function() {
  var input = document.getElementById('id_username');
  var dropdown = document.getElementById('username-dropdown');
  if (!input || !dropdown) return;

  var timer = null;

  function search(query) {
    if (query.length < 1) { dropdown.classList.add('hidden'); return; }
    clearTimeout(timer);
    timer = setTimeout(function() {
      fetch('/api/user-search/?q=' + encodeURIComponent(query))
        .then(function(r) { return r.json(); })
        .then(function(results) {
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
            el.addEventListener('mousedown', function(e) {
              e.preventDefault();
              input.value = r.username;
              dropdown.classList.add('hidden');
            });
            dropdown.appendChild(el);
          });
          dropdown.classList.remove('hidden');
        });
    }, 150);
  }

  input.addEventListener('input', function() {
    search(input.value.trim());
  });

  input.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') dropdown.classList.add('hidden');
    if (e.key === 'Tab' && !dropdown.classList.contains('hidden')) {
      var first = dropdown.querySelector('div');
      if (first) { e.preventDefault(); first.dispatchEvent(new MouseEvent('mousedown', {bubbles: true})); }
    }
  });

  document.addEventListener('click', function(e) {
    if (!input.contains(e.target) && !dropdown.contains(e.target)) {
      dropdown.classList.add('hidden');
    }
  });
})();
