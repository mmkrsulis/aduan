import os, sqlite3, json, secrets, csv, io
from datetime import datetime
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify, g, Response, send_file
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.middleware.proxy_fix import ProxyFix
import requests
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
app.secret_key = os.getenv("SECRET_KEY", secrets.token_hex(32))
app.config.update(MAX_CONTENT_LENGTH=8*1024*1024,SESSION_COOKIE_HTTPONLY=True,SESSION_COOKIE_SAMESITE="Lax",SESSION_COOKIE_SECURE=os.getenv("COOKIE_SECURE","false").lower()=="true",PERMANENT_SESSION_LIFETIME=28800)
DB = os.getenv("DATABASE_PATH", os.path.join(os.path.dirname(__file__), "aduan.db"))

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
    if request.method=="POST" and request.endpoint!="webhook":
        expected=session.get("csrf",""); supplied=request.form.get("csrf_token","") or request.headers.get("X-CSRF-Token","")
        if not expected or not secrets.compare_digest(expected,supplied): return ("Invalid or expired form token",400)

SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS organizations(id INTEGER PRIMARY KEY, name TEXT NOT NULL, slug TEXT UNIQUE, logo TEXT, accent TEXT DEFAULT '#2563eb', terminology TEXT DEFAULT 'Complaint', mpwa_url TEXT, mpwa_key TEXT, mpwa_sender TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, org_id INTEGER NOT NULL, name TEXT NOT NULL, email TEXT UNIQUE NOT NULL, password TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('owner','admin','supervisor','agent','viewer')), unit TEXT, active INTEGER DEFAULT 1, last_login TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(org_id) REFERENCES organizations(id));
CREATE TABLE IF NOT EXISTS contacts(id INTEGER PRIMARY KEY, org_id INTEGER NOT NULL, name TEXT, phone TEXT NOT NULL, location TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, UNIQUE(org_id,phone), FOREIGN KEY(org_id) REFERENCES organizations(id));
CREATE TABLE IF NOT EXISTS tickets(id INTEGER PRIMARY KEY, org_id INTEGER NOT NULL, contact_id INTEGER NOT NULL, code TEXT UNIQUE, subject TEXT NOT NULL, category TEXT DEFAULT 'General', priority TEXT DEFAULT 'normal', status TEXT DEFAULT 'new', unit TEXT, assignee_id INTEGER, sla_due TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP, closed_at TEXT, FOREIGN KEY(org_id) REFERENCES organizations(id), FOREIGN KEY(contact_id) REFERENCES contacts(id), FOREIGN KEY(assignee_id) REFERENCES users(id));
CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY, ticket_id INTEGER NOT NULL, direction TEXT NOT NULL, body TEXT NOT NULL, sender TEXT, internal INTEGER DEFAULT 0, created_at TEXT DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(ticket_id) REFERENCES tickets(id) ON DELETE CASCADE);
CREATE TABLE IF NOT EXISTS audit_logs(id INTEGER PRIMARY KEY, org_id INTEGER NOT NULL, user_id INTEGER, action TEXT NOT NULL, entity TEXT, entity_id INTEGER, metadata TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
CREATE TABLE IF NOT EXISTS units(id INTEGER PRIMARY KEY, org_id INTEGER NOT NULL, name TEXT NOT NULL, officer_name TEXT, officer_phone TEXT, active INTEGER DEFAULT 1, created_at TEXT DEFAULT CURRENT_TIMESTAMP, UNIQUE(org_id,name), FOREIGN KEY(org_id) REFERENCES organizations(id));
CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY, org_id INTEGER NOT NULL, user_id INTEGER, ticket_id INTEGER, title TEXT NOT NULL, body TEXT, read_at TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(org_id) REFERENCES organizations(id), FOREIGN KEY(user_id) REFERENCES users(id), FOREIGN KEY(ticket_id) REFERENCES tickets(id));
CREATE TABLE IF NOT EXISTS flow_configs(id INTEGER PRIMARY KEY, org_id INTEGER UNIQUE NOT NULL, enabled INTEGER DEFAULT 1, default_language TEXT DEFAULT 'id', welcome_id TEXT, welcome_en TEXT, service_info_id TEXT, service_info_en TEXT, confirmation_id TEXT, confirmation_en TEXT, completion_id TEXT, completion_en TEXT, office_hours TEXT DEFAULT 'Monday-Friday, 08:00-16:00', updated_at TEXT DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(org_id) REFERENCES organizations(id));
CREATE TABLE IF NOT EXISTS conversation_states(id INTEGER PRIMARY KEY, org_id INTEGER NOT NULL, phone TEXT NOT NULL, step TEXT NOT NULL DEFAULT 'menu', language TEXT DEFAULT 'id', data TEXT DEFAULT '{}', human_takeover INTEGER DEFAULT 0, updated_at TEXT DEFAULT CURRENT_TIMESTAMP, UNIQUE(org_id,phone), FOREIGN KEY(org_id) REFERENCES organizations(id));
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
    os.makedirs(os.path.dirname(DB), exist_ok=True)
    con=sqlite3.connect(DB, timeout=30); con.executescript(SCHEMA)
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

