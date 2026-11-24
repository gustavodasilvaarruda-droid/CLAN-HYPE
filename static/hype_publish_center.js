// HYPE Release Center: small, explicit controls. Server validates every upload and publication.
(() => {
  'use strict';

  function init() {
    const root = document.getElementById('hpub-app');
    if (!root) return;

    const modes = Array.from(root.querySelectorAll('[data-hpub-mode]'));
    const uploadPanels = Array.from(root.querySelectorAll('[data-hpub-upload-panel]'));

    function chooseMode(type) {
      const selected = modes.find(button => button.dataset.hpubMode === type);
      if (!selected || selected.disabled) return false;
      modes.forEach(button => {
        const active = button === selected;
        button.classList.toggle('is-selected', active);
        button.setAttribute('aria-pressed', String(active));
      });
      uploadPanels.forEach(panel => { panel.hidden = panel.dataset.hpubUploadPanel !== type; });
      return true;
    }

    function focusArea(area, input) {
      area?.scrollIntoView({ behavior: 'smooth', block: 'start' });
      input?.focus({ preventScroll: true });
    }

    modes.forEach(button => {
      button.addEventListener('click', () => chooseMode(button.dataset.hpubMode));
    });

    root.querySelectorAll('[data-hpub-select-protected]').forEach(button => {
      button.addEventListener('click', () => {
        if (!chooseMode('protected')) return;
        const target = root.querySelector('#hpub-quick-target');
        if (target) target.value = button.dataset.hpubSelectProtected;
        focusArea(root.querySelector('#hpub-quick'), target);
      });
    });

    root.querySelectorAll('[data-hpub-new-version]').forEach(button => {
      button.addEventListener('click', () => {
        if (!chooseMode('original')) return;
        focusArea(root.querySelector('#hpub-quick'), root.querySelector('#hpub-quick-original'));
      });
    });

    root.querySelectorAll('[data-hpub-publish-original]').forEach(button => {
      button.addEventListener('click', () => {
        const input = root.querySelector('#pilot_original_draft');
        if (!input) return;
        input.value = button.dataset.hpubPublishOriginal;
        focusArea(root.querySelector('#hpub-private-test'), input);
      });
    });

    root.querySelectorAll('[data-hpub-publish-protected]').forEach(button => {
      button.addEventListener('click', () => {
        const client = button.dataset.hpubMod === 'hypeclient';
        const input = root.querySelector(client ? '#draft_publish' : '#private_draft');
        if (!input) return;
        if (client) {
          const extra = root.querySelector('#hpub-extra');
          if (extra) extra.open = true;
        }
        input.value = button.dataset.hpubPublishProtected;
        focusArea(client ? root.querySelector('#hpub-extra') : root.querySelector('#hpub-protected-release'), input);
      });
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init, { once: true });
  } else {
    init();
  }
})();
