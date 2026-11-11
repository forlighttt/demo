(function () {
  var root = document.documentElement;
  var cfg = window.SITE || {};
  var bookingUrl = cfg.bookingUrl;
  var reduce = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;

  // Запуск анимации первого экрана
  requestAnimationFrame(function () { requestAnimationFrame(function () { root.classList.add('ready'); }); });

  // Плавное появление блоков при прокрутке
  var rv = document.querySelectorAll('.rv');
  if ('IntersectionObserver' in window && !reduce) {
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) { if (en.isIntersecting) { en.target.classList.add('in'); io.unobserve(en.target); } });
    }, { rootMargin: '0px 0px -8% 0px', threshold: 0.08 });
    rv.forEach(function (el) { io.observe(el); });
  } else {
    rv.forEach(function (el) { el.classList.add('in'); });
  }

  // Меню на телефоне
  var menuBtn = document.querySelector('.menu-btn');
  var nav = document.getElementById('site-nav');
  if (menuBtn && nav) {
    menuBtn.addEventListener('click', function () {
      var open = nav.classList.toggle('open');
      menuBtn.setAttribute('aria-expanded', open ? 'true' : 'false');
    });
    nav.addEventListener('click', function (e) { if (e.target.closest('a')) { nav.classList.remove('open'); menuBtn.setAttribute('aria-expanded', 'false'); } });
  }

  // Нижняя кнопка записи на телефоне появляется после первого экрана
  var sticky = document.querySelector('.sticky-cta');
  if (sticky) {
    var onScroll = function () { sticky.classList.toggle('show', window.scrollY > window.innerHeight * 0.6); };
    window.addEventListener('scroll', onScroll, { passive: true }); onScroll();
  }

  // Переключатель прайса «Собаки / Кошки»
  document.querySelectorAll('[role="tablist"]').forEach(function (list) {
    var tabs = list.querySelectorAll('[role="tab"]');
    tabs.forEach(function (t) {
      t.addEventListener('click', function () {
        tabs.forEach(function (x) {
          var on = x === t;
          x.setAttribute('aria-selected', on ? 'true' : 'false');
          var panel = document.getElementById(x.getAttribute('aria-controls'));
          if (panel) {
            panel.hidden = !on;
            if (on) panel.querySelectorAll('.rv').forEach(function (el) { el.classList.add('in'); });
          }
        });
      });
    });
  });

  // Слайдер «до и после»
  document.querySelectorAll('.ba input').forEach(function (inp) {
    var box = inp.closest('.ba');
    var set = function () { box.style.setProperty('--pos', inp.value + '%'); };
    inp.addEventListener('input', set); set();
  });

  function goal(name, params) {
    try { if (cfg.metrika && window.ym) window.ym(cfg.metrika, 'reachGoal', name, params || {}); } catch (e) {}
  }

  // Окно записи: форма bimassist открывается поверх сайта
  var modal = document.getElementById('booking');
  var frame = modal && modal.querySelector('iframe');
  var lastFocus = null;
  function openBooking(service) {
    goal('booking_open', service ? { service: service } : undefined);
    if (!modal || !frame || window.innerWidth < 340) { window.open(bookingUrl, '_blank', 'noopener'); return; }
    lastFocus = document.activeElement;
    if (!frame.getAttribute('src')) frame.setAttribute('src', bookingUrl);
    var label = modal.querySelector('[data-service-label]');
    if (label) label.textContent = service ? service : 'Онлайн-запись';
    modal.hidden = false;
    document.body.classList.add('no-scroll');
    modal.querySelector('.booking-close').focus();
  }
  function closeBooking() {
    if (!modal) return;
    modal.hidden = true;
    document.body.classList.remove('no-scroll');
    if (lastFocus && lastFocus.focus) lastFocus.focus();
  }
  document.addEventListener('click', function (e) {
    var a = e.target.closest('[data-book]');
    if (a) {
      if (e.ctrlKey || e.metaKey || e.shiftKey) return;
      e.preventDefault();
      openBooking(a.getAttribute('data-book') || '');
      return;
    }
    if (modal && !modal.hidden && (e.target === modal || e.target.closest('.booking-close'))) closeBooking();
    if (e.target.closest('a[href^="tel:"]')) goal('phone_click');
  });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && modal && !modal.hidden) closeBooking(); });
  if (location.hash === '#zapis') openBooking('');

  // «Сейчас открыто» по времени Краснодара (UTC+3)
  document.querySelectorAll('[data-open-from]').forEach(function (st) {
    var from = +st.getAttribute('data-open-from'), to = +st.getAttribute('data-open-to');
    var now = new Date(Date.now() + 3 * 3600 * 1000);
    var m = now.getUTCHours() * 60 + now.getUTCMinutes();
    var open = m >= from && m < to;
    var hh = function (x) { return String(Math.floor(x / 60)).padStart(2, '0') + ':' + String(x % 60).padStart(2, '0'); };
    var t = st.querySelector('[data-open-text]');
    if (t) t.textContent = open ? 'Открыто до ' + hh(to) : 'Откроемся в ' + hh(from);
    var d = st.querySelector('.dot'); if (d) d.classList.toggle('off', !open);
  });
})();
