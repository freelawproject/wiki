(function() {
  var nav = document.getElementById('toc-nav');
  if (!nav) return;
  var headings = document.querySelectorAll('.wiki-content h2, .wiki-content h3, .wiki-content h4');
  if (!headings.length) return;

  var observer = new IntersectionObserver(function(entries) {
    entries.forEach(function(entry) {
      if (entry.isIntersecting) {
        var id = entry.target.id;
        if (!id) return;
        var links = nav.querySelectorAll('a');
        links.forEach(function(a) { a.classList.remove('toc-active'); });
        var match = nav.querySelector('a[href="#' + CSS.escape(id) + '"]');
        if (match) match.classList.add('toc-active');
      }
    });
  }, { rootMargin: '0px 0px -80% 0px' });

  headings.forEach(function(h) { observer.observe(h); });
})();
