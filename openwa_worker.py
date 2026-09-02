"""One dispatcher only. Interrupted/ambiguous sends are never automatically replayed."""
import base64
import logging
import os
import re
import sqlite3
import time
import requests
import delivery
import json

logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')

def call(method,args=None):
    base=os.environ['OPENWA_URL'].rstrip('/'); sid=os.environ['OPENWA_SESSION_ID']
    headers={'X-API-Key':os.environ['WA_API_KEY']}; args=args or {}
    if method=='sendText':
        response=requests.post(f'{base}/api/sessions/{sid}/messages/send-text',headers=headers,json={'chatId':args['to'],'text':args['content']},timeout=(5,75))
    elif method=='sendFile':
        match=re.fullmatch(r'data:([^;]+);base64,(.+)',args['file'],re.DOTALL)
        if not match: raise ValueError('Invalid media payload')
        mime,encoded=match.groups(); route='send-image' if mime.startswith('image/') else 'send-video' if mime.startswith('video/') else 'send-audio' if mime.startswith('audio/') else 'send-document'
        response=requests.post(f'{base}/api/sessions/{sid}/messages/{route}',headers=headers,json={'chatId':args['to'],'base64':encoded,'mimetype':mime,'filename':args.get('filename'),'caption':args.get('caption','')[:1024]},timeout=(5,90))
    elif method=='getMessageById':
        response=requests.get(f'{base}/api/sessions/{sid}/messages/{args["messageId"]}',headers=headers,timeout=(5,75))
    else: raise ValueError('Unsupported OpenWA operation')
    response.raise_for_status()
    data=response.json()
    if not isinstance(data,dict): raise ValueError('Gateway rejected request')
    if method in ('sendText','sendFile'): return data.get('messageId') or data.get('id')
    return data

def register():
    base=os.environ['OPENWA_URL'].rstrip('/'); sid=os.environ['OPENWA_SESSION_ID']; headers={'X-API-Key':os.environ['WA_API_KEY']}
    response=requests.get(f'{base}/api/sessions/{sid}/webhooks',headers=headers,timeout=(5,30)); response.raise_for_status(); existing=response.json()
    for url,event in ((os.environ['OPENWA_ACK_URL'],'message.ack'),(os.environ['OPENWA_INCOMING_URL'],'message.received')):
        if not any(isinstance(item,dict) and item.get('url')==url and event in item.get('events',[]) for item in existing):
            response=requests.post(f'{base}/api/sessions/{sid}/webhooks',headers=headers,json={'url':url,'events':[event],'headers':{'Authorization':'Bearer '+os.environ['WEBHOOK_SECRET']},'retryCount':3},timeout=(5,30))
            response.raise_for_status()
            logging.info('%s listener registered',event)
    return True

def process_incoming(con):
    row=con.execute("SELECT * FROM openwa_inbox WHERE status='queued' ORDER BY created_at,rowid LIMIT 1").fetchone()
    if not row: return
    data=json.loads(row['payload']); payload={'id':row['id']}
    if data.get('media'):
        try:
            encoded=call('decryptMedia',{'message':row['id']})
            if isinstance(encoded,str) and encoded.startswith('data:') and len(encoded)<=11*1024*1024:
                payload['media']=encoded
        except (requests.RequestException,ValueError):
            logging.warning('Incoming attachment unavailable')
    response=requests.post(os.environ['ADUAN_INTERNAL_URL']+'/internal/openwa/process',json=payload,
        headers={'X-OpenWA-Token':os.environ['WEBHOOK_SECRET']},timeout=(5,30))
    if response.status_code==413 or (response.status_code==422 and payload.get('media')):
        payload.pop('media',None)
        response=requests.post(os.environ['ADUAN_INTERNAL_URL']+'/internal/openwa/process',json=payload,
            headers={'X-OpenWA-Token':os.environ['WEBHOOK_SECRET']},timeout=(5,30))
    response.raise_for_status()
    logging.info('Incoming event processed')

def recipient(con,org_id,phone):
    row=con.execute('SELECT payload FROM openwa_inbox WHERE org_id=? AND phone=? ORDER BY created_at DESC,rowid DESC LIMIT 1',(org_id,phone)).fetchone()
    target=json.loads(row['payload']).get('chat_id') if row else None
    return target if isinstance(target,str) and re.fullmatch(r'\d{8,20}@(lid|c\.us|s\.whatsapp\.net)',target) else phone+'@c.us'

