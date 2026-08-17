import os
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

if __name__=="__main__":
    while True:
        try:
            while process_one(): pass
        except (sqlite3.Error,KeyError,TypeError): pass
        time.sleep(10)
