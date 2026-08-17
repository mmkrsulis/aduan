const icons={grid:'<rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/>',inbox:'<path d="M4 4h16v16H4z"/><path d="M4 14h5l2 3h2l2-3h5"/>',users:'<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/>',settings:'<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .34 1.88l.06.06-2.83 2.83-.06-.06A1.7 1.7 0 0 0 15 19.4a1.7 1.7 0 0 0-1 .6 1.7 1.7 0 0 0-.4 1V21h-4v-.08A1.7 1.7 0 0 0 8.6 19.4a1.7 1.7 0 0 0-1.88.34l-.06.06-2.83-2.83.06-.06A1.7 1.7 0 0 0 4.6 15a1.7 1.7 0 0 0-.6-1 1.7 1.7 0 0 0-1-.4H3v-4h.08A1.7 1.7 0 0 0 4.6 8.6a1.7 1.7 0 0 0-.34-1.88l-.06-.06 2.83-2.83.06.06A1.7 1.7 0 0 0 9 4.6a1.7 1.7 0 0 0 1-.6 1.7 1.7 0 0 0 .4-1V3h4v.08A1.7 1.7 0 0 0 15.4 4.6a1.7 1.7 0 0 0 1.88-.34l.06-.06 2.83 2.83-.06.06A1.7 1.7 0 0 0 19.4 9c.16.36.37.7.6 1 .27.29.62.46 1 .48H21v4h-.08A1.7 1.7 0 0 0 19.4 15z"/>',logout:'<path d="M10 17l5-5-5-5M15 12H3M21 19V5a2 2 0 0 0-2-2h-6"/>',moon:'<path d="M21 12.8A9 9 0 1 1 11.2 3 7 7 0 0 0 21 12.8z"/>',menu:'<path d="M3 6h18M3 12h18M3 18h18"/>',search:'<circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/>',send:'<path d="m22 2-7 20-4-9-9-4Z"/><path d="M22 2 11 13"/>',spark:'<path d="m12 3-1.5 4.5L6 9l4.5 1.5L12 15l1.5-4.5L18 9l-4.5-1.5Z"/>',clock:'<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',check:'<path d="M20 6 9 17l-5-5"/>'};
document.querySelectorAll('[data-icon]').forEach(e=>{e.innerHTML=`<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">${icons[e.dataset.icon]||''}</svg>`});
const preferred=()=>localStorage.theme||(matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light');
const applyTheme=()=>{const dark=preferred()==='dark',id=document.documentElement.lang==='id';document.body.classList.toggle('dark',dark);document.documentElement.classList.toggle('dark',dark);document.documentElement.style.colorScheme=dark?'dark':'light';const label=document.querySelector('#theme-label');if(label)label.textContent=id?(dark?'Gelap':'Terang'):(dark?'Dark':'Light');document.querySelector('#theme')?.setAttribute('aria-pressed',String(dark))};
applyTheme();document.querySelector('#theme')?.addEventListener('click',()=>{localStorage.theme=preferred()==='dark'?'light':'dark';applyTheme()});document.querySelector('#menu')?.addEventListener('click',()=>document.querySelector('#side').classList.toggle('open'));

const notificationButton=document.querySelector('.notification-button');
if(notificationButton){
  let notificationState={last:0,key:'',soundEnabled:true,soundUrl:null,ready:false};
  const deviceSoundEnabled=()=>localStorage.getItem('aduanSoundEnabled')!=='false';
  const deviceVolume=()=>Math.max(0,Math.min(1,Number(localStorage.getItem('aduanSoundVolume')||70)/100));
  const playAlert=async()=>{
    if(!notificationState.soundEnabled||!deviceSoundEnabled())return;
    try{
      if(notificationState.soundUrl){const audio=new Audio(notificationState.soundUrl);audio.volume=deviceVolume();await audio.play();return}
      const Context=window.AudioContext||window.webkitAudioContext;if(!Context)return;
      const context=new Context();await context.resume();const gain=context.createGain();const oscillator=context.createOscillator();
      oscillator.type='sine';oscillator.frequency.setValueAtTime(740,context.currentTime);oscillator.frequency.exponentialRampToValueAtTime(980,context.currentTime+.18);gain.gain.setValueAtTime(.0001,context.currentTime);gain.gain.exponentialRampToValueAtTime(Math.max(.0001,.24*deviceVolume()),context.currentTime+.025);gain.gain.exponentialRampToValueAtTime(.0001,context.currentTime+.42);oscillator.connect(gain).connect(context.destination);oscillator.start();oscillator.stop(context.currentTime+.43);oscillator.onended=()=>context.close();
    }catch(_){/* Browser audio requires a prior user interaction. */}
  };
  const showBrowserAlert=item=>{
    if(!notificationState.soundEnabled||!('Notification'in window)||Notification.permission!=='granted')return;
    const alert=new Notification(item.title,{body:item.body||item.code||'',tag:`aduan-${item.id}`});
    alert.onclick=()=>{window.focus();if(item.ticket_id)location.href=`/tickets/${item.ticket_id}`;alert.close()};
  };
  const updateBadge=count=>{
    let badge=notificationButton.querySelector('b');
    if(count&&!badge){badge=document.createElement('b');notificationButton.appendChild(badge)}
    if(badge){badge.textContent=count>99?'99+':String(count);badge.hidden=!count}
  };
  const pollNotifications=async()=>{
    try{
      const response=await fetch(`/notifications/poll?after=${notificationState.ready?notificationState.last:0}`,{headers:{Accept:'application/json'}});if(!response.ok)return;
      const data=await response.json();notificationState.soundEnabled=data.sound_enabled;notificationState.soundUrl=data.sound_url;
      if(!notificationState.ready){notificationState.key=`aduanNotificationLastId:${data.user_key}`;const saved=localStorage.getItem(notificationState.key);notificationState.last=saved===null?data.latest:Number(saved);notificationState.ready=true;if(saved===null)localStorage.setItem(notificationState.key,String(data.latest));updateBadge(data.unread);syncNotificationSettings();return}
      const fresh=(data.notifications||[]).filter(item=>item.id>notificationState.last);if(fresh.length){notificationState.last=Math.max(...fresh.map(item=>item.id));localStorage.setItem(notificationState.key,String(notificationState.last));await playAlert();fresh.slice(-3).forEach(showBrowserAlert)}
      notificationState.last=Math.max(notificationState.last,data.latest||0);localStorage.setItem(notificationState.key,String(notificationState.last));updateBadge(data.unread);
    }catch(_){/* The next poll retries automatically. */}
  };
  const syncNotificationSettings=()=>{
    const enabled=document.querySelector('#device-sound-enabled'),volume=document.querySelector('#notification-volume'),value=document.querySelector('#notification-volume-value'),status=document.querySelector('#browser-alert-status');
    if(enabled)enabled.checked=deviceSoundEnabled();if(volume)volume.value=String(Math.round(deviceVolume()*100));if(value)value.textContent=`${Math.round(deviceVolume()*100)}%`;
    if(status&&'Notification'in window)status.textContent=document.documentElement.lang==='id'?`Status notifikasi browser: ${Notification.permission}`:`Browser notification status: ${Notification.permission}`;
  };
  document.querySelector('#device-sound-enabled')?.addEventListener('change',event=>localStorage.setItem('aduanSoundEnabled',String(event.target.checked)));
  document.querySelector('#notification-volume')?.addEventListener('input',event=>{localStorage.setItem('aduanSoundVolume',event.target.value);const value=document.querySelector('#notification-volume-value');if(value)value.textContent=`${event.target.value}%`});
  document.querySelector('#test-notification-sound')?.addEventListener('click',playAlert);
  document.querySelector('#enable-browser-alerts')?.addEventListener('click',async()=>{if('Notification'in window)await Notification.requestPermission();syncNotificationSettings()});
  pollNotifications();setInterval(pollNotifications,12000);
}
