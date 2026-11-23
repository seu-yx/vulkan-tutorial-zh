// Read saved preferences before painting the reader; compatible with script-src 'self'.
try {
  const theme = localStorage.getItem('vt-theme');
  const mode = localStorage.getItem('vt-mode');
  document.documentElement.dataset.sidebar = localStorage.getItem('vt-sidebar-collapsed') === 'true' ? 'collapsed' : 'expanded';
  const sidebarWidth = Number(localStorage.getItem('vt-sidebar-width'));
  if (matchMedia('(min-width: 1000px)').matches && Number.isFinite(sidebarWidth) && sidebarWidth >= 220 && sidebarWidth <= 560) document.documentElement.style.setProperty('--sidebar-width', `${Math.min(sidebarWidth, 560, innerWidth - 560)}px`);
  document.documentElement.dataset.theme = theme === 'dark' || theme === 'light' ? theme : matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  document.documentElement.dataset.mode = ['zh', 'en', 'dual'].includes(mode) ? mode : 'zh';
} catch {}
