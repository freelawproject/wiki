(function() {
  var headings = document.querySelectorAll(
    '.wiki-content h1[id], .wiki-content h2[id], .wiki-content h3[id], ' +
    '.wiki-content h4[id], .wiki-content h5[id], .wiki-content h6[id]'
  );
  headings.forEach(function(h) {
    var link = document.createElement('a');
    link.href = '#' + h.id;
    link.className = 'heading-anchor';
    link.setAttribute('aria-label', 'Link to this section');
    link.textContent = '\u00B6';
    h.appendChild(link);
  });
})();
