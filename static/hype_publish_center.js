// HYPE Release Center: small, explicit controls. Server validates every upload and publication.
(() => {
  'use strict';

  function init() {
    const root = document.getElementById('hpub-app');
    if (!root) return;

    // Client-side filters only change presentation; permissions and releases remain server-side.
    const libraryCards = Array.from(root.querySelectorAll('[data-hpub-file-card]'));
    const librarySearch = root.querySelector('#hpub-library-search');
    const libraryStage = root.querySelector('#hpub-library-stage');
    const visibleCount = root.querySelector('#hpub-visible-count');
    const noResults = root.querySelector('#hpub-library-no-results');
    const normalizeText = text => String(text || '').normalize('NFD')
      .replace(/[\u0300-\u036f]/g, '').toLowerCase();

    function filterLibrary() {
      const query = normalizeText(librarySearch?.value.trim());
      const filter = libraryStage?.value || 'all';
      let visible = 0;
      libraryCards.forEach(card => {
        const state = card.dataset.hpubFileStatus || '';
        const job = card.dataset.hpubJobStatus || '';
        const matchesText = normalizeText(card.dataset.hpubSearch).includes(query);
        const matchesStage = filter === 'all'
          || (filter === 'rejected' && state === 'rejeitado')
          || (filter === 'review' && ['em_teste', 'pronto_para_aprovacao'].includes(state))
          || (filter === 'pending' && state !== 'rejeitado'
              && (state === 'aguardando_protecao' || ['queued', 'running', 'failed'].includes(job)));
        card.hidden = !(matchesText && matchesStage);
        if (!card.hidden) visible += 1;
      });
      if (visibleCount) visibleCount.textContent = visible + ' de ' + libraryCards.length + ' arquivo(s)';
      if (noResults) noResults.hidden = visible > 0 || libraryCards.length === 0;
    }

    librarySearch?.addEventListener('input', filterLibrary);
    libraryStage?.addEventListener('change', filterLibrary);
    filterLibrary();

    const modes = Array.from(root.querySelectorAll('[data-hpub-mode]'));
    const uploadPanels = Array.from(root.querySelectorAll('[data-hpub-upload-panel]'));

    function chooseMode(type) {
      const selected = modes.find(button => button.dataset.hpubMode === type);
      if (!selected || selected.disabled) return false;
      const manualPanel = root.querySelector('#hpub-manual-tools');
      if (manualPanel) manualPanel.open = type === 'protected';
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

    const originalChoice = root.querySelector('#pilot_original_draft');
    const protectedChoice = root.querySelector('#private_draft');
    const unifiedPublishForm = root.querySelector('#hpub-unified-release-form');
    const privatePublishAction = unifiedPublishForm?.getAttribute('action') || '';

    function setSelectedCard(id) {
      root.querySelectorAll('[data-hpub-file-card]').forEach(card => {
        card.classList.toggle('is-selected-for-publish', Boolean(id) && card.dataset.hpubFileCard === id);
      });
    }

    function updatePublicationChoice(input, noteId, submitId) {
      const option = input?.selectedOptions[0];
      const selected = Boolean(option?.value);
      const ready = selected && option.dataset.hpubReady === 'yes';
      const note = root.querySelector(noteId);
      const submit = root.querySelector(submitId);
      if (note) note.textContent = selected
        ? option.dataset.hpubNext || 'Confira as pendências desse arquivo.'
        : 'Selecione um arquivo já guardado em Meus arquivos.';
      if (submit) submit.disabled = !ready;
      return { selected, ready, id: selected ? option.value : '' };
    }

    function updateOriginalChoice() {
      return updatePublicationChoice(originalChoice, '#hpub-original-choice-note', '#hpub-submit-original');
    }

    function updateProtectedChoice() {
      const state = updatePublicationChoice(protectedChoice, '#hpub-protected-choice-note', '#hpub-submit-protected');
      const option = protectedChoice?.selectedOptions[0];
      const isClient = state.selected && option?.dataset.hpubMod === 'hypeclient';
      if (unifiedPublishForm) {
        // Only choose between two known server-generated URLs; both endpoints revalidate everything.
        unifiedPublishForm.action = isClient ? unifiedPublishForm.dataset.hpubClientAction : privatePublishAction;
      }
      const submit = root.querySelector('#hpub-submit-protected');
      if (submit) submit.textContent = isClient ? 'Publicar HYPE Client protegido' : 'Publicar protegido aprovado';
      const review = root.querySelector('#hpub-review-selected');
      if (review) review.hidden = !state.selected || state.ready;
      return state;
    }

    originalChoice?.addEventListener('change', () => {
      const state = updateOriginalChoice();
      setSelectedCard(state.id);
    });
    protectedChoice?.addEventListener('change', () => {
      const state = updateProtectedChoice();
      setSelectedCard(state.id);
    });

    function openSelectedReview(id) {
      const review = Array.from(root.querySelectorAll('.hpub-file-review')).find(
        panel => panel.id === 'hpub-review-' + id
      );
      if (!review) return;
      review.open = true;
      focusArea(review, review.querySelector('summary'));
    }
    root.querySelector('#hpub-review-selected')?.addEventListener('click', () => {
      openSelectedReview(protectedChoice?.value);
    });

    root.querySelectorAll('[data-hpub-publish-original]').forEach(button => {
      button.addEventListener('click', () => {
        if (!originalChoice) return;
        const publishing = root.querySelector('#hpub-publishing-tools');
        if (publishing) publishing.open = true;
        originalChoice.value = button.dataset.hpubPublishOriginal;
        setSelectedCard(originalChoice.value);
        updateOriginalChoice();
        focusArea(root.querySelector('#hpub-private-test'), originalChoice);
      });
    });

    const existingOriginal = root.querySelector('#existing_original');
    const existingCandidate = root.querySelector('#existing_candidate');
    function filterExistingCandidates() {
      if (!existingOriginal || !existingCandidate) return;
      const src = existingOriginal.selectedOptions[0];
      Array.from(existingCandidate.options).forEach(opt => {
        if (!opt.value) return;
        const compatible = Boolean(src?.value)
          && opt.value !== src.value
          && opt.dataset.mod === src.dataset.mod
          && opt.dataset.version === src.dataset.version
          && opt.dataset.sha !== src.dataset.sha;
        opt.disabled = !compatible;
        opt.hidden = !compatible;
      });
      if (existingCandidate.selectedOptions[0]?.disabled) existingCandidate.value = '';
    }
    existingOriginal?.addEventListener('change', filterExistingCandidates);
    filterExistingCandidates();

    root.querySelectorAll('[data-hpub-publish-protected]').forEach(button => {
      button.addEventListener('click', () => {
        if (!protectedChoice) return;
        const publishing = root.querySelector('#hpub-publishing-tools');
        if (publishing) publishing.open = true;
        protectedChoice.value = button.dataset.hpubPublishProtected;
        setSelectedCard(protectedChoice.value);
        updateProtectedChoice();
        focusArea(root.querySelector('#hpub-protected-release'), protectedChoice);
      });
    });

    // No upload or release is triggered by the interface itself.
    // Every POST is an explicit admin action with server-side authorization and CSRF.
    const originalInput = root.querySelector('#hpub-quick-original');
    const uploadForm = originalInput?.closest('form');
    const uploadSubmit = uploadForm?.querySelector('[type="submit"]');
    const defaultSubmitText = uploadSubmit?.textContent || '';
    originalInput?.addEventListener('change', () => {
      const file = originalInput.files?.[0];
      const valid = Boolean(file && file.name.toLowerCase().endsWith('.jar')
        && file.size > 0 && file.size <= 10 * 1024 * 1024);
      if (uploadSubmit) {
        uploadSubmit.disabled = Boolean(file) && !valid;
        uploadSubmit.textContent = file && valid ? 'Enviar ' + file.name : defaultSubmitText;
      }
    });

    updateOriginalChoice();
    updateProtectedChoice();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init, { once: true });
  } else {
    init();
  }
})();
