/* Filtros puramente visuais: nenhuma alteração de cargo/membro é enviada ao servidor. */
(function(){
  'use strict';
  function normalize(value){return String(value||'').normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLocaleLowerCase('pt-BR').trim();}
  document.querySelectorAll('[data-hype-filter-root]').forEach(function(root){
    var tableId=root.getAttribute('data-table-id'), table=document.getElementById(tableId);
    if(!table)return;
    var rows=Array.from(table.querySelectorAll('tbody tr[data-player]'));
    var search=root.querySelector('[data-filter-search]'),role=root.querySelector('[data-filter-role]'),
        hype=root.querySelector('[data-filter-hype]'),reset=root.querySelector('[data-filter-reset]'),
        feedback=root.querySelector('[data-filter-feedback]'),chips=root.querySelector('[data-filter-chips]');
    var none=table.querySelector('[data-filter-empty]');
    function apply(){
      var term=normalize(search.value),selected=role.value,status=hype.value,visible=0;
      rows.forEach(function(row){
        var matchesName=normalize(row.dataset.player+' '+row.dataset.email).includes(term);
        var matchesRole=!selected||row.dataset.role===selected;
        var matchesHype=!status||row.dataset.hype===status;
        var show=matchesName&&matchesRole&&matchesHype;
        row.hidden=!show;row.style.display=show?'':'none';if(show)visible++;
      });
      if(none)none.hidden=visible!==0;
      if(feedback)feedback.textContent=visible+' de '+rows.length+' jogador(es) exibido(s)';
      if(chips)chips.querySelectorAll('[data-chip-role]').forEach(function(chip){
        chip.setAttribute('aria-pressed',String(chip.dataset.chipRole===role.value));
      });
    }
    if(chips){
      var counts={};
      rows.forEach(function(row){counts[row.dataset.role]=(counts[row.dataset.role]||0)+1});
      Array.from(role.options).forEach(function(option){
        var chip=document.createElement('button');chip.type='button';chip.className='hype-filter-chip';
        chip.dataset.chipRole=option.value;
        chip.textContent=option.textContent.trim()+' ('+(option.value?(counts[option.value]||0):rows.length)+')';
        chip.addEventListener('click',function(){role.value=option.value;apply()});chips.appendChild(chip);
      });
    }
    [search,role,hype].forEach(function(control){control.addEventListener('input',apply);control.addEventListener('change',apply)});
    if(reset)reset.addEventListener('click',function(){search.value='';role.value='';hype.value='';apply();search.focus()});
    apply();
  });
})();
