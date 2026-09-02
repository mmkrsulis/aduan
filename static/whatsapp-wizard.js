(()=>{
  const wizard=document.querySelector('.wa-wizard');
  if(!wizard)return;
  const scanUrl=location.hostname.startsWith('172.16.31.')?`http://${location.hostname}:8080`:wizard.dataset.scanUrl;
  wizard.dataset.scanUrl=scanUrl;
  const scanLink=document.querySelector('#wa-open-scan');
  const id=wizard.dataset.lang==='id';
  const csrf=document.querySelector('meta[name="csrf-token"]')?.content||'';
  const number=document.querySelector('#wa-active-number');
  const detail=document.querySelector('#wa-status-detail');
  const badge=document.querySelector('#wa-connection-badge');
  const badgeText=document.querySelector('#wa-connection-text');
  const message=document.querySelector('#wa-wizard-message');
  const disconnect=document.querySelector('#wa-disconnect');
  const activate=document.querySelector('#wa-activate');
  const refresh=document.querySelector('#wa-refresh');
  const testPhone=document.querySelector('#wa-test-phone');
  const testButton=document.querySelector('#wa-test-send');
  const testResult=document.querySelector('#wa-test-result');
  const qrDialog=document.querySelector('#wa-qr-dialog');
  const qrImage=document.querySelector('#wa-qr-image');
  const qrLoading=document.querySelector('#wa-qr-loading');
  const qrStatus=document.querySelector('#wa-qr-status');
  let qrTimer=0,qrStatusTimer=0;

  const formatPhone=value=>value?`+${value.replace(/^(\d{2})(\d{3})(\d+)/,'$1 $2 $3')}`:'—';
  const announce=(text,type='')=>{message.textContent=text;message.className=`wa-wizard-message ${type}`};
  const busy=(button,value)=>{button.disabled=value;button.classList.toggle('loading',value)};
  const delay=milliseconds=>new Promise(resolve=>setTimeout(resolve,milliseconds));
  const closeQr=()=>{clearTimeout(qrTimer);clearTimeout(qrStatusTimer);qrTimer=0;qrStatusTimer=0;if(qrDialog?.open)qrDialog.close()};
  const refreshQr=()=>{
    if(!qrDialog?.open)return;
    qrLoading.hidden=false;qrImage.hidden=true;qrStatus.textContent=id?'Meminta kode QR terbaru…':'Requesting the latest QR code…';
    qrImage.onload=()=>{qrLoading.hidden=true;qrImage.hidden=false;qrStatus.textContent=id?'Pindai kode ini melalui menu Perangkat tertaut di WhatsApp.':'Scan this code from Linked devices in WhatsApp.';qrTimer=setTimeout(refreshQr,20000)};
    qrImage.onerror=()=>{qrLoading.hidden=false;qrImage.hidden=true;qrStatus.textContent=id?'QR belum siap. Mencoba kembali…':'QR is not ready. Retrying…';qrTimer=setTimeout(refreshQr,1500)};
    qrImage.src=`${wizard.dataset.qrUrl}?t=${Date.now()}`;
  };
  const watchQrStatus=async()=>{if(!qrDialog?.open)return;const state=await status(true);if(state.connected){announce(id?`WhatsApp ${formatPhone(state.phone)} berhasil terhubung.`:`WhatsApp ${formatPhone(state.phone)} connected successfully.`,'success');return}qrStatusTimer=setTimeout(watchQrStatus,1500)};
  const openQr=()=>{if(!qrDialog)return;if(typeof qrDialog.showModal==='function'){if(!qrDialog.open)qrDialog.showModal()}else qrDialog.setAttribute('open','');refreshQr();clearTimeout(qrStatusTimer);qrStatusTimer=setTimeout(watchQrStatus,800)};

  async function status(silent=false){
    if(!silent){busy(refresh,true);announce(id?'Memeriksa koneksi OpenWA…':'Checking OpenWA connection…')}
    try{
      const response=await fetch(wizard.dataset.statusUrl,{headers:{Accept:'application/json'}});
      if(!response.ok)throw Error();
      const data=await response.json();
      badge.classList.toggle('offline',!data.connected);
      badgeText.textContent=data.connected?(id?'Terhubung':'Connected'):(id?'Belum terhubung':'Disconnected');
      number.textContent=data.connected?formatPhone(data.phone):'—';
      detail.textContent=data.connected?(id?'OpenWA siap menerima dan mengirim pesan.':'OpenWA is ready to receive and send messages.'):(id?'Buka pemindai QR dan hubungkan nomor baru.':'Open the QR scanner and connect the new number.');
      disconnect.disabled=!data.connected;
      if(data.connected&&qrDialog?.open)closeQr();
      if(!silent)announce(data.connected?(id?'Koneksi aktif.':'Connection is active.'):(id?'OpenWA menunggu nomor baru.':'OpenWA is waiting for a new number.'),data.connected?'success':'');
      return data;
    }catch(_){
      badge.classList.add('offline');badgeText.textContent=id?'Menunggu QR':'Waiting for QR';disconnect.disabled=true;
      detail.textContent=id?'API belum aktif; ini normal ketika QR sedang ditampilkan.':'The API is unavailable while the QR scanner is active.';
      if(!silent)announce(id?'Buka pemindai QR untuk melanjutkan.':'Open the QR scanner to continue.');
      return {connected:false};
    }finally{busy(refresh,false)}
  }

  async function post(url){
    const response=await fetch(url,{method:'POST',headers:{Accept:'application/json','X-CSRF-Token':csrf}});
    const data=await response.json().catch(()=>({}));
    if(!response.ok)throw Error(data.error||(id?'Permintaan gagal.':'Request failed.'));
    return data;
  }

  async function postJson(url,payload){
    const response=await fetch(url,{method:'POST',headers:{Accept:'application/json','Content-Type':'application/json','X-CSRF-Token':csrf},body:JSON.stringify(payload)});
    const data=await response.json().catch(()=>({}));
    if(!response.ok)throw Error(data.error||(id?'Permintaan gagal.':'Request failed.'));
    return data;
  }

  refresh.addEventListener('click',()=>status());
  testButton?.addEventListener('click',async()=>{
    const phone=testPhone?.value.trim()||'';
    if(!phone){testResult.textContent=id?'Masukkan nomor tujuan terlebih dahulu.':'Enter a destination number first.';testResult.className='error';return}
    busy(testButton,true);testResult.textContent=id?'Mengirim pesan uji…':'Sending test message…';testResult.className='';
    try{const data=await postJson(wizard.dataset.testUrl,{phone});testResult.textContent=id?`Pesan uji berhasil dikirim ke +${data.phone}.`:`Test message sent to +${data.phone}.`;testResult.className='success'}
    catch(error){testResult.textContent=error.message;testResult.className='error'}
    finally{busy(testButton,false)}
  });
  scanLink?.addEventListener('click',openQr);
  document.querySelector('#wa-qr-close')?.addEventListener('click',closeQr);
  qrDialog?.addEventListener('cancel',event=>{event.preventDefault();closeQr()});
  disconnect.addEventListener('click',async()=>{
    if(!confirm(id?'Putuskan koneksi nomor WhatsApp? Pengiriman berhenti sementara sampai nomor baru terhubung.':'Disconnect the WhatsApp number? Sending pauses until the new number is connected.'))return;
    busy(disconnect,true);announce(id?'Memutuskan sesi lama…':'Disconnecting old session…');
    try{
      await post(wizard.dataset.disconnectUrl);
      announce(id?'Nomor lama sudah diputus. Menunggu pemindai QR siap…':'Old number disconnected. Waiting for the QR scanner…');
      number.textContent='—';badge.classList.add('offline');badgeText.textContent=id?'Menunggu QR':'Waiting for QR';
      let ready=false;
      for(let attempt=0;attempt<45&&!ready;attempt++){
        const state=await status(true);ready=Boolean(state.scanner_ready);
        if(!ready)await delay(1000);
      }
      if(!ready)throw Error(id?'Pemindai QR belum siap. Gunakan tombol “Buka pemindai QR” untuk mencoba kembali.':'QR scanner is not ready. Use the Open QR scanner button to retry.');
      openQr();announce(id?'Pemindai siap. Pindai QR di jendela ini.':'Scanner ready. Scan the QR code in this window.','success');
    }catch(error){
      announce(error.message,'error');
    }
    finally{busy(disconnect,false)}
  });
  activate.addEventListener('click',async()=>{
    busy(activate,true);announce(id?'Memverifikasi nomor baru…':'Verifying the new number…');
    try{
      const data=await post(wizard.dataset.activateUrl);
      number.textContent=formatPhone(data.phone);badge.classList.remove('offline');badgeText.textContent=id?'Terhubung':'Connected';
      detail.textContent=id?'Nomor baru aktif dan tombol WhatsApp publik sudah diperbarui.':'New number is active and the public WhatsApp button has been updated.';
      announce(id?`Nomor ${formatPhone(data.phone)} berhasil diaktifkan.`:`${formatPhone(data.phone)} is now active.`,'success');
    }catch(error){announce(error.message,'error')}
    finally{busy(activate,false)}
  });

  status(true);
  setInterval(()=>{if(document.visibilityState==='visible')status(true)},10000);
})();
