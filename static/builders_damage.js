(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const API = 'https://pokeapi.co/api/v2';
  const cache = new Map();
  let attacker = null, defender = null, move = null;

  const defenseChart = {
    normal:{fighting:2,ghost:0}, fire:{water:2,ground:2,rock:2,fire:.5,grass:.5,ice:.5,bug:.5,steel:.5,fairy:.5},
    water:{electric:2,grass:2,fire:.5,water:.5,ice:.5,steel:.5}, electric:{ground:2,electric:.5,flying:.5,steel:.5},
    grass:{fire:2,ice:2,poison:2,flying:2,bug:2,water:.5,electric:.5,grass:.5,ground:.5}, ice:{fire:2,fighting:2,rock:2,steel:2,ice:.5},
    fighting:{flying:2,psychic:2,fairy:2,bug:.5,rock:.5,dark:.5}, poison:{ground:2,psychic:2,grass:.5,fighting:.5,poison:.5,bug:.5,fairy:.5},
    ground:{water:2,grass:2,ice:2,poison:.5,rock:.5,electric:0}, flying:{electric:2,ice:2,rock:2,grass:.5,fighting:.5,bug:.5,ground:0},
    psychic:{bug:2,ghost:2,dark:2,fighting:.5,psychic:.5}, bug:{fire:2,flying:2,rock:2,grass:.5,fighting:.5,ground:.5},
    rock:{water:2,grass:2,fighting:2,ground:2,steel:2,normal:.5,fire:.5,poison:.5,flying:.5}, ghost:{ghost:2,dark:2,poison:.5,bug:.5,normal:0,fighting:0},
    dragon:{ice:2,dragon:2,fairy:2,fire:.5,water:.5,electric:.5,grass:.5}, dark:{fighting:2,bug:2,fairy:2,ghost:.5,dark:.5,psychic:0},
    steel:{fire:2,fighting:2,ground:2,normal:.5,grass:.5,ice:.5,flying:.5,psychic:.5,bug:.5,rock:.5,dragon:.5,steel:.5,fairy:.5,poison:0},
    fairy:{poison:2,steel:2,fighting:.5,bug:.5,dark:.5,dragon:0}
  };

  function slug(v){ return String(v||'').trim().toLowerCase().replace(/\s+/g,'-'); }
  function stat(data, name){ return data?.stats?.find(x => x.stat.name === name)?.base_stat || 1; }
  function types(data){ return (data?.types || []).sort((a,b)=>a.slot-b.slot).map(x=>x.type.name); }
  function stageMult(stage){ stage=Number(stage)||0; return stage>=0 ? (2+stage)/2 : 2/(2-stage); }
  function calcHP(base, iv, ev, level){ return Math.floor(((2*base + iv + Math.floor(ev/4))*level)/100) + level + 10; }
  function calcStat(base, iv, ev, level, nature){ return Math.floor((Math.floor(((2*base + iv + Math.floor(ev/4))*level)/100)+5) * nature); }
  function typeEffect(moveType, defenderTypes){ return defenderTypes.reduce((m,t)=>m*(defenseChart[t]?.[moveType] ?? 1),1); }
  function fmtMult(n){ if(n===0)return '0×'; if(n===.25)return '¼×'; if(n===.5)return '½×'; if(n===1)return '1×'; if(n===2)return '2×'; if(n===4)return '4×'; return `${Number(n.toFixed(3))}×`; }

  async function fetchJson(url){
    if(cache.has(url)) return cache.get(url);
    const p = fetch(url).then(r => { if(!r.ok) throw new Error('Dados não encontrados'); return r.json(); });
    cache.set(url,p); return p;
  }

  async function loadLists(){
    try{
      const [p,m] = await Promise.all([
        fetchJson(`${API}/pokemon?limit=2000`), fetchJson(`${API}/move?limit=2000`)
      ]);
      $('pokemonDamageList').innerHTML = p.results.map(x=>`<option value="${x.name}"></option>`).join('');
      $('moveDamageList').innerHTML = m.results.map(x=>`<option value="${x.name}"></option>`).join('');
    }catch(e){ /* O usuário ainda pode digitar manualmente. */ }
  }

  function setPreview(prefix, data){
    const img=$(prefix+'Sprite'), fallback=$(prefix+'Fallback');
    const src=data?.sprites?.other?.['official-artwork']?.front_default || data?.sprites?.front_default || '';
    if(src){ img.src=src; img.style.display='block'; fallback.style.display='none'; }
    else { img.removeAttribute('src'); img.style.display='none'; fallback.style.display='grid'; }
  }

  async function loadPokemon(which){
    const input = $(which+'Pokemon');
    const name=slug(input.value); if(!name) return;
    try{
      const data=await fetchJson(`${API}/pokemon/${encodeURIComponent(name)}`);
      if(which==='attacker') attacker=data; else defender=data;
      setPreview(which,data); input.value=data.name;
      $('damageState').textContent='Dados carregados. Escolha o golpe e calcule.';
    }catch(e){
      if(which==='attacker') attacker=null; else defender=null;
      setPreview(which,null); $('damageState').textContent=`Não encontrei ${input.value} na PokéAPI.`;
    }
  }

  async function loadMove(){
    const name=slug($('moveName').value); if(!name) return;
    try{
      move=await fetchJson(`${API}/move/${encodeURIComponent(name)}`);
      $('moveName').value=move.name;
      if(move.power) $('movePower').value=move.power;
      if(move.damage_class?.name==='physical' || move.damage_class?.name==='special') $('moveClass').value=move.damage_class.name;
      if(move.type?.name) $('moveType').value=move.type.name;
      if(!move.power) $('damageState').textContent='Esse golpe não possui Power fixo na PokéAPI. Informe o Power manualmente se aplicável.';
    }catch(e){ move=null; $('damageState').textContent='Golpe não encontrado. Você pode preencher Power, categoria e tipo manualmente.'; }
  }

  function validateEV(id){ const el=$(id); let n=Math.max(0,Math.min(252,Number(el.value)||0)); el.value=n; return n; }
  function validateIV(id){ const el=$(id); let n=Math.max(0,Math.min(31,Number(el.value)||0)); el.value=n; return n; }

  function itemAttackModifier(item, cls, notes){
    if(item==='choice-band' && cls==='physical'){ notes.push('Choice Band: Atk ×1.5'); return 1.5; }
    if(item==='choice-specs' && cls==='special'){ notes.push('Choice Specs: SpA ×1.5'); return 1.5; }
    return 1;
  }
  function itemDefenseModifier(item, cls, notes){
    if(item==='eviolite'){ notes.push('Eviolite: defesa usada ×1.5 (assumindo Pokémon elegível)'); return 1.5; }
    if(item==='assault-vest' && cls==='special'){ notes.push('Assault Vest: SpD ×1.5'); return 1.5; }
    return 1;
  }
  function itemDamageModifier(item, cls, eff, notes){
    if(item==='life-orb'){ notes.push('Life Orb: dano ×1.3'); return 1.3; }
    if(item==='expert-belt' && eff>1){ notes.push('Expert Belt: dano super efetivo ×1.2'); return 1.2; }
    if(item==='muscle-band' && cls==='physical'){ notes.push('Muscle Band: dano físico ×1.1'); return 1.1; }
    if(item==='wise-glasses' && cls==='special'){ notes.push('Wise Glasses: dano especial ×1.1'); return 1.1; }
    return 1;
  }

  function calculate(e){
    if(e) e.preventDefault();
    if(!attacker || !defender){ $('damageState').textContent='Carregue atacante e defensor primeiro.'; return; }
    const level=Math.max(1,Math.min(100,Number($('level').value)||50));
    const power=Math.max(1,Number($('movePower').value)||1);
    const cls=$('moveClass').value;
    const moveType=$('moveType').value;
    const atkStatName=cls==='physical'?'attack':'special-attack';
    const defStatName=cls==='physical'?'defense':'special-defense';
    const notes=[];

    let atkStage=Number($('attackStage').value)||0, defStage=Number($('defenseStage').value)||0;
    const crit=Number($('critical').value)||1;
    if(crit>1){ atkStage=Math.max(0,atkStage); defStage=Math.min(0,defStage); notes.push('Crítico: ignora drops ofensivos e boosts defensivos relevantes'); }

    let A=calcStat(stat(attacker,atkStatName),validateIV('attackIV'),validateEV('attackEV'),level,Number($('attackNature').value)||1);
    let D=calcStat(stat(defender,defStatName),validateIV('defenseIV'),validateEV('defenseEV'),level,Number($('defenseNature').value)||1);
    const HP=calcHP(stat(defender,'hp'),validateIV('hpIV'),validateEV('hpEV'),level);
    A=Math.floor(A*stageMult(atkStage)); D=Math.floor(D*stageMult(defStage));

    const atkAbility=$('attackerAbility').value, defAbility=$('defenderAbility').value;
    const atkItem=$('attackerItem').value, defItem=$('defenderItem').value;
    A=Math.floor(A*itemAttackModifier(atkItem,cls,notes));
    D=Math.floor(D*itemDefenseModifier(defItem,cls,notes));
    if(cls==='physical' && ['huge-power','pure-power'].includes(atkAbility)){ A=Math.floor(A*2); notes.push(`${atkAbility==='huge-power'?'Huge Power':'Pure Power'}: Atk ×2`); }
    if(cls==='physical' && atkAbility==='hustle'){ A=Math.floor(A*1.5); notes.push('Hustle: Atk ×1.5 (precisão não calculada)'); }
    if(cls==='physical' && defAbility==='fur-coat'){ D=Math.floor(D*2); notes.push('Fur Coat: Defense ×2'); }
    if(cls==='special' && defAbility==='ice-scales'){ D=Math.floor(D*2); notes.push('Ice Scales: dano especial efetivamente reduzido via SpD ×2'); }

    const weather=$('weather').value;
    if(weather==='sand' && cls==='special' && types(defender).includes('rock')){ D=Math.floor(D*1.5); notes.push('Sand: SpD de Rock ×1.5'); }
    if(weather==='snow' && cls==='physical' && types(defender).includes('ice')){ D=Math.floor(D*1.5); notes.push('Snow: Defense de Ice ×1.5 (regra moderna)'); }

    const atkTypes=types(attacker), defTypes=types(defender);
    let stab=atkTypes.includes(moveType)?1.5:1;
    if(stab>1 && atkAbility==='adaptability'){ stab=2; notes.push('Adaptability: STAB 2×'); }
    let eff=typeEffect(moveType,defTypes);
    let modifier=stab*eff*crit*(Number($('screen').value)||1)*(Number($('otherModifier').value)||1);

    if(weather==='sun'){ if(moveType==='fire'){modifier*=1.5;notes.push('Sol: Fire ×1.5');} if(moveType==='water'){modifier*=.5;notes.push('Sol: Water ×0.5');} }
    if(weather==='rain'){ if(moveType==='water'){modifier*=1.5;notes.push('Chuva: Water ×1.5');} if(moveType==='fire'){modifier*=.5;notes.push('Chuva: Fire ×0.5');} }
    if(defAbility==='thick-fat' && ['fire','ice'].includes(moveType)){ modifier*=.5; notes.push('Thick Fat: Fire/Ice ×0.5'); }
    if(defAbility==='water-bubble' && moveType==='fire'){ modifier*=.5; notes.push('Water Bubble defensivo: Fire ×0.5'); }
    if(['filter','solid-rock','prism-armor'].includes(defAbility) && eff>1){ modifier*=.75; notes.push('Ability defensiva: super efetivo ×0.75'); }
    if(['multiscale','shadow-shield'].includes(defAbility) && $('fullHP').checked){ modifier*=.5; notes.push('Multiscale/Shadow Shield em HP cheio: ×0.5'); }
    if(atkAbility==='technician' && power<=60){ modifier*=1.5; notes.push('Technician: Power ≤ 60, dano ×1.5'); }
    if(atkAbility==='tinted-lens' && eff<1 && eff>0){ modifier*=2; notes.push('Tinted Lens: golpe resistido ×2'); }
    modifier*=itemDamageModifier(atkItem,cls,eff,notes);

    const status=$('attackerStatus').value;
    const moveName=slug($('moveName').value);
    if(cls==='physical' && status==='burn' && atkAbility!=='guts' && moveName!=='facade'){ modifier*=.5; notes.push('Burn: dano físico ×0.5'); }
    if(cls==='physical' && status!=='none' && atkAbility==='guts'){ A=Math.floor(A*1.5); notes.push('Guts com status: Atk ×1.5 e Burn não reduz dano'); }

    const base=Math.floor(Math.floor(Math.floor((Math.floor(2*level/5)+2)*power*A/Math.max(1,D))/50)+2);
    const max=Math.max(0,Math.floor(base*modifier));
    const min=Math.max(0,Math.floor(base*modifier*.85));
    const minPct=HP?min/HP*100:0, maxPct=HP?max/HP*100:0;

    let ko='';
    if(eff===0) ko='Imune — o golpe não causa dano por matchup de tipo.';
    else if(min>=HP) ko='OHKO garantido (sem considerar efeitos fora do formulário).';
    else if(max>=HP) ko='Possível OHKO.';
    else if(min*2>=HP) ko='2HKO garantido.';
    else if(max*2>=HP) ko='Possível 2HKO.';
    else if(min*3>=HP) ko='3HKO garantido.';
    else if(max*3>=HP) ko='Possível 3HKO.';
    else ko='Não alcança 3HKO apenas por dano direto nessa configuração.';

    $('damageState').textContent=`${attacker.name} usando ${$('moveName').value || moveType} em ${defender.name}`;
    $('damageRange').textContent=`${min} – ${max}`;
    $('damagePercent').textContent=`${minPct.toFixed(1)}% – ${maxPct.toFixed(1)}% do HP`;
    $('damageHpFill').style.width=`${Math.min(100,maxPct)}%`;
    $('koResult').textContent=ko;
    $('usedAttack').textContent=`${A} ${atkStatName==='attack'?'Atk':'SpA'}`;
    $('usedDefense').textContent=`${D} ${defStatName==='defense'?'Def':'SpD'}`;
    $('defenderHP').textContent=HP;
    $('stabValue').textContent=fmtMult(stab);
    $('effectivenessValue').textContent=fmtMult(eff);
    $('modifierValue').textContent=`${Number(modifier.toFixed(4))}×`;
    $('modifierNotes').textContent=notes.length?notes.join(' · '):'Nenhum modificador especial adicional aplicado.';
  }

  $('attackerPokemon').addEventListener('change',()=>loadPokemon('attacker'));
  $('defenderPokemon').addEventListener('change',()=>loadPokemon('defender'));
  $('moveName').addEventListener('change',loadMove);
  $('damageForm').addEventListener('submit',calculate);
  loadLists();
})();
