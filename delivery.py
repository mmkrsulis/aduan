"""Durable, at-most-once dispatch for the development OpenWA account."""
import os
import sqlite3
import secrets
import re

class Connection(sqlite3.Connection):
    hold_commit = False
    def commit(self):
        if not self.hold_commit:
            super().commit()

def normalize_incoming(data):
    if not isinstance(data,dict): raise ValueError('invalid message')
    mid=data.get('id')
    if isinstance(mid,dict): mid=mid.get('_serialized')
    if not isinstance(mid,str) or len(mid)>250: raise ValueError('invalid id')
    if data.get('fromMe') or data.get('isGroupMsg') or data.get('isGroup'): return None
    address=data.get('from','')
    if not isinstance(address,str): raise ValueError('invalid sender')
    if address.endswith(('@g.us','@broadcast','@newsletter')): return None
    chat_id=address
    sender=data.get('sender') if isinstance(data.get('sender'),dict) else (data.get('contact') if isinstance(data.get('contact'),dict) else {})
    if address.endswith('@lid'):
        # Modern WhatsApp uses privacy IDs for chats; never treat a LID as a phone number.
        candidate=data.get('senderPhone') or sender.get('phoneNumber') or sender.get('id')
        if isinstance(candidate,str) and re.fullmatch(r'\d{8,15}',candidate): candidate+='@c.us'
        if isinstance(candidate,str) and re.fullmatch(r'\d{8,15}@(c\.us|s\.whatsapp\.net)',candidate): address=candidate
    if not re.fullmatch(r'\d{8,15}@(c\.us|s\.whatsapp\.net)',address): raise ValueError('unsupported sender address')
    kind=data.get('type','text')
    if kind not in ('chat','text','image','video','audio','voice','ptt','document','sticker'): return None
    body=(data.get('body') if kind in ('chat','text') else (data.get('caption') or data.get('body'))) or ''
    if not isinstance(body,str) or len(body)>16000: raise ValueError('invalid body')
    return {'id':mid,'phone':address.split('@')[0],'chat_id':chat_id,'name':str(sender.get('pushname') or sender.get('formattedName') or 'Pelapor')[:120],
            'body':body or '[Lampiran]','media':kind not in ('chat','text'),'mime':str(data.get('mimetype') or (data.get('media') or {}).get('mimetype') or '').split(';')[0],
            'filename':str(data.get('filename') or 'lampiran')[:200]}

ACK_STATUS = {-1: 'failed', 0: 'pending', 1: 'sent', 2: 'delivered', 3: 'read', 4: 'played'}

def enabled():
    return os.getenv('OPENWA_DELIVERY', '').lower() == 'true'

def migrate(con):
    columns = {r[1] for r in con.execute('PRAGMA table_info(messages)')}
    for name, kind in {'delivery_gateway':'TEXT', 'client_token':'TEXT', 'delivery_ack':'INTEGER', 'delivery_error':'TEXT'}.items():
        if name not in columns:
            try:
                con.execute(f'ALTER TABLE messages ADD COLUMN {name} {kind}')
            except sqlite3.OperationalError as exc:
                if 'duplicate column' not in str(exc).lower():
                    raise
    con.execute('CREATE UNIQUE INDEX IF NOT EXISTS messages_client_token ON messages(ticket_id,client_token) WHERE client_token IS NOT NULL')
    con.execute('CREATE TABLE IF NOT EXISTS openwa_acks(external_id TEXT PRIMARY KEY, ack INTEGER NOT NULL, updated_at TEXT DEFAULT CURRENT_TIMESTAMP)')
    con.execute("CREATE TABLE IF NOT EXISTS openwa_inbox(id TEXT PRIMARY KEY,org_id INTEGER NOT NULL,phone TEXT NOT NULL,payload TEXT NOT NULL,status TEXT DEFAULT 'queued',error TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP)")
    con.execute("CREATE TABLE IF NOT EXISTS openwa_system_outbox(id INTEGER PRIMARY KEY,org_id INTEGER NOT NULL,phone TEXT NOT NULL,body TEXT NOT NULL,token TEXT UNIQUE NOT NULL,status TEXT DEFAULT 'queued',external_id TEXT,message_id INTEGER,created_at TEXT DEFAULT CURRENT_TIMESTAMP)")
    con.commit()

def queue_system(con,org_id,phone,body,token=None):
    phone=re.sub(r'\D','',phone or '')
    if phone.startswith('0'): phone='62'+phone[1:]
    if not 8<=len(phone)<=15 or not body: raise ValueError('Invalid recipient or empty message')
    token=token or secrets.token_hex(24)
    con.execute('INSERT OR IGNORE INTO openwa_system_outbox(org_id,phone,body,token) VALUES(?,?,?,?)',(org_id,phone,body,token))
    con.commit()
    return con.execute('SELECT id FROM openwa_system_outbox WHERE token=?',(token,)).fetchone()[0]

def enqueue(con, ticket, sender, body, attachment, token):
    con.execute('''INSERT OR IGNORE INTO messages(ticket_id,direction,body,sender,attachment_path,attachment_name,attachment_type,delivery_status,channel,delivery_gateway,client_token)
        VALUES(?,'out',?,?,?,?,?,'queued','whatsapp','openwa',?)''',
        (ticket['id'],body,sender,*(attachment or (None,None,None)),token))
    con.execute('UPDATE tickets SET updated_at=CURRENT_TIMESTAMP WHERE id=?',(ticket['id'],))
    con.execute("INSERT INTO conversation_states(org_id,phone,step,language,data,human_takeover) VALUES(?,?,'human_chat','id','{}',1) ON CONFLICT(org_id,phone) DO UPDATE SET step='human_chat',human_takeover=1,updated_at=CURRENT_TIMESTAMP",(ticket['org_id'],ticket['phone']))
    con.commit()
    return con.execute('SELECT * FROM messages WHERE ticket_id=? AND client_token=?',(ticket['id'],token)).fetchone()

def acknowledge(con, external_id, ack):
    # An ACK can arrive before sendText returns its message ID. Keep it for reconciliation.
    con.execute('''INSERT INTO openwa_acks(external_id,ack) VALUES(?,?) ON CONFLICT(external_id) DO UPDATE SET
        ack=CASE WHEN MAX(openwa_acks.ack,excluded.ack)>=1 THEN MAX(openwa_acks.ack,excluded.ack)
        WHEN MIN(openwa_acks.ack,excluded.ack)=-1 THEN -1 ELSE 0 END,updated_at=CURRENT_TIMESTAMP''',(external_id,ack))
    current = con.execute('SELECT ack FROM openwa_acks WHERE external_id=?',(external_id,)).fetchone()[0]
    con.execute("UPDATE messages SET delivery_ack=?,delivery_status=?,delivery_error=NULL WHERE external_id=? AND delivery_gateway='openwa'",(current,ACK_STATUS[current],external_id))
    con.execute('UPDATE openwa_system_outbox SET status=? WHERE external_id=?',(ACK_STATUS[current],external_id))
    con.commit()

def finish(con, mid, external_id):
    con.execute("UPDATE messages SET external_id=?,delivery_status='pending' WHERE id=?",(external_id,mid))
    con.commit()
    ack=con.execute('SELECT ack FROM openwa_acks WHERE external_id=?',(external_id,)).fetchone()
    if ack:
        acknowledge(con,external_id,ack[0])
