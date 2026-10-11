/* HYPE V36: interação mobile progressiva, sem dependência de bibliotecas */
(() => {
  'use strict';
  if (window.__hypeMobileV36Loaded) return;
  window.__hypeMobileV36Loaded = true;
  const mobile = () => window.matchMedia('(max-width: 900px)').matches;
  const sidebar = document.getElementById('hgbSidebar');
  const menuBtn = document.getElementById('hgbMobileMenu');
  const homebar = document.querySelector('.hype-v6-homebar');
  const homeNav = homebar && homebar.querySelector('nav');
  let homeBtn = null;
  let backdrop = null;

  function getBackdrop() {
    if (backdrop) return backdrop;
    backdrop = document.createElement('div');
    backdrop.className = 'hype-mobile-nav-backdrop';
    backdrop.hidden = true;
    backdrop.addEventListener('click', closeMenus);
    document.body.appendChild(backdrop);
    return backdrop;
  }
  function isOpen() {
    return !!((sidebar && sidebar.classList.contains('open')) ||
      (homebar && homebar.classList.contains('hype-home-nav-open')));
  }
  function syncMenus() {
    const open = mobile() && isOpen();
    if (open) getBackdrop();
    if (backdrop) backdrop.hidden = !open;
    if (menuBtn) menuBtn.setAttribute('aria-expanded', sidebar && sidebar.classList.contains('open') ? 'true' : 'false');
    if (homeBtn) homeBtn.setAttribute('aria-expanded', homebar && homebar.classList.contains('hype-home-nav-open') ? 'true' : 'false');
    document.body.classList.toggle('hype-mobile-menu-open', !!open);
  }
  function closeMenus() {
    if (sidebar) sidebar.classList.remove('open');
    if (homebar) homebar.classList.remove('hype-home-nav-open');
    syncMenus();
  }
  if (sidebar && menuBtn) {
    menuBtn.setAttribute('aria-controls', 'hgbSidebar');
    menuBtn.setAttribute('aria-expanded', 'false');
    // O script original já alterna a classe .open; só acompanhamos a mudança.
    new MutationObserver(syncMenus).observe(sidebar, {attributes:true, attributeFilter:['class']});
    sidebar.querySelectorAll('a').forEach(a => a.addEventListener('click', closeMenus));
  }
  if (homebar && homeNav) {
    homeNav.id ||= 'hype-home-mobile-nav';
    homeBtn = document.createElement('button');
    homeBtn.type = 'button';
    homeBtn.className = 'hype-mobile-home-toggle';
    homeBtn.textContent = '☰';
    homeBtn.setAttribute('aria-label','Abrir menu HYPE');
    homeBtn.setAttribute('aria-controls',homeNav.id);
    homeBtn.setAttribute('aria-expanded','false');
    homebar.querySelector('.hype-v6-home-actions')?.appendChild(homeBtn);
    homeBtn.addEventListener('click', () => {
      if (!mobile()) return;
      homebar.classList.toggle('hype-home-nav-open');
      syncMenus();
    });
    homeNav.querySelectorAll('a').forEach(a => a.addEventListener('click',closeMenus));
  }
  document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && isOpen()) { closeMenus(); (homeBtn || menuBtn)?.focus(); }
  });
  window.addEventListener('resize', () => { if (!mobile()) closeMenus(); });

  // Tabelas administrativas não devem forçar a largura da página no Android.
  if (mobile()) {
    document.querySelectorAll('table').forEach(table => {
      if (table.closest('.table-wrap,.v28-fin-table-wrap,.hype-mobile-table-scroll,[class*=table-scroll],[class*=table-wrap]')) return;
      const parent = table.parentNode;
      if (!parent || parent.nodeType !== 1) return;
      const wrapper = document.createElement('div');
      wrapper.className = 'hype-mobile-table-scroll';
      wrapper.tabIndex = 0;
      wrapper.setAttribute('role','region');
      wrapper.setAttribute('aria-label','Tabela com rolagem horizontal');
      parent.insertBefore(wrapper, table);
      wrapper.appendChild(table);
    });
  }
  document.querySelectorAll('img').forEach(img => {
    if (!img.hasAttribute('loading') && !img.closest('header,nav,[class*=logo]')) img.loading = 'lazy';
  });
  syncMenus();
})();