@app.context_processor
def ctx():
    unread=0
    if session.get("org_id"):
        unread=db().execute("SELECT count(*) FROM notifications WHERE org_id=? AND read_at IS NULL AND (user_id IS NULL OR user_id=?)",(session["org_id"],session.get("uid"))).fetchone()[0]
    return {"me":session,"now":datetime.utcnow(),"statuses":["new","verified","assigned","in_progress","waiting","resolved","closed"],"tr":tr,"lang":session.get("lang","en"),"unread":unread,"csrf_token":csrf_token}

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
            session.clear(); session.update(uid=u["id"],org_id=u["org_id"],name=u["name"],role=u["role"],org_name=u["org_name"]); db().execute("UPDATE users SET last_login=CURRENT_TIMESTAMP WHERE id=?",(u["id"],)); db().commit(); return redirect(url_for("dashboard"))
        flash("Invalid credentials","error")
    return render_template("login.html")

@app.route("/logout")
def logout(): session.clear(); return redirect(url_for("login"))

@app.route("/")
@login_required
def dashboard():
    oid=session["org_id"]
    stats={s:db().execute("SELECT count(*) FROM tickets WHERE org_id=? AND status=?",(oid,s)).fetchone()[0] for s in ["new","in_progress","resolved","closed"]}
    stats["all"]=db().execute("SELECT count(*) FROM tickets WHERE org_id=?",(oid,)).fetchone()[0]
    tickets=db().execute("SELECT t.*,c.name contact,c.phone,u.name assignee FROM tickets t JOIN contacts c ON c.id=t.contact_id LEFT JOIN users u ON u.id=t.assignee_id WHERE t.org_id=? ORDER BY t.updated_at DESC LIMIT 8",(oid,)).fetchall()
    cats=db().execute("SELECT category,count(*) n FROM tickets WHERE org_id=? GROUP BY category ORDER BY n DESC",(oid,)).fetchall()
    return render_template("dashboard.html",stats=stats,tickets=tickets,cats=cats)

@app.route("/tickets")
@login_required
def tickets():
    q=request.args.get("q",""); status=request.args.get("status",""); params=[session["org_id"]]; where="t.org_id=?"
    if q: where+=" AND (t.code LIKE ? OR t.subject LIKE ? OR c.name LIKE ? OR c.phone LIKE ?)"; params += [f"%{q}%"]*4
    if status: where+=" AND t.status=?"; params.append(status)
    rows=db().execute(f"SELECT t.*,c.name contact,c.phone,u.name assignee FROM tickets t JOIN contacts c ON c.id=t.contact_id LEFT JOIN users u ON u.id=t.assignee_id WHERE {where} ORDER BY t.updated_at DESC",params).fetchall()
    return render_template("tickets.html",tickets=rows)

