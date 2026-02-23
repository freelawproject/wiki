(function() {
  var config = JSON.parse(
    document.getElementById('history-config').textContent
  );
  document.getElementById('compare-btn').addEventListener('click', function() {
    var v1 = document.querySelector('input[name="v1"]:checked');
    var v2 = document.querySelector('input[name="v2"]:checked');
    if (v1 && v2) {
      window.location.href = config.diffBase + v1.value + '/' + v2.value + '/';
    }
  });
})();
