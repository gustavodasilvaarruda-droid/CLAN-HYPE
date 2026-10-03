/* HYPE V34 — raridade + atmosfera elemental sem alterar regras de negócio. */
(() => {
  const script = document.currentScript;
  const ASSET_BASE = script ? new URL('breed_types/', script.src).href : '/static/breed_types/';
  const ROOT = window.HYPE_BREED_SCRIPT_ROOT || '';
  const labels = {
    normal:'Normal', fire:'Fogo', water:'Água', electric:'Elétrico', grass:'Planta', ice:'Gelo',
    fighting:'Lutador', poison:'Veneno', ground:'Terra', flying:'Voador', psychic:'Psíquico', bug:'Inseto',
    rock:'Pedra', ghost:'Fantasma', dragon:'Dragão', dark:'Sombrio', steel:'Aço', fairy:'Fada'
  };
  const colors = {
    normal:'#b7bdc8', fire:'#ff6b2c', water:'#289cff', electric:'#ffd83d', grass:'#5fd175', ice:'#72e2f3',
    fighting:'#ef5d59', poison:'#b75ee0', ground:'#c58b4a', flying:'#89bdf5', psychic:'#f260dd', bug:'#9ccb37',
    rock:'#ae926d', ghost:'#8d71d9', dragon:'#796eff', dark:'#737e8e', steel:'#aebdca', fairy:'#ff91d0'
  };
  const rarityLabels = {comum:'Comum', raro:'Raro', ultra_raro:'Ultra Raro'};
  const cacheKey = 'hype-breed-v34-types';
  const cacheTTL = 1000 * 60 * 60 * 24 * 30;
  let cache = {};
  try { cache = JSON.parse(localStorage.getItem(cacheKey) || '{}') || {}; } catch (_) { cache = {}; }

  function saveCache(){
    try { localStorage.setItem(cacheKey, JSON.stringify(cache)); } catch (_) {}
  }
  function applyMeta(el, meta){
    const types = Array.isArray(meta?.types) ? meta.types.filter(Boolean) : [];
    const primary = String(types[0] || 'normal').toLowerCase();
    el.dataset.pokeType = primary;
    el.style.setProperty('--breed-type', colors[primary] || colors.normal);
    el.style.setProperty('--breed-type-bg', `url("${ASSET_BASE}${primary}.svg")`);
    const slot = el.querySelector('.breed-v34-meta-slot');
    if(slot && !slot.querySelector('.breed-v34-type-badge')){
      types.slice(0,2).forEach(type => {
        const t = String(type).toLowerCase();
        const badge = document.createElement('span');
        badge.className = 'breed-v34-type-badge';
        badge.textContent = labels[t] || t;
        badge.style.setProperty('--breed-type', colors[t] || colors.normal);
        slot.appendChild(badge);
      });
    }
  }
  async function hydrate(el){
    if(el.dataset.v34Hydrated === '1') return;
    el.dataset.v34Hydrated = '1';
    const id = Number(el.dataset.pokemonId || 0);
    if(!id) return;
    const name = el.dataset.pokemonName || '';
    const c = cache[id];
    if(c && c.savedAt && (Date.now() - c.savedAt) < cacheTTL){ applyMeta(el,c); return; }
    try{
      const res = await fetch(`${ROOT}/api/breed/pokemon/${id}?nome=${encodeURIComponent(name)}`, {headers:{'Accept':'application/json'}});
      if(!res.ok) throw new Error('meta');
      const data = await res.json();
      const meta = {types:data.types || [], savedAt:Date.now()};
      cache[id] = meta; saveCache(); applyMeta(el,meta);
    }catch(_){ applyMeta(el,{types:['normal']}); }
  }
  function ensureRarity(el){
    const r = String(el.dataset.rarity || 'comum').toLowerCase();
    el.dataset.rarity = ['comum','raro','ultra_raro'].includes(r) ? r : 'comum';
    const slot = el.querySelector('.breed-v34-meta-slot');
    if(slot && !slot.querySelector('.breed-v34-rarity-badge')){
      const badge = document.createElement('span');
      badge.className = 'breed-v34-rarity-badge';
      badge.textContent = rarityLabels[el.dataset.rarity] || 'Comum';
      slot.prepend(badge);
    }
  }
  const cards = [...document.querySelectorAll('.breed-v34-themed[data-pokemon-id]')];
  cards.forEach(ensureRarity);
  if('IntersectionObserver' in window){
    const io = new IntersectionObserver(entries => entries.forEach(entry => {
      if(entry.isIntersecting){ hydrate(entry.target); io.unobserve(entry.target); }
    }), {rootMargin:'300px 0px'});
    cards.forEach(c => io.observe(c));
  } else {
    cards.forEach(hydrate);
  }
})();
