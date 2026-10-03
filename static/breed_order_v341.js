/* HYPE V34.4 — Fazer Pedido Premium sem rajada de requests.
   O visual de tipo/raridade usa somente os dados da seleção já validados pelo endpoint HYPE.
   Nenhum card dispara /api/breed/pokemon/<id> apenas para decoração. */
(() => {
  'use strict';
  const script = document.currentScript;
  const ASSET_BASE = script ? new URL('breed_types/', script.src).href : '/static/breed_types/';
  const grid = document.getElementById('hypeQuickPokemonGrid');
  const detail = document.getElementById('pokemonDetail');
  const shell = document.getElementById('fazer-pedido');
  if (!grid || !detail || !shell) return;

  const colors = {
    normal:'#b7bdc8',fire:'#ff6b2c',water:'#289cff',electric:'#ffd83d',grass:'#5fd175',ice:'#72e2f3',
    fighting:'#ef5d59',poison:'#b75ee0',ground:'#c58b4a',flying:'#89bdf5',psychic:'#f260dd',bug:'#9ccb37',
    rock:'#ae926d',ghost:'#8d71d9',dragon:'#796eff',dark:'#737e8e',steel:'#aebdca',fairy:'#ff91d0'
  };
  const typeLabels = {
    normal:'Normal',fire:'Fogo',water:'Água',electric:'Elétrico',grass:'Planta',ice:'Gelo',fighting:'Lutador',
    poison:'Veneno',ground:'Terra',flying:'Voador',psychic:'Psíquico',bug:'Inseto',rock:'Pedra',ghost:'Fantasma',
    dragon:'Dragão',dark:'Sombrio',steel:'Aço',fairy:'Fada'
  };
  const rarityColors = {comum:'#c8ced7',raro:'#349cff',ultra_raro:'#a85df6'};
  const rarityLabels = {comum:'Comum',raro:'Raro',ultra_raro:'Ultra Raro'};
  const cacheKey = 'hype-breed-v343-catalog-meta';
  const cacheTTL = 1000 * 60 * 60 * 24 * 30;
  let cache = {};
  try { cache = JSON.parse(localStorage.getItem(cacheKey) || '{}') || {}; } catch (_) { cache = {}; }

  function saveCache(){ try { localStorage.setItem(cacheKey, JSON.stringify(cache)); } catch (_) {} }
  function rarityOf(v){
    const x = String(v || 'comum').toLowerCase().replace(/\s+/g,'_');
    return ['comum','raro','ultra_raro'].includes(x) ? x : 'comum';
  }
  function metaFrom(data){
    const types = Array.isArray(data?.types) ? data.types.map(x => String(x||'').toLowerCase()).filter(Boolean) : [];
    const rarity = rarityOf(data?.categoria || data?.category);
    return {types:types.length?types:['normal'],rarity,rarityLabel:data?.categoria_label||rarityLabels[rarity]||'Comum',savedAt:Date.now()};
  }
  function getCardId(card){ return Number(card?.dataset?.id || 0); }
  function ensureShade(card){
    if (card && !card.querySelector('.breed-v341-card-shade')) {
      const s=document.createElement('span'); s.className='breed-v341-card-shade'; card.prepend(s);
    }
  }
  function renderCardMeta(card, meta){
    if (!card || !meta) return;
    ensureShade(card);
    const primary=meta.types[0]||'normal', rarity=rarityOf(meta.rarity);
    card.dataset.pokeType=primary; card.dataset.rarity=rarity; card.dataset.v341Ready='1';
    card.style.setProperty('--card-type',colors[primary]||colors.normal);
    card.style.setProperty('--card-type-soft',`${colors[primary]||colors.normal}26`);
    card.style.setProperty('--card-rarity',rarityColors[rarity]||rarityColors.comum);
    card.style.setProperty('--card-type-bg',`url("${ASSET_BASE}${primary}.svg")`);
    let badge=card.querySelector('.breed-v341-rarity-badge');
    if(!badge){badge=document.createElement('span');badge.className='breed-v341-rarity-badge';card.appendChild(badge);}
    badge.textContent=rarityLabels[rarity]||meta.rarityLabel||'Comum';
    const typeBox=card.querySelector('.breed-card-types');
    if(typeBox) typeBox.innerHTML=meta.types.slice(0,2).map(t=>`<span>${typeLabels[t]||t}</span>`).join('');
  }
  function setSelectedTheme(card, meta){
    if (!meta) return;
    const primary=meta.types[0]||'normal', rarity=rarityOf(meta.rarity);
    const typeColor=colors[primary]||colors.normal, rarityColor=rarityColors[rarity]||rarityColors.comum;
    const bg=`url("${ASSET_BASE}${primary}.svg")`;
    shell.style.setProperty('--breed-selected-type',typeColor);
    shell.style.setProperty('--breed-selected-type-soft',`${typeColor}2e`);
    shell.style.setProperty('--breed-selected-rarity',rarityColor);
    shell.style.setProperty('--breed-selected-bg',bg);
    shell.dataset.pokeType=primary; shell.dataset.rarity=rarity;
    detail.dataset.v341Selected='1'; detail.dataset.pokeType=primary; detail.dataset.rarity=rarity;
    detail.style.setProperty('--detail-type',typeColor); detail.style.setProperty('--detail-type-soft',`${typeColor}2e`);
    detail.style.setProperty('--detail-rarity',rarityColor); detail.style.setProperty('--detail-type-bg',bg);
    const art=detail.querySelector('.breed-detail-art');
    if(art){
      art.dataset.v341Selected='1'; art.dataset.pokeType=primary; art.dataset.rarity=rarity;
      art.style.setProperty('--detail-type',typeColor); art.style.setProperty('--detail-type-soft',`${typeColor}2e`);
      art.style.setProperty('--detail-rarity',rarityColor); art.style.setProperty('--detail-type-bg',bg);
    }
    let db=detail.querySelector('.breed-v341-detail-rarity');
    if(!db){db=document.createElement('span');db.className='breed-v341-detail-rarity';detail.querySelector('#detailTypes')?.insertAdjacentElement('afterend',db);}
    db.textContent=rarityLabels[rarity]||'Comum';
    document.querySelectorAll('.breed-stage-card,.breed-review-card,.breed-send-card,.breed-selected-mini').forEach(el=>{
      el.dataset.v341Selected='1'; el.dataset.pokeType=primary; el.dataset.rarity=rarity;
      el.style.setProperty('--detail-type',typeColor); el.style.setProperty('--detail-type-soft',`${typeColor}2e`);
      el.style.setProperty('--detail-rarity',rarityColor); el.style.setProperty('--detail-type-bg',bg);
    });
    if(card) renderCardMeta(card,meta);
  }
  function hydrateCachedCards(root=grid){
    root.querySelectorAll?.('.breed-ref-poke-card').forEach(card=>{
      ensureShade(card);
      const c=cache[getCardId(card)];
      if(c?.savedAt && Date.now()-c.savedAt<cacheTTL) renderCardMeta(card,c);
    });
  }
  function selectedCard(){ return grid.querySelector('.breed-ref-poke-card.selected'); }
  function applyCachedSelected(){
    const card=selectedCard(); if(!card) return;
    const c=cache[getCardId(card)];
    if(c?.savedAt && Date.now()-c.savedAt<cacheTTL) setSelectedTheme(card,c);
  }

  hydrateCachedCards();
  const mo=new MutationObserver(()=>{hydrateCachedCards();applyCachedSelected();});
  mo.observe(grid,{childList:true,subtree:true,attributes:true,attributeFilter:['class']});
  grid.addEventListener('click',()=>queueMicrotask(applyCachedSelected));

  window.addEventListener('hype:breed-pokemon-selected',ev=>{
    const id=Number(ev.detail?.id||0), info=ev.detail?.info||{};
    if(!id) return;
    const meta=metaFrom(info); cache[id]=meta; saveCache();
    const card=[...grid.querySelectorAll('.breed-ref-poke-card')].find(c=>getCardId(c)===id) || selectedCard();
    setSelectedTheme(card,meta);
  });
})();
