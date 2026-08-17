import email, imaplib, os, re, ssl, time, html, hashlib
from email import policy
from email.header import decode_header, make_header
from email.utils import parseaddr
from html.parser import HTMLParser
from app import app, db, decrypt_secret, next_ticket_code, send_ticket_email, store_upload

INTERVAL=max(15,int(os.getenv("EMAIL_POLL_SECONDS","60")))

class TextExtractor(HTMLParser):
    def __init__(self): super().__init__(); self.parts=[]
    def handle_data(self,data): self.parts.append(data)
    def text(self): return re.sub(r"\n{3,}","\n\n",html.unescape(" ".join(self.parts))).strip()

def decoded(value):
    try: return str(make_header(decode_header(value or "")))
    except Exception: return value or ""

def message_text(message):
    plain=[]; rich=[]
    for part in message.walk():
        if part.get_content_disposition()=="attachment": continue
        kind=part.get_content_type()
        if kind not in ("text/plain","text/html"): continue
        try: content=part.get_content()
        except Exception: continue
        if kind=="text/plain": plain.append(content)
        else:
            parser=TextExtractor(); parser.feed(content); rich.append(parser.text())
    text="\n".join(plain or rich).strip()
    # Remove the most common quoted reply marker while retaining the actual response.
    return re.split(r"\nOn .+ wrote:\s*\n|\nPada .+ menulis:\s*\n",text,maxsplit=1,flags=re.I)[0].strip()[:12000]

def attachments(message):
    stored=[]
    for part in message.iter_attachments():
        mime=part.get_content_type(); filename=decoded(part.get_filename() or "attachment")
        try:
            item=store_upload(payload=part.get_payload(decode=True),original_name=filename,mime=mime); stored.append(item)
        except (ValueError,TypeError): continue
    return stored

def connect(config):
    if config["imap_security"]=="ssl": client=imaplib.IMAP4_SSL(config["imap_host"],config["imap_port"],ssl_context=ssl.create_default_context(),timeout=30)
    else:
        client=imaplib.IMAP4(config["imap_host"],config["imap_port"],timeout=30)
        if config["imap_security"]=="starttls": client.starttls(ssl_context=ssl.create_default_context())
    client.login(config["imap_username"],decrypt_secret(config["imap_password"])); client.select(config["imap_folder"] or "INBOX")
    return client

def find_ticket(org_id,subject,message,sender_email):
    code_match=re.search(r"\[([A-Za-z0-9][A-Za-z0-9._/-]{2,79})\]",subject or "")
    if code_match:
        row=db().execute("SELECT t.* FROM tickets t JOIN contacts c ON c.id=t.contact_id WHERE t.org_id=? AND t.code=? AND lower(COALESCE(c.email,c.phone))=?",(org_id,code_match.group(1),sender_email)).fetchone()
        if row: return row
    refs=" ".join(filter(None,[message.get("In-Reply-To"),message.get("References")]))
    ids=re.findall(r"<[^>]+>",refs)
    if ids:
        placeholders=",".join("?" for _ in ids)
        return db().execute(f"SELECT t.* FROM tickets t JOIN contacts c ON c.id=t.contact_id JOIN messages m ON m.ticket_id=t.id WHERE t.org_id=? AND lower(COALESCE(c.email,c.phone))=? AND m.external_id IN ({placeholders}) ORDER BY m.id DESC LIMIT 1",[org_id,sender_email,*ids]).fetchone()
    return None

