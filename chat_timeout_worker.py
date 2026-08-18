import os
import json
import sqlite3
import time

import requests
from app import app, create_notification, db as app_db

DB=os.getenv("DATABASE_PATH","/data/aduan.db")

def send(org,phone,message):
    base=org["mpwa_url"] or os.getenv("MPWA_BASE_URL","")
    key=org["mpwa_key"] or os.getenv("MPWA_API_KEY","")
    sender=org["mpwa_sender"] or os.getenv("MPWA_SENDER","")
    if not (base and key and sender): return False
    try:
        response=requests.post(base.rstrip("/")+"/send-message",data={"api_key":key,"sender":sender,"number":phone,"message":message},timeout=15)
        payload=response.json() if response.content else {}
        return response.ok and payload.get("status") is True
    except (requests.RequestException,ValueError): return False

def process_one():
    con=sqlite3.connect(DB,timeout=30); con.row_factory=sqlite3.Row; con.execute("PRAGMA busy_timeout=30000")
    notification=None
    try:
        con.execute("BEGIN IMMEDIATE")
        chat=con.execute("SELECT * FROM chat_requests WHERE status='pending' AND expires_at<=CURRENT_TIMESTAMP ORDER BY expires_at LIMIT 1").fetchone()
        if not chat: con.commit(); return False
        changed=con.execute("UPDATE chat_requests SET status='processing' WHERE id=? AND status='pending'",(chat["id"],)).rowcount; con.commit()
        if not changed: return True
        org=con.execute("SELECT * FROM organizations WHERE id=?",(chat["org_id"],)).fetchone(); flow=con.execute("SELECT * FROM flow_configs WHERE org_id=?",(chat["org_id"],)).fetchone()
        message=flow["chat_timeout_id" if chat["language"]=="id" else "chat_timeout_en"]
        if send(org,chat["phone"],message):
            con.execute("UPDATE chat_requests SET status='expired',expired_at=CURRENT_TIMESTAMP WHERE id=?",(chat["id"],))
            con.execute("UPDATE conversation_states SET step='menu',human_takeover=0,data='{}',updated_at=CURRENT_TIMESTAMP WHERE org_id=? AND phone=?",(chat["org_id"],chat["phone"]))
            con.execute("INSERT INTO messages(ticket_id,direction,body,sender,delivery_status) VALUES(?,?,?,?,?)",(chat["ticket_id"],"out",message,"Sistem","sent"))
            notification=(chat["org_id"],chat["ticket_id"],"Permintaan chat kedaluwarsa","Tidak ada petugas yang mengonfirmasi dalam 5 menit.")
        else: con.execute("UPDATE chat_requests SET status='pending' WHERE id=?",(chat["id"],))
        con.commit()
        if notification:
            with app.app_context():
                create_notification(*notification); app_db().commit()
        return True
    finally: con.close()

def process_idle_one():
    con=sqlite3.connect(DB,timeout=30); con.row_factory=sqlite3.Row; con.execute("PRAGMA busy_timeout=30000")
    try:
        con.execute("BEGIN IMMEDIATE")
        state=con.execute("""SELECT s.*,f.idle_minutes,f.idle_message_id,f.idle_message_en FROM conversation_states s JOIN flow_configs f ON f.org_id=s.org_id WHERE s.human_takeover=1 AND f.idle_enabled=1 AND f.idle_minutes>=5 AND s.updated_at<=datetime('now','-' || f.idle_minutes || ' minutes') ORDER BY s.updated_at LIMIT 1""").fetchone()
        if not state: con.commit(); return False
        changed=con.execute("UPDATE conversation_states SET step='idle_processing' WHERE id=? AND updated_at=?",(state["id"],state["updated_at"])).rowcount; con.commit()
        if not changed: return True
        org=con.execute("SELECT * FROM organizations WHERE id=?",(state["org_id"],)).fetchone(); message=state["idle_message_id" if state["language"]=="id" else "idle_message_en"]
        if not message or not send(org,state["phone"],message):
            con.execute("UPDATE conversation_states SET step=? WHERE id=? AND step='idle_processing'",(state["step"],state["id"])); con.commit(); return True
        try: ticket_id=int(json.loads(state["data"] or "{}").get("ticket_id") or 0)
        except (ValueError,TypeError,AttributeError): ticket_id=0
        if not ticket_id:
            ticket=con.execute("SELECT t.id FROM tickets t JOIN contacts c ON c.id=t.contact_id WHERE t.org_id=? AND c.phone=? ORDER BY t.updated_at DESC LIMIT 1",(state["org_id"],state["phone"])).fetchone(); ticket_id=ticket["id"] if ticket else 0
        if ticket_id: con.execute("INSERT INTO messages(ticket_id,direction,body,sender,delivery_status) VALUES(?,?,?,?,?)",(ticket_id,"out",message,"Sistem","sent"))
        con.execute("UPDATE conversation_states SET step='identity',human_takeover=0,data='{}',updated_at=CURRENT_TIMESTAMP WHERE id=? AND step='idle_processing'",(state["id"],)); con.commit(); return True
    finally: con.close()

if __name__=="__main__":
    while True:
        try:
            while process_one(): pass
            while process_idle_one(): pass
        except (sqlite3.Error,KeyError,TypeError): pass
        time.sleep(10)
