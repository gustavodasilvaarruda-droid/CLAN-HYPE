// HYPE Mods: one upload. Validation and publishing permissions remain on the server.
(() => {
  function init() {
    const root = document.getElementById('hpub-app');
    if (!root) return;
    const form = root.querySelector('#hpub-unified-upload-form');
    const fileInput = root.querySelector('#hpub-quick-file');
    const submit = root.querySelector('#hpub-submit-upload');
    const note = root.querySelector('#hpub-upload-file-note');
    const MAX_BYTES = 10 * 1024 * 1024;
    if (!form || !fileInput || !submit) return;
    function getError() {
      const file = fileInput.files?.[0];
      if (!file) return 'Selecione um arquivo .jar.';
      if (!file.name.toLowerCase().endsWith('.jar')) return 'Envie um arquivo .jar.';
      if (file.size === 0) return 'Arquivo vazio.';
      if (file.size > MAX_BYTES) return 'Arquivo acima do limite de 10 MiB.';
      return '';
    }
    fileInput.addEventListener('change', () => {
      const file = fileInput.files?.[0];
      const error = file ? getError() : '';
      submit.disabled = Boolean(error);
      if (note) note.textContent = error || (file ? file.name : 'JAR Fabric · até 10 MiB');
    });
    form.addEventListener('submit', event => {
      const error = getError();
      if (error) {
        event.preventDefault();
        if (note) note.textContent = error;
        return;
      }
      submit.disabled = true;
      submit.textContent = 'Enviando...';
    });
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init, {once:true});
  } else init();
})();