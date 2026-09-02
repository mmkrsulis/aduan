(() => {
  const chat = document.querySelector('.messages');
  const labels = {queued:'Mengantre',sending:'Mengirim',pending:'Menunggu konfirmasi',sent:'✓ Terkirim',delivered:'✓✓ Sampai',read:'✓✓ Dibaca',played:'✓✓ Diputar',failed:'! Gagal',unknown:'? Belum pasti',received:'Diterima'};
  function status(element, value, error) {
    element.dataset.status = value;
    element.textContent = labels[value] || value;
    element.title = error || labels[value] || value;
    element.setAttribute('aria-label', element.title);
  }
  document.querySelectorAll('.delivery-status').forEach(el => status(el, el.dataset.status));
  if (!chat?.dataset.deliveryUrl) return;
  const url = chat.dataset.deliveryUrl, form = document.querySelector('.chat-composer');
  const notice = document.createElement('div');
  notice.className = 'delivery-notice'; notice.setAttribute('role','status'); chat.after(notice);
  function reconcile(message) {
    let bubble = [...chat.querySelectorAll('.message')].find(el => el.dataset.messageId === String(message.id) || (message.client_token && el.dataset.clientToken === message.client_token));
    if (!bubble) {
      bubble = document.createElement('div'); bubble.className = 'message out';
      const meta = document.createElement('small');
      meta.append(document.createTextNode(`${message.sender || 'Anda'} · ${message.created_at || 'Sekarang'} · `));
      const indicator = document.createElement('span'); indicator.className = 'delivery-status'; meta.append(indicator);
      bubble.append(meta);
      if (message.body) { const body = document.createElement('p'); body.textContent = message.body; bubble.append(body); }
      if (message.attachment_name) { const attachment = document.createElement('span'); attachment.className = 'delivery-file'; attachment.textContent = '📎 ' + message.attachment_name; bubble.append(attachment); }
      chat.append(bubble); chat.scrollTop = chat.scrollHeight;
    }
    if (message.id) bubble.dataset.messageId = String(message.id);
    bubble.dataset.clientToken = message.client_token || '';
    if (message.attachment_url && bubble.querySelector('.delivery-file')) {
      const link=document.createElement('a'); link.href=message.attachment_url; link.textContent='📎 '+message.attachment_name;
      bubble.querySelector('.delivery-file').replaceWith(link);
    }
    status(bubble.querySelector('.delivery-status'),message.delivery_status,message.delivery_error);
    return bubble;
  }
  async function poll() {
    try {
      const response = await fetch(url,{headers:{Accept:'application/json'},signal:AbortSignal.timeout(10000)});
      if (!response.ok || response.redirected) throw new Error();
      const data = await response.json(); data.messages.forEach(reconcile);
      if (notice.dataset.pollError) { notice.textContent=''; delete notice.dataset.pollError; }
    } catch (_) { if (!notice.textContent || notice.dataset.pollError) { notice.textContent='Pembaruan status terputus. Mencoba menyambung kembali…'; notice.dataset.pollError='1'; } }
    setTimeout(poll,3000);
  }
  poll();
  let busy = false;
  form?.addEventListener('submit', async event => {
    if ((event.submitter?.value || document.getElementById('composer-submit').value) !== 'reply') return;
    event.preventDefault(); if (busy) return;
    const body = form.querySelector('[name="body"]'), file = form.querySelector('[name="attachment"]');
    if (!body.value.trim() && !file.files.length) return;
    busy = true;
    const bytes = crypto.getRandomValues(new Uint8Array(20));
    const token = Array.from(bytes,b=>b.toString(16).padStart(2,'0')).join('');
    const data = new FormData(form); data.set('client_token',token);
    const bubble = reconcile({body:body.value,client_token:token,attachment_name:file.files[0]?.name,delivery_status:'sending'});
    const originalBody=body.value; body.value=''; body.dispatchEvent(new Event('input'));
    file.value=''; document.getElementById('attachment-chip').hidden=true;
    notice.textContent=''; delete notice.dataset.pollError;
    try {
      const response=await fetch(url,{method:'POST',body:data,headers:{'X-CSRF-Token':document.querySelector('meta[name="csrf-token"]').content},signal:AbortSignal.timeout(30000)});
      if (response.redirected) throw new Error();
      const result=await response.json();
      if (!response.ok) {
        if (response.status>=500) throw new Error();
        status(bubble.querySelector('.delivery-status'),'failed',result.error);
        notice.textContent=result.error || 'Pesan ditolak. Silakan periksa lalu kirim ulang.';
        if (!body.value) body.value=originalBody;
        return;
      }
      reconcile(result.message);
    } catch (_) {
      status(bubble.querySelector('.delivery-status'),'unknown','Koneksi terputus. Tunggu pembaruan status sebelum mengirim ulang.');
      notice.textContent='Hasil pengiriman belum pasti. Tunggu pembaruan otomatis dan periksa WhatsApp sebelum mengirim ulang.';
    } finally { busy=false; }
  });
})();
