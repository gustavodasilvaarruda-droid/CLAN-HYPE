/* Arena HYPE — prévia dos formatos. Apenas o servidor define as regras salvas. */
(() => {
  "use strict";
  const form = document.querySelector("[data-arena-create]");
  const raw = document.getElementById("arena-format-presets-json");
  if (!form || !raw) return;

  let presets;
  try {
    presets = JSON.parse(raw.textContent || "[]");
  } catch (_) {
    return;
  }
  const byCode = new Map(presets.map((item) => [item.codigo, item]));
  const generation = form.querySelector("[data-arena-generation]");
  const selection = form.querySelector("[data-arena-preset]");
  const preview = form.querySelector("[data-arena-preview]");
  const rules = form.querySelector("[data-arena-rules]");
  const legacy = [form.querySelector('[name="formato_codigo"]'), form.querySelector('[name="formato"]')];
  if (!generation || !selection || !preview || !rules) return;

  let manualRules = rules.value;
  rules.addEventListener("input", () => {
    if (!selection.value) manualRules = rules.value;
  });
  function el(name, text) {
    const node = document.createElement(name);
    node.textContent = text;
    return node;
  }
  function refresh() {
    for (const option of selection.options) {
      if (!option.value) continue;
      option.disabled = option.dataset.generation !== generation.value;
    }
    const chosen = byCode.get(selection.value);
    if (chosen && String(chosen.geracao) !== generation.value) selection.value = "";
    const preset = byCode.get(selection.value);
    preview.replaceChildren();

    if (!preset) {
      rules.readOnly = false;
      rules.value = manualRules;
      for (const field of legacy) if (field) field.disabled = false;
      preview.append(el("p", "Modo manual: informe o formato e as regras. O preset revisado da Geração 9 está disponível no seletor."));
      return;
    }
    rules.value = preset.regulamento;
    rules.readOnly = true;
    for (const field of legacy) if (field) field.disabled = true;
    preview.append(el("strong", preset.nome));
    preview.append(el("p", preset.resumo));
    preview.append(el("p", "Pokémon proibidos no resumo: " + preset.pokemons_proibidos.join(", ")));
    preview.append(el("p", "Golpes proibidos no resumo: " + preset.golpes_proibidos.join(", ")));
    preview.append(el("p", "Referência revisada em " + preset.revisado_em + ". O regulamento abaixo será salvo junto ao torneio."));
    const link = el("a", "Abrir regras de referência na Smogon");
    link.href = preset.fonte;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    preview.append(link);
    preview.append(el("small", "A validação completa de Pokémon, golpes, itens e habilidades será integrada na etapa do Team Builder."));
  }
  generation.addEventListener("change", refresh);
  selection.addEventListener("change", refresh);
  refresh();
})();
