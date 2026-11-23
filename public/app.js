(() => {
  'use strict';
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  // Resolve against this script, so the same build works at / and /repository/.
  const siteBase = new URL('./', document.currentScript?.src || document.baseURI);
  const siteHref = path => new URL(path, siteBase).href;
  const rebaseMirrorHref = address => {
    if (address.startsWith('/assets/')) return siteHref(address.slice(1));
    if (address.startsWith('/?page=')) return `${siteBase.pathname}${address.slice(1)}`;
    return address;
  };
  function rebaseContent(content) {
    // Rebase cached markup before insertion, avoiding requests to the host root.
    // Hosting changes never alter protected markup in the Google cache.
    $$('[href], [src], [poster]', content).forEach(element => {
      ['href', 'src', 'poster'].forEach(attribute => {
        const address = element.getAttribute(attribute);
        if (address) element.setAttribute(attribute, rebaseMirrorHref(address));
      });
    });
  }
  const storage = { get(key, fallback) { try { return localStorage.getItem(key) ?? fallback; } catch { return fallback; } }, set(key, value) { try { localStorage.setItem(key, value); } catch {} } };
  function readGroupPreferences() {
    const preferences = Object.create(null);
    try {
      const saved = JSON.parse(storage.get('vt-nav-groups', '{}'));
      if (saved && typeof saved === 'object' && !Array.isArray(saved)) Object.entries(saved).forEach(([name, open]) => { if (typeof open === 'boolean') preferences[name] = open; });
    } catch {}
    return preferences;
  }
  const state = { catalog: null, navigation: null, page: null, mode: ['zh', 'en', 'dual'].includes(storage.get('vt-mode', 'zh')) ? storage.get('vt-mode', 'zh') : 'zh', terms: storage.get('vt-terms', 'false') === 'true', sidebarCollapsed: storage.get('vt-sidebar-collapsed', 'false') === 'true', navGroups: readGroupPreferences(), navDefaults: new Map(), navSearchScroll: null, query: '', request: 0 };
  let observer;
  let toastTimer;
  async function fetchDocument(url) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 30000);
    try {
      const response = await fetch(url, { cache: 'no-cache', signal: controller.signal });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return await response.json();
    } finally { clearTimeout(timer); }
  }
  const displayTitle = page => state.mode === 'en' ? page.title || page.titleZh || page.id : page.titleZh || page.title || page.id;
  const groupTranslations = { 'Introduction': '简介', 'Overview': '概览', 'Build and development environment': '构建与开发环境', 'Drawing a triangle': '绘制三角形', 'Vertex buffers': '顶点缓冲区', 'Uniform buffers': '统一缓冲区', 'Texture mapping': '纹理映射', 'Depth buffering': '深度缓冲', 'Loading models': '加载模型', 'Generating Mipmaps': '生成 Mipmap', 'Multisampling': '多重采样', 'Compute Shader': '计算着色器', 'Ecosystem Utilities and GPU Compatibility': '生态工具与 GPU 兼容性', 'Vulkan Profiles': 'Vulkan Profiles', 'Android': 'Android', 'Migrating to Modern Asset Formats: glTF and KTX2': '现代资产格式：glTF 与 KTX2', 'Rendering Multiple Objects': '渲染多个对象', 'Multithreading': '多线程', 'Conclusion': '结语', 'Ray Tracing': '光线追踪', 'How to write a Vulkan application in 2026': '2026 年的 Vulkan 应用开发', 'Building a Simple Engine': '构建简单引擎', 'AI-Assisted Vulkan Development': 'AI 辅助 Vulkan 开发', 'Advanced Vulkan Compute': '进阶 Vulkan 计算', 'Advanced glTF': '进阶 glTF', 'Machine Learning Inference': '机器学习推理', 'Vulkan for XR': '面向 XR 的 Vulkan', 'Synchronization': '同步' };
  const groupTitle = name => state.mode === 'en' ? name : groupTranslations[name] || name;
  Object.assign(groupTranslations, {
    'Setup': '基础设置', 'Presentation': '呈现', 'Graphics pipeline basics': '图形管线基础', 'Drawing': '绘制',
    'Engine Architecture': '引擎架构', 'Camera Transformations': '相机变换', 'Lighting & Materials': '光照与材质',
    'GUI': '图形界面', 'Loading Models': '加载模型', 'Subsystems': '子系统', 'Tooling': '开发工具',
    'Mobile Development': '移动端开发', 'Extra Courses': '扩展课程', 'Opacity Micromaps': '不透明度微映射',
    'Advanced Topics': '进阶主题', 'Appendix': '附录', 'Environment Setup': '环境配置',
    'Model Selection & Specialization': '模型选择与专用化', 'Multimodal AI': '多模态 AI', 'Workflow': '工作流程',
    'Debugging': '调试', 'Advanced MCP Tooling': '进阶 MCP 工具', 'Deployment': '部署',
    'The Compute Architecture and Execution Model': '计算架构与执行模型', 'Memory Models and Consistency': '内存模型与一致性',
    'Subgroup Operations: The Hidden Power': '子组操作：隐藏的力量', 'Heterogeneous Ecosystem: OpenCL on Vulkan': '异构生态：在 Vulkan 上运行 OpenCL',
    'Advanced Data Structures on the GPU': 'GPU 进阶数据结构', 'Indirect Dispatch and GPU-Driven Pipelines': '间接分派与 GPU 驱动管线',
    'Asynchronous Compute Orchestration': '异步计算编排', 'Cooperative Matrices and Specialized Math': '协作矩阵与专用数学运算',
    'Performance Auditing and Optimization': '性能审查与优化', 'Diagnostics and AI-Assisted Compute Refinement': '诊断与 AI 辅助计算优化',
    'Mobile and Embedded Compute': '移动端与嵌入式计算', 'Synchronization 2': 'Synchronization 2 同步',
    'Anatomy of a Dependency': '依赖关系解析', 'Pipeline Barriers and Transitions': '管线屏障与状态转换',
    'Timeline Semaphores': '时间线信号量', 'Frame-in-Flight Architecture': '多帧并行架构',
    'Asynchronous Compute & Overlap': '异步计算与重叠执行', 'Transfer Queues & Asset Streaming Sync': '传输队列与资产流式加载同步',
    'Synchronization in Dynamic Rendering': '动态渲染中的同步', 'Host Image Copies & Memory Mapped Sync': '主机图像复制与内存映射同步',
    'Debugging with Synchronization Validation': '使用同步验证进行调试', 'Profiling, Batching, and Optimization': '性能分析、批处理与优化',
    'Advanced glTF: High-Performance Character Pipelines': '进阶 glTF：高性能角色管线',
    'Scene Graph & Transform Hierarchy': '场景图与变换层级', 'Skeletal & Compute Skinning': '骨骼与计算蒙皮',
    'Physics Integration': '物理系统集成', 'Procedural Animation & IK': '程序化动画与逆运动学',
    'Morph Targets & Facial Animation': '变形目标与面部动画', 'Tooling & Production Pipeline': '工具与制作管线',
    'Debugging & Visual Auditing': '调试与可视化审查', 'ML Inference Pipeline': '机器学习推理管线',
    'Integrating Third-Party ML Libraries': '集成第三方机器学习库', 'Vulkan Compute for ML': '用于机器学习的 Vulkan 计算',
    'Building the Inference Engine': '构建推理引擎', 'Debugging and Performance': '调试与性能',
    'Desktop Applications': '桌面应用', 'Embedded Applications': '嵌入式应用',
    'OpenXR and Vulkan 1.3 Spatial Computing': 'OpenXR 与 Vulkan 1.3 空间计算',
    'The OpenXR-Vulkan 1.3 Handshake': 'OpenXR 与 Vulkan 1.3 的协同初始化', 'Runtime-Owned Swapchains': '运行时管理的交换链',
    'Dynamic Rendering for Spatial Views': '空间视图的动态渲染', 'The Predictive Frame Loop': '预测式帧循环',
    'Late Latching': 'Late Latching 延迟锁存', 'Action Spaces and Input': '动作空间与输入',
    'Slang for Spatial Shaders': '使用 Slang 编写空间着色器', 'Quad-Views and Foveated Rendering': '四视图与注视点渲染',
    'Variable Rate Shading': '可变速率着色', 'Canted Displays': '倾斜式显示器', 'CAVE Architecture': 'CAVE 架构',
    'Warp and Blend': '图像变形与融合', 'LightField Theory': '光场理论', 'Plenoptic Synthesis': '全光合成',
    'Scene Understanding': '场景理解', 'ML Inference for Spatial Data': '空间数据的机器学习推理',
    'Semantic Occlusion': '语义遮挡', 'Platform Divergence': '平台差异', 'Spatial Diagnostics': '空间诊断'
  });
  function buildNavigationTree(catalog) {
    const pages = new Map((catalog.pages || []).map(page => [page.id, page]));
    const roots = [], stack = [], used = new Set();
    const entries = Array.isArray(catalog.navigation) ? catalog.navigation : [];
    for (const entry of entries) {
      if (!entry || typeof entry.title !== 'string') continue;
      const depth = Math.max(1, Number(entry.depth) || 1);
      while (stack.length && stack.at(-1).depth >= depth) stack.pop();
      const parent = stack.at(-1)?.node;
      const page = pages.get(entry.id);
      if (page) used.add(page.id);
      const node = {title: entry.title, titleZh: entry.titleZh, page, children: [], key: `${parent?.key || 'nav'}|${entry.id || ''}:${entry.title}`};
      (parent ? parent.children : roots).push(node);
      stack.push({depth, node});
    }
    // Older catalogs and source pages outside the official menu remain reachable.
    const groups = new Map(), folders = new Map();
    for (const page of pages.values()) {
      if (used.has(page.id)) continue;
      const name = entries.length ? '更多专题' : page.group || '教程章节';
      if (!groups.has(name)) {
        const node = {title: name, children: [], key: `fallback:${name}`};
        groups.set(name, node); roots.push(node);
      }
      let parent = groups.get(name), prefix = '';
      for (const part of page.id.split('/').slice(0, -1)) {
        prefix += `/${part}`;
        const key = `fallback:${name}${prefix}`;
        if (!folders.has(key)) {
          const node = {title: part.replace(/^\d+_/, '').replaceAll('_', ' '), children: [], key};
          folders.set(key, node); parent.children.push(node);
        }
        parent = folders.get(key);
      }
      parent.children.push({title: page.title, page, children: [], key: `${parent.key}|${page.id}`});
    }
    function complete(node) {
      node.children = node.children.map(complete).filter(child => child.ids.size);
      const ids = new Set(node.children.flatMap(child => [...child.ids]));
      if (node.page && node.children.length && !ids.has(node.page.id)) {
        node.children.unshift({title: node.page.title, page: node.page, children: [], ids: new Set([node.page.id]), key: `${node.key}|page`});
      }
      if (node.page) ids.add(node.page.id);
      node.ids = ids;
      return node;
    }
    return roots.map(complete).filter(node => node.ids.size);
  }
  function filterNavigationTree(nodes, query) {
    if (!query) return nodes;
    const compact = query.replace(/[\s_\-]/g, '');
    const matches = node => {
      const text = `${node.title || ''} ${node.titleZh || ''} ${groupTranslations[node.title] || ''} ${node.children.length ? '' : `${node.page?.title || ''} ${node.page?.titleZh || ''} ${node.page?.id || ''}`}`.toLocaleLowerCase();
      return text.includes(query) || text.replace(/[\s_\-]/g, '').includes(compact);
    };
    function visit(node, parentMatches) {
      const matched = parentMatches || matches(node);
      const children = node.children.map(child => visit(child, matched)).filter(Boolean);
      if (!matched && !children.length) return null;
      const ids = new Set(children.flatMap(child => [...child.ids]));
      if (node.page && matched) ids.add(node.page.id);
      if (!ids.size) return null;
      return {...node, children, ids};
    }
    return nodes.map(node => visit(node, false)).filter(Boolean);
  }
  function visitNavigation(nodes, callback) { nodes.forEach(node => { callback(node); visitNavigation(node.children, callback); }); }
  const pageHref = id => `${siteBase.pathname}?page=${encodeURIComponent(id)}`;
  const formatTime = value => { const date = new Date(value); return Number.isNaN(date.getTime()) ? '暂未同步' : new Intl.DateTimeFormat('zh-CN', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }).format(date); };
  function notify(message) { $('#toast').textContent = message; $('#toast').hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => { $('#toast').hidden = true; }, 2300); }
  function syncSidebarAccess() {
    const compact = matchMedia('(max-width: 999px)').matches;
    const closed = compact ? !document.body.classList.contains('menu-open') : state.sidebarCollapsed;
    const sidebar = $('#sidebar');
    const toggle = $('#menu-toggle');
    if (closed && sidebar.contains(document.activeElement)) toggle.focus({ preventScroll: true });
    sidebar.inert = closed;
    const label = compact ? closed ? '打开章节目录' : '关闭章节目录' : closed ? '展开侧栏' : '收起侧栏';
    toggle.setAttribute('aria-expanded', String(!closed)); toggle.setAttribute('aria-label', label); toggle.title = label;
  }
  function setMenu(open) { open = matchMedia('(max-width: 999px)').matches && open; document.body.classList.toggle('menu-open', open); $('#menu-scrim').hidden = !open; syncSidebarAccess(); }
  function setSidebarCollapsed(collapsed, persist = true) {
    state.sidebarCollapsed = !!collapsed; document.documentElement.dataset.sidebar = collapsed ? 'collapsed' : 'expanded';
    if (persist) storage.set('vt-sidebar-collapsed', String(state.sidebarCollapsed));
    syncSidebarAccess();
  }
  function revealSidebar() { if (matchMedia('(max-width: 999px)').matches) setMenu(true); else setSidebarCollapsed(false); }
  function setSearchOpen(open, focus = false) {
    const compact = matchMedia('(max-width: 1100px)').matches;
    if (compact && !open && $('#header-search')?.contains(document.activeElement)) $('#search-toggle')?.focus({preventScroll: true});
    document.body.classList.toggle('search-open', compact && open);
    $('#search-toggle')?.setAttribute('aria-expanded', String(compact && open));
    if (focus) $('#chapter-search').focus({preventScroll: true});
  }
  function saveGroupPreferences() { storage.set('vt-nav-groups', JSON.stringify(state.navGroups)); }
  function clearSearch(render = true) {
    state.query = ''; $('#chapter-search').value = '';
    if ($('#search-clear')) $('#search-clear').hidden = true;
    if (render && state.catalog) renderNavigation();
  }
  function setAllGroups(open) {
    if (!state.catalog) return;
    // Search only changes the temporary results view, never saved group choices.
    if (state.query.trim()) { $$('.nav-group', $('#chapter-nav')).forEach(section => { section.open = open; }); return; }
    visitNavigation(state.navigation, node => { if (node.children.length) state.navGroups[node.key] = open; });
    saveGroupPreferences(); renderNavigation();
  }
  function locateCurrentChapter() {
    if (!state.page || !state.catalog) return;
    const current = state.catalog.pages.find(page => page.id === state.page.id);
    if (!current) return;
    clearSearch(false); visitNavigation(state.navigation, node => { if (node.children.length && node.ids.has(current.id)) state.navGroups[node.key] = true; }); saveGroupPreferences(); revealSidebar(); renderNavigation();
    requestAnimationFrame(() => {
      const nav = $('#chapter-nav'), active = $('a[aria-current="page"]', nav);
      if (!active) return;
      const navRect = nav.getBoundingClientRect(), linkRect = active.getBoundingClientRect();
      const top = Math.max(0, nav.scrollTop + linkRect.top - navRect.top - (nav.clientHeight - linkRect.height) / 2);
      nav.scrollTo({ top, behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
      active.focus({ preventScroll: true });
    });
  }
  function setMode(mode) {
    state.mode = mode; storage.set('vt-mode', mode); document.documentElement.dataset.mode = mode; document.documentElement.lang = mode === 'en' ? 'en' : 'zh-CN';
    $$('.mode-button').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.mode === mode)));
    if (state.catalog) renderNavigation();
    if (state.page) { updatePageHeading(); buildToc(); updatePageLinks(); }
  }
  function applyTerms() {
    $$('#article-content .vt-zh .vt-term, #article-title .vt-term').forEach(term => {
      if (!term.dataset.originalZh) term.dataset.originalZh = term.textContent;
      const english = term.dataset.term || term.dataset.english || term.title;
      if (english) term.textContent = state.terms ? english : term.dataset.originalZh;
      term.tabIndex = 0;
      if (english) { term.title = english; term.setAttribute('aria-label', `${term.textContent}（${english}）`); }
    });
    if (state.page) buildToc();
  }
  function renderNavigation() {
    const nav = $('#chapter-nav'); let scrollTop = nav.scrollTop; nav.replaceChildren();
    const pages = state.catalog.pages || [];
    const query = state.query.trim().toLocaleLowerCase();
    if (query && state.navSearchScroll === null) state.navSearchScroll = scrollTop;
    if (!query && state.navSearchScroll !== null) { scrollTop = state.navSearchScroll; state.navSearchScroll = null; }
    if ($('#search-clear')) $('#search-clear').hidden = !state.query.length;
    const nodes = filterNavigationTree(state.navigation, query);
    const matchedIds = new Set(nodes.flatMap(node => [...node.ids]));
    $('#search-summary').textContent = query ? `${matchedIds.size} 个匹配章节` : `${pages.length} 篇教程`;
    if (!nodes.length) { const message = document.createElement('p'); message.className = 'empty-search'; message.textContent = '没有找到匹配章节，试试英文术语。'; nav.append(message); nav.scrollTop = scrollTop; return; }
    const initialPage = state.page?.id || new URLSearchParams(location.search).get('page') || pages.find(page => page.id === '00_Introduction')?.id || pages[0]?.id;
    function renderNodes(items, depth = 0) {
      const list = document.createElement('ul'); list.className = depth ? 'nav-children' : 'nav-tree';
      items.forEach(node => {
        const li = document.createElement('li');
        if (node.children.length) {
          if (!query && !state.navDefaults.has(node.key)) state.navDefaults.set(node.key, node.ids.has(initialPage));
          const preferredOpen = Object.hasOwn(state.navGroups, node.key) ? state.navGroups[node.key] : state.navDefaults.get(node.key) || false;
          const section = document.createElement('details'); section.className = 'nav-group'; section.dataset.group = node.key; section.dataset.depth = String(depth); section.open = !!query || preferredOpen;
          let displayedOpen = section.open;
          section.addEventListener('toggle', event => {
            if (event.target !== section || !section.isConnected || section.open === displayedOpen) return;
            displayedOpen = section.open;
            if (state.query.trim()) return;
            state.navGroups[node.key] = section.open; saveGroupPreferences();
          });
          const summary = document.createElement('summary'); const label = document.createElement('span'); label.className = 'nav-label'; label.textContent = state.mode === 'en' ? node.title : node.titleZh || groupTitle(node.title); label.title = node.title; summary.append(label);
          const count = document.createElement('span'); count.className = 'group-count'; count.textContent = String(node.ids.size); summary.append(count); section.append(summary, renderNodes(node.children, depth + 1)); li.append(section);
        } else if (node.page) {
          const page = node.page; const link = document.createElement('a'); link.href = pageHref(page.id); link.dataset.page = page.id; link.textContent = displayTitle(page); link.title = `${page.titleZh || ''}${page.titleZh ? ' · ' : ''}${page.title || ''}`; link.style.setProperty('--depth', 0);
          if (page.id === state.page?.id) { link.classList.add('active'); link.setAttribute('aria-current', 'page'); }
          li.append(link);
        }
        list.append(li);
      });
      return list;
    }
    nav.append(renderNodes(nodes));
    nav.scrollTop = scrollTop;
  }
  function updatePageHeading() {
    const page = state.page; const title = displayTitle(page);
    if (state.mode !== 'en' && page.titleZhHtml) $('#article-title').innerHTML = page.titleZhHtml;
    else $('#article-title').textContent = title;
    $('#breadcrumb-current').textContent = title; $('#article-group').textContent = groupTitle(page.group || state.catalog?.pages.find(item => item.id === page.id)?.group || 'VULKAN TUTORIAL');
    $('#article-subtitle').textContent = state.mode !== 'en' && page.titleZh && page.titleZh !== page.title ? page.title : '';
    $('#article-subtitle').hidden = !$('#article-subtitle').textContent;
    $('#original-link').href = page.originalUrl || `https://docs.vulkan.org/tutorial/latest/${page.id.split('/').map(encodeURIComponent).join('/')}.html`;
    $('#source-link').href = page.sourceUrl || `https://github.com/KhronosGroup/Vulkan-Tutorial/blob/main/en/${page.id.split('/').map(encodeURIComponent).join('/')}.adoc`;
    document.title = `${title} · Vulkan 教程中文镜像`;
    const englishText = $$('.vt-en', $('#article-content')).map(element => element.textContent).join(' ');
    const wordCount = englishText ? englishText.split(/\s+/).length : $('#article-content').textContent.split(/\s+/).length;
    $('#reading-time').textContent = `约 ${Math.max(1, Math.ceil(wordCount / 220))} 分钟阅读`;
    const translated = Number(page.translated ?? page.stats?.translated ?? 0), total = Number(page.total ?? page.stats?.total ?? 0);
    $('#translation-status').textContent = total ? `Google 翻译 · ${Math.min(translated < total ? 99 : 100, Math.floor(translated / total * 100))}% 已翻译` : 'Google 翻译 · 可随时对照原文';
    const pending = total > translated;
    const notice = $('#notice'); notice.hidden = !pending;
    if (pending) notice.textContent = '本章翻译正在补全，尚未翻译的段落保留英文。你可以随时切换到英文或中英对照阅读。';
    const license = typeof page.license === 'string' ? page.license.trim() : '';
    const copyright = Array.isArray(page.copyright) ? page.copyright.filter(value => typeof value === 'string' && value.trim()) : [];
    $('#page-attribution').hidden = !license && !copyright.length;
    $('#page-license').hidden = !license;
    $('#page-license').textContent = license ? `本章许可：${license}` : '';
    $('#page-copyright').hidden = !copyright.length;
    $('#page-copyright').textContent = copyright.join('\n');
    applyTerms();
  }
  function buildToc() {
    if (observer) observer.disconnect();
    const nav = $('#toc-nav'); nav.replaceChildren();
    const content = $('#article-content');
    // Translation clones carry the source heading ID. Keep that ID on the
    // visible heading, so both source cross-links and the TOC scroll correctly.
    const allHeadings = $$('h2, h3, h4, h5, h6', content);
    allHeadings.forEach((heading, index) => {
      const pair = heading.closest('.vt-pair');
      const english = pair?.querySelector('h2.vt-en, h3.vt-en, h4.vt-en, h5.vt-en, h6.vt-en');
      heading.dataset.vtAnchor ||= english?.dataset.vtAnchor || english?.id || heading.id || `section-${index + 1}`;
    });
    allHeadings.forEach((heading, index) => { heading.id = `${heading.dataset.vtAnchor}--vt-${index}`; });
    const visibleHeadings = allHeadings.filter(heading => {
      if (heading.closest('.vt-zh') && state.mode === 'en') return false;
      if (heading.closest('.vt-en') && state.mode !== 'en' && !heading.closest('.vt-pending') && heading.closest('.vt-pair')?.querySelector('.vt-zh')) return false;
      return true;
    });
    const anchorIds = new Set();
    visibleHeadings.forEach((heading, index) => {
      let id = heading.dataset.vtAnchor;
      if (anchorIds.has(id)) id = `${id}-${index}`;
      anchorIds.add(id); heading.id = id;
    });
    const headings = visibleHeadings.filter(heading => heading.tagName === 'H2' || heading.tagName === 'H3');
    const usedIds = new Set();
    headings.forEach((heading, index) => {
      let id = heading.id || `section-${index + 1}`;
      if (usedIds.has(id)) id = `${id}-${index}`;
      usedIds.add(id); heading.id = id;
      const link = document.createElement('a'); link.href = `#${encodeURIComponent(id)}`; link.textContent = heading.textContent; link.className = heading.tagName === 'H3' ? 'toc-nested' : ''; link.dataset.target = id; nav.append(link);
    });
    $('.toc').classList.toggle('no-headings', !headings.length);
    if ('IntersectionObserver' in window) {
      observer = new IntersectionObserver(entries => {
        const entry = entries.find(item => item.isIntersecting); if (!entry) return;
        $$('a', nav).forEach(link => link.classList.toggle('active', link.dataset.target === entry.target.id));
      }, { rootMargin: '-100px 0px -65% 0px', threshold: 0 });
      headings.forEach(heading => observer.observe(heading));
    }
  }
  function updatePageLinks() {
    const index = state.catalog.pages.findIndex(page => page.id === state.page.id);
    [['previous-page', state.catalog.pages[index - 1]], ['next-page', state.catalog.pages[index + 1]]].forEach(([id, page]) => {
      const link = $(`#${id}`); link.hidden = !page;
      if (page) { link.href = pageHref(page.id); link.dataset.page = page.id; $('.page-nav-title', link).textContent = displayTitle(page); }
    });
  }
  function prepareContent() {
    const content = $('#article-content');
    window.VulkanSyntax?.highlight(content);
    // Asciidoctor document headers are already represented by the reader header.
    $$('h1', content).forEach(heading => { if (heading.textContent.trim() === state.page.title?.trim() || heading.textContent.trim() === state.page.titleZh?.trim()) { const pair = heading.closest('.vt-pair'); if (pair) pair.classList.add('duplicate-title'); else heading.classList.add('duplicate-title'); } });
    $$('pre', content).forEach(pre => {
      const button = document.createElement('button'); button.className = 'copy-code'; button.type = 'button'; button.textContent = '复制'; button.setAttribute('aria-label', '复制代码');
      button.addEventListener('click', async () => {
        try { await navigator.clipboard.writeText($('code', pre)?.textContent || [...pre.childNodes].filter(node => node !== button).map(node => node.textContent).join('')); button.textContent = '已复制'; setTimeout(() => { button.textContent = '复制'; }, 1800); }
        catch { notify('无法访问剪贴板，请选择代码后复制。'); }
      }); pre.append(button);
    });
    $$('a', content).forEach(link => { if (/^https?:\/\//.test(link.href) && new URL(link.href).origin !== location.origin) { link.target = '_blank'; link.rel = 'noopener noreferrer'; } });
    $$('img', content).forEach(image => { image.loading = 'lazy'; image.decoding = 'async'; });
    applyTerms();
  }
  async function loadPage(id, options = {}) {
    const token = ++state.request;
    const pageInfo = state.catalog.pages.find(page => page.id === id);
    if (!pageInfo) { showError('没有找到这个章节', '该章节可能已更名或被上游移除，请从左侧目录选择章节。'); return; }
    setMenu(false); setSearchOpen(false); $('#article-content').setAttribute('aria-busy', 'true'); $('#article-content').classList.add('is-loading');
    try {
      const path = id.split('/').map(encodeURIComponent).join('/');
      const page = await fetchDocument(siteHref(`data/pages/${path}.json`)); if (token !== state.request) return;
      state.page = { ...pageInfo, ...page };
      const template = document.createElement('template'); template.innerHTML = page.html;
      rebaseContent(template.content); $('#article-content').replaceChildren(template.content);
      $('#article-content').setAttribute('aria-busy', 'false'); $('#article-content').classList.remove('is-loading');
      prepareContent(); updatePageHeading(); renderNavigation(); updatePageLinks(); buildToc();
      if (options.push) history.pushState({ page: id }, '', `${pageHref(id)}${options.hash || ''}`);
      if (options.scroll !== false) window.scrollTo({ top: 0, behavior: 'instant' });
      const hash = location.hash.slice(1); if (hash) { let decoded = hash; try { decoded = decodeURIComponent(hash); } catch {} requestAnimationFrame(() => document.getElementById(decoded)?.scrollIntoView()); }
    } catch (error) { if (token === state.request) showError('章节暂时无法加载', '请检查网络后重试，或通过上方链接阅读官方原文。', () => loadPage(id, options)); }
  }
  function showError(title, message, retry) {
    const content = $('#article-content'); content.replaceChildren(); content.classList.remove('is-loading'); content.setAttribute('aria-busy', 'false'); $('#article-title').textContent = title; $('#notice').hidden = true;
    const section = document.createElement('div'); section.className = 'error-state'; const p = document.createElement('p'); p.textContent = message; section.append(p);
    if (retry) { const button = document.createElement('button'); button.className = 'primary-button'; button.textContent = '重新加载'; button.addEventListener('click', retry); section.append(button); }
    content.append(section);
  }
  function updateSyncInfo() {
    const { upstream = {}, translation = {} } = state.catalog;
    $('#sync-time').textContent = upstream.syncedAt ? `${formatTime(upstream.syncedAt)} 同步` : '与官方源码同步';
    $('#about-commit').textContent = upstream.commit ? upstream.commit.slice(0, 12) : '未知'; $('#about-synced').textContent = upstream.syncedAt ? `${formatTime(upstream.syncedAt)}（北京时间）` : '未知';
    $('#about-translation').textContent = translation.total ? `${Number(translation.translated || 0).toLocaleString()} / ${Number(translation.total).toLocaleString()} 段落` : '翻译进度尚未记录';
  }
  async function init() {
    setMode(state.mode); setSidebarCollapsed(state.sidebarCollapsed, false); setMenu(false); $('#english-terms').checked = state.terms;
    window.addEventListener('resize', () => { if (!matchMedia('(max-width: 999px)').matches && document.body.classList.contains('menu-open')) setMenu(false); else syncSidebarAccess(); if (!matchMedia('(max-width: 1100px)').matches) setSearchOpen(false); else if ($('#header-search')?.contains(document.activeElement)) setSearchOpen(true); });
    $$('.mode-button').forEach(button => button.addEventListener('click', () => setMode(button.dataset.mode)));
    $('#english-terms').addEventListener('change', event => { state.terms = event.target.checked; storage.set('vt-terms', String(state.terms)); applyTerms(); });
    $('#theme-toggle').addEventListener('click', () => { const theme = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark'; document.documentElement.dataset.theme = theme; storage.set('vt-theme', theme); $('#theme-toggle').setAttribute('aria-label', `切换${theme === 'dark' ? '浅色' : '深色'}模式`); });
    $('#chapter-search').addEventListener('input', event => { state.query = event.target.value; if (state.catalog) renderNavigation(); if (state.query.trim()) revealSidebar(); });
    $('#search-toggle')?.addEventListener('click', () => { const open = !document.body.classList.contains('search-open'); setSearchOpen(open, open); });
    $('#search-clear')?.addEventListener('click', () => { clearSearch(); $('#chapter-search').focus({ preventScroll: true }); });
    $('#nav-expand-all')?.addEventListener('click', () => setAllGroups(true)); $('#nav-collapse-all')?.addEventListener('click', () => setAllGroups(false)); $('#nav-current')?.addEventListener('click', locateCurrentChapter);
    $('#menu-toggle').addEventListener('click', () => { if (matchMedia('(max-width: 999px)').matches) setMenu(!document.body.classList.contains('menu-open')); else setSidebarCollapsed(!state.sidebarCollapsed); }); $('#menu-scrim').addEventListener('click', () => setMenu(false));
    const dialog = $('#about-dialog'); [$('#about-open'), $('#about-footer')].forEach(button => button.addEventListener('click', () => dialog.showModal())); $('#about-close').addEventListener('click', () => dialog.close()); dialog.addEventListener('click', event => { if (event.target === dialog) { const rect = dialog.getBoundingClientRect(); if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) dialog.close(); } });
    $('#back-top').addEventListener('click', () => window.scrollTo({ top: 0, behavior: 'smooth' }));
    document.addEventListener('keydown', event => { if (event.key === 'Escape') { setMenu(false); setSearchOpen(false); } if (event.key === '/' && !/^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName) && !document.activeElement?.isContentEditable && !dialog.open) { event.preventDefault(); setSearchOpen(true, true); } });
    document.addEventListener('click', event => {
      const link = event.target.closest('a'); if (!link || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || event.button !== 0 || link.target === '_blank') return;
      const url = new URL(link.href, location.href); if (url.origin !== location.origin) return;
      const id = link.dataset.page || url.searchParams.get('page'); if (id && state.catalog) { event.preventDefault(); if (id === state.page?.id) { if (url.hash) { history.pushState({}, '', `${pageHref(id)}${url.hash}`); document.getElementById(decodeURIComponent(url.hash.slice(1)))?.scrollIntoView(); } else window.scrollTo({ top: 0 }); setMenu(false); setSearchOpen(false); return; } loadPage(id, { push: true, hash: url.hash }); }
    });
    window.addEventListener('popstate', () => { if (state.catalog) loadPage(new URLSearchParams(location.search).get('page') || state.catalog.pages[0]?.id); });
    try {
      state.catalog = await fetchDocument(siteHref('data/catalog.json')); if (!Array.isArray(state.catalog.pages) || !state.catalog.pages.length) throw new Error('Empty catalog'); state.navigation = buildNavigationTree(state.catalog);
      updateSyncInfo(); renderNavigation(); await loadPage(new URLSearchParams(location.search).get('page') || state.catalog.pages.find(page => page.id === '00_Introduction')?.id || state.catalog.pages[0].id);
    } catch (error) { $('#chapter-nav').textContent = '目录暂时不可用'; $('#search-summary').textContent = ''; showError('教程正在准备中', '暂时无法读取教程目录。请稍后重新加载。', () => location.reload()); }
  }
  init();
})();
