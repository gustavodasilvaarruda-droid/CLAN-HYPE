// HYPE unified mod library: all uploads stay private; release authorization stays server-side.
(() => {
  'use strict';

  function init() {
    const root = document.getElementById('hpub-app');
    if (!root) return;

    const cards = Array.from(root.querySelectorAll('[data-hpub-file-card]'));
    const groups = Array.from(root.querySelectorAll('[data-hpub-mod-group]'));
    const search = root.querySelector('#hpub-library-search');
    const stage = root.querySelector('#hpub-library-stage');
    const visibleCount = root.querySelector('#hpub-visible-count');
    const noResults = root.querySelector('#hpub-library-no-results');
    const normalize = value => String(value || '').normalize('NFD')
      .replace(/[\u0300-\u036f]/g, '').toLowerCase();

    function filterLibrary() {
      const query = normalize(search?.value.trim());
      const filter = stage?.value || 'all';
      let count = 0;
      cards.forEach(card => {
        const status = card.dataset.hpubFileStatus || '';
        const matches = normalize(card.dataset.hpubSearch).includes(query);
        const stateMatches = filter === 'all'
          || (filter === 'rejected' && status === 'rejeitado')
          || (filter === 'saved' && status !== 'rejeitado');
        card.hidden = !(matches && stateMatches);
        if (!card.hidden) count++;
      });
      groups.forEach(group => {
        const hasVisibleFile = Array.from(group.querySelectorAll('[data-hpub-file-card]'))
          .some(card => !card.hidden);
        group.hidden = !hasVisibleFile;
        if (hasVisibleFile && query) group.open = true;
      });
      if (visibleCount) visibleCount.textContent = count + ' de ' + cards.length + ' arquivo(s)';
      if (noResults) noResults.hidden = count > 0 || cards.length === 0;
    }

    search?.addEventListener('input', filterLibrary);
    stage?.addEventListener('change', filterLibrary);
    filterLibrary();

    const upload = root.querySelector('#hpub-unified-upload-form');
    const fileInput = root.querySelector('#hpub-quick-file');
    const uploadButton = root.querySelector('#hpub-submit-upload');
    const fileNote = root.querySelector('#hpub-upload-file-note');
    const progress = root.querySelector('#hpub-upload-progress');
    const defaultLabel = uploadButton?.textContent || 'Enviar arquivo';
    const limit = 10 * 1024 * 1024;

    function fileError(file) {
      if (!file) return 'Escolha um arquivo .jar.';
      if (!file.name.toLowerCase().endsWith('.jar')) return 'O arquivo precisa terminar em .jar.';
      if (file.size === 0) return 'O arquivo está vazio.';
      if (file.size > limit) return 'Este JAR passa de 10 MiB. Escolha uma versão menor.';
      return '';
    }

    fileInput?.addEventListener('change', () => {
      const file = fileInput.files?.[0];
      const error = file ? fileError(file) : '';
      if (uploadButton) {
        uploadButton.disabled = Boolean(error);
        uploadButton.textContent = !file || error ? defaultLabel : 'Enviar ' + file.name;
      }
      if (fileNote) fileNote.textContent = error || (file
        ? file.name + ' · ' + (file.size / 1048576).toFixed(2) + ' MiB · será armazenado no grupo do mod'
        : 'Escolha um JAR Fabric, independente de ser original ou modificado.');
    });

    upload?.addEventListener('submit', event => {
      const error = fileError(fileInput?.files?.[0]);
      if (error) {
        event.preventDefault();
        if (fileNote) fileNote.textContent = error;
        return;
      }
      if (uploadButton) {
        uploadButton.disabled = true;
        uploadButton.textContent = 'Enviando arquivo...';
      }
      if (progress) {
        progress.hidden = false;
        progress.textContent = 'Enviando para a biblioteca privada. Aguarde a confirmação do site.';
      }
    });

    root.querySelectorAll('[data-hpub-new-version]').forEach(button => {
      button.addEventListener('click', () => {
        const target = root.querySelector('#hpub-quick');
        target?.scrollIntoView({ behavior: 'smooth', block: 'start' });
        fileInput?.focus({ preventScroll: true });
      });
    });

    const releaseForm = root.querySelector('#hpub-unified-release-form');
    const releaseSelect = root.querySelector('#private_draft');
    const releaseButton = root.querySelector('#hpub-submit-release');
    const releaseNote = root.querySelector('#hpub-release-choice-note');
    const standardAction = releaseForm?.getAttribute('action') || '';
    function updateReleaseChoice() {
      const option = releaseSelect?.selectedOptions[0];
      const chosen = Boolean(option?.value);
      const ready = chosen && option.dataset.hpubReady === 'yes';
      if (releaseForm) {
        releaseForm.action = chosen && option.dataset.hpubMod === 'hypeclient'
          ? releaseForm.dataset.hpubClientAction : standardAction;
      }
      if (releaseButton) releaseButton.disabled = !ready;
      if (releaseNote) releaseNote.textContent = chosen
        ? option.dataset.hpubNext || 'Confira os requisitos da versão.'
        : 'Selecione um arquivo da biblioteca para conferir a publicação.';
    }
    releaseSelect?.addEventListener('change', updateReleaseChoice);
    updateReleaseChoice();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init, { once: true });
  } else {
    init();
  }
})();