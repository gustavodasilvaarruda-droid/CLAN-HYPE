(()=>{
  'use strict';
  const $=(s,r=document)=>r.querySelector(s), $$=(s,r=document)=>[...r.querySelectorAll(s)];
  const root=$('#breederQueue'), search=$('#queueSearch'), filterBox=$('#queueFilters');
  if(!root || !filterBox) return;
  const cards=$$('.breed-v21-order',root), empty=$('#queueEmptyState'), emptyText=$('#queueEmptyText');
  const pagination=$('#queuePagination'), pageInfo=$('#queuePageInfo'), pages=$('#queuePages'), prev=$('#queuePrev'), next=$('#queueNext');
  const availabilityFilter=$('#availabilityFilter');
  const valid=new Set(['todos','pendente','em_andamento','concluido','meus']);
  const working=new Set(['em_andamento','aguardando_pagamento','em_producao','cancelamento_solicitado']);
  const finished=new Set(['concluido','aguardando_confirmacao','aguardando_confirmacao_cliente']);
  const params=new URLSearchParams(location.search);
  let current=valid.has(params.get('filtro'))?params.get('filtro'):(filterBox.dataset.initialFilter||'todos');
  if(!valid.has(current)) current='todos';
  let page=1; const perPage=5;

  function matchesFilter(c){
    const st=c.dataset.status||'';
    if(current==='pendente') return st==='pendente';
    if(current==='em_andamento') return working.has(st);
    if(current==='concluido') return finished.has(st);
    if(current==='meus') return c.dataset.mine==='1';
    return true;
  }
  function visibleSet(){
    const term=(search?.value||'').trim().toLowerCase();
    return cards.filter(c=>matchesFilter(c) && (!term || (c.dataset.search||'').toLowerCase().includes(term)));
  }
  function emptyMessage(){
    if((search?.value||'').trim()) return 'Nenhum pedido corresponde à sua busca neste filtro.';
    if(current==='meus') return 'Você ainda não possui Breeds nesta fila.';
    if(current==='pendente') return 'Não há pedidos pendentes no momento.';
    if(current==='em_andamento') return 'Não há pedidos em andamento no momento.';
    if(current==='concluido') return 'Não há pedidos concluídos aguardando finalização.';
    return 'Quando novos pedidos chegarem, eles aparecerão aqui.';
  }
  function syncControls(){
    $$('button[data-filter]',filterBox).forEach(b=>{
      const on=b.dataset.filter===current;
      b.classList.toggle('active',on); b.setAttribute('aria-pressed',on?'true':'false');
    });
    if(availabilityFilter) availabilityFilter.value=current;
  }
  function syncUrl(){
    const u=new URL(location.href);
    if(current==='todos') u.searchParams.delete('filtro'); else u.searchParams.set('filtro',current);
    history.replaceState(null,'',u.pathname+(u.searchParams.toString()?'?'+u.searchParams.toString():'')+u.hash);
  }
  function render(){
    syncControls();
    const visible=visibleSet(), total=visible.length, maxPage=Math.max(1,Math.ceil(total/perPage));
    page=Math.max(1,Math.min(page,maxPage));
    const start=(page-1)*perPage, end=Math.min(start+perPage,total);
    cards.forEach(c=>{c.hidden=true;c.classList.add('breed-filter-hidden')});
    visible.slice(start,end).forEach(c=>{c.hidden=false;c.classList.remove('breed-filter-hidden')});
    if(empty){empty.hidden=total!==0;if(emptyText)emptyText.textContent=emptyMessage();}
    if(pagination){pagination.hidden=total<=perPage;}
    if(pageInfo) pageInfo.textContent=total?`Mostrando ${start+1} a ${end} de ${total} pedido${total!==1?'s':''}`:'Nenhum pedido encontrado';
    if(pages){pages.innerHTML='';const first=Math.max(1,Math.min(page-2,maxPage-4)),last=Math.min(maxPage,first+4);for(let i=first;i<=last;i++){const b=document.createElement('button');b.type='button';b.textContent=i;b.className=i===page?'active':'';b.addEventListener('click',()=>{page=i;render();});pages.appendChild(b)}}
    if(prev)prev.disabled=page<=1;if(next)next.disabled=page>=maxPage;
  }
  filterBox.addEventListener('click',e=>{const b=e.target.closest('button[data-filter]');if(!b)return;current=b.dataset.filter;page=1;syncUrl();render();});
  search?.addEventListener('input',()=>{page=1;render();});
  prev?.addEventListener('click',()=>{if(page>1){page--;render();}});next?.addEventListener('click',()=>{const max=Math.max(1,Math.ceil(visibleSet().length/perPage));if(page<max){page++;render();}});
  $$('.breed-copy-req').forEach(b=>b.addEventListener('click',async()=>{try{await navigator.clipboard.writeText(b.dataset.copy||'');const old=b.textContent;b.textContent='✓ Requisitos copiados';setTimeout(()=>b.textContent=old,1400);}catch(_){if(b.dataset.copy)alert(b.dataset.copy);}}));
  render();
})();