def process_message(config,raw):
    message=email.message_from_bytes(raw,policy=policy.default); message_id=(message.get("Message-ID") or f"generated-{hashlib.sha256(raw).hexdigest()}").strip()
    if db().execute("SELECT 1 FROM email_receipts WHERE org_id=? AND message_id=?",(config["org_id"],message_id)).fetchone(): return
    sender_name,sender_email=parseaddr(message.get("From") or ""); sender_email=sender_email.strip().lower()
    if not sender_email or sender_email==str(config["address"] or "").lower(): return
    subject=decoded(message.get("Subject") or "Tanpa subjek")[:500]; body=message_text(message) or "[Email tanpa isi teks]"; files=attachments(message)
    ticket=find_ticket(config["org_id"],subject,message,sender_email); created=False
    if not ticket:
        contact=db().execute("SELECT * FROM contacts WHERE org_id=? AND (email=? OR phone=?)",(config["org_id"],sender_email,sender_email)).fetchone()
        if contact: cid=contact["id"]; db().execute("UPDATE contacts SET name=COALESCE(NULLIF(?,''),name),email=? WHERE id=?",(sender_name,sender_email,cid))
        else: db().execute("INSERT INTO contacts(org_id,name,phone,email,location) VALUES(?,?,?,?,?)",(config["org_id"],sender_name or sender_email,sender_email,sender_email,"Email")); cid=db().execute("SELECT last_insert_rowid()").fetchone()[0]
        org=db().execute("SELECT * FROM organizations WHERE id=?",(config["org_id"],)).fetchone(); code=next_ticket_code(org)
        db().execute("INSERT INTO tickets(org_id,contact_id,code,subject,channel,email_subject) VALUES(?,?,?,?,?,?)",(config["org_id"],cid,code,subject,"email",subject)); tid=db().execute("SELECT last_insert_rowid()").fetchone()[0]; ticket=db().execute("SELECT t.*,c.email,c.phone FROM tickets t JOIN contacts c ON c.id=t.contact_id WHERE t.id=?",(tid,)).fetchone(); created=True
    else:
        tid=ticket["id"]
    db().execute("INSERT INTO messages(ticket_id,direction,body,sender,delivery_status,channel,external_id) VALUES(?,?,?,?,?,?,?)",(tid,"in",body,sender_name or sender_email,"received","email",message_id))
    for path,name,mime in files: db().execute("INSERT INTO messages(ticket_id,direction,body,sender,attachment_path,attachment_name,attachment_type,delivery_status,channel,external_id) VALUES(?,?,?,?,?,?,?,?,?,?)",(tid,"in","",sender_name or sender_email,path,name,mime,"received","email",message_id+":"+path))
    db().execute("INSERT INTO email_receipts(org_id,message_id,ticket_id) VALUES(?,?,?)",(config["org_id"],message_id,tid)); db().execute("UPDATE tickets SET updated_at=CURRENT_TIMESTAMP WHERE id=?",(tid,)); title="Aduan email baru" if created else "Balasan email baru"; db().execute("INSERT INTO notifications(org_id,ticket_id,title,body) VALUES(?,?,?,?)",(config["org_id"],tid,title,f"{sender_name or sender_email}: {subject}")); db().commit()
    if created and config["auto_reply"]:
        full=db().execute("SELECT t.*,c.email,c.phone FROM tickets t JOIN contacts c ON c.id=t.contact_id WHERE t.id=?",(tid,)).fetchone(); text=f"Email Anda telah kami terima dan tercatat dengan nomor {full['code']}. Simpan nomor ini untuk komunikasi selanjutnya."
        ok,_=send_ticket_email(full,text)
        if ok: db().execute("INSERT INTO messages(ticket_id,direction,body,sender,delivery_status,channel) VALUES(?,?,?,?,?,?)",(tid,"out",text,config["sender_name"] or "Sistem","sent","email")); db().commit()

def poll(config):
    client=connect(config)
    try:
        status,data=client.search(None,"UNSEEN")
        if status!="OK": raise RuntimeError("IMAP search failed")
        for uid in data[0].split()[:100]:
            status,payload=client.fetch(uid,"(RFC822)")
            if status=="OK" and payload and isinstance(payload[0],tuple): process_message(config,payload[0][1]); client.store(uid,"+FLAGS","\\Seen")
    finally:
        try: client.logout()
        except Exception: pass

def run_once():
    with app.app_context():
        configs=db().execute("SELECT * FROM email_configs WHERE enabled=1").fetchall()
        for config in configs:
            try: poll(config); db().execute("UPDATE email_configs SET last_checked_at=CURRENT_TIMESTAMP,last_error=NULL WHERE id=?",(config["id"],)); db().commit()
            except Exception as exc: db().execute("UPDATE email_configs SET last_error=? WHERE id=?",(str(exc)[:500],config["id"])); db().commit()

if __name__=="__main__":
    while True: run_once(); time.sleep(INTERVAL)
