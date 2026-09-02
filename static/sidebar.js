(()=>{
  const side=document.querySelector('#side');
  const toggle=document.querySelector('#menu');
  if(!side||!toggle)return;

  const root=document.documentElement;
  const mobile=window.matchMedia('(max-width: 1100px)');
  const id=root.lang==='id';
  const labels={
    open:id?'Buka navigasi':'Open navigation',
    close:id?'Tutup navigasi':'Close navigation',
    collapse:id?'Ciutkan navigasi':'Collapse navigation',
    expand:id?'Perluas navigasi':'Expand navigation'
  };
  let returnFocus=false;

  side.setAttribute('aria-label',id?'Navigasi utama':'Main navigation');
  toggle.classList.remove('mobile');
  toggle.classList.add('sidebar-toggle');
  toggle.type='button';
  toggle.setAttribute('aria-controls','side');

  const close=document.createElement('button');
  close.type='button';
  close.id='sidebar-close';
  close.className='sidebar-close';
  close.setAttribute('aria-label',labels.close);
  close.textContent='×';
  side.prepend(close);

  const backdrop=document.createElement('button');
  backdrop.type='button';
  backdrop.id='sidebar-backdrop';
  backdrop.className='sidebar-backdrop';
  backdrop.tabIndex=-1;
  backdrop.setAttribute('aria-label',labels.close);
  side.after(backdrop);

  side.querySelectorAll('nav a').forEach(link=>{
    const label=link.textContent.trim();
    if(label&&!link.title)link.title=label;
  });
  side.querySelectorAll('.nav-settings summary').forEach(summary=>{
    const label=summary.textContent.replace('⌄','').trim();
    if(label&&!summary.title)summary.title=label;
    summary.addEventListener('click',event=>{
      if(!mobile.matches&&root.classList.contains('sidebar-collapsed')){
        event.preventDefault();
        setCollapsed(false);
        summary.parentElement.open=true;
      }
    });
  });

  function setCollapsed(value,persist=true){
    root.classList.toggle('sidebar-collapsed',value);
    if(persist){
      try{localStorage.setItem('aduanhubSidebarCollapsed',value?'1':'0')}catch(_){}
    }
    syncState();
  }

  function openDrawer(){
    side.classList.add('open');
    root.classList.add('sidebar-drawer-open');
    returnFocus=true;
    syncState();
    close.focus();
  }

  function closeDrawer(focusToggle=false){
    side.classList.remove('open');
    root.classList.remove('sidebar-drawer-open');
    syncState();
    if(focusToggle&&returnFocus)toggle.focus();
    returnFocus=false;
  }

  function syncState(){
    const drawerOpen=mobile.matches&&side.classList.contains('open');
    const collapsed=!mobile.matches&&root.classList.contains('sidebar-collapsed');
    toggle.setAttribute('aria-expanded',String(mobile.matches?drawerOpen:!collapsed));
    toggle.setAttribute('aria-label',mobile.matches?(drawerOpen?labels.close:labels.open):(collapsed?labels.expand:labels.collapse));
    side.setAttribute('aria-hidden',String(mobile.matches&&!drawerOpen));
  }

  toggle.addEventListener('click',()=>{
    if(mobile.matches){
      side.classList.contains('open')?closeDrawer(true):openDrawer();
    }else setCollapsed(!root.classList.contains('sidebar-collapsed'));
  });
  close.addEventListener('click',()=>closeDrawer(true));
  backdrop.addEventListener('click',()=>closeDrawer(true));
  side.querySelectorAll('nav a').forEach(link=>link.addEventListener('click',()=>{
    if(mobile.matches)closeDrawer(false);
  }));
  document.addEventListener('keydown',event=>{
    if(event.key==='Escape'&&mobile.matches&&side.classList.contains('open'))closeDrawer(true);
  });
  mobile.addEventListener('change',()=>{closeDrawer(false);syncState()});
  closeDrawer(false);
  syncState();
})();
