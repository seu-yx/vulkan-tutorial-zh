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
