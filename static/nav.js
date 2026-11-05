/* Shared navigation: one compact link bar in every page header, linking the hub and all views.
   Pages are served by two local servers: static pages on :8000, the review workbench on :8001. */
(function () {
  const STATIC = location.port === '8001' ? 'http://localhost:8000/' : '';
  const REVIEW = location.port === '8001' ? '/' : 'http://localhost:8001/';
  const links = [
    ['home', 'Gnomon', STATIC + 'index.html'],
    ['statewide', 'Statewide stop signs', STATIC + 'statewide.html'],
    ['swarm', 'Search swarm', STATIC + 'swarm.html'],
    ['review', 'Review', REVIEW],
    ['assets', 'Asset positions', STATIC + 'assets.html'],
    ['regulations', 'Wellesley regulations', STATIC + 'regulations.html'],
  ];
  const file = location.pathname.split('/').pop() || (location.port === '8001' ? 'review' : 'index.html');
  const current = { 'index.html': 'home', 'statewide.html': 'statewide', 'swarm.html': 'swarm', 'assets.html': 'assets',
    'regulations.html': 'regulations', 'workbench.html': 'review', 'review': 'review' }[file];
  const css = document.createElement('style');
  css.textContent = `.gnav{display:flex;align-items:center;gap:2px;flex-wrap:wrap;font:500 12px/1 system-ui,"Segoe UI",sans-serif}
  .gnav a{color:rgba(255,255,255,.72);text-decoration:none;padding:6px 9px;border-radius:5px;white-space:nowrap;transition:background-color .15s,color .15s}
  .gnav a:hover{color:#fff;background:rgba(255,255,255,.1)}.gnav a[aria-current="page"]{color:#fff;background:rgba(255,255,255,.14)}
  .gnav a.home{font-weight:700;letter-spacing:.04em;color:#fff;margin-right:6px}.gnav .sep{width:1px;height:16px;background:rgba(255,255,255,.2);margin:0 6px}
  @media (max-width:900px){.gnav a:not(.home):not([aria-current]){display:none}}`;
  document.head.append(css);
  const nav = document.createElement('nav'); nav.className = 'gnav'; nav.setAttribute('aria-label', 'Gnomon views');
  links.forEach(([id, label, href], i) => {
    if (i === 1) { const s = document.createElement('span'); s.className = 'sep'; nav.append(s); }
    const a = document.createElement('a'); a.href = href; a.textContent = id === 'home' && document.querySelector('.brand, .mark') ? 'Home' : label; if (id === 'home') a.className = 'home';
    if (id === current) a.setAttribute('aria-current', 'page'); nav.append(a);
  });
  const header = document.querySelector('header'); if (!header) return;
  const slot = header.querySelector('.header-note');
  if (slot) slot.replaceWith(nav);
  else { const actions = header.querySelector('.top-actions, .live'); actions ? header.insertBefore(nav, actions) : header.append(nav); }
})();
