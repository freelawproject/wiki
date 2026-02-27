/**
 * Code block enhancements: syntax highlighting + copy button.
 *
 * Loaded on page/directory detail views after highlight.js.
 * Runs after DOM is ready — wraps each <pre> in a container and
 * injects a copy button, then applies highlight.js.
 */
document.addEventListener('DOMContentLoaded', function () {
  var blocks = document.querySelectorAll('.wiki-content pre code');

  blocks.forEach(function (code) {
    // Syntax highlighting
    hljs.highlightElement(code);

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
  });
});