@app.route("/tickets/<int:tid>",methods=["GET","POST"])
@login_required
def ticket(tid):
    t=db().execute("SELECT t.*,c.name contact,c.phone,c.location FROM tickets t JOIN contacts c ON c.id=t.contact_id WHERE t.id=? AND t.org_id=?",(tid,session["org_id"])).fetchone()
    if not t: return ("Not found",404)
    if request.method=="POST":
        action=request.form.get("action")
        if action=="update": db().execute("UPDATE tickets SET status=?,priority=?,category=?,unit=?,assignee_id=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(request.form["status"],request.form["priority"],request.form["category"],request.form["unit"],request.form.get("assignee") or None,tid)); audit("ticket.updated","ticket",tid)
        elif action in ("reply","note"):
            body=request.form["body"].strip(); internal=action=="note"
            if body:
                if internal:
                    db().execute("INSERT INTO messages(ticket_id,direction,body,sender,internal) VALUES(?,?,?,?,1)",(tid,"out",body,session["name"])); db().execute("UPDATE tickets SET updated_at=CURRENT_TIMESTAMP WHERE id=?",(tid,)); db().commit(); audit("note.added","ticket",tid)
                else:
                    ok,msg=send_mpwa(t["phone"],body); flash(msg,"success" if ok else "error")
                    if ok:
                        db().execute("INSERT INTO messages(ticket_id,direction,body,sender,internal) VALUES(?,?,?,?,0)",(tid,"out",body,session["name"])); db().execute("UPDATE tickets SET updated_at=CURRENT_TIMESTAMP WHERE id=?",(tid,)); db().commit(); audit("reply.sent","ticket",tid)
                    else: audit("reply.failed","ticket",tid,{"reason":msg})
        elif action=="forward":
            unit=db().execute("SELECT * FROM units WHERE id=? AND org_id=? AND active=1",(request.form.get("unit_id"),session["org_id"])).fetchone()
            if unit and unit["officer_phone"]:
                text=f"New complaint assigned\n{t['code']} — {t['subject']}\nReporter: {t['contact']}\nPriority: {t['priority']}\nPlease coordinate the follow-up with the service desk."
                ok,msg=send_mpwa(unit["officer_phone"],text); flash(msg,"success" if ok else "error")
                if ok:
                    db().execute("UPDATE tickets SET unit=?,status='assigned',updated_at=CURRENT_TIMESTAMP WHERE id=?",(unit["name"],tid))
                    db().execute("INSERT INTO messages(ticket_id,direction,body,sender,internal) VALUES(?,?,?,?,1)",(tid,"out",f"Forwarded to {unit['officer_name'] or unit['name']} via WhatsApp",session["name"]))
                    audit("ticket.forwarded","ticket",tid,{"unit":unit["name"],"officer":unit["officer_name"]})
            else: flash("The selected unit has no officer WhatsApp number.","error")
        db().commit(); return redirect(url_for("ticket",tid=tid))
    msgs=db().execute("SELECT * FROM messages WHERE ticket_id=? ORDER BY created_at",(tid,)).fetchall(); users=db().execute("SELECT * FROM users WHERE org_id=? AND active=1 ORDER BY name",(session["org_id"],)).fetchall(); units=db().execute("SELECT * FROM units WHERE org_id=? ORDER BY name",(session["org_id"],)).fetchall()
    return render_template("ticket.html",t=t,msgs=msgs,users=users,units=units)

def send_mpwa(phone,body):
    org=db().execute("SELECT * FROM organizations WHERE id=?",(session["org_id"],)).fetchone(); base=org["mpwa_url"] or os.getenv("MPWA_BASE_URL",""); key=org["mpwa_key"] or os.getenv("MPWA_API_KEY",""); sender=org["mpwa_sender"] or os.getenv("MPWA_SENDER","")
    if not (base and key and sender): return False,"Reply saved; configure MPWA credentials to transmit it."
    try:
        r=requests.post(base.rstrip("/")+"/send-message",data={"api_key":key,"sender":sender,"number":phone,"message":body},timeout=15)
        try: payload=r.json()
        except ValueError: payload={}
        ok=r.ok and payload.get("status") is True
        message=payload.get("msg") or payload.get("message")
        return ok,("Message sent through MPWA." if ok else (message or f"MPWA rejected the message ({r.status_code})."))
    except requests.RequestException as e: return False,f"MPWA connection failed: {e}"

@app.route("/users",methods=["GET","POST"])
@login_required
@roles("owner","admin")
def users():
    if request.method=="POST":
        try: db().execute("INSERT INTO users(org_id,name,email,password,role,unit) VALUES(?,?,?,?,?,?)",(session["org_id"],request.form["name"],request.form["email"].lower(),generate_password_hash(request.form["password"]),request.form["role"],request.form["unit"])); db().commit(); audit("user.created","user"); flash("User created","success")
        except sqlite3.IntegrityError: flash("Email already exists","error")
    rows=db().execute("SELECT * FROM users WHERE org_id=? ORDER BY active DESC,name",(session["org_id"],)).fetchall(); return render_template("users.html",users=rows)

@app.post("/users/<int:uid>/toggle")
@login_required
@roles("owner","admin")
def toggle_user(uid):
    if uid!=session["uid"]: db().execute("UPDATE users SET active=1-active WHERE id=? AND org_id=?",(uid,session["org_id"])); db().commit(); audit("user.toggled","user",uid)
    return redirect(url_for("users"))

@app.route("/settings",methods=["GET","POST"])
@login_required
@roles("owner","admin")
def settings():
    if request.method=="POST":
        db().execute("UPDATE organizations SET name=?,accent=?,terminology=?,mpwa_url=?,mpwa_key=?,mpwa_sender=? WHERE id=?",(request.form["name"],request.form["accent"],request.form["terminology"],request.form["mpwa_url"],request.form["mpwa_key"],request.form["mpwa_sender"],session["org_id"])); db().commit(); session["org_name"]=request.form["name"]; audit("organization.updated","organization",session["org_id"]); flash("Settings saved","success")
    org=db().execute("SELECT * FROM organizations WHERE id=?",(session["org_id"],)).fetchone(); units=db().execute("SELECT * FROM units WHERE org_id=? ORDER BY name",(session["org_id"],)).fetchall(); return render_template("settings.html",org=org,units=units)

@app.post("/units")
@login_required
@roles("owner","admin")
def create_unit():
    try:
        db().execute("INSERT INTO units(org_id,name,officer_name,officer_phone) VALUES(?,?,?,?)",(session["org_id"],request.form["name"],request.form.get("officer_name"),request.form.get("officer_phone"))); db().commit(); audit("unit.created","unit"); flash("Responsible unit added","success")
    except sqlite3.IntegrityError: flash("Unit name already exists","error")
    return redirect(url_for("settings"))

@app.post("/units/<int:unit_id>/update")
@login_required
@roles("owner","admin")
def update_unit(unit_id):
    unit=db().execute("SELECT * FROM units WHERE id=? AND org_id=?",(unit_id,session["org_id"])).fetchone()
    if not unit: return ("Not found",404)
    name=request.form["name"].strip(); officer=request.form.get("officer_name","").strip(); phone=request.form.get("officer_phone","").strip()
    if not name: flash("Unit name is required","error"); return redirect(url_for("settings")+"#units")
    try:
        db().execute("UPDATE units SET name=?,officer_name=?,officer_phone=?,active=1 WHERE id=? AND org_id=?",(name,officer,phone,unit_id,session["org_id"])); db().execute("UPDATE tickets SET unit=? WHERE org_id=? AND unit=?",(name,session["org_id"],unit["name"])); db().commit(); audit("unit.updated","unit",unit_id,{"old_name":unit["name"],"new_name":name}); flash("Responsible unit updated","success")
    except sqlite3.IntegrityError: flash("Unit name already exists","error")
    return redirect(url_for("settings")+"#units")

@app.post("/units/<int:unit_id>/delete")
@login_required
@roles("owner","admin")
def delete_unit(unit_id):
    unit=db().execute("SELECT name FROM units WHERE id=? AND org_id=?",(unit_id,session["org_id"])).fetchone()
    if not unit: return ("Not found",404)
    db().execute("DELETE FROM units WHERE id=? AND org_id=?",(unit_id,session["org_id"])); db().commit(); audit("unit.deleted","unit",unit_id,{"name":unit["name"]}); flash("Responsible unit deleted","success"); return redirect(url_for("settings")+"#units")

def report_rows():
    where=["t.org_id=?"]; params=[session["org_id"]]
    for key,column in (("status","t.status"),("category","t.category"),("unit","t.unit"),("priority","t.priority")):
        if request.args.get(key): where.append(column+"=?"); params.append(request.args[key])
    if request.args.get("date_from"): where.append("date(t.created_at)>=date(?)"); params.append(request.args["date_from"])
    if request.args.get("date_to"): where.append("date(t.created_at)<=date(?)"); params.append(request.args["date_to"])
    return db().execute("SELECT t.code,t.created_at,c.name contact,c.phone,c.location,t.subject,t.category,t.priority,t.status,t.unit,u.name assignee,t.updated_at,t.closed_at FROM tickets t JOIN contacts c ON c.id=t.contact_id LEFT JOIN users u ON u.id=t.assignee_id WHERE "+" AND ".join(where)+" ORDER BY t.created_at DESC",params).fetchall()

@app.get("/reports")
@login_required
def reports():
    rows=report_rows(); categories=db().execute("SELECT DISTINCT category FROM tickets WHERE org_id=? ORDER BY category",(session["org_id"],)).fetchall(); units=db().execute("SELECT name FROM units WHERE org_id=? AND active=1 ORDER BY name",(session["org_id"],)).fetchall()
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
    rows=db().execute("SELECT n.*,t.code FROM notifications n LEFT JOIN tickets t ON t.id=n.ticket_id WHERE n.org_id=? AND (n.user_id IS NULL OR n.user_id=?) ORDER BY n.created_at DESC LIMIT 100",(session["org_id"],session["uid"])).fetchall()
    db().execute("UPDATE notifications SET read_at=CURRENT_TIMESTAMP WHERE org_id=? AND read_at IS NULL AND (user_id IS NULL OR user_id=?)",(session["org_id"],session["uid"])); db().commit()
    return render_template("notifications.html",notifications=rows)

@app.route("/settings/flow",methods=["GET","POST"])
@login_required
@roles("owner","admin")
def flow_settings():
    if request.method=="POST":
        fields=("default_language","welcome_id","welcome_en","service_info_id","service_info_en","confirmation_id","confirmation_en","completion_id","completion_en","office_hours")
        values=[request.form.get(k,"").strip() for k in fields]
        db().execute("UPDATE flow_configs SET enabled=?,default_language=?,welcome_id=?,welcome_en=?,service_info_id=?,service_info_en=?,confirmation_id=?,confirmation_en=?,completion_id=?,completion_en=?,office_hours=?,updated_at=CURRENT_TIMESTAMP WHERE org_id=?",[1 if request.form.get("enabled") else 0,*values,session["org_id"]]); db().commit(); audit("flow.updated","flow",session["org_id"]); flash("Complaint flow saved","success")
    flow=db().execute("SELECT * FROM flow_configs WHERE org_id=?",(session["org_id"],)).fetchone()
    return render_template("flow_settings.html",flow=flow)

def fill(text, org, data=None, **extra):
    values={"organization":org["name"],**(data or {}),**extra}
    for key,value in values.items(): text=(text or "").replace("{"+key+"}",str(value or "-"))
    return text

def flow_reply(org,phone,body,name):
    flow=db().execute("SELECT * FROM flow_configs WHERE org_id=?",(org["id"],)).fetchone()
    if not flow or not flow["enabled"]: return None
    state=db().execute("SELECT * FROM conversation_states WHERE org_id=? AND phone=?",(org["id"],phone)).fetchone(); command=body.strip().upper(); lang=state["language"] if state else flow["default_language"]
    if command in ("EN","ENGLISH"): lang="en"; state=None
    if command in ("ID","INDONESIA","BAHASA"): lang="id"; state=None
    welcome=flow["welcome_id" if lang=="id" else "welcome_en"]
    if command in ("MENU","START","MULAI") or not state:
        db().execute("INSERT INTO conversation_states(org_id,phone,step,language,data) VALUES(?,?,?,?,?) ON CONFLICT(org_id,phone) DO UPDATE SET step='menu',language=excluded.language,data='{}',human_takeover=0,updated_at=CURRENT_TIMESTAMP",(org["id"],phone,"menu",lang,"{}")); db().commit(); return fill(welcome,org)
    if state["human_takeover"]: return None
    data=json.loads(state["data"] or "{}"); step=state["step"]
    def move(next_step, reply, new_data=None):
        db().execute("UPDATE conversation_states SET step=?,language=?,data=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(next_step,lang,json.dumps(new_data if new_data is not None else data),state["id"])); db().commit(); return reply
    if command in ("BATAL","CANCEL"):
        return move("menu",("Proses dibatalkan. Ketik MENU untuk kembali ke menu utama." if lang=="id" else "The process was cancelled. Type MENU to return to the main menu."),{})
    if step=="menu":
        if command=="1": return move("name","Silakan tuliskan nama lengkap Anda." if lang=="id" else "Please enter your full name.")
        if command=="2": return move("status","Silakan kirim nomor aduan Anda, contoh: DEM-2026-00001." if lang=="id" else "Please send your complaint number, for example: DEM-2026-00001.")
        if command=="3": return move("menu",fill(flow["service_info_id" if lang=="id" else "service_info_en"],org))
        return "Pilihan tidak dikenali. Balas 1, 2, atau 3." if lang=="id" else "Unknown option. Reply with 1, 2, or 3."
    if step=="status":
        t=db().execute("SELECT code,status,subject,unit,updated_at FROM tickets WHERE org_id=? AND upper(code)=upper(?)",(org["id"],body.strip())).fetchone()
        if not t: return "Nomor aduan tidak ditemukan. Periksa kembali atau ketik MENU." if lang=="id" else "Complaint number not found. Check it or type MENU."
        reply=(f"Status {t['code']}: {t['status'].replace('_',' ')}\nAduan: {t['subject']}\nUnit: {t['unit'] or '-'}\nPembaruan: {t['updated_at']}" if lang=="id" else f"Status {t['code']}: {t['status'].replace('_',' ')}\nComplaint: {t['subject']}\nUnit: {t['unit'] or '-'}\nUpdated: {t['updated_at']}")
        return move("menu",reply,{})
    if step=="name": data["name"]=body.strip()[:120]; return move("location","Sebutkan lokasi, unit, sekolah, cabang, atau tempat kejadian." if lang=="id" else "Enter the location, unit, school, branch, or incident site.",data)
    if step=="location": data["location"]=body.strip()[:240]; return move("description","Jelaskan aduan Anda secara lengkap dalam satu pesan." if lang=="id" else "Describe your complaint completely in one message.",data)
    if step=="description":
        data["description"]=body.strip()[:4000]
        text=fill(flow["confirmation_id" if lang=="id" else "confirmation_en"],org,data)
        return move("confirm",text,data)
    if step=="confirm":
        if command in ("UBAH","EDIT"): return move("name","Silakan tuliskan kembali nama lengkap Anda." if lang=="id" else "Please re-enter your full name.",{})
        if command not in ("KIRIM","SEND"): return "Balas KIRIM, UBAH, atau BATAL." if lang=="id" else "Reply SEND, EDIT, or CANCEL."
        c=db().execute("SELECT * FROM contacts WHERE org_id=? AND phone=?",(org["id"],phone)).fetchone()
        if c: cid=c["id"]; db().execute("UPDATE contacts SET name=?,location=? WHERE id=?",(data["name"],data["location"],cid))
        else: db().execute("INSERT INTO contacts(org_id,name,phone,location) VALUES(?,?,?,?)",(org["id"],data["name"],phone,data["location"])); cid=db().execute("SELECT last_insert_rowid()").fetchone()[0]
        n=db().execute("SELECT count(*)+1 FROM tickets WHERE org_id=?",(org["id"],)).fetchone()[0]; code=f"{org['slug'][:3].upper()}-{datetime.utcnow().year}-{n:05}"
        db().execute("INSERT INTO tickets(org_id,contact_id,code,subject) VALUES(?,?,?,?)",(org["id"],cid,code,data["description"][:100])); tid=db().execute("SELECT last_insert_rowid()").fetchone()[0]
        db().execute("INSERT INTO messages(ticket_id,direction,body,sender) VALUES(?,?,?,?)",(tid,"in",data["description"],data["name"])); db().execute("INSERT INTO notifications(org_id,ticket_id,title,body) VALUES(?,?,?,?)",(org["id"],tid,"New WhatsApp complaint",f"{data['name']}: {data['description'][:120]}")); db().execute("UPDATE conversation_states SET step='menu',data='{}',updated_at=CURRENT_TIMESTAMP WHERE id=?",(state["id"],)); db().commit()
        return fill(flow["completion_id" if lang=="id" else "completion_en"],org,code=code)
    return move("menu",fill(welcome,org),{})

@app.post("/webhooks/mpwa/<slug>")
def webhook(slug):
    org=db().execute("SELECT * FROM organizations WHERE slug=?",(slug,)).fetchone()
    if not org: return jsonify(error="unknown organization"),404
    expected=os.getenv("WEBHOOK_SECRET","")
    if expected and not secrets.compare_digest(request.args.get("token",""),expected): return jsonify(error="unauthorized webhook"),401
    p=request.get_json(silent=True) or request.form; phone=str(p.get("from","")).split("@")[0]; body=p.get("message") or "[Media message]"; name=p.get("name") or phone
    if not phone: return jsonify(error="missing sender"),400
    reply=flow_reply(org,phone,body,name)
    if reply is not None: return jsonify(text=reply)
    c=db().execute("SELECT * FROM contacts WHERE org_id=? AND phone=?",(org["id"],phone)).fetchone()
    if not c: db().execute("INSERT INTO contacts(org_id,name,phone) VALUES(?,?,?)",(org["id"],name,phone)); cid=db().execute("SELECT last_insert_rowid()").fetchone()[0]
    else: cid=c["id"]
    t=db().execute("SELECT * FROM tickets WHERE org_id=? AND contact_id=? AND status NOT IN ('resolved','closed') ORDER BY id DESC LIMIT 1",(org["id"],cid)).fetchone()
    if not t:
        n=db().execute("SELECT count(*)+1 FROM tickets WHERE org_id=?",(org["id"],)).fetchone()[0]; code=f"{org['slug'][:3].upper()}-{datetime.utcnow().year}-{n:05}"; db().execute("INSERT INTO tickets(org_id,contact_id,code,subject) VALUES(?,?,?,?)",(org["id"],cid,code,body[:100])); tid=db().execute("SELECT last_insert_rowid()").fetchone()[0]
    else: tid=t["id"]
    db().execute("INSERT INTO messages(ticket_id,direction,body,sender) VALUES(?,?,?,?)",(tid,"in",body,name)); db().execute("UPDATE tickets SET updated_at=CURRENT_TIMESTAMP WHERE id=?",(tid,)); db().execute("INSERT INTO notifications(org_id,ticket_id,title,body) VALUES(?,?,?,?)",(org["id"],tid,"New WhatsApp complaint",f"{name}: {body[:120]}")); db().commit(); return jsonify(status=True,ticket_id=tid)

with app.app_context(): init_db()
if __name__=="__main__": app.run(host="0.0.0.0",port=8080,debug=True)