def dispatch_system(con):
    con.execute('BEGIN IMMEDIATE')
    row=con.execute("SELECT * FROM openwa_system_outbox WHERE status='queued' ORDER BY id LIMIT 1").fetchone()
    if not row: con.commit(); return
    con.execute("UPDATE openwa_system_outbox SET status='sending' WHERE id=?",(row['id'],))
    if row['message_id']: con.execute("UPDATE messages SET delivery_status='sending' WHERE id=?",(row['message_id'],))
    con.commit()
    try:
        result=call('sendText',{'to':recipient(con,row['org_id'],row['phone']),'content':row['body']})
        if not isinstance(result,str) or not result: raise ValueError('Missing message ID')
        con.execute("UPDATE openwa_system_outbox SET external_id=?,status='pending' WHERE id=?",(result,row['id']))
        con.commit()
        if row['message_id']: delivery.finish(con,row['message_id'],result)
        ack=con.execute('SELECT ack FROM openwa_acks WHERE external_id=?',(result,)).fetchone()
        if ack: delivery.acknowledge(con,result,ack[0])
        logging.info('Autoreply %s accepted by OpenWA',row['id'])
    except (requests.RequestException,ValueError):
        con.execute("UPDATE openwa_system_outbox SET status='unknown' WHERE id=?",(row['id'],))
        if row['message_id']: con.execute("UPDATE messages SET delivery_status='unknown' WHERE id=?",(row['message_id'],))
        con.commit(); logging.warning('Autoreply %s uncertain; not replayed',row['id'])

def dispatch(con):
    con.execute('BEGIN IMMEDIATE')
    row=con.execute("SELECT m.*,c.phone,t.org_id FROM messages m JOIN tickets t ON t.id=m.ticket_id JOIN contacts c ON c.id=t.contact_id WHERE m.delivery_gateway='openwa' AND m.delivery_status='queued' AND NOT EXISTS(SELECT 1 FROM openwa_system_outbox o WHERE o.message_id=m.id) ORDER BY m.id LIMIT 1").fetchone()
    if not row:
        con.commit()
        return
    con.execute("UPDATE messages SET delivery_status='sending' WHERE id=?",(row['id'],))
    con.commit()
    phone=re.sub(r'\D','',row['phone'] or '')
    if phone.startswith('0'):
        phone='62'+phone[1:]
    try:
        if not 8<=len(phone)<=15:
            raise ValueError('Nomor WhatsApp tidak valid')
        target=recipient(con,row['org_id'],phone)
        args={'to':target,'content':row['body']}
        method='sendText'
        if row['attachment_path']:
            root=os.path.realpath(os.path.join(os.path.dirname(os.environ['DATABASE_PATH']),'uploads'))
            path=os.path.realpath(os.path.join(root,row['attachment_path']))
            if not path.startswith(root+os.sep):
                raise ValueError('Lokasi lampiran tidak valid')
            with open(path,'rb') as stream:
                content=base64.b64encode(stream.read()).decode()
            method='sendFile'
            args={'to':target,'file':'data:'+row['attachment_type']+';base64,'+content,'filename':row['attachment_name'],'caption':row['body'],'waitForId':True}
    except (ValueError,OSError):
        con.execute("UPDATE messages SET delivery_status='failed',delivery_error='Nomor atau lampiran tidak valid; belum dikirim.' WHERE id=?",(row['id'],))
        con.commit()
        return
    try:
        result=call(method,args)
        if not isinstance(result,str) or not result:
            raise ValueError('No reliable outbound message ID')
        delivery.finish(con,row['id'],result)
        logging.info('Message %s accepted by gateway',row['id'])
    except (requests.RequestException,ValueError):
        con.execute("UPDATE messages SET delivery_status='unknown',delivery_error='Hasil pengiriman belum pasti. Periksa WhatsApp sebelum mengirim ulang.' WHERE id=?",(row['id'],))
        con.commit()
        logging.warning('Message %s dispatch uncertain; not retried',row['id'])

def main():
    con=sqlite3.connect(os.environ['DATABASE_PATH'],timeout=30)
    con.row_factory=sqlite3.Row
    delivery.migrate(con)
    con.execute("UPDATE messages SET delivery_status='unknown',delivery_error='Worker terhenti saat mengirim. Periksa WhatsApp.' WHERE delivery_gateway='openwa' AND delivery_status='sending'")
    con.execute("UPDATE openwa_system_outbox SET status='unknown' WHERE status='sending'")
    con.commit()
    last_registration=0
    reconcile_cursor=0
    while True:
        try:
            if time.monotonic()-last_registration>30:
                register()
                last_registration=time.monotonic()
                # Recover missed webhook notifications without resending anything.
                rows=con.execute("SELECT id,external_id FROM messages WHERE delivery_gateway='openwa' AND external_id IS NOT NULL AND delivery_status IN ('pending','sent','delivered') AND created_at>datetime('now','-7 days') AND id>? ORDER BY id LIMIT 5",(reconcile_cursor,)).fetchall()
                for row in rows:
                    reconcile_cursor=row['id']
                    try:
                        message=call('getMessageById',{'messageId':row['external_id']})
                        ack=message.get('ack') if isinstance(message,dict) else None
                        if type(ack) is int and ack in delivery.ACK_STATUS:
                            delivery.acknowledge(con,row['external_id'],ack)
                    except (requests.RequestException,ValueError):
                        pass
                if len(rows)<5:
                    reconcile_cursor=0
            try: process_incoming(con)
            except (requests.RequestException,ValueError): logging.warning('Incoming processing unavailable; retained for retry')
            dispatch_system(con)
            dispatch(con)
        except Exception:
            logging.warning('Gateway/listener unavailable; queued messages retained')
        time.sleep(2)

if __name__=='__main__':
    main()
