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
    // A complete inventory is shown even when no release is approved.
    // Navigation never submits a publish form or bypasses server-side validation.
    const releaseChoice = root.querySelector('#hpub-release-choice');
    const releaseStatus = root.querySelector('#hpub-release-choice-status');
    const releaseNext = root.querySelector('#hpub-release-choice-next');
    if (releaseChoice && releaseStatus && releaseNext) {
      const current = () => releaseChoice.selectedOptions[0];
      function refreshChoice() {
        const option = current();
        const selected = option && option.value;
        releaseNext.disabled = !selected;
        if (!selected) {
          releaseStatus.textContent = 'Selecione uma versão para ver o caminho até a publicação.';
          releaseNext.textContent = 'Abrir etapa da versão';
          return;
        }
        const ready = option.dataset.ready === 'yes';
        releaseStatus.textContent = ready
          ? 'Versão aprovada. Falta anexar o manifesto Ed25519 assinado e confirmar a publicação.'
          : 'Ainda não pode publicar: ' + (option.dataset.nextStep || 'é necessário concluir a preparação') + '.';
        releaseNext.textContent = ready ? 'Ir para publicar release' : 'Ir para a etapa necessária';
      }
      releaseChoice.addEventListener('change', refreshChoice);
      releaseNext.addEventListener('click', () => {
        const option = current();
        if (!option || !option.value) return;
        const stage = option.dataset.nextStage;
        if (stage && names.has(stage)) activate(stage, false);
        if (option.dataset.ready === 'yes') {
          const targetId = option.dataset.module === 'hypeclient' ? 'draft_publish' : 'private_draft';
          const target = root.querySelector('#' + targetId);
          if (target) {
            target.value = option.value;
            target.scrollIntoView({behavior: 'smooth', block: 'center'});
            target.focus({preventScroll: true});
          }
        } else {
          const target = root.querySelector('[data-hpub-stage="' + stage + '"]');
          if (target) target.scrollIntoView({behavior: 'smooth', block: 'start'});
        }
      });
      refreshChoice();
    }
    root.querySelectorAll('.hpub-stage form').forEach(form => form.addEventListener('submit', () => {
      const stage = form.closest('[data-hpub-stage]');
      if (stage) remember(stage.dataset.hpubStage);
    }));
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init, {once:true});
  else init();
})();