// HYPE Publishing Center — progressive enhancement only; never bypass server validation.
(() => {
  'use strict';
  function init() {
    const root = document.getElementById('hpub-app');
    if (!root) return;
    const stages = Array.from(root.querySelectorAll('[data-hpub-stage]'));
    const nav = Array.from(root.querySelectorAll('[data-hpub-goto]'));
    if (!stages.length || !nav.length) return;
    const names = new Set(stages.map(stage => stage.dataset.hpubStage));
    const key = 'hype-publisher-active-step-v1';
    function remember(step) {
      try { window.sessionStorage.setItem(key, step); } catch (_ignored) { /* optional */ }
    }
    function restore() {
      const hash = window.location.hash.slice(1);
      if (hash.startsWith('hpub-')) {
        const choice = hash.slice(5);
        if (names.has(choice)) return choice;
      }
      try {
        const saved = window.sessionStorage.getItem(key);
        if (names.has(saved)) return saved;
      } catch (_ignored) { /* private mode */ }
      return 'arquivo';
    }
    function activate(step, scroll) {
      if (!names.has(step)) return;
      const button = nav.find(item => item.dataset.hpubGoto === step);
      if (button && button.disabled) return;
      stages.forEach(section => {
        const active = section.dataset.hpubStage === step;
        section.classList.toggle('is-active', active);
        section.setAttribute('aria-hidden', active ? 'false' : 'true');
      });
      nav.forEach(item => {
        const active = item.dataset.hpubGoto === step;
        item.classList.toggle('is-active', active);
        item.setAttribute('aria-pressed', active ? 'true' : 'false');
        if (active) item.setAttribute('aria-current', 'step');
        else item.removeAttribute('aria-current');
      });
      remember(step);
      if (scroll) {
        root.querySelector('.hpub-stepper')?.scrollIntoView({
          behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth',
          block: 'start'
        });
      }
    }
    root.classList.add('hpub-enhanced');
    activate(restore(), false);
    root.addEventListener('click', event => {
      const control = event.target.closest('[data-hpub-goto],[data-hpub-next],[data-hpub-prev]');
      if (!control || control.disabled || !root.contains(control)) return;
      const choice = control.dataset.hpubGoto || control.dataset.hpubNext || control.dataset.hpubPrev;
      activate(choice, true);
    });
    root.querySelectorAll('.hpub-stage form').forEach(form => form.addEventListener('submit', () => {
      const stage = form.closest('[data-hpub-stage]');
      if (stage) remember(stage.dataset.hpubStage);
    }));
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init, {once:true});
  else init();
})();