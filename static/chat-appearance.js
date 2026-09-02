(() => {
  const chat=document.querySelector('.conversation'), panel=document.querySelector('.chat-appearance');
  if (!chat || !panel) return;
  const key='aduanhubChatAppearanceV1';
  const presets={blue:{bg:'#edf4fc',in:'#ffffff',out:'#dcecff',note:'#fff3ce'},green:{bg:'#edf5ef',in:'#ffffff',out:'#d9f3df',note:'#fff3ce'},violet:{bg:'#f1eef9',in:'#ffffff',out:'#e7ddfa',note:'#fff3ce'},neutral:{bg:'#ebedf0',in:'#ffffff',out:'#dfe4ea',note:'#fff3ce'}};
  const palette=document.getElementById('chat-palette'),pattern=document.getElementById('chat-pattern');
  const inputs=[...panel.querySelectorAll('[data-chat-color]')];
  let config=null;
  // WCAG luminance: select the higher-contrast text color for arbitrary user colors.
  function textColor(hex) {
    const rgb=[1,3,5].map(i=>parseInt(hex.slice(i,i+2),16)/255).map(c=>c<=.04045?c/12.92:((c+.055)/1.055)**2.4);
    const luminance=rgb[0]*.2126+rgb[1]*.7152+rgb[2]*.0722;
    return (luminance+.05)/.05>=1.05/(luminance+.05)?'#000000':'#ffffff';
  }
  function valid(value) { return value && ['bg','in','out','note'].every(k=>/^#[0-9a-f]{6}$/i.test(value[k])); }
  function apply(save=false) {
    const colors=config || presets.blue;
    chat.classList.toggle('custom-chat-colors',!!config);
    for (const name of ['bg','in','out','note']) {
      chat.style.setProperty('--chat-'+name,colors[name]);
      chat.style.setProperty('--chat-'+name+'-text',textColor(colors[name]));
    }
    chat.classList.toggle('chat-no-pattern',config?.pattern===false);
    palette.value=config?.preset || 'blue'; pattern.checked=config?.pattern!==false;
    inputs.forEach(input=>input.value=colors[input.dataset.chatColor]);
    if (save) { try { if(config)localStorage.setItem(key,JSON.stringify(config)); else localStorage.removeItem(key); } catch (_) {} }
  }
  try { const stored=JSON.parse(localStorage.getItem(key)); if(valid(stored))config=stored; } catch (_) {}
  apply();
  palette.addEventListener('change',()=>{if(presets[palette.value]){config={...presets[palette.value],preset:palette.value,pattern:pattern.checked};apply(true);}});
  inputs.forEach(input=>input.addEventListener('input',()=>{config={...(config||presets.blue),[input.dataset.chatColor]:input.value,preset:'custom',pattern:pattern.checked};apply(true);}));
  pattern.addEventListener('change',()=>{config={...(config||presets.blue),preset:palette.value,pattern:pattern.checked};apply(true);});
  document.getElementById('chat-appearance-reset').addEventListener('click',()=>{config=null;apply(true);});
  document.addEventListener('click',event=>{if(!panel.contains(event.target))panel.open=false;});
  panel.addEventListener('keydown',event=>{if(event.key==='Escape'){panel.open=false;panel.querySelector('summary').focus();}});
})();
