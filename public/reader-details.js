(() => {
  'use strict';
  const progress = document.getElementById('reading-progress');
  const article = document.getElementById('article-content');
  if (!progress || !article) return;
  let queued = false;
  function update() {
    queued = false;
    const loading = article.getAttribute('aria-busy') === 'true' || !!article.querySelector('.error-state');
    progress.hidden = loading;
    if (loading) return;
    const top = document.querySelector('.site-header').getBoundingClientRect().bottom;
    const rect = article.getBoundingClientRect();
    const travel = rect.height - (innerHeight - top);
    const fraction = travel > 0 ? Math.max(0, Math.min(1, (top - rect.top) / travel)) : rect.bottom <= innerHeight ? 1 : 0;
    const percent = Math.round(fraction * 100);
    progress.style.setProperty('--reading-progress', String(fraction));
    progress.setAttribute('aria-valuenow', String(percent));
    progress.setAttribute('aria-valuetext', `${percent}% 已阅读`);
  }
  function schedule() {
    if (!queued) { queued = true; requestAnimationFrame(update); }
  }
  addEventListener('scroll', schedule, {passive: true});
  addEventListener('resize', schedule, {passive: true});
  new MutationObserver(schedule).observe(article, {childList: true, attributes: true, attributeFilter: ['aria-busy']});
  if ('ResizeObserver' in window) new ResizeObserver(schedule).observe(article);
  schedule();
})();

(() => {
  'use strict';
  const sidebar = document.getElementById('sidebar');
  const resizer = document.getElementById('sidebar-resizer');
  if (!sidebar || !resizer) return;
  const root = document.documentElement;
  const desktop = matchMedia('(min-width: 1000px)');
  const storageKey = 'vt-sidebar-width';
  let preferredWidth = null;
  let drag = null;
  try {
    const saved = Number(localStorage.getItem(storageKey));
    if (Number.isFinite(saved) && saved >= 220 && saved <= 560) preferredWidth = saved;
  } catch {}

  const maximumWidth = () => Math.min(560, innerWidth - 560);
  const clampWidth = width => Math.round(Math.max(220, Math.min(maximumWidth(), width)));
  function persist() {
    try {
      if (preferredWidth === null) localStorage.removeItem(storageKey);
      else localStorage.setItem(storageKey, String(preferredWidth));
    } catch {}
  }
  function update() {
    resizer.hidden = !desktop.matches;
    if (desktop.matches && preferredWidth !== null) root.style.setProperty('--sidebar-width', `${clampWidth(preferredWidth)}px`);
    else root.style.removeProperty('--sidebar-width');
    if (!desktop.matches) return;
    const width = Math.round(sidebar.getBoundingClientRect().width);
    resizer.setAttribute('aria-valuemin', '220');
    resizer.setAttribute('aria-valuemax', String(maximumWidth()));
    resizer.setAttribute('aria-valuenow', String(width));
    resizer.setAttribute('aria-valuetext', `${width} 像素`);
  }
  function resize(width) {
    preferredWidth = clampWidth(width);
    update();
  }
  function finishDrag(cancel = false) {
    if (!drag) return;
    const previous = drag;
    drag = null;
    document.body.classList.remove('sidebar-resizing');
    if (cancel) preferredWidth = previous.preferredWidth;
    if (resizer.hasPointerCapture(previous.pointerId)) resizer.releasePointerCapture(previous.pointerId);
    update();
    persist();
  }
  resizer.addEventListener('pointerdown', event => {
    if (!desktop.matches || root.dataset.sidebar === 'collapsed' || !event.isPrimary || event.button !== 0) return;
    event.preventDefault();
    drag = { pointerId: event.pointerId, startX: event.clientX, startWidth: sidebar.getBoundingClientRect().width, preferredWidth };
    resizer.focus({ preventScroll: true });
    resizer.setPointerCapture(event.pointerId);
    document.body.classList.add('sidebar-resizing');
  });
  resizer.addEventListener('pointermove', event => {
    if (drag && event.pointerId === drag.pointerId) resize(drag.startWidth + event.clientX - drag.startX);
  });
  resizer.addEventListener('pointerup', event => { if (drag?.pointerId === event.pointerId) finishDrag(); });
  resizer.addEventListener('pointercancel', event => { if (drag?.pointerId === event.pointerId) finishDrag(true); });
  resizer.addEventListener('lostpointercapture', event => { if (drag?.pointerId === event.pointerId) finishDrag(); });
  resizer.addEventListener('dblclick', () => {
    if (!desktop.matches) return;
    preferredWidth = null;
    update();
    persist();
  });
  resizer.addEventListener('keydown', event => {
    if (!desktop.matches) return;
    if (event.key === 'Escape' && drag) { event.preventDefault(); finishDrag(true); return; }
    const width = sidebar.getBoundingClientRect().width;
    const step = event.shiftKey ? 40 : 16;
    const next = { ArrowLeft: width - step, ArrowRight: width + step, Home: 220, End: maximumWidth() }[event.key];
    if (next === undefined) return;
    event.preventDefault();
    resize(next);
    persist();
  });
  addEventListener('resize', () => {
    if (!desktop.matches && drag) finishDrag(true);
    update();
  }, { passive: true });
  update();
})();
