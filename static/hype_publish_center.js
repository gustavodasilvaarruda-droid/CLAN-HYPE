// HYPE Mods: stage uploads and release actions in the same screen.
// Every POST uses the server's existing admin, CSRF, signature and delete guards.
(() => {
  function init() {
    const root = document.getElementById('hpub-app');
    const toolbar = root?.querySelector('#hpub-batch-toolbar');
    const form = root?.querySelector('#hpub-unified-upload-form');
    if (!root || !toolbar || !form) return;

    const fileInput = root.querySelector('#hpub-quick-file');
    const note = root.querySelector('#hpub-upload-file-note');
    const publishNew = root.querySelector('#hpub-publish-new');
    const status = root.querySelector('#hpub-batch-status');
    const save = root.querySelector('#hpub-save-batch');
    const csrf = root.querySelector('#hpub-batch-csrf')?.value;
    const maxBytes = 10 * 1024 * 1024;
    const maxFiles = 30;
    let busy = false;
    if (!fileInput || !status || !save || !csrf) return;

    root.classList.add('hpub-js-enhanced');

    const selections = () => [...root.querySelectorAll('.hpub-batch-select')];
    const tasks = () => selections()
      .filter(el => Boolean(el.value))
      .map(el => ({
        action: el.value, id: el.dataset.draftId,
        modId: el.dataset.modId,
        ownerPilot: el.dataset.ownerPilot === '1',
        duplicate: el.dataset.duplicate === '1',
        active: el.dataset.active === '1'
      }));

    function say(message, error = false) {
      status.textContent = message;
      status.classList.toggle('hpub-batch-error', error);
    }

    function updateCount() {
      const files = [...fileInput.files];
      const changes = tasks();
      const total = files.length + changes.length;
      save.textContent = total ? 'Salvar tudo (' + total + ')' : 'Salvar tudo';
      if (!busy) {
        say(total
          ? files.length + ' arquivo(s) para enviar · ' + changes.length + ' ação(ões) selecionada(s).'
          : 'Nenhuma alteração selecionada.');
      }
      if (note) note.textContent = files.length
        ? files.length + ' JAR(s) escolhido(s): ' + files.map(f => f.name).join(', ')
        : 'Vários JARs Fabric · até 10 MiB por arquivo';
    }

    function validateFiles(files) {
      if (files.length > maxFiles) return 'Selecione no máximo 30 JARs por salvamento.';
      for (const file of files) {
        if (!file.name.toLowerCase().endsWith('.jar')) {
          return 'Apenas arquivos .jar são aceitos: ' + file.name;
        }
        if (file.size < 1 || file.size > maxBytes) {
          return 'JAR vazio ou acima de 10 MiB: ' + file.name;
        }
      }
      return '';
    }

    function fields(values) {
      const data = new FormData();
      data.set('csrf_token', csrf);
      for (const [key, value] of Object.entries(values)) data.set(key, value);
      return data;
    }

    async function post(url, data) {
      if (!url) throw new Error('A publicação automática não está habilitada.');
      const response = await fetch(url, {
        method: 'POST', body: data, credentials: 'same-origin',
        headers: { 'X-HYPE-BATCH': '1', 'Accept': 'application/json' },
        cache: 'no-store'
      });
      let result;
      try { result = await response.json(); }
      catch (_) { throw new Error('O servidor não retornou um resultado válido. Confira a sessão e tente novamente.'); }
      const explanation = (result.messages || []).map(m => m.text).join(' ');
      if (!response.ok || !result.ok) {
        throw new Error(explanation || 'Operação recusada pelo servidor (' + response.status + ').');
      }
      return result;
    }

    async function performAction(action, id, ownerPilot = false, duplicate = false, active = false) {
      if (action === 'publish') {
        return post(toolbar.dataset.publishUrl, fields({
          draft_id: id, confirm_public_distribution: 'yes'
        }));
      }
      if (action === 'delete' || action === 'delete_active') {
        return post(toolbar.dataset.deleteUrl, fields({
          draft_id: id, confirm_delete: 'yes',
          confirm_owner_pilot_retire: ownerPilot ? 'yes' : 'no',
          confirm_duplicate_retire: duplicate ? 'yes' : 'no',
          confirm_live_retire: active || action === 'delete_active' ? 'yes' : 'no'
        }));
      }
      throw new Error('Ação desconhecida.');
    }

    async function refreshLibrary() {
      const response = await fetch(window.location.pathname, {
        credentials: 'same-origin', cache: 'no-store'
      });
      if (!response.ok) throw new Error('Não foi possível atualizar a lista de arquivos.');
      const html = new DOMParser().parseFromString(await response.text(), 'text/html');
      const next = html.querySelector('.hpub-library');
      const old = root.querySelector('.hpub-library');
      if (!next || !old) throw new Error('Não foi possível carregar a lista atualizada.');
      old.replaceWith(next);
    }

    async function saveAll() {
      if (busy) return;
      const files = [...fileInput.files];
      const actions = tasks();
      const error = validateFiles(files);
      if (error) { say(error, true); return; }
      if (!files.length && !actions.length) {
        say('Escolha os JARs ou marque uma ação antes de salvar.', true);
        return;
      }
      const ids = new Set();
      for (const task of actions.filter(t => t.action === 'publish')) {
        if (ids.has(task.modId)) {
          say('Escolha somente uma versão por mod para publicar neste salvamento: ' + task.modId, true);
          return;
        }
        ids.add(task.modId);
      }

      const willPublish = Boolean(publishNew?.checked && files.length)
        || actions.some(t => t.action === 'publish');
      const willDelete = actions.some(t => t.action === 'delete' || t.action === 'delete_active');
      const willRetireActive = actions.some(t => t.action === 'delete_active');
      let confirmation = 'Confirmar ' + files.length + ' novo(s) arquivo(s) e '
        + actions.length + ' ação(ões) selecionada(s)?';
      if (willPublish) confirmation += '\n\nOs JARs publicados poderão ser baixados publicamente, sem ofuscação automática.';
      if (willDelete) confirmation += '\n\nOs arquivos escolhidos para exclusão serão removidos definitivamente.';
      if (willRetireActive) confirmation += '\n\nATENÇÃO: mods ATIVOS selecionados serão retirados do Bootstrap. Versões antigas NÃO voltarão automaticamente. Arquivos já instalados nos PCs não serão desinstalados.';
      if (!window.confirm(confirmation)) return;

      busy = true;
      root.setAttribute('aria-busy', 'true');
      save.disabled = true;
      const completed = [];
      const failures = [];

      // Send and publish replacements first; only then remove older versions.
      // A failed new release must never leave an active mod deleted by accident.
      let uploadFailed = false;
      for (const file of files) {
        say('Enviando ' + file.name + '...');
        try {
          const data = fields({});
          data.set('jar', file, file.name);
          const uploaded = await post(toolbar.dataset.uploadUrl, data);
          completed.push((uploaded.duplicate ? 'Já existia: ' : 'Enviado: ') + file.name);
          if (publishNew?.checked) {
            if (!uploaded.draft_id) {
              throw new Error('O envio foi registrado, mas o servidor não informou o ID para publicar.');
            }
            await performAction('publish', uploaded.draft_id);
            completed.push('Publicado: ' + file.name);
          }
        } catch (err) {
          uploadFailed = true;
          failures.push(file.name + ': ' + err.message);
        }
      }

      for (const task of actions) {
        if (task.action === 'delete_active' && files.length && publishNew?.checked && uploadFailed) {
          failures.push(task.modId + ': retirada cancelada porque a publicação do novo JAR falhou.');
          continue;
        }
        say('Aplicando alterações: ' + (completed.length + failures.length + 1) + '/' + (actions.length + files.length) + '...');
        try {
          const result = await performAction(task.action, task.id, task.ownerPilot, task.duplicate, task.active);
          completed.push((task.action === 'publish' ? 'Publicado: ' : task.action === 'delete_active' ? 'Retirado e apagado: ' : 'Apagado: ') + task.modId);
          if (result.messages?.length) {
            // Per-file server messages are retained in the status summary.
          }
        } catch (err) {
          failures.push(task.modId + ': ' + err.message);
        }
      }

      try {
        await refreshLibrary();
        fileInput.value = '';
        if (publishNew) publishNew.checked = false;
      } catch (err) {
        failures.push(err.message);
      }

      busy = false;
      root.removeAttribute('aria-busy');
      save.disabled = false;
      updateCount();
      if (failures.length) {
        say(completed.length + ' etapa(s) concluída(s); ' + failures.length
          + ' falha(s). ' + failures.join(' | ')
          + ' Outras etapas podem ter sido salvas; confira a lista antes de repetir.', true);
      } else {
        say('Tudo salvo: ' + completed.length
          + ' etapa(s) concluída(s). A lista foi atualizada sem recarregar a página.');
      }
    }

    form.addEventListener('submit', event => { event.preventDefault(); saveAll(); });
    save.addEventListener('click', saveAll);
    root.addEventListener('change', event => {
      if (event.target === fileInput || event.target?.matches('.hpub-batch-select')) updateCount();
    });
    root.querySelector('#hpub-mark-newest')?.addEventListener('click', () => {
      selections().forEach(sel => {
        if (sel.dataset.newest === '1' && sel.dataset.published !== '1'
            && [...sel.options].some(option => option.value === 'publish')) {
          sel.value = 'publish';
        }
      });
      updateCount();
    });
    root.querySelector('#hpub-mark-deletable')?.addEventListener('click', () => {
      let selected = 0;
      selections().forEach(sel => {
        if ([...sel.options].some(option => option.value === 'delete')) {
          sel.value = 'delete';
          selected++;
        }
      });
      updateCount();
      if (!selected) {
        say("Nenhum arquivo antigo selecionável. Para retirar o mod ativo, escolha 'Apagar e retirar do Bootstrap' na pasta dele.", true);
      }
    });
    root.querySelector('#hpub-clear-choices')?.addEventListener('click', () => {
      selections().forEach(sel => { sel.value = ''; });
      fileInput.value = '';
      if (publishNew) publishNew.checked = false;
      updateCount();
    });
    updateCount();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init, { once: true });
  } else init();
})();
