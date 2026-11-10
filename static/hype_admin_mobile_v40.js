(()=> {
 const btn=document.getElementById('admin2MobileToggle');
 const sidebar=document.getElementById('admin2Sidebar');
 const closeBtn=document.getElementById('admin2MobileClose');
 const backdrop=document.getElementById('admin2MobileBackdrop');
 if(!btn||!sidebar||!backdrop)return;
 let previousFocus=null;
 const isOpen=()=>sidebar.classList.contains('is-open');
 function toggle(open){
  if(open)previousFocus=document.activeElement;
  sidebar.classList.toggle('is-open',open);
  backdrop.hidden=!open;
  document.body.classList.toggle('hype-admin-drawer-open',open);
  btn.setAttribute('aria-expanded',String(open));
  sidebar.setAttribute('aria-hidden',String(!open && window.matchMedia('(max-width:980px)').matches));
  if(open)closeBtn?.focus();else if(previousFocus&&previousFocus.isConnected)previousFocus.focus();
 }
 btn.addEventListener('click',()=>toggle(!isOpen()));
 closeBtn?.addEventListener('click',()=>toggle(false));
 backdrop.addEventListener('click',()=>toggle(false));
 sidebar.querySelectorAll('a').forEach(a=>a.addEventListener('click',()=>toggle(false)));
 document.addEventListener('keydown',e=>{
  if(e.key==='Escape'&&isOpen()){e.preventDefault();toggle(false)}
  if(e.key==='Tab'&&isOpen()){
    const els=[...sidebar.querySelectorAll('button:not([disabled]),a[href]')].filter(el=>el.getClientRects().length);
    if(!els.length)return;const first=els[0],last=els[els.length-1];
    if(e.shiftKey&&document.activeElement===first){e.preventDefault();last.focus()}
    if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus()}
  }
 });
 window.addEventListener('resize',()=>{if(window.innerWidth>980&&isOpen())toggle(false);else if(!isOpen())sidebar.removeAttribute('aria-hidden')});
})();
