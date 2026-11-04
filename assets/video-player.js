/** Prefer local MP4 when present; otherwise embed Scrimba EN/HI walkthroughs. */
(function () {
  function mount(el, lang) {
    lang = lang || 'en';
    var mp4 = el.getAttribute('data-mp4-' + lang) || el.getAttribute('data-mp4');
    var embed = el.getAttribute('data-embed-' + lang)
      || el.getAttribute('data-embed')
      || '';
    var title = el.getAttribute('data-title') || 'Demo video';
    if (!mp4 && !embed) return;

    function showEmbed() {
      if (!embed) {
        el.innerHTML = '<div class="video-fallback"><strong>' + title + '</strong><span>Add the MP4 at <code>' + (mp4 || '') + '</code>.</span></div>';
        return;
      }
      el.setAttribute('data-embed', embed);
      el.innerHTML = '<iframe src="' + embed + '" title="' + title + '" loading="eager" allow="fullscreen; autoplay" allowfullscreen referrerpolicy="strict-origin-when-cross-origin"></iframe>';
    }

    function showMp4() {
      el.innerHTML = '<video controls preload="metadata" playsinline><source src="' + mp4 + '" type="video/mp4"></video>';
      var v = el.querySelector('video');
      if (v) v.addEventListener('error', showEmbed);
    }

    if (!mp4) { showEmbed(); return; }
    fetch(mp4, { method: 'HEAD', cache: 'no-store' }).then(function (r) {
      var len = Number(r.headers.get('content-length') || 0);
      if (r.ok && len > 1000) showMp4();
      else showEmbed();
    }).catch(showEmbed);
  }

  document.querySelectorAll('[data-video-frame]').forEach(function (el) {
    mount(el, 'en');
  });

  document.querySelectorAll('[data-video-lang]').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var lang = btn.getAttribute('data-video-lang') || 'en';
      var targetId = btn.getAttribute('data-target');
      var frame = targetId ? document.getElementById(targetId) : btn.closest('.video-shell') && btn.closest('.video-shell').querySelector('[data-video-frame]');
      if (!frame) return;
      btn.parentElement.querySelectorAll('.lang-btn').forEach(function (b) { b.classList.remove('active'); });
      btn.classList.add('active');
      mount(frame, lang);
    });
  });
})();
