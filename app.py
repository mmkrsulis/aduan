import os, sqlite3, json, secrets, csv, io, base64, uuid, re, hashlib, smtplib, ssl
from email.message import EmailMessage
from datetime import datetime, timezone, timedelta
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, g, Response, send_file, send_from_directory
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.middleware.proxy_fix import ProxyFix
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from cryptography.fernet import Fernet, InvalidToken
import requests
import qrcode
from zoneinfo import ZoneInfo
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
app.secret_key = os.getenv("SECRET_KEY", secrets.token_hex(32))
app.config.update(MAX_CONTENT_LENGTH=8*1024*1024,SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SAMESITE="Lax",SESSION_COOKIE_SECURE=os.getenv("COOKIE_SECURE","false").lower()=="true",PERMANENT_SESSION_LIFETIME=timedelta(days=30))
api_tokens=URLSafeTimedSerializer(app.secret_key,salt="aduanhub-mobile-v1")
DB = os.getenv("DATABASE_PATH", os.path.join(os.path.dirname(__file__), "aduan.db"))
UPLOAD_DIR = os.getenv("UPLOAD_DIR", os.path.join(os.path.dirname(DB), "uploads"))
ALLOWED_MEDIA = {"image/jpeg":"jpg","image/png":"png","image/webp":"webp","video/mp4":"mp4","audio/mpeg":"mp3","audio/ogg":"ogg","application/pdf":"pdf"}
ANDROID_APK_PATH = os.getenv("ANDROID_APK_PATH", os.path.join(os.path.dirname(DB), "releases", "AduanHub.apk"))

def api_token_version(password_hash):
    return hashlib.sha256((password_hash or "").encode()).hexdigest()[:16]

def credential_cipher():
    key=base64.urlsafe_b64encode(hashlib.sha256(app.secret_key.encode()).digest())
    return Fernet(key)

def encrypt_secret(value): return credential_cipher().encrypt((value or "").encode()).decode() if value else None
def decrypt_secret(value):
    if not value: return ""
    try: return credential_cipher().decrypt(value.encode()).decode()
    except (InvalidToken,ValueError): return ""

def issue_mobile_token(user, device_name="Android"):
    cur=db().execute("INSERT INTO mobile_devices(org_id,user_id,name,platform,last_seen_at) VALUES(?,?,?,?,CURRENT_TIMESTAMP)",(user["org_id"],user["id"],(device_name or "Android")[:80],"android"))
    did=cur.lastrowid
    return api_tokens.dumps({"uid":user["id"],"did":did,"v":api_token_version(user["password"])})

ID = {
 "Overview":"Ringkasan","Service intelligence at a glance":"Ringkasan kinerja layanan",
 "Complaints":"Aduan","Users":"Pengguna","Settings":"Pengaturan","Complaint Flow":"Alur Aduan","Reports":"Laporan","Sign out":"Keluar",
 "MPWA channel":"Kanal MPWA","All complaints":"Semua aduan","Across every channel":"Dari seluruh kanal",
 "New intake":"Aduan baru","Needs triage":"Perlu diverifikasi","In progress":"Sedang diproses",
 "Being handled":"Dalam penanganan","Resolved":"Terselesaikan","Completed cases":"Aduan selesai",
 "Recent complaints":"Aduan terbaru","Latest conversations requiring attention":"Percakapan terbaru yang perlu ditangani",
 "View all":"Lihat semua","Category overview":"Ringkasan kategori","Current intake distribution":"Distribusi aduan saat ini",
 "Case":"Nomor","Citizen / Customer":"Pelapor / Pelanggan","Category":"Kategori","Priority":"Prioritas","Status":"Status",
 "Search case, person, phone…":"Cari nomor, pelapor, telepon…","All statuses":"Semua status","Filter":"Saring",
 "Triage, assign, and resolve every incoming request":"Verifikasi, disposisi, dan selesaikan setiap aduan",
 "User management":"Manajemen pengguna","Control workspace access, roles, and responsibilities":"Kelola akses, peran, dan tanggung jawab pengguna",
 "Workspace users":"Pengguna workspace","registered team members":"anggota tim terdaftar","Invite a user":"Tambah pengguna",
 "Create secure workspace access":"Buat akses workspace yang aman","Full name":"Nama lengkap","Email":"Email",
 "Temporary password":"Kata sandi sementara","Role":"Peran","Unit / department":"Unit / bidang","Create user":"Buat pengguna",
 "Workspace settings":"Pengaturan workspace","Brand and connect this deployment to your WhatsApp gateway":"Atur identitas dan koneksi ke gateway WhatsApp",
 "Organization":"Organisasi","White-label identity shown to your team":"Identitas white-label yang ditampilkan kepada tim",
 "Organization name":"Nama organisasi","Service terminology":"Istilah layanan","Accent color":"Warna utama",
 "MPWA connection":"Koneksi MPWA","Existing gateway used for inbound and outbound messages":"Gateway untuk menerima dan mengirim pesan",
 "API key":"Kunci API","Sender / device token":"Pengirim / token perangkat","Configure this as the device webhook in MPWA":"Gunakan alamat ini sebagai webhook perangkat MPWA",
 "Save settings":"Simpan pengaturan","Case details":"Detail aduan","Responsible unit":"Unit penanggung jawab",
 "Assignee":"Petugas","Unassigned":"Belum ditugaskan","Save changes":"Simpan perubahan","Add internal note":"Tambah catatan internal",
 "Reply":"Balas","Write a reply or internal note…":"Tulis balasan atau catatan internal…","Internal note":"Catatan internal",
 "Location not provided":"Lokasi belum tersedia","No complaints found.":"Tidak ada aduan ditemukan.",
 "Welcome back":"Selamat datang","Sign in to your organization workspace.":"Masuk ke workspace organisasi Anda.",
 "Email address":"Alamat email","Password":"Kata sandi","Sign in":"Masuk","Demo accounts":"Akun demo",
 "Operations console":"Konsol operasional","Turn conversations into accountable service.":"Ubah percakapan menjadi layanan yang terukur.",
 "One calm workspace for WhatsApp intake, assignment, resolution, and reporting.":"Satu workspace untuk penerimaan WhatsApp, disposisi, penyelesaian, dan pelaporan.",
 "Every message deserves a clear owner and a measurable outcome.":"Setiap pesan berhak memiliki penanggung jawab dan hasil yang terukur.",
 "new":"baru","verified":"terverifikasi","assigned":"ditugaskan","in progress":"diproses","waiting":"menunggu","resolved":"selesai","closed":"ditutup",
 "low":"rendah","normal":"normal","high":"tinggi","urgent":"mendesak","Language":"Bahasa"
}

def tr(value):
    return ID.get(value, value) if session.get("lang", "en") == "id" else value

def csrf_token():
    if "csrf" not in session: session["csrf"]=secrets.token_urlsafe(32)
    return session["csrf"]

@app.before_request
def csrf_protect():
    # Credentials authenticate login; exempt it to avoid stale-token errors after
    # logout, browser back/forward cache, or signing in from multiple tabs.
    if request.method=="POST" and request.endpoint not in ("webhook","login") and not request.path.startswith("/api/"):
        expected=session.get("csrf",""); supplied=request.form.get("csrf_token","") or request.headers.get("X-CSRF-Token","")
        if not expected or not secrets.compare_digest(expected,supplied): return ("Invalid or expired form token",400)

SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS organizations(id INTEGER PRIMARY KEY, name TEXT NOT NULL, app_name TEXT DEFAULT 'AduanHub', slug TEXT UNIQUE, logo TEXT, icon TEXT, accent TEXT DEFAULT '#2563eb', terminology TEXT DEFAULT 'Complaint', timezone TEXT DEFAULT 'Asia/Jakarta', ticket_prefix TEXT DEFAULT 'ADU', ticket_format TEXT DEFAULT '{prefix}-{year}-{number:05d}', notification_sound TEXT, notification_sound_enabled INTEGER DEFAULT 1, mpwa_url TEXT, mpwa_key TEXT, mpwa_sender TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, org_id INTEGER NOT NULL, name TEXT NOT NULL, email TEXT UNIQUE NOT NULL, password TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('owner','admin','supervisor','agent','viewer')), unit TEXT, active INTEGER DEFAULT 1, last_login TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(org_id) REFERENCES organizations(id));
CREATE TABLE IF NOT EXISTS contacts(id INTEGER PRIMARY KEY, org_id INTEGER NOT NULL, name TEXT, phone TEXT NOT NULL, location TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, UNIQUE(org_id,phone), FOREIGN KEY(org_id) REFERENCES organizations(id));
CREATE TABLE IF NOT EXISTS tickets(id INTEGER PRIMARY KEY, org_id INTEGER NOT NULL, contact_id INTEGER NOT NULL, code TEXT UNIQUE, subject TEXT NOT NULL, category TEXT DEFAULT 'General', priority TEXT DEFAULT 'normal', status TEXT DEFAULT 'new', unit TEXT, assignee_id INTEGER, sla_due TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP, closed_at TEXT, FOREIGN KEY(org_id) REFERENCES organizations(id), FOREIGN KEY(contact_id) REFERENCES contacts(id), FOREIGN KEY(assignee_id) REFERENCES users(id));
CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY, ticket_id INTEGER NOT NULL, direction TEXT NOT NULL, body TEXT NOT NULL, sender TEXT, internal INTEGER DEFAULT 0, attachment_path TEXT, attachment_name TEXT, attachment_type TEXT, delivery_status TEXT DEFAULT 'received', created_at TEXT DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(ticket_id) REFERENCES tickets(id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS audit_logs(id INTEGER PRIMARY KEY, org_id INTEGER NOT NULL, user_id INTEGER, action TEXT NOT NULL, entity TEXT, entity_id INTEGER, metadata TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS units(id INTEGER PRIMARY KEY, org_id INTEGER NOT NULL, name TEXT NOT NULL, officer_name TEXT, officer_phone TEXT, active INTEGER DEFAULT 1, created_at TEXT DEFAULT CURRENT_TIMESTAMP, UNIQUE(org_id,name), FOREIGN KEY(org_id) REFERENCES organizations(id));
CREATE TABLE IF NOT EXISTS categories(id INTEGER PRIMARY KEY, org_id INTEGER NOT NULL, name TEXT NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP, UNIQUE(org_id,name), FOREIGN KEY(org_id) REFERENCES organizations(id));
CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY, org_id INTEGER NOT NULL, user_id INTEGER, ticket_id INTEGER, title TEXT NOT NULL, body TEXT, read_at TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(org_id) REFERENCES organizations(id), FOREIGN KEY(user_id) REFERENCES users(id), FOREIGN KEY(ticket_id) REFERENCES tickets(id));
CREATE TABLE IF NOT EXISTS flow_configs(id INTEGER PRIMARY KEY, org_id INTEGER UNIQUE NOT NULL, enabled INTEGER DEFAULT 1, default_language TEXT DEFAULT 'id', welcome_id TEXT, welcome_en TEXT, service_info_id TEXT, service_info_en TEXT, confirmation_id TEXT, confirmation_en TEXT, completion_id TEXT, completion_en TEXT, forward_template_id TEXT, forward_template_en TEXT, status_template_id TEXT, status_template_en TEXT, unavailable_id TEXT, unavailable_en TEXT, menu_items TEXT DEFAULT '[]', ai_enabled INTEGER DEFAULT 0, ai_prompt TEXT, ai_confidence REAL DEFAULT .8, session_timeout_minutes INTEGER DEFAULT 30, office_hours TEXT DEFAULT 'Monday-Friday, 08:00-16:00', updated_at TEXT DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(org_id) REFERENCES organizations(id));
CREATE TABLE IF NOT EXISTS conversation_states(id INTEGER PRIMARY KEY, org_id INTEGER NOT NULL, phone TEXT NOT NULL, step TEXT NOT NULL DEFAULT 'menu', language TEXT DEFAULT 'id', data TEXT DEFAULT '{}', human_takeover INTEGER DEFAULT 0, updated_at TEXT DEFAULT CURRENT_TIMESTAMP, UNIQUE(org_id,phone), FOREIGN KEY(org_id) REFERENCES organizations(id));
CREATE TABLE IF NOT EXISTS chat_requests(id INTEGER PRIMARY KEY, org_id INTEGER NOT NULL, ticket_id INTEGER NOT NULL, phone TEXT NOT NULL, language TEXT DEFAULT 'id', status TEXT DEFAULT 'pending', expires_at TEXT NOT NULL, approved_by INTEGER, approved_at TEXT, expired_at TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(org_id) REFERENCES organizations(id), FOREIGN KEY(ticket_id) REFERENCES tickets(id) ON DELETE CASCADE, FOREIGN KEY(approved_by) REFERENCES users(id));
CREATE TABLE IF NOT EXISTS mobile_pairings(id INTEGER PRIMARY KEY, org_id INTEGER NOT NULL, user_id INTEGER NOT NULL, token_hash TEXT UNIQUE NOT NULL, expires_at TEXT NOT NULL, used_at TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(org_id) REFERENCES organizations(id), FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS mobile_devices(id INTEGER PRIMARY KEY, org_id INTEGER NOT NULL, user_id INTEGER NOT NULL, name TEXT NOT NULL, platform TEXT DEFAULT 'android', last_seen_at TEXT, revoked_at TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(org_id) REFERENCES organizations(id), FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS email_configs(id INTEGER PRIMARY KEY, org_id INTEGER UNIQUE NOT NULL, enabled INTEGER DEFAULT 0, address TEXT, sender_name TEXT, imap_host TEXT, imap_port INTEGER DEFAULT 993, imap_security TEXT DEFAULT 'ssl', imap_username TEXT, imap_password TEXT, imap_folder TEXT DEFAULT 'INBOX', smtp_host TEXT, smtp_port INTEGER DEFAULT 587, smtp_security TEXT DEFAULT 'starttls', smtp_username TEXT, smtp_password TEXT, signature TEXT, auto_reply INTEGER DEFAULT 1, last_checked_at TEXT, last_error TEXT, updated_at TEXT DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(org_id) REFERENCES organizations(id));
CREATE TABLE IF NOT EXISTS email_receipts(id INTEGER PRIMARY KEY, org_id INTEGER NOT NULL, message_id TEXT NOT NULL, ticket_id INTEGER, received_at TEXT DEFAULT CURRENT_TIMESTAMP, UNIQUE(org_id,message_id), FOREIGN KEY(org_id) REFERENCES organizations(id), FOREIGN KEY(ticket_id) REFERENCES tickets(id) ON DELETE SET NULL);
"""

def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB,timeout=30); g.db.row_factory = sqlite3.Row; g.db.execute("PRAGMA foreign_keys=ON"); g.db.execute("PRAGMA busy_timeout=30000")
    return g.db

@app.teardown_appcontext
def close_db(_=None):
    c=g.pop("db",None)
    if c: c.close()

@app.after_request
def security_headers(response):
    response.headers["X-Content-Type-Options"]="nosniff"; response.headers["X-Frame-Options"]="DENY"; response.headers["Referrer-Policy"]="strict-origin-when-cross-origin"; response.headers["Permissions-Policy"]="camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"]="default-src 'self'; style-src 'self' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; script-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'"
    return response

def init_db():
    os.makedirs(os.path.dirname(DB), exist_ok=True); os.makedirs(UPLOAD_DIR, exist_ok=True)
    con=sqlite3.connect(DB, timeout=30); con.executescript(SCHEMA)
    migrations={
      "organizations":{"app_name":"TEXT DEFAULT 'AduanHub'","icon":"TEXT","timezone":"TEXT DEFAULT 'Asia/Jakarta'","ticket_prefix":"TEXT DEFAULT 'ADU'","ticket_format":"TEXT DEFAULT '{prefix}-{year}-{number:05d}'","notification_sound":"TEXT","notification_sound_enabled":"INTEGER DEFAULT 1"},
      "contacts":{"email":"TEXT"},
      "tickets":{"channel":"TEXT DEFAULT 'whatsapp'","email_subject":"TEXT"},
      "messages":{"attachment_path":"TEXT","attachment_name":"TEXT","attachment_type":"TEXT","delivery_status":"TEXT DEFAULT 'received'","channel":"TEXT DEFAULT 'whatsapp'","external_id":"TEXT"},
      "flow_configs":{"forward_template_id":"TEXT","forward_template_en":"TEXT","status_template_id":"TEXT","status_template_en":"TEXT","unavailable_id":"TEXT","unavailable_en":"TEXT","identity_prompt_id":"TEXT","identity_prompt_en":"TEXT","chat_waiting_id":"TEXT","chat_waiting_en":"TEXT","chat_connected_id":"TEXT","chat_connected_en":"TEXT","chat_timeout_id":"TEXT","chat_timeout_en":"TEXT","menu_items":"TEXT DEFAULT '[]'","ai_enabled":"INTEGER DEFAULT 0","ai_prompt":"TEXT","ai_confidence":"REAL DEFAULT .8","session_timeout_minutes":"INTEGER DEFAULT 30"}
    }
    for table,columns in migrations.items():
        existing={r[1] for r in con.execute(f"PRAGMA table_info({table})")}
        for column,definition in columns.items():
            if column not in existing:
                try: con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
                except sqlite3.OperationalError as e:
                    if "duplicate column" not in str(e).lower(): raise
    con.execute("BEGIN IMMEDIATE")
    if not con.execute("SELECT 1 FROM organizations WHERE slug='demo'").fetchone():
        con.execute("INSERT OR IGNORE INTO organizations(name,slug,terminology,mpwa_url) VALUES(?,?,?,?)", ("Education & Culture Office","demo","Complaint",os.getenv("MPWA_BASE_URL","http://host.docker.internal:18082")))
        oid=con.execute("SELECT id FROM organizations WHERE slug='demo'").fetchone()[0]
        users=[("System Owner","owner@demo.local","owner","Executive Office"),("Service Admin","admin@demo.local","admin","Public Service"),("Intake Agent","agent@demo.local","agent","Service Desk"),("Department Head","supervisor@demo.local","supervisor","Education")]
        bootstrap_password=os.getenv("BOOTSTRAP_PASSWORD","ChangeMeBeforeLaunch!")
        for name,email,role,unit in users: con.execute("INSERT INTO users(org_id,name,email,password,role,unit) VALUES(?,?,?,?,?,?)",(oid,name,email,generate_password_hash(bootstrap_password),role,unit))
        samples=[("Siti Rahma","628123456780","North District","Damaged classroom roof","Facilities","high","in_progress","Primary Education"),("Ahmad Fajar","628123456781","Central District","Scholarship disbursement inquiry","Scholarship","normal","new","Student Affairs"),("Budi Santoso","628123456782","West District","Certificate legalization request","Administration","low","resolved","Secretariat")]
        for i,s in enumerate(samples,1):
            con.execute("INSERT INTO contacts(org_id,name,phone,location) VALUES(?,?,?,?)",(oid,*s[:3])); cid=con.execute("SELECT last_insert_rowid()").fetchone()[0]
            con.execute("INSERT INTO tickets(org_id,contact_id,code,subject,category,priority,status,unit) VALUES(?,?,?,?,?,?,?,?)",(oid,cid,f"EDU-2026-{i:05}",*s[3:]))
            tid=con.execute("SELECT last_insert_rowid()").fetchone()[0]; con.execute("INSERT INTO messages(ticket_id,direction,body,sender) VALUES(?,?,?,?)",(tid,"in",s[3],s[0]))
        for unit,officer in [("Secretariat","Secretary"),("Primary Education","Division Head"),("Student Affairs","Coordinator"),("Culture","Division Head")]:
            con.execute("INSERT OR IGNORE INTO units(org_id,name,officer_name) VALUES(?,?,?)",(oid,unit,officer))
    demo=con.execute("SELECT id FROM organizations WHERE slug='demo'").fetchone()
    if demo and not con.execute("SELECT 1 FROM units WHERE org_id=?",(demo[0],)).fetchone():
        for unit,officer in [("Secretariat","Secretary"),("Primary Education","Division Head"),("Student Affairs","Coordinator"),("Culture","Division Head")]:
            con.execute("INSERT OR IGNORE INTO units(org_id,name,officer_name) VALUES(?,?,?)",(demo[0],unit,officer))
    if demo and not con.execute("SELECT 1 FROM flow_configs WHERE org_id=?",(demo[0],)).fetchone():
        con.execute("""INSERT INTO flow_configs(org_id,welcome_id,welcome_en,service_info_id,service_info_en,confirmation_id,confirmation_en,completion_id,completion_en) VALUES(?,?,?,?,?,?,?,?,?)""",(
            demo[0],
            "Halo, selamat datang di Layanan Aduan {organization}.\n\n1. Buat aduan baru\n2. Cek status aduan\n3. Informasi layanan\n\nBalas dengan angka 1, 2, atau 3.",
            "Hello, welcome to {organization} Complaint Service.\n\n1. Create a new complaint\n2. Check complaint status\n3. Service information\n\nReply with 1, 2, or 3.",
            "Layanan ini menerima aduan dan permintaan informasi. Ketik MENU kapan saja untuk kembali ke menu utama.",
            "This service accepts complaints and information requests. Type MENU at any time to return to the main menu.",
            "Periksa kembali ringkasan berikut:\n\nNama: {name}\nLokasi: {location}\nAduan: {description}\n\nBalas KIRIM untuk membuat aduan, UBAH untuk mengulang, atau BATAL.",
            "Please review this summary:\n\nName: {name}\nLocation: {location}\nComplaint: {description}\n\nReply SEND to submit, EDIT to restart, or CANCEL.",
            "Aduan Anda telah tercatat dengan nomor {code}. Simpan nomor ini untuk memeriksa status aduan.",
            "Your complaint has been registered as {code}. Keep this number to check its status."
        ))
    con.execute("UPDATE flow_configs SET office_hours='Senin–Jumat, 08.00–16.00' WHERE office_hours='Monday-Friday, 08:00-16:00'")
    con.execute("UPDATE flow_configs SET welcome_id=replace(welcome_id,'Balas dengan angka 1, 2, atau 3.','Balas dengan angka 1, 2, 3, atau 4.'),welcome_en=replace(welcome_en,'Reply with 1, 2, or 3.','Reply with 1, 2, 3, or 4.')")
    con.execute("UPDATE organizations SET ticket_prefix=upper(substr(slug,1,3)) WHERE ticket_prefix IS NULL OR ticket_prefix='' OR ticket_prefix='ADU'")
    con.execute("INSERT OR IGNORE INTO categories(org_id,name) SELECT org_id,category FROM tickets WHERE category IS NOT NULL AND trim(category)<>''")
    con.execute("""UPDATE flow_configs SET
      forward_template_id=COALESCE(forward_template_id,'Aduan baru ditugaskan\n{code} — {description}\nPelapor: {name}\nLokasi: {location}\nPrioritas: {priority}\nMohon koordinasikan tindak lanjut dengan layanan aduan.'),
      forward_template_en=COALESCE(forward_template_en,'New complaint assigned\n{code} — {description}\nReporter: {name}\nLocation: {location}\nPriority: {priority}\nPlease coordinate the follow-up with the complaint desk.'),
      status_template_id=COALESCE(status_template_id,'Status {code}: {status}\nAduan: {description}\nUnit: {unit}\nPembaruan: {updated_at}'),
      status_template_en=COALESCE(status_template_en,'Status {code}: {status}\nComplaint: {description}\nUnit: {unit}\nUpdated: {updated_at}'),
      unavailable_id=COALESCE(unavailable_id,'Layanan sedang di luar jam operasional ({office_hours}). Pesan Anda tetap kami terima.'),
      unavailable_en=COALESCE(unavailable_en,'The service is currently outside operating hours ({office_hours}). Your message is still received.'),
      identity_prompt_id=COALESCE(identity_prompt_id,'Halo, selamat datang di Layanan Aduan {organization}.\n\nSebelum melanjutkan, apakah Anda berkenan membagikan nama?\n\n1. Bagikan nama\n2. Tetap rahasia\n\nBalas dengan angka 1 atau 2.'),
      identity_prompt_en=COALESCE(identity_prompt_en,'Hello, welcome to the Complaint Service of {organization}.\n\nBefore continuing, would you like to share your name?\n\n1. Share my name\n2. Remain anonymous\n\nReply with 1 or 2.'),
      chat_waiting_id=COALESCE(chat_waiting_id,'Kami akan menghubungkan Anda dengan petugas layanan. Silakan menunggu maksimal 5 menit.'),
      chat_waiting_en=COALESCE(chat_waiting_en,'We will connect you with a service officer. Please wait for up to 5 minutes.'),
      chat_connected_id=COALESCE(chat_connected_id,'Anda sudah terhubung ke petugas layanan. Silakan sampaikan pesan Anda.'),
      chat_connected_en=COALESCE(chat_connected_en,'You are now connected to a service officer. Please send your message.'),
      chat_timeout_id=COALESCE(chat_timeout_id,'Maaf, petugas layanan saat ini belum tersedia. Silakan pilih menu Buat Aduan agar laporan Anda tercatat dan dapat kami proses. Ketik MENU untuk kembali ke menu utama.'),
      chat_timeout_en=COALESCE(chat_timeout_en,'Sorry, a service officer is currently unavailable. Please choose Create a Complaint so your report is recorded and can be processed. Type MENU to return to the main menu.'),
      ai_prompt=COALESCE(ai_prompt,'Klasifikasikan aduan secara singkat, objektif, dan jangan membuat fakta baru.'),
      menu_items=CASE WHEN menu_items IS NULL OR menu_items='' OR menu_items='[]' THEN '[{"key":"1","label_id":"Buat aduan baru","label_en":"Create a new complaint","action":"new"},{"key":"2","label_id":"Cek status aduan","label_en":"Check complaint status","action":"status"},{"key":"3","label_id":"Informasi layanan","label_en":"Service information","action":"info"}]' ELSE menu_items END""")
    for row in con.execute("SELECT id,menu_items,welcome_id,welcome_en FROM flow_configs").fetchall():
        try: items=json.loads(row[1] or "[]")
        except (ValueError,TypeError): items=[]
        chat_item=next((item for item in items if item.get("action")=="chat_admin"),None); had_chat=bool(chat_item)
        if not chat_item:
            used={str(item.get("key","")) for item in items}; key=next((str(i) for i in range(1,10) if str(i) not in used),"ADMIN")
            chat_item={"key":key,"label_id":"Chat dengan admin","label_en":"Chat with admin","action":"chat_admin","response_id":"Baik, percakapan ini diteruskan kepada admin. Silakan tuliskan pesan Anda. Admin akan membalas melalui WhatsApp ini.","response_en":"This conversation has been forwarded to an admin. Please write your message and an admin will reply through this WhatsApp chat."}; items.append(chat_item)
        key=str(chat_item.get("key") or "4"); welcome_id=(row[2] or "").replace("\r\n","\n"); welcome_en=(row[3] or "").replace("\r\n","\n")
        if "Chat dengan admin" not in welcome_id and "\n\nBalas" in welcome_id: welcome_id=welcome_id.replace("\n\nBalas",f"\n{key}. Chat dengan admin\n\nBalas",1)
        if "Chat with admin" not in welcome_en and "\n\nReply" in welcome_en: welcome_en=welcome_en.replace("\n\nReply",f"\n{key}. Chat with admin\n\nReply",1)
        if welcome_id!=row[2] or welcome_en!=row[3] or not had_chat:
            con.execute("UPDATE flow_configs SET menu_items=?,welcome_id=?,welcome_en=? WHERE id=?",(json.dumps(items),welcome_id,welcome_en,row[0]))
    con.execute("UPDATE units SET active=1")
    con.commit(); con.close()

def login_required(fn):
    @wraps(fn)
    def inner(*a,**kw):
        if not session.get("uid"): return redirect(url_for("login"))
        return fn(*a,**kw)
    return inner

def roles(*allowed):
    def deco(fn):
        @wraps(fn)
        def inner(*a,**kw):
            if session.get("role") not in allowed: return ("Forbidden",403)
            return fn(*a,**kw)
        return inner
    return deco

def audit(action,entity=None,eid=None,metadata=None):
    db().execute("INSERT INTO audit_logs(org_id,user_id,action,entity,entity_id,metadata) VALUES(?,?,?,?,?,?)",(session.get("org_id",1),session.get("uid"),action,entity,eid,json.dumps(metadata or {}))); db().commit()

def is_central_admin(): return session.get("role") in ("owner","admin")

def ticket_access(ticket_row):
    if is_central_admin(): return True
    unit=(session.get("unit") or "").strip()
    if not ticket_row["unit"] or ticket_row["unit"]!=unit: return False
    if session.get("role")=="agent" and ticket_row["assignee_id"]: return ticket_row["assignee_id"]==session.get("uid")
    return True

def scoped_ticket_where(alias="t"):
    if is_central_admin(): return "1=1",[]
    if session.get("role")=="agent": return f"{alias}.unit=? AND ({alias}.assignee_id IS NULL OR {alias}.assignee_id=?)",[session.get("unit") or "",session.get("uid")]
    return f"{alias}.unit=?",[session.get("unit") or ""]

def notify_assigned_users(org_id,ticket_id,title,body,unit=None,assignee_id=None):
    params=[org_id]; where="org_id=? AND active=1 AND role IN ('supervisor','agent')"
    if assignee_id: where+=" AND (id=? OR (role='supervisor' AND unit=?))"; params.extend([assignee_id,unit or ""])
    elif unit: where+=" AND unit=?"; params.append(unit)
    else: return
    for user in db().execute(f"SELECT id FROM users WHERE {where}",params).fetchall():
        db().execute("INSERT INTO notifications(org_id,user_id,ticket_id,title,body) VALUES(?,?,?,?,?)",(org_id,user["id"],ticket_id,title,body))

@app.context_processor
def ctx():
    unread=0
    if session.get("org_id"):
        if is_central_admin(): unread=db().execute("SELECT count(*) FROM notifications WHERE org_id=? AND read_at IS NULL AND (user_id IS NULL OR user_id=?)",(session["org_id"],session.get("uid"))).fetchone()[0]
        else: unread=db().execute("SELECT count(*) FROM notifications WHERE org_id=? AND user_id=? AND read_at IS NULL",(session["org_id"],session.get("uid"))).fetchone()[0]
    brand=None
    if session.get("org_id"): brand=db().execute("SELECT name,app_name,logo,icon,accent,terminology,timezone,notification_sound,notification_sound_enabled FROM organizations WHERE id=?",(session["org_id"],)).fetchone()
    def localdt(value):
        if not value: return "-"
        try:
            parsed=datetime.fromisoformat(str(value).replace("Z","+00:00")); parsed=parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
            return parsed.astimezone(ZoneInfo((brand["timezone"] if brand else None) or "UTC")).strftime("%d %b %Y, %H:%M:%S")
        except (ValueError,TypeError,KeyError): return str(value)
    def localdate(value):
        formatted=localdt(value)
        try: return datetime.strptime(formatted,"%d %b %Y, %H:%M:%S").strftime("%d %b %Y")
        except ValueError: return formatted
    return {"me":session,"brand":brand,"now":datetime.utcnow(),"statuses":["new","verified","assigned","in_progress","waiting","resolved","closed"],"tr":tr,"lang":session.get("lang","en"),"unread":unread,"csrf_token":csrf_token,"localdt":localdt,"localdate":localdate}

def store_upload(file=None, payload=None, original_name=None, mime=None):
    if file:
        mime=(file.mimetype or "").split(";")[0].lower(); raw=file.read(); original_name=secure_filename(file.filename or "attachment")
    else: raw=payload
    if mime not in ALLOWED_MEDIA or not raw: raise ValueError("Format lampiran tidak didukung")
    if len(raw)>8*1024*1024: raise ValueError("Lampiran melebihi batas 8 MB")
    filename=f"{uuid.uuid4().hex}.{ALLOWED_MEDIA[mime]}"
    with open(os.path.join(UPLOAD_DIR,filename),"wb") as target: target.write(raw)
    return filename,(original_name or filename)[:200],mime

def next_ticket_code(org):
    now=datetime.now(timezone.utc); number=db().execute("SELECT count(*)+1 FROM tickets WHERE org_id=?",(org["id"],)).fetchone()[0]
    pattern=(org["ticket_format"] or "{prefix}-{year}-{number:05d}")[:80]; values={"prefix":(org["ticket_prefix"] or org["slug"][:3]).upper(),"year":now.year,"month":f"{now.month:02d}","day":f"{now.day:02d}","number":number}
    try: code=pattern.format_map(values)
    except (KeyError,ValueError): code=f"{values['prefix']}-{now.year}-{number:05d}"
    while db().execute("SELECT 1 FROM tickets WHERE code=?",(code,)).fetchone():
        number+=1; values["number"]=number
        try: code=pattern.format_map(values)
        except (KeyError,ValueError): code=f"{values['prefix']}-{now.year}-{number:05d}"
    return code[:80]

@app.get("/media/<path:filename>")
def media_file(filename):
    # Random UUID filenames are unguessable and required so MPWA can retrieve outbound media.
    if not filename.replace(".","").isalnum() or ".." in filename: return ("Not found",404)
    return send_from_directory(UPLOAD_DIR,filename,as_attachment=request.args.get("download")=="1")

@app.get("/language/<code>")
def language(code):
    if code in ("en","id"): session["lang"]=code
    target=request.args.get("next","/")
    return redirect(target if target.startswith("/") and not target.startswith("//") else "/")

@app.route("/health")
def health(): return jsonify(status="ok")

@app.route("/login",methods=["GET","POST"])
def login():
    if request.method=="POST":
        u=db().execute("SELECT u.*,o.name org_name FROM users u JOIN organizations o ON o.id=u.org_id WHERE email=? AND active=1",(request.form["email"].lower(),)).fetchone()
        if u and check_password_hash(u["password"],request.form["password"]):
            remember=request.form.get("remember")=="1"; session.clear(); session.permanent=remember; session.update(uid=u["id"],org_id=u["org_id"],name=u["name"],role=u["role"],unit=u["unit"] or "",org_name=u["org_name"]); db().execute("UPDATE users SET last_login=CURRENT_TIMESTAMP WHERE id=?",(u["id"],)); db().commit(); return redirect(url_for("dashboard"))
        flash("Invalid credentials","error")
    login_brand=db().execute("SELECT name,app_name,logo,icon,accent,terminology FROM organizations ORDER BY id LIMIT 1").fetchone()
    return render_template("login.html",login_brand=login_brand)

@app.route("/logout")
def logout(): session.clear(); return redirect(url_for("login"))

@app.route("/")
@login_required
def dashboard():
    oid=session["org_id"]; scope,scope_params=scoped_ticket_where("t"); base=f"t.org_id=? AND {scope}"
    stats={s:db().execute(f"SELECT count(*) FROM tickets t WHERE {base} AND t.status=?",[oid,*scope_params,s]).fetchone()[0] for s in ["new","in_progress","resolved","closed"]}
    stats["all"]=db().execute(f"SELECT count(*) FROM tickets t WHERE {base}",[oid,*scope_params]).fetchone()[0]
    tickets=db().execute(f"SELECT t.*,c.name contact,c.phone,u.name assignee FROM tickets t JOIN contacts c ON c.id=t.contact_id LEFT JOIN users u ON u.id=t.assignee_id WHERE {base} ORDER BY t.updated_at DESC LIMIT 8",[oid,*scope_params]).fetchall()
    cats=db().execute(f"SELECT t.category,count(*) n FROM tickets t WHERE {base} GROUP BY t.category ORDER BY n DESC",[oid,*scope_params]).fetchall()
    return render_template("dashboard.html",stats=stats,tickets=tickets,cats=cats)

@app.get("/download/android")
@login_required
def download_android():
    if not os.path.isfile(ANDROID_APK_PATH):
        return ("Android application is not available.", 404)
    return send_file(ANDROID_APK_PATH, mimetype="application/vnd.android.package-archive", as_attachment=True, download_name="AduanHub-1.1.0.apk")

@app.get("/mobile/connect")
@login_required
def mobile_connect():
    raw=secrets.token_urlsafe(32); digest=hashlib.sha256(raw.encode()).hexdigest()
    db().execute("UPDATE mobile_pairings SET used_at=CURRENT_TIMESTAMP WHERE user_id=? AND used_at IS NULL",(session["uid"],))
    cur=db().execute("INSERT INTO mobile_pairings(org_id,user_id,token_hash,expires_at) VALUES(?,?,?,datetime('now','+2 minutes'))",(session["org_id"],session["uid"],digest))
    pairing_id=cur.lastrowid; db().commit()
    payload=json.dumps({"v":1,"server":request.url_root.rstrip("/"),"token":raw},separators=(",",":"))
    image=qrcode.make(payload); output=io.BytesIO(); image.save(output,format="PNG")
    qr="data:image/png;base64,"+base64.b64encode(output.getvalue()).decode()
    devices=db().execute("SELECT d.*,u.name user_name FROM mobile_devices d JOIN users u ON u.id=d.user_id WHERE d.org_id=? AND d.revoked_at IS NULL AND (? IN ('owner','admin') OR d.user_id=?) ORDER BY d.created_at DESC",(session["org_id"],session["role"],session["uid"])).fetchall()
    return render_template("mobile_connect.html",qr=qr,pairing_id=pairing_id,devices=devices)

@app.post("/mobile/devices/<int:device_id>/revoke")
@login_required
def mobile_device_revoke(device_id):
    device=db().execute("SELECT * FROM mobile_devices WHERE id=? AND org_id=?",(device_id,session["org_id"])).fetchone()
    if not device or (session["role"] not in ("owner","admin") and device["user_id"]!=session["uid"]): return ("Not found",404)
    db().execute("UPDATE mobile_devices SET revoked_at=CURRENT_TIMESTAMP WHERE id=?",(device_id,)); db().commit(); flash("Akses perangkat dicabut","success")
    return redirect(url_for("mobile_connect"))

@app.route("/tickets")
@login_required
def tickets():
    q=request.args.get("q",""); status=request.args.get("status",""); scope,scope_params=scoped_ticket_where("t"); params=[session["org_id"],*scope_params]; where=f"t.org_id=? AND {scope}"
    if q: where+=" AND (t.code LIKE ? OR t.subject LIKE ? OR c.name LIKE ? OR c.phone LIKE ?)"; params += [f"%{q}%"]*4
    if status: where+=" AND t.status=?"; params.append(status)
    rows=db().execute(f"SELECT t.*,c.name contact,c.phone,u.name assignee FROM tickets t JOIN contacts c ON c.id=t.contact_id LEFT JOIN users u ON u.id=t.assignee_id WHERE {where} ORDER BY t.updated_at DESC",params).fetchall()
    return render_template("tickets.html",tickets=rows)

@app.route("/tickets/<int:tid>",methods=["GET","POST"])
@login_required
def ticket(tid):
    t=db().execute("SELECT t.*,c.name contact,c.phone,c.email,c.location FROM tickets t JOIN contacts c ON c.id=t.contact_id WHERE t.id=? AND t.org_id=?",(tid,session["org_id"])).fetchone()
    if not t: return ("Not found",404)
    if not ticket_access(t): return ("Forbidden",403)
    can_reply=t["status"] not in ("resolved","closed") and (is_central_admin() or (session.get("role") in ("supervisor","agent") and bool(t["unit"])))
    if request.method=="POST":
        action=request.form.get("action")
        if action=="update":
            if not is_central_admin(): return ("Forbidden",403)
            new_status=request.form["status"]; new_category=request.form.get("new_category","").strip()[:80]; category=new_category or request.form.get("category","").strip() or "General"
            new_unit=request.form["unit"]; new_assignee=request.form.get("assignee") or None
            if new_assignee and not db().execute("SELECT 1 FROM users WHERE id=? AND org_id=? AND unit=? AND active=1 AND role IN ('supervisor','agent')",(new_assignee,session["org_id"],new_unit)).fetchone(): flash("Petugas harus berasal dari unit yang dipilih.","error"); return redirect(url_for("ticket",tid=tid))
            db().execute("INSERT OR IGNORE INTO categories(org_id,name) VALUES(?,?)",(session["org_id"],category))
            db().execute("UPDATE tickets SET status=?,priority=?,category=?,unit=?,assignee_id=?,updated_at=CURRENT_TIMESTAMP,closed_at=CASE WHEN ? IN ('resolved','closed') THEN COALESCE(closed_at,CURRENT_TIMESTAMP) ELSE NULL END WHERE id=?",(new_status,request.form["priority"],category,new_unit,new_assignee,new_status,tid)); audit("ticket.updated","ticket",tid,{"status":new_status,"category":category,"unit":new_unit,"assignee":new_assignee})
            if new_unit and (new_unit!=t["unit"] or str(new_assignee or "")!=str(t["assignee_id"] or "")): notify_assigned_users(session["org_id"],tid,"Aduan ditugaskan",f"{t['code']} telah diteruskan kepada unit Anda.",new_unit,int(new_assignee) if new_assignee else None)
            if new_status in ("resolved","closed"): db().execute("DELETE FROM conversation_states WHERE org_id=? AND phone=?",(session["org_id"],t["phone"]))
        elif action in ("reply","note"):
            if not can_reply: return ("Forbidden",403)
            body=request.form["body"].strip(); internal=action=="note"
            attachment=request.files.get("attachment"); stored=None
            if attachment and attachment.filename:
                try: stored=store_upload(file=attachment)
                except ValueError as e: flash(str(e),"error"); return redirect(url_for("ticket",tid=tid))
            if body or stored:
                if internal:
                    db().execute("INSERT INTO messages(ticket_id,direction,body,sender,internal,attachment_path,attachment_name,attachment_type) VALUES(?,?,?,?,1,?,?,?)",(tid,"out",body,session["name"],*(stored or (None,None,None)))); db().execute("UPDATE tickets SET updated_at=CURRENT_TIMESTAMP WHERE id=?",(tid,)); db().commit(); audit("note.added","ticket",tid)
                else:
                    if t["channel"]=="email": ok,msg=send_ticket_email(t,body,stored)
                    elif stored:
                        media_url=request.url_root.rstrip("/")+url_for("media_file",filename=stored[0]); ok,msg=send_mpwa_media(t["phone"],media_url,stored[2],body)
                    else: ok,msg=send_mpwa(t["phone"],body)
                    flash(msg,"success" if ok else "error")
                    if ok:
                        db().execute("INSERT INTO messages(ticket_id,direction,body,sender,internal,attachment_path,attachment_name,attachment_type,delivery_status,channel) VALUES(?,?,?,?,0,?,?,?,'sent',?)",(tid,"out",body,session["name"],*(stored or (None,None,None)),t["channel"] or "whatsapp")); db().execute("UPDATE tickets SET updated_at=CURRENT_TIMESTAMP WHERE id=?",(tid,)); db().commit(); audit("reply.sent","ticket",tid,{"channel":t["channel"]})
                        if t["channel"]!="email": db().execute("INSERT INTO conversation_states(org_id,phone,step,language,data,human_takeover) VALUES(?,?,?,?,?,1) ON CONFLICT(org_id,phone) DO UPDATE SET step='human_chat',human_takeover=1,updated_at=CURRENT_TIMESTAMP",(session["org_id"],t["phone"],"human_chat",session.get("lang","id"),"{}")); db().commit()
                    else: audit("reply.failed","ticket",tid,{"reason":msg})
        elif action=="forward":
            if not is_central_admin(): return ("Forbidden",403)
            unit=db().execute("SELECT * FROM units WHERE id=? AND org_id=? AND active=1",(request.form.get("unit_id"),session["org_id"])).fetchone()
            if unit:
                flow=db().execute("SELECT * FROM flow_configs WHERE org_id=?",(session["org_id"],)).fetchone(); template=flow["forward_template_id" if session.get("lang","id")=="id" else "forward_template_en"]
                org=db().execute("SELECT * FROM organizations WHERE id=?",(session["org_id"],)).fetchone()
                original=db().execute("SELECT body FROM messages WHERE ticket_id=? AND direction='in' AND internal=0 ORDER BY id ASC LIMIT 1",(tid,)).fetchone()
                description=(original["body"] if original and original["body"] else t["subject"])
                db().execute("UPDATE tickets SET unit=?,status='assigned',updated_at=CURRENT_TIMESTAMP WHERE id=?",(unit["name"],tid)); notify_assigned_users(session["org_id"],tid,"Disposisi aduan baru",f"{t['code']} telah diteruskan ke {unit['name']}. Login untuk membaca dan menanggapi.",unit["name"])
                notification_sent=False
                if unit["officer_phone"]:
                    text=fill(template,org,{"code":t["code"],"description":description,"name":t["contact"],"location":t["location"],"priority":t["priority"],"unit":unit["name"],"officer":unit["officer_name"]})+f"\n\nLogin ke aplikasi untuk menanggapi:\n{request.url_root.rstrip('/')}/tickets/{tid}"
                    notification_sent,_=send_mpwa(unit["officer_phone"],text)
                db().execute("INSERT INTO messages(ticket_id,direction,body,sender,internal) VALUES(?,?,?,?,1)",(tid,"out",f"Diteruskan ke {unit['name']}. Notifikasi WhatsApp petugas: {'terkirim' if notification_sent else 'tidak dikirim'}.",session["name"])); audit("ticket.forwarded","ticket",tid,{"unit":unit["name"],"officer":unit["officer_name"]}); flash("Aduan berhasil diteruskan. Petugas harus login untuk menanggapi.","success")
            else: flash("Pilih unit penanggung jawab.","error")
        elif action=="approve_chat" and session.get("role") in ("owner","admin"):
            chat=db().execute("SELECT * FROM chat_requests WHERE ticket_id=? AND org_id=? AND status='pending' AND expires_at>CURRENT_TIMESTAMP ORDER BY id DESC LIMIT 1",(tid,session["org_id"])).fetchone()
            if not chat: flash("Permintaan chat sudah diproses atau kedaluwarsa.","error")
            else:
                flow=db().execute("SELECT * FROM flow_configs WHERE org_id=?",(session["org_id"],)).fetchone(); template=flow["chat_connected_id" if chat["language"]=="id" else "chat_connected_en"]
                ok,msg=send_mpwa(chat["phone"],template)
                if ok:
                    db().execute("UPDATE chat_requests SET status='approved',approved_by=?,approved_at=CURRENT_TIMESTAMP WHERE id=? AND status='pending'",(session["uid"],chat["id"]))
                    db().execute("UPDATE conversation_states SET step='human_chat',human_takeover=1,updated_at=CURRENT_TIMESTAMP WHERE org_id=? AND phone=?",(session["org_id"],chat["phone"]))
                    db().execute("INSERT INTO messages(ticket_id,direction,body,sender,delivery_status) VALUES(?,?,?,?,?)",(tid,"out",template,session["name"],"sent")); audit("chat.approved","ticket",tid); flash("Pelapor sudah terhubung ke petugas layanan.","success")
                else: flash(msg,"error")
        db().commit(); return redirect(url_for("ticket",tid=tid))
    msgs=db().execute("SELECT * FROM messages WHERE ticket_id=? ORDER BY created_at",(tid,)).fetchall(); users=db().execute("SELECT * FROM users WHERE org_id=? AND active=1 AND role IN ('supervisor','agent') ORDER BY unit,name",(session["org_id"],)).fetchall(); units=db().execute("SELECT * FROM units WHERE org_id=? ORDER BY name",(session["org_id"],)).fetchall(); categories=db().execute("SELECT * FROM categories WHERE org_id=? ORDER BY name",(session["org_id"],)).fetchall(); activities=db().execute("SELECT a.*,u.name user_name FROM audit_logs a LEFT JOIN users u ON u.id=a.user_id WHERE a.org_id=? AND a.entity='ticket' AND a.entity_id=? ORDER BY a.created_at DESC LIMIT 20",(session["org_id"],tid)).fetchall(); chat_request=db().execute("SELECT * FROM chat_requests WHERE ticket_id=? ORDER BY id DESC LIMIT 1",(tid,)).fetchone()
    return render_template("ticket.html",t=t,msgs=msgs,users=users,units=units,categories=categories,activities=activities,chat_request=chat_request,can_reply=can_reply,can_manage=is_central_admin())

@app.post("/tickets/<int:tid>/delete")
@login_required
@roles("owner","admin")
def delete_ticket(tid):
    ticket_row=db().execute("SELECT code FROM tickets WHERE id=? AND org_id=?",(tid,session["org_id"])).fetchone()
    if not ticket_row: return ("Not found",404)
    attachments=[r[0] for r in db().execute("SELECT attachment_path FROM messages WHERE ticket_id=? AND attachment_path IS NOT NULL",(tid,)).fetchall()]
    audit("ticket.deleted","ticket",tid,{"code":ticket_row["code"]})
    db().execute("DELETE FROM notifications WHERE ticket_id=? AND org_id=?",(tid,session["org_id"])); db().execute("DELETE FROM tickets WHERE id=? AND org_id=?",(tid,session["org_id"])); db().commit()
    for filename in attachments:
        try: os.unlink(os.path.join(UPLOAD_DIR,filename))
        except FileNotFoundError: pass
    flash(f"Aduan {ticket_row['code']} telah dihapus permanen.","success"); return redirect(url_for("tickets"))

def send_mpwa_for_org(org,phone,body):
    base=org["mpwa_url"] or os.getenv("MPWA_BASE_URL",""); key=org["mpwa_key"] or os.getenv("MPWA_API_KEY",""); sender=org["mpwa_sender"] or os.getenv("MPWA_SENDER","")
    if not (base and key and sender): return False,"Reply saved; configure MPWA credentials to transmit it."
    chunks=[]; remaining=(body or "").strip()
    while remaining:
        if len(remaining)<=3500: chunks.append(remaining); break
        cut=remaining.rfind("\n",0,3500)
        if cut<1000: cut=remaining.rfind(" ",0,3500)
        if cut<1000: cut=3500
        chunks.append(remaining[:cut].rstrip()); remaining=remaining[cut:].lstrip()
    try:
        total=max(1,len(chunks))
        for index,chunk in enumerate(chunks or [""],1):
            message_body=chunk if total==1 else f"({index}/{total})\n{chunk}"
            r=requests.post(base.rstrip("/")+"/send-message",data={"api_key":key,"sender":sender,"number":phone,"message":message_body},timeout=15)
            try: payload=r.json()
            except ValueError: payload={}
            ok=r.ok and payload.get("status") is True
            if not ok:
                message=payload.get("msg") or payload.get("message")
                return False,(message or f"MPWA rejected message part {index}/{total} ({r.status_code}).")
        return True,("Message sent through MPWA." if total==1 else f"Complete message sent in {total} parts through MPWA.")
    except requests.RequestException as e: return False,f"MPWA connection failed: {e}"

def send_mpwa(phone,body):
    org=db().execute("SELECT * FROM organizations WHERE id=?",(session["org_id"],)).fetchone()
    return send_mpwa_for_org(org,phone,body)

def email_config(org_id): return db().execute("SELECT * FROM email_configs WHERE org_id=?",(org_id,)).fetchone()

def smtp_connect(config):
    password=decrypt_secret(config["smtp_password"])
    if config["smtp_security"]=="ssl": server=smtplib.SMTP_SSL(config["smtp_host"],config["smtp_port"],timeout=20,context=ssl.create_default_context())
    else:
        server=smtplib.SMTP(config["smtp_host"],config["smtp_port"],timeout=20)
        if config["smtp_security"]=="starttls": server.starttls(context=ssl.create_default_context())
    if config["smtp_username"]: server.login(config["smtp_username"],password)
    return server

def send_ticket_email(ticket_row,body,stored=None):
    config=email_config(ticket_row["org_id"])
    recipient=ticket_row["email"] if "email" in ticket_row.keys() else ticket_row["phone"]
    if not config or not config["enabled"] or not recipient: return False,"Koneksi email belum aktif atau alamat penerima tidak tersedia."
    message=EmailMessage(); sender_name=config["sender_name"] or config["address"]
    message["From"]=f'{sender_name} <{config["address"]}>'; message["To"]=recipient
    original=(ticket_row["email_subject"] or ticket_row["subject"] or "Aduan").strip()
    message["Subject"]=f'[{ticket_row["code"]}] Re: {re.sub(r"^\s*(re:\s*)+","",original,flags=re.I)}'
    reference=db().execute("SELECT external_id FROM messages WHERE ticket_id=? AND channel='email' AND external_id IS NOT NULL ORDER BY id DESC LIMIT 1",(ticket_row["id"],)).fetchone()
    if reference: message["In-Reply-To"]=reference["external_id"]; message["References"]=reference["external_id"]
    text=(body or "").strip(); signature=(config["signature"] or "").strip()
    if signature: text+=f"\n\n{signature}"
    message.set_content(text or "Lampiran terlampir.")
    if stored:
        path,name,mime=stored; major,minor=mime.split("/",1)
        with open(os.path.join(UPLOAD_DIR,path),"rb") as source: message.add_attachment(source.read(),maintype=major,subtype=minor,filename=name)
    try:
        with smtp_connect(config) as server: server.send_message(message)
        return True,"Balasan berhasil dikirim melalui email."
    except (OSError,smtplib.SMTPException) as e: return False,f"Pengiriman email gagal: {e}"

def send_mpwa_media_for_org(org,phone,url,mime,caption=""):
    base=org["mpwa_url"] or os.getenv("MPWA_BASE_URL",""); key=org["mpwa_key"] or os.getenv("MPWA_API_KEY",""); sender=org["mpwa_sender"] or os.getenv("MPWA_SENDER","")
    if not (base and key and sender): return False,"Konfigurasikan koneksi MPWA terlebih dahulu."
    media_type="image" if mime.startswith("image/") else "video" if mime.startswith("video/") else "audio" if mime.startswith("audio/") else "document"
    try:
        r=requests.post(base.rstrip("/")+"/send-media",data={"api_key":key,"sender":sender,"number":phone,"media_type":media_type,"url":url,"caption":caption},timeout=30); payload=r.json() if r.content else {}; ok=r.ok and payload.get("status") is True
        return ok,("Lampiran dikirim melalui MPWA." if ok else (payload.get("msg") or payload.get("message") or f"MPWA menolak lampiran ({r.status_code})."))
    except (requests.RequestException,ValueError) as e: return False,f"Pengiriman lampiran gagal: {e}"

def send_mpwa_media(phone,url,mime,caption=""):
    org=db().execute("SELECT * FROM organizations WHERE id=?",(session["org_id"],)).fetchone()
    return send_mpwa_media_for_org(org,phone,url,mime,caption)

@app.route("/users",methods=["GET","POST"])
@login_required
@roles("owner","admin")
def users():
    if request.method=="POST":
        role=request.form.get("role","agent"); unit=request.form.get("unit","").strip()
        valid_unit=not unit or db().execute("SELECT 1 FROM units WHERE org_id=? AND name=? AND active=1",(session["org_id"],unit)).fetchone()
        if role in ("supervisor","agent") and not unit: flash("Akun bidang/petugas wajib memiliki unit.","error")
        elif not valid_unit: flash("Unit tidak valid.","error")
        else:
            try: db().execute("INSERT INTO users(org_id,name,email,password,role,unit) VALUES(?,?,?,?,?,?)",(session["org_id"],request.form["name"],request.form["email"].lower(),generate_password_hash(request.form["password"]),role,unit)); db().commit(); audit("user.created","user"); flash("User created","success")
            except sqlite3.IntegrityError: flash("Email already exists","error")
    rows=db().execute("SELECT * FROM users WHERE org_id=? ORDER BY active DESC,name",(session["org_id"],)).fetchall(); units=db().execute("SELECT name FROM units WHERE org_id=? AND active=1 ORDER BY name",(session["org_id"],)).fetchall(); return render_template("users.html",users=rows,units=units)

@app.post("/users/<int:uid>/toggle")
@login_required
@roles("owner","admin")
def toggle_user(uid):
    user=db().execute("SELECT * FROM users WHERE id=? AND org_id=?",(uid,session["org_id"])).fetchone()
    if not user: return ("Not found",404)
    if uid==session["uid"]: flash("Anda tidak dapat menonaktifkan akun sendiri.","error")
    elif user["role"]=="owner" and user["active"] and db().execute("SELECT count(*) FROM users WHERE org_id=? AND role='owner' AND active=1",(session["org_id"],)).fetchone()[0]<=1: flash("Owner aktif terakhir tidak dapat dinonaktifkan.","error")
    else: db().execute("UPDATE users SET active=1-active WHERE id=?",(uid,)); db().commit(); audit("user.toggled","user",uid); flash("Status pengguna diperbarui.","success")
    return redirect(url_for("users"))

@app.post("/users/<int:uid>/update")
@login_required
@roles("owner","admin")
def update_user(uid):
    user=db().execute("SELECT * FROM users WHERE id=? AND org_id=?",(uid,session["org_id"])).fetchone()
    if not user: return ("Not found",404)
    role=request.form.get("role","agent")
    if role not in ("owner","admin","supervisor","agent","viewer"): role="agent"
    if user["role"]=="owner" and role!="owner" and db().execute("SELECT count(*) FROM users WHERE org_id=? AND role='owner'",(session["org_id"],)).fetchone()[0]<=1: flash("Owner terakhir tidak dapat diubah perannya.","error"); return redirect(url_for("users"))
    password=request.form.get("password","")
    unit=request.form.get("unit","").strip()
    if role in ("supervisor","agent") and not unit: flash("Akun bidang/petugas wajib memiliki unit.","error"); return redirect(url_for("users"))
    if unit and not db().execute("SELECT 1 FROM units WHERE org_id=? AND name=? AND active=1",(session["org_id"],unit)).fetchone(): flash("Unit tidak valid.","error"); return redirect(url_for("users"))
    if password and len(password)<8: flash("Kata sandi baru minimal 8 karakter.","error"); return redirect(url_for("users"))
    try:
        if password: db().execute("UPDATE users SET name=?,email=?,role=?,unit=?,password=? WHERE id=?",(request.form["name"].strip(),request.form["email"].strip().lower(),role,unit,generate_password_hash(password),uid))
        else: db().execute("UPDATE users SET name=?,email=?,role=?,unit=? WHERE id=?",(request.form["name"].strip(),request.form["email"].strip().lower(),role,unit,uid))
        db().commit(); audit("user.updated","user",uid,{"role":role}); flash("Pengguna berhasil diperbarui.","success")
        if uid==session["uid"]: session.update(name=request.form["name"].strip(),role=role,unit=request.form.get("unit","").strip())
    except sqlite3.IntegrityError: flash("Email sudah digunakan pengguna lain.","error")
    return redirect(url_for("users"))

@app.post("/users/<int:uid>/delete")
@login_required
@roles("owner","admin")
def delete_user(uid):
    user=db().execute("SELECT * FROM users WHERE id=? AND org_id=?",(uid,session["org_id"])).fetchone()
    if not user: return ("Not found",404)
    if uid==session["uid"]: flash("Anda tidak dapat menghapus akun sendiri.","error")
    elif user["role"]=="owner" and db().execute("SELECT count(*) FROM users WHERE org_id=? AND role='owner'",(session["org_id"],)).fetchone()[0]<=1: flash("Owner terakhir tidak dapat dihapus.","error")
    else:
        db().execute("UPDATE tickets SET assignee_id=NULL WHERE assignee_id=?",(uid,)); db().execute("DELETE FROM notifications WHERE user_id=?",(uid,)); db().execute("UPDATE audit_logs SET user_id=NULL WHERE user_id=?",(uid,)); db().execute("DELETE FROM users WHERE id=?",(uid,)); db().commit(); audit("user.deleted","user",uid,{"email":user["email"]}); flash("Pengguna berhasil dihapus.","success")
    return redirect(url_for("users"))

@app.route("/settings",methods=["GET","POST"])
@login_required
@roles("owner","admin")
def settings():
    section=request.args.get("section","general")
    if section not in ("general","whatsapp","email","notifications","units","categories"): section="general"
    if request.method=="POST":
        section=request.form.get("section","general")
        org=db().execute("SELECT * FROM organizations WHERE id=?",(session["org_id"],)).fetchone(); logo=org["logo"]; icon=org["icon"]
        if section=="whatsapp":
            db().execute("UPDATE organizations SET mpwa_url=?,mpwa_key=?,mpwa_sender=? WHERE id=?",(request.form.get("mpwa_url","").strip(),request.form.get("mpwa_key","").strip(),request.form.get("mpwa_sender","").strip(),session["org_id"])); db().commit(); audit("organization.mpwa_updated","organization",session["org_id"]); flash("Koneksi WhatsApp berhasil disimpan.","success"); return redirect(url_for("settings",section="whatsapp"))
        if section=="email":
            current=email_config(session["org_id"]); imap_password=request.form.get("imap_password",""); smtp_password=request.form.get("smtp_password","")
            if not imap_password and current: encrypted_imap=current["imap_password"]
            else: encrypted_imap=encrypt_secret(imap_password)
            if request.form.get("same_credentials")=="1" and not smtp_password: encrypted_smtp=encrypted_imap
            elif not smtp_password and current: encrypted_smtp=current["smtp_password"]
            else: encrypted_smtp=encrypt_secret(smtp_password)
            values=(1 if request.form.get("enabled") else 0,request.form.get("address","").strip().lower(),request.form.get("sender_name","").strip(),request.form.get("imap_host","").strip(),max(1,min(65535,int(request.form.get("imap_port") or 993))),request.form.get("imap_security","ssl"),request.form.get("imap_username","").strip(),encrypted_imap,request.form.get("imap_folder","INBOX").strip() or "INBOX",request.form.get("smtp_host","").strip(),max(1,min(65535,int(request.form.get("smtp_port") or 587))),request.form.get("smtp_security","starttls"),request.form.get("smtp_username","").strip(),encrypted_smtp,request.form.get("signature","").strip()[:2000],1 if request.form.get("auto_reply") else 0,session["org_id"])
            db().execute("""INSERT INTO email_configs(enabled,address,sender_name,imap_host,imap_port,imap_security,imap_username,imap_password,imap_folder,smtp_host,smtp_port,smtp_security,smtp_username,smtp_password,signature,auto_reply,org_id) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(org_id) DO UPDATE SET enabled=excluded.enabled,address=excluded.address,sender_name=excluded.sender_name,imap_host=excluded.imap_host,imap_port=excluded.imap_port,imap_security=excluded.imap_security,imap_username=excluded.imap_username,imap_password=excluded.imap_password,imap_folder=excluded.imap_folder,smtp_host=excluded.smtp_host,smtp_port=excluded.smtp_port,smtp_security=excluded.smtp_security,smtp_username=excluded.smtp_username,smtp_password=excluded.smtp_password,signature=excluded.signature,auto_reply=excluded.auto_reply,updated_at=CURRENT_TIMESTAMP""",values); db().commit(); audit("organization.email_updated","organization",session["org_id"]); flash("Koneksi email berhasil disimpan.","success"); return redirect(url_for("settings",section="email"))
        if section=="notifications":
            sound=org["notification_sound"]
            try:
                if request.form.get("remove_sound")=="1": sound=None
                if request.files.get("notification_sound") and request.files["notification_sound"].filename: sound=store_upload(file=request.files["notification_sound"])[0]
            except ValueError as e: flash(str(e),"error"); return redirect(url_for("settings",section="notifications"))
            db().execute("UPDATE organizations SET notification_sound=?,notification_sound_enabled=? WHERE id=?",(sound,1 if request.form.get("notification_sound_enabled") else 0,session["org_id"])); db().commit(); audit("organization.notification_updated","organization",session["org_id"]); flash("Pengaturan notifikasi berhasil disimpan.","success"); return redirect(url_for("settings",section="notifications"))
        try:
            if request.files.get("logo") and request.files["logo"].filename: logo=store_upload(file=request.files["logo"])[0]
            if request.files.get("icon") and request.files["icon"].filename: icon=store_upload(file=request.files["icon"])[0]
        except ValueError as e: flash(str(e),"error"); return redirect(url_for("settings",section="general"))
        prefix="".join(c for c in request.form.get("ticket_prefix","ADU").upper() if c.isalnum())[:12] or "ADU"; ticket_format=request.form.get("ticket_format","{prefix}-{year}-{number:05d}").strip()[:80]
        try: ticket_format.format_map({"prefix":prefix,"year":2026,"month":"08","day":"13","number":1})
        except (KeyError,ValueError): flash("Format nomor aduan tidak valid.","error"); return redirect(url_for("settings",section="general"))
        db().execute("UPDATE organizations SET name=?,app_name=?,accent=?,terminology=?,timezone=?,ticket_prefix=?,ticket_format=?,logo=?,icon=? WHERE id=?",(request.form["name"],request.form.get("app_name","AduanHub").strip()[:60] or "AduanHub",request.form["accent"],request.form["terminology"],request.form.get("timezone","Asia/Jakarta"),prefix,ticket_format,logo,icon,session["org_id"])); db().commit(); session["org_name"]=request.form["name"]; audit("organization.updated","organization",session["org_id"]); flash("Pengaturan berhasil disimpan","success")
    org=db().execute("SELECT * FROM organizations WHERE id=?",(session["org_id"],)).fetchone(); units=db().execute("SELECT * FROM units WHERE org_id=? ORDER BY name",(session["org_id"],)).fetchall(); categories=db().execute("SELECT c.*,(SELECT count(*) FROM tickets t WHERE t.org_id=c.org_id AND t.category=c.name) usage_count FROM categories c WHERE c.org_id=? ORDER BY c.name",(session["org_id"],)).fetchall(); return render_template("settings.html",org=org,email=email_config(session["org_id"]),units=units,categories=categories,section=section)

@app.post("/settings/email/test")
@login_required
@roles("owner","admin")
def test_email_connection():
    config=email_config(session["org_id"])
    if not config: flash("Simpan konfigurasi email terlebih dahulu.","error"); return redirect(url_for("settings",section="email"))
    import imaplib
    try:
        if config["imap_security"]=="ssl": client=imaplib.IMAP4_SSL(config["imap_host"],config["imap_port"],ssl_context=ssl.create_default_context(),timeout=20)
        else:
            client=imaplib.IMAP4(config["imap_host"],config["imap_port"],timeout=20)
            if config["imap_security"]=="starttls": client.starttls(ssl_context=ssl.create_default_context())
        client.login(config["imap_username"],decrypt_secret(config["imap_password"])); client.select(config["imap_folder"] or "INBOX",readonly=True); client.logout()
        with smtp_connect(config) as server: server.noop()
        db().execute("UPDATE email_configs SET last_error=NULL WHERE org_id=?",(session["org_id"],)); db().commit(); flash("Koneksi IMAP dan SMTP berhasil.","success")
    except Exception as e:
        message=str(e)[:300]; db().execute("UPDATE email_configs SET last_error=? WHERE org_id=?",(message,session["org_id"])); db().commit(); flash(f"Uji koneksi gagal: {message}","error")
    return redirect(url_for("settings",section="email"))

@app.post("/categories")
@login_required
@roles("owner","admin")
def create_category():
    name=request.form.get("name","").strip()[:80]
    if not name: flash("Nama kategori wajib diisi.","error")
    else:
        try: db().execute("INSERT INTO categories(org_id,name) VALUES(?,?)",(session["org_id"],name)); db().commit(); audit("category.created","category"); flash("Kategori berhasil ditambahkan.","success")
        except sqlite3.IntegrityError: flash("Kategori tersebut sudah tersedia.","error")
    return redirect(url_for("settings",section="categories"))

@app.post("/categories/<int:category_id>/delete")
@login_required
@roles("owner","admin")
def delete_category(category_id):
    category=db().execute("SELECT * FROM categories WHERE id=? AND org_id=?",(category_id,session["org_id"])).fetchone()
    if not category: return ("Not found",404)
    db().execute("DELETE FROM categories WHERE id=?",(category_id,)); db().commit(); audit("category.deleted","category",category_id,{"name":category["name"]}); flash("Kategori dihapus dari pilihan. Aduan lama tetap menyimpan kategorinya.","success"); return redirect(url_for("settings",section="categories"))

@app.post("/units")
@login_required
@roles("owner","admin")
def create_unit():
    try:
        db().execute("INSERT INTO units(org_id,name,officer_name,officer_phone) VALUES(?,?,?,?)",(session["org_id"],request.form["name"],request.form.get("officer_name"),request.form.get("officer_phone"))); db().commit(); audit("unit.created","unit"); flash("Responsible unit added","success")
    except sqlite3.IntegrityError: flash("Unit name already exists","error")
    return redirect(url_for("settings",section="units"))

@app.post("/units/<int:unit_id>/update")
@login_required
@roles("owner","admin")
def update_unit(unit_id):
    unit=db().execute("SELECT * FROM units WHERE id=? AND org_id=?",(unit_id,session["org_id"])).fetchone()
    if not unit: return ("Not found",404)
    name=request.form["name"].strip(); officer=request.form.get("officer_name","").strip(); phone=request.form.get("officer_phone","").strip()
    if not name: flash("Unit name is required","error"); return redirect(url_for("settings",section="units"))
    try:
        db().execute("UPDATE units SET name=?,officer_name=?,officer_phone=?,active=1 WHERE id=? AND org_id=?",(name,officer,phone,unit_id,session["org_id"])); db().execute("UPDATE tickets SET unit=? WHERE org_id=? AND unit=?",(name,session["org_id"],unit["name"])); db().execute("UPDATE users SET unit=? WHERE org_id=? AND unit=?",(name,session["org_id"],unit["name"])); db().commit(); audit("unit.updated","unit",unit_id,{"old_name":unit["name"],"new_name":name}); flash("Responsible unit updated","success")
    except sqlite3.IntegrityError: flash("Unit name already exists","error")
    return redirect(url_for("settings",section="units"))

@app.post("/units/<int:unit_id>/delete")
@login_required
@roles("owner","admin")
def delete_unit(unit_id):
    unit=db().execute("SELECT name FROM units WHERE id=? AND org_id=?",(unit_id,session["org_id"])).fetchone()
    if not unit: return ("Not found",404)
    used=db().execute("SELECT (SELECT count(*) FROM users WHERE org_id=? AND unit=?)+(SELECT count(*) FROM tickets WHERE org_id=? AND unit=?)",(session["org_id"],unit["name"],session["org_id"],unit["name"])).fetchone()[0]
    if used: flash("Unit masih digunakan oleh akun atau aduan dan tidak dapat dihapus.","error")
    else: db().execute("DELETE FROM units WHERE id=? AND org_id=?",(unit_id,session["org_id"])); db().commit(); audit("unit.deleted","unit",unit_id,{"name":unit["name"]}); flash("Responsible unit deleted","success")
    return redirect(url_for("settings",section="units"))

def report_rows():
    scope,scope_params=scoped_ticket_where("t"); where=["t.org_id=?",scope]; params=[session["org_id"],*scope_params]
    for key,column in (("status","t.status"),("category","t.category"),("unit","t.unit"),("priority","t.priority")):
        if request.args.get(key): where.append(column+"=?"); params.append(request.args[key])
    if request.args.get("date_from"): where.append("date(t.created_at)>=date(?)"); params.append(request.args["date_from"])
    if request.args.get("date_to"): where.append("date(t.created_at)<=date(?)"); params.append(request.args["date_to"])
    return db().execute("SELECT t.code,t.created_at,c.name contact,c.phone,c.location,t.subject,t.category,t.priority,t.status,t.unit,u.name assignee,t.updated_at,t.closed_at FROM tickets t JOIN contacts c ON c.id=t.contact_id LEFT JOIN users u ON u.id=t.assignee_id WHERE "+" AND ".join(where)+" ORDER BY t.created_at DESC",params).fetchall()

@app.get("/reports")
@login_required
def reports():
    rows=report_rows(); categories=db().execute("SELECT name category FROM categories WHERE org_id=? ORDER BY name",(session["org_id"],)).fetchall(); units=db().execute("SELECT name FROM units WHERE org_id=? AND active=1 ORDER BY name",(session["org_id"],)).fetchall()
    return render_template("reports.html",rows=rows,categories=categories,units=units)

@app.get("/reports.csv")
@login_required
def reports_csv():
    rows=report_rows(); out=io.StringIO(); writer=csv.writer(out); writer.writerow(["Ticket","Created","Reporter","WhatsApp","Location","Complaint","Category","Priority","Status","Unit","Assignee","Last updated","Closed"])
    for r in rows: writer.writerow(list(r))
    audit("report.exported","csv",metadata={"rows":len(rows)})
    return Response("\ufeff"+out.getvalue(),mimetype="text/csv",headers={"Content-Disposition":f"attachment; filename=complaints-{datetime.utcnow().date()}.csv"})

@app.get("/reports.pdf")
@login_required
def reports_pdf():
    rows=report_rows(); org=db().execute("SELECT name FROM organizations WHERE id=?",(session["org_id"],)).fetchone(); buf=io.BytesIO(); doc=SimpleDocTemplate(buf,pagesize=landscape(A4),rightMargin=20,leftMargin=20,topMargin=24,bottomMargin=24); styles=getSampleStyleSheet(); story=[Paragraph(f"Complaint Report — {org['name']}",styles["Title"]),Paragraph(f"Generated {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')} · {len(rows)} records",styles["Normal"]),Spacer(1,12)]; data=[["Ticket","Created","Reporter","Complaint","Category","Priority","Status","Unit","Updated"]]
    for r in rows: data.append([r["code"],r["created_at"][:10],r["contact"],Paragraph(r["subject"][:100],styles["BodyText"]),r["category"],r["priority"],r["status"],r["unit"] or "-",r["updated_at"][:10]])
    table=Table(data,repeatRows=1,colWidths=[70,55,80,190,75,45,60,85,55]); table.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#1e3a5f")),("TEXTCOLOR",(0,0),(-1,0),colors.white),("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("FONTSIZE",(0,0),(-1,-1),7),("GRID",(0,0),(-1,-1),.3,colors.HexColor("#d7dce3")),("VALIGN",(0,0),(-1,-1),"TOP"),("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,colors.HexColor("#f5f7fa")]) ])); story.append(table); doc.build(story); buf.seek(0); audit("report.exported","pdf",metadata={"rows":len(rows)}); return send_file(buf,mimetype="application/pdf",as_attachment=True,download_name=f"complaints-{datetime.utcnow().date()}.pdf")

@app.route("/notifications")
@login_required
def notifications():
    condition="(n.user_id IS NULL OR n.user_id=?)" if is_central_admin() else "n.user_id=?"
    rows=db().execute(f"SELECT n.*,t.code FROM notifications n LEFT JOIN tickets t ON t.id=n.ticket_id WHERE n.org_id=? AND {condition} ORDER BY n.created_at DESC LIMIT 100",(session["org_id"],session["uid"])).fetchall()
    db().execute(f"UPDATE notifications AS n SET read_at=CURRENT_TIMESTAMP WHERE n.org_id=? AND n.read_at IS NULL AND {condition}",(session["org_id"],session["uid"])); db().commit()
    return render_template("notifications.html",notifications=rows)

@app.get("/notifications/poll")
@login_required
def notifications_poll():
    after=max(0,request.args.get("after",type=int) or 0); condition="(n.user_id IS NULL OR n.user_id=?)" if is_central_admin() else "n.user_id=?"
    rows=db().execute(f"SELECT n.id,n.ticket_id,n.title,n.body,t.code FROM notifications n LEFT JOIN tickets t ON t.id=n.ticket_id WHERE n.org_id=? AND {condition} AND n.id>? ORDER BY n.id",(session["org_id"],session["uid"],after)).fetchall()
    latest=db().execute(f"SELECT COALESCE(max(n.id),0) FROM notifications n WHERE n.org_id=? AND {condition}",(session["org_id"],session["uid"])).fetchone()[0]
    unread=db().execute(f"SELECT count(*) FROM notifications n WHERE n.org_id=? AND {condition} AND n.read_at IS NULL",(session["org_id"],session["uid"])).fetchone()[0]
    org=db().execute("SELECT notification_sound,notification_sound_enabled FROM organizations WHERE id=?",(session["org_id"],)).fetchone()
    sound_url=url_for("media_file",filename=org["notification_sound"]) if org and org["notification_sound"] else None
    return jsonify(latest=latest,unread=unread,user_key=f"{session['org_id']}-{session['uid']}",sound_enabled=bool(org and org["notification_sound_enabled"]),sound_url=sound_url,notifications=[dict(row) for row in rows])

@app.get("/documentation")
@login_required
def documentation(): return render_template("documentation.html")

@app.route("/settings/flow",methods=["GET","POST"])
@login_required
@roles("owner","admin")
def flow_settings():
    if request.method=="POST":
        fields=("default_language","welcome_id","welcome_en","service_info_id","service_info_en","confirmation_id","confirmation_en","completion_id","completion_en","forward_template_id","forward_template_en","status_template_id","status_template_en","unavailable_id","unavailable_en","identity_prompt_id","identity_prompt_en","chat_waiting_id","chat_waiting_en","chat_connected_id","chat_connected_en","chat_timeout_id","chat_timeout_en","office_hours","ai_prompt","ai_confidence")
        values=[request.form.get(k,"").strip() for k in fields]
        menu=[]
        rows=zip(request.form.getlist("menu_key"),request.form.getlist("menu_label_id"),request.form.getlist("menu_label_en"),request.form.getlist("menu_action"),request.form.getlist("menu_response_id"),request.form.getlist("menu_response_en"))
        for key,label_id,label_en,action,response_id,response_en in rows:
            if key.strip() and label_id.strip(): menu.append({"key":key.strip()[:8],"label_id":label_id.strip()[:100],"label_en":label_en.strip()[:100],"action":action if action in ("new","status","info","chat_admin","custom") else "custom","response_id":response_id.strip()[:4000],"response_en":response_en.strip()[:4000]})
        timeout=max(0,min(1440,int(request.form.get("session_timeout_minutes") or 30)))
        db().execute("""UPDATE flow_configs SET enabled=?,default_language=?,welcome_id=?,welcome_en=?,service_info_id=?,service_info_en=?,confirmation_id=?,confirmation_en=?,completion_id=?,completion_en=?,forward_template_id=?,forward_template_en=?,status_template_id=?,status_template_en=?,unavailable_id=?,unavailable_en=?,identity_prompt_id=?,identity_prompt_en=?,chat_waiting_id=?,chat_waiting_en=?,chat_connected_id=?,chat_connected_en=?,chat_timeout_id=?,chat_timeout_en=?,office_hours=?,ai_prompt=?,ai_confidence=?,menu_items=?,ai_enabled=?,session_timeout_minutes=?,updated_at=CURRENT_TIMESTAMP WHERE org_id=?""",[1 if request.form.get("enabled") else 0,*values,json.dumps(menu),1 if request.form.get("ai_enabled") else 0,timeout,session["org_id"]]); db().commit(); audit("flow.updated","flow",session["org_id"]); flash("Alur dan template pesan berhasil disimpan","success")
    flow=db().execute("SELECT * FROM flow_configs WHERE org_id=?",(session["org_id"],)).fetchone()
    try: menu_items=json.loads(flow["menu_items"] or "[]")
    except ValueError: menu_items=[]
    return render_template("flow_settings.html",flow=flow,menu_items=menu_items)

def fill(text, org, data=None, **extra):
    values={"organization":org["name"],"office_hours":"-",**(data or {}),**extra}
    for key,value in values.items(): text=(text or "").replace("{"+key+"}",str(value or "-"))
    return text

def flow_reply(org,phone,body,name,attachment=None):
    flow=db().execute("SELECT * FROM flow_configs WHERE org_id=?",(org["id"],)).fetchone()
    if not flow or not flow["enabled"]: return None
    state=db().execute("SELECT * FROM conversation_states WHERE org_id=? AND phone=?",(org["id"],phone)).fetchone(); command=body.strip().upper(); lang=state["language"] if state else flow["default_language"]; expired=False
    if command in ("RESET","RESET SESSION","HAPUS SESI","ULANG SESI"):
        db().execute("DELETE FROM conversation_states WHERE org_id=? AND phone=?",(org["id"],phone))
        db().execute("UPDATE chat_requests SET status='cancelled' WHERE org_id=? AND phone=? AND status='pending'",(org["id"],phone)); db().commit()
        db().execute("INSERT INTO conversation_states(org_id,phone,step,language,data,human_takeover) VALUES(?,?,?,?,?,0)",(org["id"],phone,"identity_choice",lang,"{}")); db().commit()
        prompt=fill(flow["identity_prompt_id" if lang=="id" else "identity_prompt_en"],org)
        return ("Sesi percakapan berhasil dihapus. Pengujian dimulai dari awal.\n\n" if lang=="id" else "The conversation session has been cleared. Testing starts from the beginning.\n\n")+prompt
    if state and flow["session_timeout_minutes"] and state["step"]!="menu":
        try: expired=(datetime.now(timezone.utc)-datetime.fromisoformat(state["updated_at"]).replace(tzinfo=timezone.utc)).total_seconds()>flow["session_timeout_minutes"]*60
        except (ValueError,TypeError): expired=False
        if expired: state=None
    if command in ("EN","ENGLISH"): lang="en"; state=None
    if command in ("ID","INDONESIA","BAHASA"): lang="id"; state=None
    welcome=flow["welcome_id" if lang=="id" else "welcome_en"]
    try: menu=json.loads(flow["menu_items"] or "[]")
    except ValueError: menu=[]
    if command in ("MENU","START","MULAI") or not state:
        db().execute("UPDATE chat_requests SET status='cancelled' WHERE org_id=? AND phone=? AND status='pending'",(org["id"],phone))
        db().execute("INSERT INTO conversation_states(org_id,phone,step,language,data) VALUES(?,?,?,?,?) ON CONFLICT(org_id,phone) DO UPDATE SET step='identity_choice',language=excluded.language,data='{}',human_takeover=0,updated_at=CURRENT_TIMESTAMP",(org["id"],phone,"identity_choice",lang,"{}")); db().commit(); notice=("Sesi sebelumnya telah berakhir karena tidak ada aktivitas. Silakan mulai kembali.\n\n" if lang=="id" else "Your previous session expired due to inactivity. Please start again.\n\n") if expired else ""; return notice+fill(flow["identity_prompt_id" if lang=="id" else "identity_prompt_en"],org)
    if state["human_takeover"]: return None
    data=json.loads(state["data"] or "{}"); step=state["step"]
    def move(next_step, reply, new_data=None):
        db().execute("UPDATE conversation_states SET step=?,language=?,data=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(next_step,lang,json.dumps(new_data if new_data is not None else data),state["id"])); db().commit(); return reply
    if command in ("BATAL","CANCEL"):
        return move("menu",("Proses dibatalkan. Ketik MENU untuk kembali ke menu utama." if lang=="id" else "The process was cancelled. Type MENU to return to the main menu."),{})
    if step=="identity_choice":
        if command in ("1","NAMA","NAME"): return move("identity_name","Silakan tuliskan nama Anda." if lang=="id" else "Please enter your name.",{})
        if command in ("2","RAHASIA","ANONIM","ANONYMOUS"):
            data={"name":"Pelapor anonim" if lang=="id" else "Anonymous reporter"}; return move("menu",fill(welcome,org),data)
        return "Balas 1 untuk membagikan nama atau 2 untuk tetap rahasia." if lang=="id" else "Reply 1 to share your name or 2 to remain anonymous."
    if step=="identity_name":
        data={"name":body.strip()[:120] or ("Pelapor anonim" if lang=="id" else "Anonymous reporter")}; return move("menu",fill(welcome,org),data)
    if step=="menu":
        selected=next((item for item in menu if str(item.get("key","")).upper()==command),None)
        if selected and selected.get("action")=="new":
            prompt=("Silakan ceritakan aduan Anda dalam satu pesan. Anda dapat melampirkan foto atau video." if lang=="id" else "Please describe your complaint in one message. You may attach a photo or video.")
            return move("complaint_description",prompt,data)
        if selected and selected.get("action")=="status": return move("status","Silakan kirim nomor aduan Anda, contoh: DEM-2026-00001." if lang=="id" else "Please send your complaint number, for example: DEM-2026-00001.")
        if selected and selected.get("action")=="info": return move("menu",fill(flow["service_info_id" if lang=="id" else "service_info_en"],org))
        if selected and selected.get("action")=="chat_admin":
            c=db().execute("SELECT * FROM contacts WHERE org_id=? AND phone=?",(org["id"],phone)).fetchone()
            if c: cid=c["id"]
            else: db().execute("INSERT INTO contacts(org_id,name,phone) VALUES(?,?,?)",(org["id"],name,phone)); cid=db().execute("SELECT last_insert_rowid()").fetchone()[0]
            t=db().execute("SELECT id,code FROM tickets WHERE org_id=? AND contact_id=? AND status NOT IN ('resolved','closed') ORDER BY id DESC LIMIT 1",(org["id"],cid)).fetchone()
            if t: tid,code=t["id"],t["code"]
            else:
                code=next_ticket_code(org); db().execute("INSERT INTO tickets(org_id,contact_id,code,subject,category) VALUES(?,?,?,?,?)",(org["id"],cid,code,"Permintaan chat dengan admin","General")); tid=db().execute("SELECT last_insert_rowid()").fetchone()[0]
            expires=(datetime.now(timezone.utc)+timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
            db().execute("UPDATE chat_requests SET status='cancelled' WHERE org_id=? AND phone=? AND status='pending'",(org["id"],phone))
            db().execute("INSERT INTO chat_requests(org_id,ticket_id,phone,language,expires_at) VALUES(?,?,?,?,?)",(org["id"],tid,phone,lang,expires))
            db().execute("INSERT INTO notifications(org_id,ticket_id,title,body) VALUES(?,?,?,?)",(org["id"],tid,"Permintaan chat menunggu konfirmasi",f"{name or phone} menunggu petugas layanan. Konfirmasi maksimal 5 menit ({code})."))
            db().execute("UPDATE conversation_states SET step='chat_waiting',human_takeover=1,data='{}',updated_at=CURRENT_TIMESTAMP WHERE id=?",(state["id"],)); db().commit()
            return fill(flow["chat_waiting_id" if lang=="id" else "chat_waiting_en"],org,{"code":code})
        if selected and selected.get("action")=="custom": return move("menu",fill(selected.get("response_id" if lang=="id" else "response_en") or selected.get("response_id") or "-",org))
        choices=", ".join(str(i.get("key")) for i in menu)
        return (f"Pilihan tidak dikenali. Balas {choices}." if lang=="id" else f"Unknown option. Reply with {choices}.")
    if step=="status":
        t=db().execute("SELECT code,status,subject,unit,updated_at FROM tickets WHERE org_id=? AND upper(code)=upper(?)",(org["id"],body.strip())).fetchone()
        if not t: return "Nomor aduan tidak ditemukan. Periksa kembali atau ketik MENU." if lang=="id" else "Complaint number not found. Check it or type MENU."
        template=flow["status_template_id" if lang=="id" else "status_template_en"]
        reply=fill(template,org,{"code":t["code"],"status":t["status"].replace("_"," "),"description":t["subject"],"unit":t["unit"] or "-","updated_at":t["updated_at"]})
        return move("menu",reply,{})
    if step=="complaint_description":
        description=body.strip()
        if not description or description=="[Lampiran]": return "Tuliskan isi aduan Anda dalam satu pesan." if lang=="id" else "Please write your complaint in one message."
        data["description"]=description[:4000]; data.setdefault("name","Pelapor anonim" if lang=="id" else "Anonymous reporter"); data.setdefault("location","-")
        if attachment: data["attachment"]={"path":attachment[0],"name":attachment[1],"type":attachment[2]}
        return move("confirm",fill(flow["confirmation_id" if lang=="id" else "confirmation_en"],org,data),data)
    if step=="complaint_form":
        normalized=(body or "").replace("\\n","\n").replace("：",":").replace("*","").strip(); parsed={}
        aliases={"name":"nama|name","location":"lokasi|location","description":"aduan|keluhan|complaint"}
        boundary=r"(?=\s*(?:nama|name|lokasi|location|aduan|keluhan|complaint)\s*[:\-]|$)"
        for field,alias in aliases.items():
            match=re.search(rf"(?:^|\n|\s)\s*(?:{alias})\s*[:\-]\s*(.+?){boundary}",normalized,re.IGNORECASE|re.DOTALL)
            if match: parsed[field]=match.group(1).strip()
        if not parsed.get("name") or not parsed.get("description"):
            return "Format belum lengkap. Isi minimal Nama dan Aduan sesuai contoh, atau ketik BATAL." if lang=="id" else "The format is incomplete. Complete at least Name and Complaint, or type CANCEL."
        data={"name":parsed["name"][:120],"location":parsed.get("location","")[:240] or "-","description":parsed["description"][:4000]}
        if attachment: data["attachment"]={"path":attachment[0],"name":attachment[1],"type":attachment[2]}
        text=fill(flow["confirmation_id" if lang=="id" else "confirmation_en"],org,data)
        return move("confirm",text,data)
    if step=="name": data["name"]=body.strip()[:120]; return move("location","Sebutkan lokasi, unit, sekolah, cabang, atau tempat kejadian." if lang=="id" else "Enter the location, unit, school, branch, or incident site.",data)
    if step=="location": data["location"]=body.strip()[:240]; return move("description","Jelaskan aduan Anda secara lengkap dalam satu pesan." if lang=="id" else "Describe your complaint completely in one message.",data)
    if step=="description":
        data["description"]=body.strip()[:4000]
        if attachment: data["attachment"]={"path":attachment[0],"name":attachment[1],"type":attachment[2]}
        text=fill(flow["confirmation_id" if lang=="id" else "confirmation_en"],org,data)
        return move("confirm",text,data)
    if step=="confirm":
        if command in ("UBAH","EDIT"): return move("complaint_description","Silakan tuliskan kembali aduan Anda dalam satu pesan." if lang=="id" else "Please rewrite your complaint in one message.",{"name":data.get("name","Pelapor anonim" if lang=="id" else "Anonymous reporter")})
        if command not in ("KIRIM","SEND"): return "Balas KIRIM, UBAH, atau BATAL." if lang=="id" else "Reply SEND, EDIT, or CANCEL."
        c=db().execute("SELECT * FROM contacts WHERE org_id=? AND phone=?",(org["id"],phone)).fetchone()
        if c: cid=c["id"]; db().execute("UPDATE contacts SET name=?,location=? WHERE id=?",(data["name"],data["location"],cid))
        else: db().execute("INSERT INTO contacts(org_id,name,phone,location) VALUES(?,?,?,?)",(org["id"],data["name"],phone,data["location"])); cid=db().execute("SELECT last_insert_rowid()").fetchone()[0]
        code=next_ticket_code(org)
        db().execute("INSERT INTO tickets(org_id,contact_id,code,subject) VALUES(?,?,?,?)",(org["id"],cid,code,data["description"][:100])); tid=db().execute("SELECT last_insert_rowid()").fetchone()[0]
        media=data.get("attachment") or {}
        db().execute("INSERT INTO messages(ticket_id,direction,body,sender,attachment_path,attachment_name,attachment_type) VALUES(?,?,?,?,?,?,?)",(tid,"in",data["description"],data["name"],media.get("path"),media.get("name"),media.get("type"))); db().execute("INSERT INTO notifications(org_id,ticket_id,title,body) VALUES(?,?,?,?)",(org["id"],tid,"Aduan WhatsApp baru",f"{data['name']}: {data['description'][:120]}")); db().execute("UPDATE conversation_states SET step='ticket_chat',data=?,human_takeover=1,updated_at=CURRENT_TIMESTAMP WHERE id=?",(json.dumps({"ticket_id":tid}),state["id"])); db().commit()
        return fill(flow["completion_id" if lang=="id" else "completion_en"],org,code=code)
    return move("menu",fill(welcome,org),{})

def api_auth(fn):
    @wraps(fn)
    def inner(*args,**kwargs):
        header=request.headers.get("Authorization","")
        if not header.startswith("Bearer "): return jsonify(error="authentication_required"),401
        try: payload=api_tokens.loads(header[7:],max_age=30*24*3600)
        except SignatureExpired: return jsonify(error="token_expired"),401
        except BadSignature: return jsonify(error="invalid_token"),401
        user=db().execute("SELECT u.*,o.name org_name,o.app_name,o.logo,o.icon,o.accent,o.terminology,o.timezone FROM users u JOIN organizations o ON o.id=u.org_id WHERE u.id=? AND u.active=1",(payload.get("uid"),)).fetchone()
        if not user or payload.get("v")!=api_token_version(user["password"]): return jsonify(error="invalid_token"),401
        if payload.get("did"):
            device=db().execute("SELECT id FROM mobile_devices WHERE id=? AND user_id=? AND revoked_at IS NULL",(payload["did"],user["id"])).fetchone()
            if not device: return jsonify(error="device_revoked",message="Akses perangkat ini telah dicabut."),401
            db().execute("UPDATE mobile_devices SET last_seen_at=CURRENT_TIMESTAMP WHERE id=?",(payload["did"],)); db().commit()
        g.api_user=user
        return fn(*args,**kwargs)
    return inner

def api_can_access(user,ticket_row):
    if user["role"] in ("owner","admin"): return True
    if not ticket_row["unit"] or ticket_row["unit"]!=(user["unit"] or ""): return False
    return not (user["role"]=="agent" and ticket_row["assignee_id"] and ticket_row["assignee_id"]!=user["id"])

def api_ticket_dict(row):
    return {key:row[key] for key in ("id","code","subject","category","priority","status","unit","assignee_id","created_at","updated_at","closed_at")} | {"contact":{"name":row["contact"],"phone":row["phone"],"location":row["location"] or "-"},"assignee":row["assignee"] if "assignee" in row.keys() else None}

@app.post("/api/v1/auth/login")
def api_login():
    body=request.get_json(silent=True) or {}; email=str(body.get("email","")).strip().lower(); password=str(body.get("password", ""))
    user=db().execute("SELECT u.*,o.name org_name,o.app_name,o.logo,o.icon,o.accent,o.terminology FROM users u JOIN organizations o ON o.id=u.org_id WHERE u.email=? AND u.active=1",(email,)).fetchone()
    if not user or not check_password_hash(user["password"],password): return jsonify(error="invalid_credentials",message="Email atau kata sandi tidak sesuai."),401
    token=issue_mobile_token(user,str(body.get("device_name") or "Android")); db().execute("UPDATE users SET last_login=CURRENT_TIMESTAMP WHERE id=?",(user["id"],)); db().commit()
    return jsonify(token=token,user={"id":user["id"],"name":user["name"],"email":user["email"],"role":user["role"],"unit":user["unit"] or ""},organization={"name":user["org_name"],"app_name":user["app_name"],"accent":user["accent"],"logo":url_for("media_file",filename=user["logo"],_external=True) if user["logo"] else None})

@app.post("/api/v1/auth/pair")
def api_pair():
    body=request.get_json(silent=True) or {}; raw=str(body.get("token") or "")
    if not raw: return jsonify(error="invalid_pairing",message="QR tidak valid."),400
    digest=hashlib.sha256(raw.encode()).hexdigest(); con=db()
    try:
        con.execute("BEGIN IMMEDIATE")
        pairing=con.execute("SELECT * FROM mobile_pairings WHERE token_hash=? AND used_at IS NULL AND expires_at>CURRENT_TIMESTAMP",(digest,)).fetchone()
        if not pairing: con.rollback(); return jsonify(error="pairing_expired",message="QR sudah digunakan atau kedaluwarsa. Buat QR baru dari dashboard."),410
        user=con.execute("SELECT u.*,o.name org_name,o.app_name,o.logo,o.icon,o.accent,o.terminology FROM users u JOIN organizations o ON o.id=u.org_id WHERE u.id=? AND u.active=1",(pairing["user_id"],)).fetchone()
        if not user: con.rollback(); return jsonify(error="invalid_pairing"),401
        con.execute("UPDATE mobile_pairings SET used_at=CURRENT_TIMESTAMP WHERE id=?",(pairing["id"],))
        token=issue_mobile_token(user,str(body.get("device_name") or "Android")); con.execute("UPDATE users SET last_login=CURRENT_TIMESTAMP WHERE id=?",(user["id"],)); con.commit()
    except Exception: con.rollback(); raise
    return jsonify(token=token,user={"id":user["id"],"name":user["name"],"email":user["email"],"role":user["role"],"unit":user["unit"] or ""},organization={"name":user["org_name"],"app_name":user["app_name"],"accent":user["accent"],"logo":url_for("media_file",filename=user["logo"],_external=True) if user["logo"] else None})

@app.get("/api/v1/me")
@api_auth
def api_me():
    u=g.api_user
    unread=db().execute("SELECT count(*) FROM notifications WHERE org_id=? AND user_id=? AND read_at IS NULL",(u["org_id"],u["id"])).fetchone()[0] if u["role"] not in ("owner","admin") else db().execute("SELECT count(*) FROM notifications WHERE org_id=? AND read_at IS NULL AND (user_id IS NULL OR user_id=?)",(u["org_id"],u["id"])).fetchone()[0]
    return jsonify(user={"id":u["id"],"name":u["name"],"email":u["email"],"role":u["role"],"unit":u["unit"] or ""},organization={"name":u["org_name"],"app_name":u["app_name"],"accent":u["accent"],"logo":url_for("media_file",filename=u["logo"],_external=True) if u["logo"] else None},unread=unread)

def api_scope(user,alias="t"):
    if user["role"] in ("owner","admin"): return "1=1",[]
    if user["role"]=="agent": return f"{alias}.unit=? AND ({alias}.assignee_id IS NULL OR {alias}.assignee_id=?)",[user["unit"] or "",user["id"]]
    return f"{alias}.unit=?",[user["unit"] or ""]

@app.get("/api/v1/dashboard")
@api_auth
def api_dashboard():
    u=g.api_user; scope,params=api_scope(u); base=f"t.org_id=? AND {scope}"; args=[u["org_id"],*params]
    counts={status:db().execute(f"SELECT count(*) FROM tickets t WHERE {base} AND status=?",[*args,status]).fetchone()[0] for status in ("new","assigned","in_progress","waiting","resolved")}; counts["all"]=db().execute(f"SELECT count(*) FROM tickets t WHERE {base}",args).fetchone()[0]
    return jsonify(counts=counts)

@app.get("/api/v1/tickets")
@api_auth
def api_tickets():
    u=g.api_user; scope,scope_params=api_scope(u); where=["t.org_id=?",scope]; params=[u["org_id"],*scope_params]
    status=request.args.get("status","").strip(); query=request.args.get("q","").strip()
    if status: where.append("t.status=?"); params.append(status)
    if query: where.append("(t.code LIKE ? OR t.subject LIKE ? OR c.name LIKE ?)"); params.extend([f"%{query}%"]*3)
    rows=db().execute("SELECT t.*,c.name contact,c.phone,c.location,u.name assignee FROM tickets t JOIN contacts c ON c.id=t.contact_id LEFT JOIN users u ON u.id=t.assignee_id WHERE "+" AND ".join(where)+" ORDER BY t.updated_at DESC LIMIT 200",params).fetchall()
    return jsonify(tickets=[api_ticket_dict(row) for row in rows])

@app.get("/api/v1/tickets/<int:tid>")
@api_auth
def api_ticket_detail(tid):
    u=g.api_user; t=db().execute("SELECT t.*,c.name contact,c.phone,c.location,u.name assignee FROM tickets t JOIN contacts c ON c.id=t.contact_id LEFT JOIN users u ON u.id=t.assignee_id WHERE t.id=? AND t.org_id=?",(tid,u["org_id"])).fetchone()
    if not t: return jsonify(error="not_found"),404
    if not api_can_access(u,t): return jsonify(error="forbidden"),403
    messages=db().execute("SELECT * FROM messages WHERE ticket_id=? ORDER BY id",(tid,)).fetchall()
    return jsonify(ticket=api_ticket_dict(t),can_manage=u["role"] in ("owner","admin"),can_reply=t["status"] not in ("resolved","closed") and (u["role"] in ("owner","admin") or (u["role"] in ("supervisor","agent") and bool(t["unit"]))),allowed_statuses=list(("new","verified","assigned","in_progress","waiting","resolved","closed") if u["role"] in ("owner","admin") else ("in_progress","waiting","resolved")),messages=[{"id":m["id"],"direction":m["direction"],"body":m["body"],"sender":m["sender"],"internal":bool(m["internal"]),"attachment_url":url_for("media_file",filename=m["attachment_path"],_external=True) if m["attachment_path"] else None,"attachment_name":m["attachment_name"],"attachment_type":m["attachment_type"],"delivery_status":m["delivery_status"],"created_at":m["created_at"]} for m in messages])

@app.get("/api/v1/assignment-options")
@api_auth
def api_assignment_options():
    u=g.api_user
    if u["role"] not in ("owner","admin"): return jsonify(error="forbidden"),403
    units=db().execute("SELECT id,name,officer_name,officer_phone FROM units WHERE org_id=? AND active=1 ORDER BY name",(u["org_id"],)).fetchall(); users=db().execute("SELECT id,name,role,unit FROM users WHERE org_id=? AND active=1 AND role IN ('supervisor','agent') ORDER BY unit,name",(u["org_id"],)).fetchall()
    return jsonify(units=[dict(row) for row in units],users=[dict(row) for row in users])

@app.post("/api/v1/tickets/<int:tid>/assign")
@api_auth
def api_ticket_assign(tid):
    u=g.api_user
    if u["role"] not in ("owner","admin"): return jsonify(error="forbidden"),403
    t=db().execute("SELECT t.*,c.name contact,c.location FROM tickets t JOIN contacts c ON c.id=t.contact_id WHERE t.id=? AND t.org_id=?",(tid,u["org_id"])).fetchone(); body=request.get_json(silent=True) or {}; unit=db().execute("SELECT * FROM units WHERE id=? AND org_id=? AND active=1",(body.get("unit_id"),u["org_id"])).fetchone()
    if not t or not unit: return jsonify(error="not_found"),404
    assignee=body.get("assignee_id")
    if assignee and not db().execute("SELECT 1 FROM users WHERE id=? AND org_id=? AND unit=? AND active=1 AND role IN ('supervisor','agent')",(assignee,u["org_id"],unit["name"])).fetchone(): return jsonify(error="invalid_assignee",message="Petugas harus berasal dari unit yang dipilih."),400
    db().execute("UPDATE tickets SET unit=?,assignee_id=?,status='assigned',updated_at=CURRENT_TIMESTAMP WHERE id=?",(unit["name"],assignee,tid)); notify_assigned_users(u["org_id"],tid,"Disposisi aduan baru",f"{t['code']} telah diteruskan ke {unit['name']}. Login untuk membaca dan menanggapi.",unit["name"],int(assignee) if assignee else None)
    if unit["officer_phone"]:
        flow=db().execute("SELECT * FROM flow_configs WHERE org_id=?",(u["org_id"],)).fetchone(); org=db().execute("SELECT * FROM organizations WHERE id=?",(u["org_id"],)).fetchone(); original=db().execute("SELECT body FROM messages WHERE ticket_id=? AND direction='in' AND internal=0 ORDER BY id LIMIT 1",(tid,)).fetchone(); template=flow["forward_template_id"]
        text=fill(template,org,{"code":t["code"],"description":original["body"] if original else t["subject"],"name":t["contact"],"location":t["location"],"priority":t["priority"],"unit":unit["name"],"officer":unit["officer_name"]})+f"\n\nLogin ke aplikasi untuk menanggapi:\n{request.url_root.rstrip('/')}/tickets/{tid}"; send_mpwa_for_org(org,unit["officer_phone"],text)
    db().execute("INSERT INTO audit_logs(org_id,user_id,action,entity,entity_id,metadata) VALUES(?,?,?,?,?,?)",(u["org_id"],u["id"],"ticket.forwarded","ticket",tid,json.dumps({"unit":unit["name"],"assignee":assignee}))); db().commit(); return jsonify(status="assigned",unit=unit["name"])

@app.post("/api/v1/tickets/<int:tid>/reply")
@api_auth
def api_ticket_reply(tid):
    u=g.api_user; t=db().execute("SELECT t.*,c.phone FROM tickets t JOIN contacts c ON c.id=t.contact_id WHERE t.id=? AND t.org_id=?",(tid,u["org_id"])).fetchone()
    if not t: return jsonify(error="not_found"),404
    if not api_can_access(u,t) or u["role"] not in ("owner","admin","supervisor","agent") or t["status"] in ("resolved","closed") or (u["role"] not in ("owner","admin") and not t["unit"]): return jsonify(error="forbidden"),403
    payload=request.get_json(silent=True) or {}; body=(request.form.get("body") if request.form else payload.get("body") or "").strip(); upload=request.files.get("attachment"); stored=None
    if upload and upload.filename:
        try: stored=store_upload(file=upload)
        except ValueError as exc: return jsonify(error="invalid_attachment",message=str(exc)),400
    if not body and not stored: return jsonify(error="empty_message"),400
    org=db().execute("SELECT * FROM organizations WHERE id=?",(u["org_id"],)).fetchone()
    if stored: ok,message=send_mpwa_media_for_org(org,t["phone"],request.url_root.rstrip("/")+url_for("media_file",filename=stored[0]),stored[2],body)
    else: ok,message=send_mpwa_for_org(org,t["phone"],body)
    if not ok: return jsonify(error="delivery_failed",message=message),502
    db().execute("INSERT INTO messages(ticket_id,direction,body,sender,attachment_path,attachment_name,attachment_type,delivery_status) VALUES(?,?,?,?,?,?,?,'sent')",(tid,"out",body,u["name"],*(stored or (None,None,None)))); db().execute("UPDATE tickets SET updated_at=CURRENT_TIMESTAMP WHERE id=?",(tid,)); db().execute("INSERT INTO conversation_states(org_id,phone,step,language,data,human_takeover) VALUES(?,?,?,?,?,1) ON CONFLICT(org_id,phone) DO UPDATE SET step='human_chat',human_takeover=1,updated_at=CURRENT_TIMESTAMP",(u["org_id"],t["phone"],"human_chat","id",json.dumps({"ticket_id":tid}))); db().execute("INSERT INTO audit_logs(org_id,user_id,action,entity,entity_id,metadata) VALUES(?,?,?,?,?,?)",(u["org_id"],u["id"],"reply.sent","ticket",tid,"{}")); db().commit()
    return jsonify(status="sent")

@app.post("/api/v1/tickets/<int:tid>/status")
@api_auth
def api_ticket_status(tid):
    u=g.api_user; t=db().execute("SELECT t.*,c.phone FROM tickets t JOIN contacts c ON c.id=t.contact_id WHERE t.id=? AND t.org_id=?",(tid,u["org_id"])).fetchone(); body=request.get_json(silent=True) or {}; status=body.get("status")
    if not t: return jsonify(error="not_found"),404
    if not api_can_access(u,t) or u["role"] not in ("owner","admin","supervisor","agent"): return jsonify(error="forbidden"),403
    allowed=("new","verified","assigned","in_progress","waiting","resolved","closed") if u["role"] in ("owner","admin") else ("in_progress","waiting","resolved")
    if status not in allowed: return jsonify(error="invalid_status"),400
    db().execute("UPDATE tickets SET status=?,updated_at=CURRENT_TIMESTAMP,closed_at=CASE WHEN ? IN ('resolved','closed') THEN COALESCE(closed_at,CURRENT_TIMESTAMP) ELSE NULL END WHERE id=?",(status,status,tid)); db().execute("INSERT INTO audit_logs(org_id,user_id,action,entity,entity_id,metadata) VALUES(?,?,?,?,?,?)",(u["org_id"],u["id"],"ticket.status_updated","ticket",tid,json.dumps({"status":status})))
    if status in ("resolved","closed"): db().execute("DELETE FROM conversation_states WHERE org_id=? AND phone=?",(u["org_id"],t["phone"]))
    db().commit(); return jsonify(status=status)

@app.get("/api/v1/notifications")
@api_auth
def api_notifications():
    u=g.api_user; condition="(user_id IS NULL OR user_id=?)" if u["role"] in ("owner","admin") else "user_id=?"; rows=db().execute(f"SELECT n.*,t.code FROM notifications n LEFT JOIN tickets t ON t.id=n.ticket_id WHERE n.org_id=? AND {condition} ORDER BY n.id DESC LIMIT 100",(u["org_id"],u["id"])).fetchall()
    return jsonify(notifications=[{"id":n["id"],"ticket_id":n["ticket_id"],"code":n["code"],"title":n["title"],"body":n["body"],"read":bool(n["read_at"]),"created_at":n["created_at"]} for n in rows])

@app.post("/api/v1/notifications/read")
@api_auth
def api_notifications_read():
    u=g.api_user; condition="(user_id IS NULL OR user_id=?)" if u["role"] in ("owner","admin") else "user_id=?"; db().execute(f"UPDATE notifications SET read_at=CURRENT_TIMESTAMP WHERE org_id=? AND {condition} AND read_at IS NULL",(u["org_id"],u["id"])); db().commit(); return jsonify(status="ok")

@app.post("/webhooks/mpwa/<slug>")
def webhook(slug):
    org=db().execute("SELECT * FROM organizations WHERE slug=?",(slug,)).fetchone()
    if not org: return jsonify(error="unknown organization"),404
    expected=os.getenv("WEBHOOK_SECRET","")
    if expected and not secrets.compare_digest(request.args.get("token",""),expected): return jsonify(error="unauthorized webhook"),401
    p=request.get_json(silent=True) or request.form
    def truthy(value): return value is True or str(value).strip().lower() in ("1","true","yes","y")
    message_data=p.get("data") if isinstance(p.get("data"),dict) else {}
    if any(truthy(p.get(k)) or truthy(message_data.get(k)) for k in ("fromMe","from_me","isFromMe","is_from_me","outgoing")):
        return jsonify(status=True,ignored="outgoing message")
    phone=str(p.get("from","")).split("@")[0]; body=p.get("message") or "[Lampiran]"; name=p.get("name") or phone
    if not phone: return jsonify(error="missing sender"),400
    attachment=None; media=p.get("media")
    if media and p.get("mimetype") in ALLOWED_MEDIA:
        try:
            stream=media.get("stream",{}) if isinstance(media,dict) else {}; raw=stream.get("data",[])
            if isinstance(raw,list): raw=bytes(raw)
            elif isinstance(raw,str): raw=base64.b64decode(raw)
            attachment=store_upload(payload=raw,original_name=media.get("fileName"),mime=p.get("mimetype"))
        except (ValueError,TypeError,base64.binascii.Error): attachment=None
    reply=flow_reply(org,phone,body,name,attachment)
    if reply is not None: return jsonify(text=reply)
    c=db().execute("SELECT * FROM contacts WHERE org_id=? AND phone=?",(org["id"],phone)).fetchone()
    if not c: db().execute("INSERT INTO contacts(org_id,name,phone) VALUES(?,?,?)",(org["id"],name,phone)); cid=db().execute("SELECT last_insert_rowid()").fetchone()[0]
    else: cid=c["id"]
    t=db().execute("SELECT * FROM tickets WHERE org_id=? AND contact_id=? AND status NOT IN ('resolved','closed') ORDER BY id DESC LIMIT 1",(org["id"],cid)).fetchone()
    if not t:
        code=next_ticket_code(org); db().execute("INSERT INTO tickets(org_id,contact_id,code,subject) VALUES(?,?,?,?)",(org["id"],cid,code,body[:100])); tid=db().execute("SELECT last_insert_rowid()").fetchone()[0]
    else: tid=t["id"]
    db().execute("INSERT INTO messages(ticket_id,direction,body,sender,attachment_path,attachment_name,attachment_type) VALUES(?,?,?,?,?,?,?)",(tid,"in",body,name,*(attachment or (None,None,None)))); db().execute("UPDATE tickets SET updated_at=CURRENT_TIMESTAMP WHERE id=?",(tid,)); db().execute("INSERT INTO notifications(org_id,ticket_id,title,body) VALUES(?,?,?,?)",(org["id"],tid,"Pesan baru dari pengadu",f"{name}: {body[:120]}")); notify_assigned_users(org["id"],tid,"Pesan baru dari pengadu",f"{t['code'] if t else code}: {body[:120]}",t["unit"] if t else None,t["assignee_id"] if t else None); db().commit(); return jsonify(status=True,ticket_id=tid)

with app.app_context(): init_db()
if __name__=="__main__": app.run(host="0.0.0.0",port=8080,debug=True)
