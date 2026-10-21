import os
import json
import uuid
import sqlite3
import datetime
import qrcode
import bcrypt
import time
import hmac
import io
import hashlib
import requests
from flask import Flask, request, jsonify, send_from_directory, Response
from flask_cors import CORS
from werkzeug.utils import secure_filename

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})

DATABASE_FILE = "database.db"
app.config['MAX_CONTENT_LENGTH'] = 15 * 1024 * 1024

PAYSTACK_SECRET_KEY = os.environ.get("PAYSTACK_SECRET_KEY", "")
PAYSTACK_PUBLIC_KEY = os.environ.get("PAYSTACK_PUBLIC_KEY", "")
PAYSTACK_SUBACCOUNT = os.environ.get("PAYSTACK_SUBACCOUNT", "")
PAYSTACK_WEBHOOK_SECRET = os.environ.get("PAYSTACK_WEBHOOK_SECRET", "")
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")
ADMIN_TOKENS = {t.strip() for t in os.environ.get("ADMIN_TOKENS", "").split(",") if t.strip()}
if ADMIN_TOKEN:
    ADMIN_TOKENS.add(ADMIN_TOKEN)

JOB_FILES_DIR = os.path.join("uploads", "job_files")
ANNOUNCEMENTS_DIR = os.path.join("uploads", "announcements")

DESIGN_RATE_DESIGNED = 1000
DESIGN_RATE_NOT_DESIGNED = 3000
ENVELOPE_DIMENSIONS = {"8x4.5": (8, 4.5), "9x5": (9, 5), "10x6": (10, 6)}
CARD_DIMENSIONS = {"3.5x2": (3.5, 2), "4x2.5": (4, 2.5), "4.5x3": (4.5, 3)}
VIP_TIER_PRICES = {"blue": 1500, "red": 3000, "yellow": 4500, "black": 6000}
VIP_TIER_VALIDITY_DAYS = {"blue": 30, "red": 90, "yellow": 180, "black": 365}
SUB_CARD_PRICE = 2000            # Naira - subsidiary (sub) card
SUB_DISCOUNT_RATE = 0.25       # 25% off every job
SUBS_PER_WEEK = 2             # subsidiary card usage per week
AFTER_CLOSE = "18:30"        # customers cannot post updates after this time
DAY_START = "09:30"         # admin starts work at this time

NOTES_CATEGORIES = ["Design / Instructions", "Size & Colour", "Special Requests", "Other"]

# Test account: full admin powers, no real payment needed (username, password, nickname)
TEST_ACCOUNT = {"username": "test1", "password": "TEST123", "nickname": "ADMINTEST"}

STATIC_PAGES = {
    "VLAND.html", "dashboard.html", "jobs.html", "payment.html",
    "renew.html", "VIP-CARD.html", "admin.html", "receipt.html",
    "VLAND.css", "VLAND.js",
}

import os
import json
import uuid
import sqlite3
import datetime
import qrcode
import bcrypt
import time
import hmac
import io
import hashlib
import requests
from flask import Flask, request, jsonify, send_from_directory, Response
from flask_cors import CORS
from werkzeug.utils import secure_filename

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})

DATABASE_FILE = "database.db"
app.config['MAX_CONTENT_LENGTH'] = 15 * 1024 * 1024

PAYSTACK_SECRET_KEY = os.environ.get("PAYSTACK_SECRET_KEY", "")
PAYSTACK_PUBLIC_KEY = os.environ.get("PAYSTACK_PUBLIC_KEY", "")
PAYSTACK_SUBACCOUNT = os.environ.get("PAYSTACK_SUBACCOUNT", "")
PAYSTACK_WEBHOOK_SECRET = os.environ.get("PAYSTACK_WEBHOOK_SECRET", "")
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")
ADMIN_TOKENS = {t.strip() for t in os.environ.get("ADMIN_TOKENS", "").split(",") if t.strip()}
if ADMIN_TOKEN:
    ADMIN_TOKENS.add(ADMIN_TOKEN)

JOB_FILES_DIR = os.path.join("uploads", "job_files")
ANNOUNCEMENTS_DIR = os.path.join("uploads", "announcements")

DESIGN_RATE_DESIGNED = 1000
DESIGN_RATE_NOT_DESIGNED = 3000
ENVELOPE_DIMENSIONS = {"8x4.5": (8, 4.5), "9x5": (9, 5), "10x6": (10, 6)}
CARD_DIMENSIONS = {"3.5x2": (3.5, 2), "4x2.5": (4, 2.5), "4.5x3": (4.5, 3)}
VIP_TIER_PRICES = {"blue": 1500, "red": 3000, "yellow": 4500, "black": 6000}
VIP_TIER_VALIDITY_DAYS = {"blue": 30, "red": 90, "yellow": 180, "black": 365}
SUB_CARD_PRICE = 2000
SUB_DISCOUNT_RATE = 0.25
SUBS_PER_WEEK = 2
AFTER_CLOSE = "18:30"
DAY_START = "09:30"
NOTES_CATEGORIES = ["Design / Instructions", "Size & Colour", "Special Requests", "Other"]
TEST_ACCOUNT = {"username": "test1", "password": "TEST123", "nickname": "ADMINTEST"}

STATIC_PAGES = {
    "VLAND.html", "dashboard.html", "jobs.html", "payment.html",
    "renew.html", "VIP-CARD.html", "admin.html", "receipt.html",
    "VLAND.css", "VLAND.js",
}

def init_db():
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute("""CREATE TABLE IF NOT EXISTS users (
        username TEXT PRIMARY KEY, password_hash TEXT, nickname TEXT,
        first_name TEXT DEFAULT '', last_name TEXT DEFAULT '',
        sex TEXT DEFAULT '', registered_at TEXT DEFAULT '')""")
    for col, decl in (("nickname", "TEXT"), ("first_name", "TEXT"), ("last_name", "TEXT"),
                    ("sex", "TEXT"), ("registered_at", "TEXT")):
        cols = {r[1] for r in cursor.execute("PRAGMA table_info(users)")}
        if col not in cols:
            cursor.execute(f"ALTER TABLE users ADD COLUMN {col} {decl}")
    cursor.execute("""CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, job_type TEXT,
        actual_price REAL, vip_money REAL, total_price REAL, status TEXT,
        production_status TEXT DEFAULT 'Awaiting Production', timestamp TEXT,
        paystack_ref TEXT, file_id TEXT, method TEXT DEFAULT '', is_vip INTEGER DEFAULT 0,
        notes TEXT DEFAULT '', notes_category TEXT DEFAULT '',
        negotiation TEXT DEFAULT '')""")
    for col, decl in (("timestamp", "TEXT"),
                    ("production_status", "TEXT DEFAULT 'Awaiting Production'"),
                    ("paystack_ref", "TEXT"), ("file_id", "TEXT"),
                    ("method", "TEXT DEFAULT ''"), ("is_vip", "INTEGER DEFAULT 0"),
                    ("notes", "TEXT DEFAULT ''"),
                    ("notes_category", "TEXT DEFAULT ''"), ("negotiation", "TEXT DEFAULT ''")):
        cols = {r[1] for r in cursor.execute("PRAGMA table_info(transactions)")}
        if col not in cols:
            cursor.execute(f"ALTER TABLE transactions ADD COLUMN {col} {decl}")
    cursor.execute("""CREATE TABLE IF NOT EXISTS vip_cards (
        card_id TEXT PRIMARY KEY, username TEXT, name TEXT, phone TEXT, sex TEXT,
        tier TEXT, issue_date TEXT, valid_until TEXT, qr_path TEXT)""")
    cols = {r[1] for r in cursor.execute("PRAGMA table_info(vip_cards)")}
    if "valid_until" not in cols:
        cursor.execute("ALTER TABLE vip_cards ADD COLUMN valid_until TEXT")
    cursor.execute("""CREATE TABLE IF NOT EXISTS sub_cards (
        sub_id TEXT PRIMARY KEY, username TEXT, vip_card_id TEXT, tag TEXT,
        registered_at TEXT, valid_until TEXT, week_key TEXT DEFAULT '',
        uses_count INTEGER DEFAULT 0, carry_count INTEGER DEFAULT 0)""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, kind TEXT,
        title TEXT, body TEXT, read INTEGER DEFAULT 0, created_at TEXT)""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS job_updates (
        id INTEGER PRIMARY KEY AUTOINCREMENT, txn_id INTEGER, username TEXT,
        text TEXT, image_file_id TEXT, source TEXT DEFAULT 'customer',
        status TEXT DEFAULT 'Pending', created_at TEXT, published_until TEXT)""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS reactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT, target_type TEXT, target_id INTEGER,
        username TEXT, reaction TEXT, created_at TEXT)""")
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_reaction ON reactions (target_type, target_id, username)")
    cursor.execute("""CREATE TABLE IF NOT EXISTS login_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, logged_at TEXT)""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS admin_settings (
        key TEXT PRIMARY KEY, value TEXT)""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS job_availability (
        job_key TEXT PRIMARY KEY, available INTEGER DEFAULT 1, reason TEXT DEFAULT '')""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS announcements (
        id INTEGER PRIMARY KEY AUTOINCREMENT, file_id TEXT, file_name TEXT,
        description TEXT, created_at TEXT)""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS tickets (
        id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, message TEXT,
        reply TEXT DEFAULT '', status TEXT DEFAULT 'Open',
        created_at TEXT, replied_at TEXT)""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS reviews (
        id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, txn_id INTEGER,
        rating INTEGER, comment TEXT, created_at TEXT)""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS order_photos (
        id INTEGER PRIMARY KEY AUTOINCREMENT, txn_id INTEGER, file_id TEXT,
        uploaded_at TEXT)""")
    cursor.execute("""CREATE TABLE IF NOT EXISTS shared_files (
        id INTEGER PRIMARY KEY AUTOINCREMENT, file_id TEXT, file_name TEXT,
        uploaded_by TEXT, uploaded_at TEXT)""")
    cursor.execute("CREATE TABLE IF NOT EXISTS payment_settings (method TEXT PRIMARY KEY, enabled INTEGER DEFAULT 1)")
    cursor.execute("INSERT OR IGNORE INTO admin_settings (key, value) VALUES ('test_mode', '0')")
    cursor.execute("INSERT OR IGNORE INTO admin_settings (key, value) VALUES ('attendance_vip_minutes', '5')")
    cursor.execute("INSERT OR IGNORE INTO admin_settings (key, value) VALUES ('attendance_normal_minutes', '10')")
    conn.commit()
    conn.close()


def get_conn():
    return sqlite3.connect(DATABASE_FILE, timeout=15)


def admin_ok(token):
    return bool(ADMIN_TOKENS) and token in ADMIN_TOKENS


def now_str():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def notify(username, kind, title, body):
    conn = get_conn()
    conn.execute("INSERT INTO notifications (username, kind, title, body, created_at) VALUES (?,?,?,?,?)",
               (username, kind, title, body, now_str()))
    conn.commit()
    conn.close()


def notify_all(title, body):
    conn = get_conn()
    users = [r[0] for r in conn.execute("SELECT username FROM users").fetchall()]
    conn.close()
    for u in users:
        notify(u, 'announcement', title, body)


def compute_job_price(job_type, params):
    copies = params.get('copies', 1)
    if not isinstance(copies, int) or copies < 1 or copies > 1000000:
        return None
    if job_type.startswith("Sticker"):
        return float(params.get('w', 0)) * float(params.get('h', 0)) * 250 * copies
    if job_type.startswith("Banner"):
        return float(params.get('w', 0)) * float(params.get('h', 0)) * float(params.get('rate', 0)) * copies
    if job_type.startswith("Mug"):
        return float(params.get('unit', 0)) * copies
    if job_type.startswith("Fixed"):
        return float(params.get('price', 0)) * copies
    if job_type.startswith("Typing"):
        return float(params.get('rate', 0)) * float(params.get('pages', 0)) * copies
    if job_type.startswith("Envelope Design"):
        dims = ENVELOPE_DIMENSIONS.get(params.get('size', ''))
        if dims is None:
            return None
        rate = DESIGN_RATE_DESIGNED if params.get('design') == 'yes' else DESIGN_RATE_NOT_DESIGNED
        return (dims[0] * dims[1] / 144) * rate * copies
    if job_type.startswith("Card Design"):
        dims = CARD_DIMENSIONS.get(params.get('size', ''))
        if dims is None:
            return None
        rate = DESIGN_RATE_DESIGNED if params.get('design') == 'yes' else DESIGN_RATE_NOT_DESIGNED
        return (dims[0] * dims[1] / 144) * rate * copies
    return None

@app.route('/api/register', methods=['POST'])
def register():
    data = request.get_json(silent=True) or {}
    username = (data.get('username') or '').strip().lower()
    password = data.get('password') or ''
    nickname = (data.get('nickname') or '').strip()
    if len(nickname) < 6:
        return jsonify({"message": "Nickname must be 6 letters or more."}), 400
    if not username or not password or not nickname.isalpha():
        return jsonify({"message": "Username, password and a valid nickname are required."}), 400
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT username FROM users WHERE username = ?", (username,))
    if cur.fetchone():
        conn.close()
        return jsonify({"message": "Username already registered."}), 400
    cur.execute("SELECT nickname FROM users WHERE nickname = ?", (nickname,))
    if cur.fetchone():
        conn.close()
        return jsonify({"message": "Nickname already taken."}), 400
    hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    cur.execute("""INSERT INTO users (username, password_hash, nickname, first_name,
        last_name, sex, registered_at) VALUES (?,?,?,?,?,?,?)""",
        (username, hashed, nickname, (data.get('first_name') or '').strip(),
         (data.get('last_name') or '').strip(), (data.get('sex') or '').strip(), now_str()))
    conn.commit()
    conn.close()
    return jsonify({"message": "FodaKem VIP Profile Formed Successfully!"}), 200


@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json(silent=True) or {}
    raw = (data.get('username') or '').strip()
    ident = raw.lower()
    password = data.get('password') or ''
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT username, password_hash FROM users WHERE username = ? OR nickname = ? COLLATE NOCASE", (ident, raw))
    row = cur.fetchone()
    conn.close()
    if row and bcrypt.checkpw(password.encode('utf-8'), row[1].encode('utf-8')):
        user = row[0]
        conn = get_conn()
        conn.execute("INSERT INTO login_log (username, logged_at) VALUES (?,?)", (user, now_str()))
        conn.commit()
        conn.close()
        return jsonify({"message": "Access Verified! Loading panel...", "username": user}), 200
    return jsonify({"message": "Error: Invalid entry credentials. Access Denied."}), 401


@app.route('/api/my-profile', methods=['GET'])
def my_profile():
    username = (request.args.get('user') or '').strip().lower()
    conn = get_conn()
    row = conn.execute("SELECT username, nickname, first_name, last_name, sex FROM users WHERE username = ?",
                    (username,)).fetchone()
    conn.close()
    if not row:
        return jsonify({"message": "No such user."}), 404
    return jsonify({"username": row[0], "nickname": row[1], "first_name": row[2],
                   "last_name": row[3], "sex": row[4]}), 200


@app.route('/api/check-expiry', methods=['GET'])
def check_expiry():
    username = (request.args.get('user') or '').strip().lower()
    conn = get_conn()
    row = conn.execute("SELECT tier, valid_until FROM vip_cards WHERE username = ?", (username,)).fetchone()
    conn.close()
    if not row:
        return jsonify({"status": "active", "has_card": False}), 200
    tier, valid_until = row
    days = VIP_TIER_VALIDITY_DAYS.get(tier, 0)
    try:
        issued = datetime.datetime.strptime(valid_until[:10], "%Y-%m-%d")
        expires = issued + datetime.timedelta(days=days)
        if datetime.datetime.now() > expires:
            return jsonify({"status": "expired", "has_card": True}), 200
    except (TypeError, ValueError):
        pass
    return jsonify({"status": "active", "has_card": True, "expires": valid_until}), 200


@app.route('/api/config', methods=['GET'])
def paystack_config():
    return jsonify({"paystack_public_key": PAYSTACK_PUBLIC_KEY,
                   "paystack_subaccount": PAYSTACK_SUBACCOUNT})


@app.route('/api/payment-methods', methods=['GET'])
def payment_methods():
    conn = get_conn()
    rows = dict(conn.execute("SELECT method, enabled FROM payment_settings").fetchall())
    conn.close()
    return jsonify({
        "paystack": bool(rows.get("paystack", 1)),
        "cash": bool(rows.get("cash", 1)),
        "transfer": bool(rows.get("transfer", 1)),
    })

def paid_in_paystack(ref):
    if not PAYSTACK_SECRET_KEY:
        return None
    try:
        res = requests.get(f"https://api.paystack.co/transaction/verify/{ref}",
                        headers={"Authorization": f"Bearer {PAYSTACK_SECRET_KEY}"}, timeout=15)
        body = res.json()
    except Exception:
        return None
    if body.get('status') and body.get('data', {}).get('status') == 'success':
        return body['data']
    return None


def vip_active(username):
    conn = get_conn()
    row = conn.execute("SELECT 1 FROM vip_cards WHERE username = ? LIMIT 1", (username,)).fetchone()
    conn.close()
    return row is not None


def sub_uses_left(username):
    conn = get_conn()
    row = conn.execute("SELECT uses_count, carry_count FROM sub_cards WHERE username = ? ORDER BY registered_at DESC LIMIT 1",
                    (username,)).fetchone()
    conn.close()
    if not row:
        return 0
    return max(0, row[1] + SUBS_PER_WEEK - row[0])


def consume_sub_use(username):
    conn = get_conn()
    row = conn.execute("SELECT sub_id FROM sub_cards WHERE username = ? ORDER BY registered_at DESC LIMIT 1",
                    (username,)).fetchone()
    if not row:
        conn.close()
        return False
    conn.execute("UPDATE sub_cards SET uses_count = uses_count + 1 WHERE sub_id = ?", (row[0],))
    conn.commit()
    conn.close()
    return True


def negotiation_blocked(username, job_type):
    conn = get_conn()
    row = conn.execute("""SELECT negotiation FROM transactions
        WHERE username = ? AND job_type = ? AND status = 'Negotiation Pending'
        ORDER BY id DESC LIMIT 1""", (username, job_type)).fetchone()
    conn.close()
    if not row:
        return False
    try:
        data = json.loads(row[0] or '{}')
    except ValueError:
        return True
    return data.get('last_price') is None


def start_negotiation_route():
    data = request.get_json(silent=True) or {}
    username = (data.get('user') or '').strip().lower()
    job_type = data.get('job_type') or ''
    params = data.get('params') or {}
    notes = str(data.get('notes') or '')
    category = str(data.get('notes_category') or '')
    surcharge_rate = float(data.get('surcharge_rate') or 0)
    if not username or not job_type:
        return jsonify({"message": "Missing order details."}), 400
    actual = compute_job_price(job_type, params)
    if actual is None:
        return jsonify({"message": "Invalid job parameters supplied."}), 400
    total = actual * (1 + surcharge_rate)
    ts = now_str()
    conn = get_conn()
    conn.execute("""INSERT INTO transactions
        (username, job_type, actual_price, vip_money, total_price, status,
         production_status, timestamp, file_id, method, is_vip, negotiation)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (username, job_type, actual, actual * surcharge_rate, total,
         'Negotiation Pending', 'Awaiting Production', ts, data.get('file_id') or '',
         '', 0, json.dumps({"message": notes, "notes_category": category, "last_price": None})))
    draft_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    conn.commit()
    conn.close()
    return jsonify({"draft_id": draft_id}), 200


@app.route('/api/start-negotiation', methods=['POST'])
def start_negotiation():
    return start_negotiation_route()


@app.route('/api/draft-status/<int:draft_id>', methods=['GET'])
def draft_status(draft_id):
    conn = get_conn()
    row = conn.execute("SELECT negotiation FROM transactions WHERE id = ?", (draft_id,)).fetchone()
    conn.close()
    if not row:
        return jsonify({"message": "Not found."}), 404
    try:
        data = json.loads(row[0] or '{}')
    except ValueError:
        data = {}
    if data.get('last_price') is not None:
        return jsonify({"status": "answered", "last_price": data['last_price']}), 200
    return jsonify({"status": "pending"}), 200


def create_txn(username, job_type, actual_price, vip_money, total_price, status, timestamp,
             paystack_ref='', file_id='', method='', production_status='Awaiting Production'):
    has_vip = 1 if vip_active(username) else 0
    conn = get_conn()
    conn.execute("""INSERT INTO transactions
        (username, job_type, actual_price, vip_money, total_price, status, timestamp,
         paystack_ref, file_id, method, production_status, is_vip)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (username, job_type, actual_price, vip_money, total_price, status, timestamp,
         paystack_ref, file_id, method, production_status, has_vip))
    conn.commit()
    conn.close()


@app.route('/api/checkout-live', methods=['POST'])
def checkout_live():
    data = request.get_json(silent=True) or {}
    username = (data.get('user') or '').strip().lower()
    job_type = data.get('job_type') or ''
    params = data.get('params') or {}
    file_id = data.get('file_id') or ''
    ref = data.get('paystack_ref') or ''
    skip_payment = (str(request.headers.get('X-Test-Mode', '0')) == '1' or request.args.get('test') == '1') and username == TEST_ACCOUNT['username']
    skip_payment = skip_payment or skip_test_payment(username)
    if not username or not job_type or not ref:
        return jsonify({"message": "Missing order details."}), 400
    actual = compute_job_price(job_type, params)
    if actual is None:
        return jsonify({"message": "Invalid job parameters supplied."}), 400
    if negotiation_blocked(username, job_type):
        return jsonify({"message": "A price decision is awaited. Please wait for the admin's answer."}), 409
    # If a negotiation was answered for this exact job, use the negotiated price
    conn = get_conn()
    nrow = conn.execute("""SELECT negotiation FROM transactions
        WHERE username = ? AND job_type = ? AND status = 'Negotiation Pending'
        ORDER BY id DESC LIMIT 1""", (username, job_type)).fetchone()
    conn.close()
    if nrow:
        try:
            ndata = json.loads(nrow[0] or '{}')
        except ValueError:
            ndata = {}
        if ndata.get('last_price') is not None:
            actual = float(ndata['last_price'])
    if not skip_payment:
        verified = paid_in_paystack(ref)
        if not verified:
            return jsonify({"message": "Payment could not be verified."}), 400
        if int(verified.get('amount') or 0) + 50 < actual * 100:
            return jsonify({"message": "Underpayment detected."}), 400
    vip_rate = float(data.get('surcharge_rate') or 0)
    if vip_rate < 0 and sub_uses_left(username) <= 0:
        return jsonify({"message": "You have used all your Sub Card uses this week."}), 400
    vip_money = actual * vip_rate
    total = actual + vip_money
    ts = now_str()
    create_txn(username, job_type, actual, vip_money, total,
              'Payment Confirmed / Approved for Production', ts, ref, file_id, 'paystack')
    if vip_rate < 0:
        consume_sub_use(username)
    # Mark any negotiation draft for this job as completed
    conn = get_conn()
    conn.execute("""UPDATE transactions SET status = 'Negotiation Completed'
        WHERE username = ? AND job_type = ? AND status = 'Negotiation Pending'""",
        (username, job_type))
    conn.commit()
    conn.close()
    notify(username, 'order', 'Payment confirmed!',
           f'{job_type} is confirmed. Total: ₦{total:,.2f}.')
    send_server_alert('New paid order', f'{username} paid for {job_type} (₦{total:,.2f}).')
    return jsonify({"redirect": "/dashboard.html?tab=transact",
                   "message": f"Payment verified! Total: ₦{total:,.2f}."}), 200


@app.route('/api/cash-order', methods=['POST'])
def cash_order():
    data = request.get_json(silent=True) or {}
    username = (data.get('user') or '').strip().lower()
    job_type = data.get('job_type') or ''
    params = data.get('params') or {}
    file_id = data.get('file_id') or ''
    if not username or not job_type:
        return jsonify({"message": "Missing order details."}), 400
    actual = compute_job_price(job_type, params)
    if actual is None:
        return jsonify({"message": "Invalid job parameters supplied."}), 400
    if negotiation_blocked(username, job_type):
        return jsonify({"message": "A price decision is awaited. Please wait for the admin's answer."}), 409
    vip_rate = float(data.get('surcharge_rate') or 0)
    if vip_rate < 0 and sub_uses_left(username) <= 0:
        return jsonify({"message": "You have used all your Sub Card uses this week."}), 400
    total = actual * (1 + vip_rate)
    ts = now_str()
    create_txn(username, job_type, actual, actual * vip_rate, total,
              'Cash Payment Pending Confirmation', ts, file_id=file_id, method='cash')
    if vip_rate < 0:
        consume_sub_use(username)
    notify(username, 'order', 'Cash order placed',
           'Your order is awaiting admin confirmation. Total: ₦%.2f.' % total)
    send_server_alert('New cash order', f'{username} placed {job_type} (₦{total:,.2f}) - cash pending.')
    return jsonify({"message": "Order placed! Awaiting admin confirmation.",
                  "redirect": "/dashboard.html?tab=transact"}), 200


TRANSFER_ACCOUNTS = [
    {"name": "Moniepoint", "account_name": "FODAKEM UNIQUE GLOBAL RESOURCES LIMITED", "number": "8308018146"},
    {"name": "Opay", "account_name": "FATORE OLADELE ADEBAYO", "number": "8065867966"},
    {"name": "Wema Bank", "account_name": "FATORE OLADELE ADEBAYO", "number": "0235640136"},
]


@app.route('/api/transfer-order', methods=['POST'])
def transfer_order():
    data = request.get_json(silent=True) or {}
    username = (data.get('user') or '').strip().lower()
    job_type = data.get('job_type') or ''
    params = data.get('params') or {}
    account = data.get('account') or {}
    if not username or not job_type:
        return jsonify({"message": "Missing order details."}), 400
    actual = compute_job_price(job_type, params)
    if actual is None:
        return jsonify({"message": "Invalid job parameters supplied."}), 400
    if negotiation_blocked(username, job_type):
        return jsonify({"message": "A price decision is awaited. Please wait for the admin's answer."}), 409
    vip_rate = float(data.get('surcharge_rate') or 0)
    if vip_rate < 0 and sub_uses_left(username) <= 0:
        return jsonify({"message": "You have used all your Sub Card uses this week."}), 400
    total = actual * (1 + vip_rate)
    chosen = [a for a in TRANSFER_ACCOUNTS if a['number'] == str(account.get('number') or '')]
    if not chosen:
        return jsonify({"message": "Choose one of the approved bank accounts."}), 400
    ts = now_str()
    create_txn(username, job_type, actual, actual * vip_rate, total,
              'Transfer Pending Approval', ts, method='transfer',
              production_status='Awaiting Production')
    conn = get_conn()
    conn.execute("UPDATE transactions SET notes = ? WHERE username = ? AND job_type = ? AND timestamp = ?",
               (json.dumps({"account": chosen[0]['name']}), username, job_type, ts))
    conn.commit()
    conn.close()
    send_server_alert('New transfer order',
                      f'{username} placed {job_type} via {chosen[0]["name"]} - awaiting approval.')
    return jsonify({"message": "Transfer order received. Awaiting admin approval.",
                   "redirect": "/dashboard.html?tab=transact"}), 200


@app.route('/api/admin/approve-transfer', methods=['POST'])
def admin_approve_transfer():
    token = request.args.get('token') or request.headers.get('X-Admin-Token') or ''
    if not admin_ok(token):
        return jsonify({"message": "Unauthorized."}), 401
    data = request.get_json(silent=True) or {}
    txn_id = data.get('id')
    conn = get_conn()
    owner = conn.execute("SELECT username FROM transactions WHERE id = ?", (txn_id,)).fetchone()
    conn.execute("UPDATE transactions SET status = 'Awaiting Production' WHERE id = ? AND status = 'Transfer Pending Approval'",
               (txn_id,))
    conn.commit()
    conn.close()
    if owner:
        notify(owner[0], 'payment', 'Transfer approved', 'Your bank transfer was approved. Your order is now in production.')
    return jsonify({"message": "Transfer approved."}), 200


@app.route('/api/admin/reject-transfer', methods=['POST'])
def admin_reject_transfer():
    token = request.args.get('token') or request.headers.get('X-Admin-Token') or ''
    if not admin_ok(token):
        return jsonify({"message": "Unauthorized."}), 401
    data = request.get_json(silent=True) or {}
    txn_id = data.get('id')
    conn = get_conn()
    owner = conn.execute("SELECT username FROM transactions WHERE id = ?", (txn_id,)).fetchone()
    conn.execute("UPDATE transactions SET status = 'Cancelled' WHERE id = ? AND status = 'Transfer Pending Approval'",
               (txn_id,))
    conn.commit()
    conn.close()
    if owner:
        notify(owner[0], 'payment', 'Transfer rejected', 'Your bank transfer was not approved. Please contact support.')
    return jsonify({"message": "Transfer rejected."}), 200

def vip_tier_validity(tier):
    return datetime.timedelta(days=VIP_TIER_VALIDITY_DAYS.get(tier, 30))


@app.route('/api/vip-checkout', methods=['POST'])
def vip_checkout():
    form = request.form
    username = (form.get('username') or '').strip().lower()
    name = form.get('name') or ''
    phone = form.get('phone') or ''
    sex = form.get('sex') or ''
    tier = form.get('tier') or ''
    buy_sub = form.get('buy_sub') in ('1', 'true', 'True')
    if tier not in VIP_TIER_PRICES:
        return jsonify({"message": "Invalid VIP tier."}), 400
    expected = VIP_TIER_PRICES[tier] + (SUB_CARD_PRICE - 500 if buy_sub else 0)
    ref = form.get('paystack_ref') or ''
    if not username or not ref:
        return jsonify({"message": "Missing details."}), 400
    if not skip_test_payment(username):
        verified = paid_in_paystack(ref)
        if not verified:
            return jsonify({"message": "Payment could not be verified."}), 400
        if int(verified.get('amount') or 0) + 50 < expected * 100:
            return jsonify({"message": "Underpayment detected."}), 400
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM vip_cards")
    count = cur.fetchone()[0] + 1
    card_id = f"{count:03d}"
    issued = form.get('issue_date') or datetime.datetime.now().strftime("%Y-%m-%dT%H:%M")
    valid_until = (datetime.datetime.fromisoformat(issued[:19]) + vip_tier_validity(tier)).strftime("%Y-%m-%d")
    cur.execute("""INSERT INTO vip_cards (card_id, username, name, phone, sex, tier,
        issue_date, valid_until, qr_path) VALUES (?,?,?,?,?,?,?,?,'')""",
        (card_id, username, name, phone, sex, tier, issued[:10], valid_until))
    if buy_sub:
        sub_id = next_sub_id()
        cur.execute("""INSERT INTO sub_cards
            (sub_id, username, vip_card_id, tag, registered_at, valid_until)
            VALUES (?,?,?,?,?,?)""",
            (sub_id, username, card_id, tier,
             datetime.datetime.now().strftime("%Y-%m-%d"), valid_until))
    conn.commit()
    conn.close()
    notify(username, 'card', 'VIP card active!',
           f'Your {tier} VIP card is now active. Card #{card_id}.')
    # Record the VIP card purchase so the admin can see it
    create_txn(username, f"VIP Card ({tier})", expected, 0.0, expected,
              'Payment Confirmed / Approved for Production', now_str(), ref, '', 'paystack')
    send_server_alert('VIP card purchased', f'{username} bought a {tier} VIP card (#{card_id}).')
    return jsonify({"redirect": "/dashboard.html?tab=transact", "card_id": card_id,
                   "message": f"VIP card #{card_id} is now active."}), 200


@app.route('/api/vip-cash-order', methods=['POST'])
def vip_cash_order():
    form = request.form
    username = (form.get('username') or '').strip().lower()
    name = form.get('name') or ''
    phone = form.get('phone') or ''
    sex = form.get('sex') or ''
    tier = form.get('tier') or ''
    buy_sub = form.get('buy_sub') in ('1', 'true', 'True')
    if tier not in VIP_TIER_PRICES:
        return jsonify({"message": "Invalid VIP tier."}), 400
    expected = VIP_TIER_PRICES[tier] + (SUB_CARD_PRICE - 500 if buy_sub else 0)
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM vip_cards")
    count = cur.fetchone()[0] + 1
    card_id = f"{count:03d}"
    valid_until = (datetime.datetime.now() +
                  vip_tier_validity(tier)).strftime("%Y-%m-%d")
    cur.execute("""INSERT INTO vip_cards (card_id, username, name, phone, sex, tier,
        issue_date, valid_until, qr_path) VALUES (?,?,?,?,?,?,?,?,'')""",
        (card_id, username, name, phone, sex, tier,
         datetime.datetime.now().strftime("%Y-%m-%d"), valid_until))
    if buy_sub:
        sub_id = next_sub_id()
        cur.execute("""INSERT INTO sub_cards
            (sub_id, username, vip_card_id, tag, registered_at, valid_until)
            VALUES (?,?,?,?,?,?)""",
            (sub_id, username, card_id, tier,
             datetime.datetime.now().strftime("%Y-%m-%d"), valid_until))
    conn.commit()
    conn.close()
    notify(username, 'card', 'VIP card active!',
           f'Your {tier} VIP card is now active. Card #{card_id} (awaiting payment).')
    # Record the VIP card purchase so the admin can see it
    create_txn(username, f"VIP Card ({tier})", expected, 0.0, expected,
              'Cash Payment Pending Confirmation', now_str(), '', '', 'cash')
    send_server_alert('VIP card cash order', f'{username} created a {tier} VIP card (#{card_id}) - awaiting cash confirmation.')
    return jsonify({"card_id": card_id,
                   "message": "VIP card created! Awaiting admin confirmation."}), 200


def next_sub_id():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM sub_cards")
    count = cur.fetchone()[0] + 1
    conn.close()
    return f"PRY {count:04d}"


def skip_test_payment(username=''):
    # Only the test account may skip payment, and only while test mode is ON
    return bool(is_test_mode()) and (username or '').strip().lower() == TEST_ACCOUNT['username']


def is_test_mode():
    conn = get_conn()
    row = conn.execute("SELECT value FROM admin_settings WHERE key = 'test_mode'").fetchone()
    conn.close()
    return row and row[0] == '1'


def send_server_alert(title, body):
    """Email/SMS alert to the admin. Needs env vars:
       SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, ALERT_EMAIL
       SMS_API_KEY, SMS_SENDER, ALERT_PHONE"""
    sent = False
    smtp_host = os.environ.get("SMTP_HOST")
    smtp_user = os.environ.get("SMTP_USER")
    smtp_pass = os.environ.get("SMTP_PASS")
    alert_email = os.environ.get("ALERT_EMAIL")
    if smtp_host and smtp_user and alert_email:
        try:
            import smtplib
            from email.mime.text import MIMEText
            msg = MIMEText(body)
            msg['Subject'] = title
            msg['From'] = smtp_user
            msg['To'] = alert_email
            server = smtplib.SMTP(smtp_host, int(os.environ.get("SMTP_PORT", 587)))
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, [alert_email], msg.as_string())
            server.quit()
            sent = True
        except Exception as exc:
            print(f"EMAIL ALERT FAILED: {exc}")
    sms_key = os.environ.get("SMS_API_KEY")
    alert_phone = os.environ.get("ALERT_PHONE")
    if sms_key and alert_phone:
        try:
            requests.post("https://api.termii.com/api/sms/send",
                json={"api_key": sms_key, "to": alert_phone,
                      "from": os.environ.get("SMS_SENDER") or "FodaKem",
                      "sms": f"{title}: {body}", "type": "plain", "channel": "generic"},
                timeout=15)
            sent = True
        except Exception as exc:
            print(f"SMS ALERT FAILED: {exc}")
    return sent


@app.route('/api/admin/test-alert', methods=['POST'])
def test_alert():
    token = request.args.get('token') or request.headers.get('X-Admin-Token') or ''
    if not admin_ok(token):
        return jsonify({"message": "Unauthorized."}), 401
    ok = send_server_alert("FodaKem VIP test alert", "This is a test alert from your admin panel.")
    return jsonify({"message": "Alert sent!" if ok else "Alert not configured - set env vars on Render."}), 200


@app.route('/api/negotiate', methods=['POST'])
def negotiate():
    data = request.get_json(silent=True) or {}
    username = (data.get('user') or '').strip().lower()
    txn_id = data.get('txn_id')
    message = (data.get('message') or '').strip()
    if not username or not txn_id or not message:
        return jsonify({"message": "Missing negotiation request."}), 400
    conn = get_conn()
    conn.execute("UPDATE transactions SET negotiation = ? WHERE id = ?",
               (json.dumps({"message": message, "closed": False}), txn_id))
    conn.commit()
    conn.close()
    return jsonify({"message": "Your request was received by the admin."}), 200


@app.route('/api/admin/set-price', methods=['POST'])
def admin_set_price():
    token = request.args.get('token') or request.headers.get('X-Admin-Token') or ''
    if not admin_ok(token):
        return jsonify({"message": "Unauthorized."}), 401
    data = request.get_json(silent=True) or {}
    reason = (data.get('reason') or '').strip()
    if not reason:
        return jsonify({"message": "A reason is required for price changes."}), 400
    mode = data.get('mode') or 'percent'
    value = float(data.get('value') or 0)
    if value == 0:
        return jsonify({"message": "Choose a new price (percent or amount)."}), 400
    conn = get_conn()
    cur = conn.cursor()
    target = data.get('txn_id')
    if target is not None and str(target).strip() != '':
        target = str(target).strip()
        if target.isdigit():
            cur.execute("SELECT * FROM transactions WHERE id = ?", (int(target),))
            rows = cur.fetchall()
        else:
            # treat as username or nickname
            conn2 = get_conn()
            urow = conn2.execute("SELECT username FROM users WHERE username = ? OR nickname = ? COLLATE NOCASE",
                                 (target.lower(), target)).fetchone()
            conn2.close()
            if not urow:
                conn.close()
                return jsonify({"message": "No such customer."}), 404
            cur.execute("SELECT * FROM transactions WHERE username = ? ORDER BY id DESC", (urow[0],))
            rows = cur.fetchall()
        if not rows:
            conn.close()
            return jsonify({"message": "Order not found."}), 404
        affected = [dict(zip([c[0] for c in cur.description], r)) for r in rows]
    else:
        affected = [dict(r) for r in cur.execute(
            "SELECT * FROM transactions WHERE status NOT LIKE '%Pending%' ORDER BY id DESC")]
    for txn in affected:
        old = float(txn['actual_price'] or 0)
        if mode == 'percent':
            new = old * (1 + value / 100.0)
        else:
            new = value
        vip_money = float(txn['vip_money'] or 0)
        total = new * (1 + (vip_money / old if old else 0))
        try:
            ndata = json.loads(txn['negotiation'] or '{}') or {}
        except ValueError:
            ndata = {}
        ndata['last_price'] = new
        ndata['closed'] = True
        conn.execute("UPDATE transactions SET actual_price = ?, total_price = ?, negotiation = ? WHERE id = ?",
                   (new, total, json.dumps(ndata), txn['id']))
    conn.commit()
    conn.close()
    # Tell every affected customer immediately, with the reason
    for u in {t['username'] for t in affected if t.get('username')}:
        notify(u, 'price', 'Price update',
               f'Your price was changed by {value:g}% . Reason: {reason}')
    return jsonify({"message": "Price updated."}), 200

@app.route('/api/my-notifications', methods=['GET'])
def my_notifications():
    username = (request.args.get('user') or '').strip().lower()
    conn = get_conn()
    rows = conn.execute("SELECT id, kind, title, body, read FROM notifications WHERE username = ? ORDER BY id DESC LIMIT 50",
                     (username,)).fetchall()
    conn.commit(); conn.close()
    out = []
    for r in rows:
        out.append({"id": r[0], "kind": r[1], "title": r[2], "body": r[3], "read": r[4]})
    return jsonify(out), 200


@app.route('/api/mark-notifications-read', methods=['POST'])
def mark_notifications_read():
    data = request.get_json(silent=True) or {}
    username = (data.get('user') or '').strip().lower()
    conn = get_conn()
    conn.execute("UPDATE notifications SET read = 1 WHERE username = ? AND read = 0", (username,))
    conn.commit(); conn.close()
    return jsonify({"message": "ok"}), 200


def attendance_notice_text(username):
    conn = get_conn()
    vip = conn.execute("SELECT COUNT(*) FROM vip_cards WHERE username = ?", (username,)).fetchone()[0]
    conn.close()
    conn = get_conn()
    tier = conn.execute("SELECT tier FROM vip_cards WHERE username = ? ORDER BY card_id DESC LIMIT 1", (username,)).fetchone()
    conn.close()
    conn = get_conn()
    minutes = 10
    if tier:
        minutes = 5
    return minutes


@app.route('/api/admin/attendance', methods=['GET'])
def admin_attendance_get():
    token = request.args.get('token') or request.headers.get('X-Admin-Token') or ''
    if not admin_ok(token):
        return jsonify({"message": "Unauthorized."}), 401
    conn = get_conn()
    rows = dict(conn.execute("SELECT key, value FROM admin_settings WHERE key LIKE 'attendance_%'").fetchall())
    conn.close()
    return jsonify({
        "vip_minutes": int(rows.get("attendance_vip_minutes", 5)),
        "normal_minutes": int(rows.get("attendance_normal_minutes", 10)),
    }), 200


@app.route('/api/admin/attendance', methods=['POST'])
def admin_attendance_post():
    token = request.args.get('token') or request.headers.get('X-Admin-Token') or ''
    if not admin_ok(token):
        return jsonify({"message": "Unauthorized."}), 401
    data = request.get_json(silent=True) or {}
    vip = max(1, min(10080, int(data.get('vip_minutes') or 5)))
    normal = max(1, min(10080, int(data.get('normal_minutes') or 10)))
    conn = get_conn()
    conn.execute("INSERT INTO admin_settings (key, value) VALUES ('attendance_vip_minutes', ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (str(vip),))
    conn.execute("INSERT INTO admin_settings (key, value) VALUES ('attendance_normal_minutes', ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (str(normal),))
    conn.commit()
    conn.close()
    return jsonify({"message": "Reply times updated."}), 200


@app.route('/api/job-update', methods=['POST'])
def create_job_update():
    data = request.get_json(silent=True) or {}
    username = (data.get('user') or '').strip().lower()
    txn_id = data.get('txn_id')
    text = (data.get('text') or '').strip()
    if not username or not txn_id or not text:
        return jsonify({"message": "Missing update details."}), 400
    if len(text.split()) > 1000:
        return jsonify({"message": "Too many words."}), 400
    now = datetime.datetime.now()
    conn = get_conn()
    if now.hour >= 18 or now.hour < 9:
        notice = ("We have closed for the day. Come at 09:30 tomorrow.")
    else:
        vip = conn.execute("SELECT tier FROM vip_cards WHERE username = ? ORDER BY card_id DESC LIMIT 1",
                        (username,)).fetchone()
        conn2 = get_conn()
        vip_mins = conn2.execute("SELECT value FROM admin_settings WHERE key = 'attendance_vip_minutes'").fetchone()
        normal_mins = conn2.execute("SELECT value FROM admin_settings WHERE key = 'attendance_normal_minutes'").fetchone()
        conn2.close()
        minutes = int(vip_mins[0] if vip_mins else 5) if vip else int(normal_mins[0] if normal_mins else 10)
        notice = f"We will attend to this in the next {minutes} minutes."
    conn.execute("""INSERT INTO job_updates (txn_id, username, text, source, status, created_at)
        VALUES (?,?,?,'customer','Pending',?)""",
        (txn_id, username, text, now_str()))
    conn.commit()
    conn.close()
    notify(username, 'update', 'Update received',
           f'{notice} An admin will review it before it is published.')
    return jsonify({"message": "Update sent for admin approval."}), 200


@app.route('/api/my-job-updates', methods=['GET'])
def my_job_updates():
    username = (request.args.get('user') or '').strip().lower()
    conn = get_conn()
    rows = conn.execute("""SELECT id, txn_id, text, status, created_at FROM job_updates
        WHERE username = ? ORDER BY id DESC""", (username,)).fetchall()
    conn.commit(); conn.close()
    return jsonify([dict(zip(['id', 'txn_id', 'text', 'status', 'created_at'], r)) for r in rows]), 200


@app.route('/api/admin/job-updates', methods=['GET'])
def admin_job_updates():
    token = request.args.get('token') or request.headers.get('X-Admin-Token') or ''
    if not admin_ok(token):
        return jsonify({"message": "Unauthorized."}), 401
    conn = get_conn()
    rows = conn.execute("""SELECT id, txn_id, username, text, source, status, created_at
        FROM job_updates ORDER BY id DESC LIMIT 100""").fetchall()
    conn.commit(); conn.close()
    out = []
    for r in rows:
        out.append({"id": r[0], "txn_id": r[1], "username": r[2], "text": r[3],
                   "source": r[4], "status": r[5], "created_at": r[6]})
    return jsonify(out), 200


@app.route('/api/admin/job-update-action', methods=['POST'])
def admin_job_update_action():
    token = request.args.get('token') or request.headers.get('X-Admin-Token') or ''
    if not admin_ok(token):
        return jsonify({"message": "Unauthorized."}), 401
    data = request.get_json(silent=True) or {}
    action = data.get('action') or ''
    if action not in ('approve', 'reject'):
        return jsonify({"message": "Invalid action."}), 400
    job_id = data.get('id')
    if action == 'approve':
        until = (datetime.datetime.now() + datetime.timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
        conn = get_conn()
        conn.execute("UPDATE job_updates SET status = 'Approved', published_until = ? WHERE id = ?",
                   (until, job_id))
        conn.commit()
        owner = conn.execute("SELECT username FROM job_updates WHERE id = ?", (job_id,)).fetchone()
        conn.close()
        if owner:
            notify(owner[0], 'update', 'Update published!',
                   'Your update is now visible on the dashboard.')
    else:
        conn = get_conn()
        conn.execute("UPDATE job_updates SET status = 'Rejected' WHERE id = ?", (job_id,))
        conn.commit(); conn.close()
    return jsonify({"message": "done"}), 200


@app.route('/api/reaction', methods=['POST'])
def add_reaction():
    data = request.get_json(silent=True) or {}
    username = (data.get('user') or '').strip().lower()
    target_type = data.get('target_type') or ''
    target_id = data.get('target_id')
    reaction = (data.get('reaction') or 'ðŸ‘').strip()
    if not username or target_id is None:
        return jsonify({"message": "Missing reaction."}), 400
    conn = get_conn()
    conn.execute("""INSERT INTO reactions (target_type, target_id, username, reaction, created_at)
        VALUES (?,?,?,?,?)
        ON CONFLICT(target_type, target_id, username) DO UPDATE SET reaction = excluded.reaction,
        created_at = excluded.created_at""",
        (target_type, target_id, username, reaction, now_str()))
    conn.commit(); conn.close()
    # Let the owner know a fellow customer reacted
    if target_type == 'update':
        conn2 = get_conn()
        owner = conn2.execute("SELECT username FROM job_updates WHERE id = ?", (target_id,)).fetchone()
        conn2.close()
        if owner and owner[0] != username:
            notify(owner[0], 'reaction', 'New reaction',
                   f'{username} reacted {reaction} to your update.')
    return jsonify({"message": "Reaction recorded."}), 200


@app.route('/api/reactions', methods=['GET'])
def list_reactions():
    target_type = request.args.get('target_type') or ''
    conn = get_conn()
    rows = conn.execute(
        "SELECT target_id, username, reaction FROM reactions WHERE target_type = ? ORDER BY id DESC",
        (target_type,)).fetchall()
    conn.commit(); conn.close()
    grouped = {}
    for r in rows:
        counts = grouped.setdefault(r[0], {})
        counts[r[2]] = counts.get(r[2], 0) + 1
    out = [{"target_id": tid, "counts": counts} for tid, counts in grouped.items()]
    return jsonify(out), 200

@app.route('/api/job-availability', methods=['GET'])
def job_availability():
    conn = get_conn()
    rows = {r[0]: {"available": bool(r[1]), "reason": r[2]} for r in conn.execute("SELECT job_key, available, reason FROM job_availability")}
    conn.close()
    return jsonify(rows), 200


@app.route('/api/admin/availability', methods=['POST'])
def admin_availability():
    token = request.args.get('token') or request.headers.get('X-Admin-Token') or ''
    if not admin_ok(token):
        return jsonify({"message": "Unauthorized."}), 401
    data = request.get_json(silent=True) or {}
    job_key = data.get('job_key') or ''
    if not job_key:
        return jsonify({"message": "Missing job key."}), 400
    conn = get_conn()
    conn.execute("""INSERT INTO job_availability (job_key, available, reason) VALUES (?,?,?)
        ON CONFLICT(job_key) DO UPDATE SET available = excluded.available, reason = excluded.reason""",
        (job_key, 1 if data.get('available', True) else 0, data.get('reason') or ''))
    conn.commit(); conn.close()
    if not data.get('available', True):
        notify_all('Service temporarily unavailable',
                   f'{job_key} is unavailable: {data.get("reason") or "no reason given"}')
    return jsonify({"message": "Availability updated."}), 200


@app.route('/api/admin/announcements', methods=['POST'])
def admin_announcements():
    token = request.args.get('token') or request.headers.get('X-Admin-Token') or ''
    if not admin_ok(token):
        return jsonify({"message": "Unauthorized."}), 401
    file = request.files.get('file')
    if not file or not file.filename:
        return jsonify({"message": "No file selected."}), 400
    description = (request.form.get('description') or '').strip()
    if not description:
        return jsonify({"message": "Description required."}), 400
    if len(description.split()) > 100:
        return jsonify({"message": "Too many words."}), 400
    file_id = uuid.uuid4().hex
    os.makedirs(ANNOUNCEMENTS_DIR, exist_ok=True)
    name = f"{file_id}_{secure_filename(file.filename) or 'news'}"
    file.save(os.path.join(ANNOUNCEMENTS_DIR, name))
    conn = get_conn()
    conn.execute("""INSERT INTO announcements (file_id, file_name, description, created_at)
        VALUES (?,?,?,?)""", (file_id, name, description, now_str()))
    conn.commit(); conn.close()
    # Let every customer know about the new update
    notify_all('New update posted', description[:120])
    return jsonify({"message": "News posted."}), 200


@app.route('/api/admin/announcements/<int:ann_id>', methods=['DELETE'])
def delete_announcement(ann_id):
    token = request.args.get('token') or request.headers.get('X-Admin-Token') or ''
    if not admin_ok(token):
        return jsonify({"message": "Unauthorized."}), 401
    conn = get_conn()
    row = conn.execute("SELECT file_id FROM announcements WHERE id = ?", (ann_id,)).fetchone()
    if not row:
        conn.close()
        return jsonify({"message": "Not found."}), 404
    conn.execute("DELETE FROM announcements WHERE id = ?", (ann_id,))
    conn.commit(); conn.close()
    return jsonify({"message": "Deleted."}), 200


@app.route('/api/announcements', methods=['GET'])
def get_announcements():
    conn = get_conn()
    rows = conn.execute("SELECT id, file_id, description, created_at FROM announcements ORDER BY id DESC LIMIT 20").fetchall()
    conn.commit(); conn.close()
    return jsonify([{"id": r[0], "file_id": r[1], "description": r[2], "created_at": r[3]} for r in rows]), 200


@app.route('/api/announcement-image/<file_id>', methods=['GET'])
def serve_announcement_image(file_id):
    if len(file_id) != 32:
        return jsonify({"message": "Invalid file id."}), 400
    for f in os.listdir(ANNOUNCEMENTS_DIR):
        if f.startswith(file_id + "_"):
            return send_from_directory(ANNOUNCEMENTS_DIR, f)
    return jsonify({"message": "Not found."}), 404


@app.route('/api/ticket', methods=['POST'])
def create_ticket():
    data = request.get_json(silent=True) or {}
    username = (data.get('username') or '').strip().lower()
    message = (data.get('message') or '').strip()
    if not username or not message:
        return jsonify({"message": "Missing message."}), 400
    conn = get_conn()
    conn.execute("INSERT INTO tickets (username, message, created_at) VALUES (?,?,?)",
               (username, message, now_str()))
    conn.commit(); conn.close()
    send_server_alert('New support message', f'{username}: {message[:120]}')
    return jsonify({"message": "Sent."}), 200


@app.route('/api/my-tickets', methods=['GET'])
def my_tickets():
    username = (request.args.get('user') or '').strip().lower()
    conn = get_conn()
    rows = conn.execute("SELECT * FROM tickets WHERE username = ? ORDER BY id DESC LIMIT 50", (username,)).fetchall()
    conn.commit(); conn.close()
    return jsonify([dict(zip(['id', 'message', 'reply', 'status', 'created_at'], r)) for r in rows]), 200


@app.route('/api/admin/tickets', methods=['GET'])
def admin_tickets():
    token = request.args.get('token') or request.headers.get('X-Admin-Token') or ''
    if not admin_ok(token):
        return jsonify({"message": "Unauthorized."}), 401
    conn = get_conn()
    rows = conn.execute("SELECT * FROM tickets ORDER BY id DESC LIMIT 100").fetchall()
    conn.commit(); conn.close()
    return jsonify([dict(zip(['id', 'username', 'message', 'reply', 'status', 'created_at'], r)) for r in rows]), 200


@app.route('/api/admin/ticket-reply', methods=['POST'])
def admin_ticket_reply():
    token = request.args.get('token') or request.headers.get('X-Admin-Token') or ''
    if not admin_ok(token):
        return jsonify({"message": "Unauthorized."}), 401
    data = request.get_json(silent=True) or {}
    ticket_id = data.get('id')
    reply = (data.get('reply') or '').strip()
    if not ticket_id or not reply:
        return jsonify({"message": "Missing reply."}), 400
    conn = get_conn()
    conn.execute("UPDATE tickets SET reply = ?, status = 'Replied' WHERE id = ?", (reply, ticket_id))
    conn.commit(); conn.close()
    return jsonify({"message": "Reply sent."}), 200


@app.route('/api/review', methods=['POST'])
def create_review():
    data = request.get_json(silent=True) or {}
    username = (data.get('user') or '').strip().lower()
    txn_id = data.get('txn_id')
    rating = int(data.get('rating') or 0)
    comment = (data.get('comment') or '').strip()
    if not username or not txn_id or rating < 1 or rating > 5 or not comment:
        return jsonify({"message": "Invalid review."}), 400
    conn = get_conn()
    conn.execute("INSERT INTO reviews (username, txn_id, rating, comment, created_at) VALUES (?,?,?,?,?)",
               (username, txn_id, rating, comment, now_str()))
    conn.commit(); conn.close()
    send_server_alert('New customer review', f'{username} rated {rating}/5: {comment[:120]}')
    return jsonify({"message": "Thank you."}), 200


@app.route('/api/reviews', methods=['GET'])
def get_reviews():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM reviews ORDER BY id DESC LIMIT 20").fetchall()
    conn.commit(); conn.close()
    return jsonify([dict(zip(['id', 'username', 'txn_id', 'rating', 'comment', 'created_at'], r)) for r in rows]), 200


@app.route('/api/upload-job-file', methods=['POST'])
def upload_job_file():
    """Customer uploads their design/artwork before paying."""
    uploaded = request.files.get('file')
    if not uploaded or not uploaded.filename:
        return jsonify({"message": "No file selected."}), 400
    file_id = uuid.uuid4().hex
    os.makedirs(JOB_FILES_DIR, exist_ok=True)
    safe_name = secure_filename(uploaded.filename) or "job_file"
    stored_name = f"{file_id}_{safe_name}"
    uploaded.save(os.path.join(JOB_FILES_DIR, stored_name))
    return jsonify({"file_id": file_id, "file_name": safe_name}), 200


@app.route('/api/job-file/<file_id>', methods=['GET'])
def serve_job_file(file_id):
    token = request.args.get('token') or request.headers.get('X-Admin-Token') or ''
    if not admin_ok(token):
        return jsonify({"message": "Unauthorized."}), 401
    if len(file_id) != 32:
        return jsonify({"message": "Invalid file id."}), 400
    for f in os.listdir(JOB_FILES_DIR):
        if f.startswith(file_id + "_"):
            return send_from_directory(JOB_FILES_DIR, f, as_attachment=True)
    return jsonify({"message": "Not found."}), 404


@app.route('/api/admin/confirm-cash', methods=['POST'])
def admin_confirm_cash():
    token = request.args.get('token') or request.headers.get('X-Admin-Token') or ''
    if not admin_ok(token):
        return jsonify({"message": "Unauthorized."}), 401
    data = request.get_json(silent=True) or {}
    conn = get_conn()
    owner = conn.execute("SELECT username FROM transactions WHERE id = ?", (data.get('id'),)).fetchone()
    conn.execute("""UPDATE transactions SET status = 'Cash Payment Confirmed / Approved for Production'
        WHERE id = ? AND status = 'Cash Payment Pending Confirmation'""",
        (data.get('id'),))
    conn.commit(); conn.close()
    if owner:
        notify(owner[0], 'payment', 'Payment confirmed', 'Your cash payment was confirmed. Your order is approved for production.')
    return jsonify({"message": "Confirmed."}), 200

@app.route('/api/admin/transactions', methods=['GET'])
def admin_transactions():
    token = request.args.get('token') or request.headers.get('X-Admin-Token') or ''
    if not admin_ok(token):
        return jsonify({"message": "Unauthorized."}), 401
    conn = get_conn()
    rows = conn.execute("""SELECT id, username, job_type, actual_price, vip_money,
        total_price, status, production_status, timestamp, method, notes, is_vip
        FROM transactions ORDER BY id DESC LIMIT 200""").fetchall()
    cards = conn.execute("SELECT card_id, username, tier, valid_until FROM vip_cards ORDER BY card_id DESC").fetchall()
    conn.close()
    return jsonify({"transactions": [dict(zip(['id', 'username', 'job_type', 'actual_price', 'vip_money',
        'total_price', 'status', 'production_status', 'timestamp', 'method', 'notes', 'is_vip'], r)) for r in rows],
                   "vip_cards": [dict(zip(['card_id', 'username', 'tier', 'valid_until'], r)) for r in cards]}), 200


@app.route('/api/admin/stats', methods=['GET'])
def admin_stats():
    token = request.args.get('token') or request.headers.get('X-Admin-Token') or ''
    if not admin_ok(token):
        return jsonify({"message": "Unauthorized."}), 401
    conn = get_conn()
    total_orders, total_revenue = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(total_price),0) FROM transactions WHERE status NOT LIKE '%Pending%'").fetchone()
    pending_cash = conn.execute(
        "SELECT COUNT(*) FROM transactions WHERE status = 'Cash Payment Pending Confirmation'").fetchone()[0]
    pending_transfer = conn.execute(
        "SELECT COUNT(*) FROM transactions WHERE status = 'Transfer Pending Approval'").fetchone()[0]
    vip_cards = conn.execute("SELECT COUNT(*) FROM vip_cards").fetchone()[0]
    subs = conn.execute("SELECT COUNT(*) FROM sub_cards").fetchone()[0]
    customers = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    today_orders, today_revenue = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(total_price),0) FROM transactions WHERE timestamp LIKE ?", (today + "%",)).fetchone()
    open_tickets = conn.execute("SELECT COUNT(*) FROM tickets WHERE status = 'Open'").fetchone()[0]
    conn.close()
    return jsonify({"total_orders": total_orders, "total_revenue": total_revenue,
                   "pending_cash": pending_cash, "pending_transfer": pending_transfer,
                   "vip_cards": vip_cards, "sub_cards": subs,
                   "customers": customers, "orders_today": today_orders,
                   "revenue_today": today_revenue, "open_tickets": open_tickets}), 200


@app.route('/api/admin/export-csv', methods=['GET'])
def export_csv():
    token = request.args.get('token') or request.headers.get('X-Admin-Token') or ''
    if not admin_ok(token):
        return jsonify({"message": "Unauthorized."}), 401
    conn = get_conn()
    rows = conn.execute("""SELECT id, username, job_type, actual_price, vip_money,
        total_price, status, production_status, timestamp, method, is_vip, notes
        FROM transactions ORDER BY id DESC""").fetchall()
    conn.close()
    lines = ["id,username,job_type,actual_price,vip_money,total_price,status,production_status,timestamp,method,is_vip,notes"]
    for r in rows:
        vals = [str(r[i] or "") for i in (0,1,2,3,4,5,6,7,8,9,10,11)]
        lines.append(",".join(vals))
    return Response("\n".join(lines), mimetype="text/csv",
                   headers={"Content-Disposition": "attachment; filename=orders.csv"}), 200


@app.route('/api/admin/order-status', methods=['POST'])
def admin_order_status():
    token = request.args.get('token') or request.headers.get('X-Admin-Token') or ''
    if not admin_ok(token):
        return jsonify({"message": "Unauthorized."}), 401
    data = request.get_json(silent=True) or {}
    status = data.get('production_status') or ''
    if status not in ("Awaiting Production", "In Production", "Ready for Pickup", "Completed", "Cancelled"):
        return jsonify({"message": "Invalid status."}), 400
    conn = get_conn()
    owner = conn.execute("SELECT username FROM transactions WHERE id = ?", (data.get('id'),)).fetchone()
    conn.execute("UPDATE transactions SET production_status = ? WHERE id = ?", (status, data.get('id')))
    conn.commit(); conn.close()
    if owner:
        notify(owner[0], 'status', 'Order update', f'Your order is now: {status}')
    return jsonify({"message": "Status updated."}), 200


@app.route('/api/admin/cancel-order', methods=['POST'])
def admin_cancel_order():
    token = request.args.get('token') or request.headers.get('X-Admin-Token') or ''
    if not admin_ok(token):
        return jsonify({"message": "Unauthorized."}), 401
    data = request.get_json(silent=True) or {}
    reason = (data.get('reason') or '').strip()
    if not reason:
        return jsonify({"message": "Reason required."}), 400
    conn = get_conn()
    conn.execute("UPDATE transactions SET production_status = 'Cancelled' WHERE id = ?", (data.get('id'),))
    conn.commit(); conn.close()
    return jsonify({"message": "Cancelled."}), 200


@app.route('/api/admin/order-photo', methods=['POST'])
def admin_order_photo():
    token = request.args.get('token') or request.headers.get('X-Admin-Token') or ''
    if not admin_ok(token):
        return jsonify({"message": "Unauthorized."}), 401
    txn_id = request.form.get('txn_id')
    uploaded = request.files.get('file')
    if not txn_id or not uploaded:
        return jsonify({"message": "Missing file."}), 400
    file_id = uuid.uuid4().hex
    os.makedirs(JOB_FILES_DIR, exist_ok=True)
    name = f"{file_id}_{secure_filename(uploaded.filename) or 'photo'}"
    uploaded.save(os.path.join(JOB_FILES_DIR, name))
    conn = get_conn()
    conn.execute("INSERT INTO order_photos (txn_id, file_id) VALUES (?,?)", (txn_id, file_id))
    conn.commit(); conn.close()
    return jsonify({"message": "Photo saved."}), 200


@app.route('/api/order-photo/<int:txn_id>', methods=['GET'])
def order_photo(txn_id):
    conn = get_conn()
    row = conn.execute("SELECT file_id FROM order_photos WHERE txn_id = ? ORDER BY id DESC LIMIT 1", (txn_id,)).fetchone()
    conn.close()
    if not row:
        return jsonify({"message": "No photo."}), 404
    for f in os.listdir(JOB_FILES_DIR):
        if f.startswith(row[0] + "_"):
            return send_from_directory(JOB_FILES_DIR, f)
    return jsonify({"message": "Not found."}), 404


@app.route('/api/vip-card-qr/<card_id>', methods=['GET'])
def serve_vip_qr(card_id):
    token = request.args.get('token') or request.headers.get('X-Admin-Token') or ''
    if not admin_ok(token):
        return jsonify({"message": "Unauthorized."}), 401
    if len(card_id) != 3:
        return jsonify({"message": "Invalid card id."}), 400
    conn = get_conn()
    row = conn.execute("SELECT qr_path, name, phone, sex, tier FROM vip_cards WHERE card_id = ?", (card_id,)).fetchone()
    conn.close()
    if not row:
        return jsonify({"message": "Not found."}), 404
    qr_path = row[0]
    if not qr_path or not os.path.exists(qr_path):
        # Generate the QR code on the fly if it is missing
        qr_data = (f"FodaKem VIP CARD ID: {card_id}\nHolder: {row[1]}\n"
                   f"Contact: {row[2]}\nGender: {row[3]}\nPlan: {row[4]}")
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(qr_data)
        qr.make(fit=True)
        qr_img = qr.make_image(fill_color="black", back_color="white")
        os.makedirs("uploads", exist_ok=True)
        qr_path = f"uploads/{card_id}_qr.png"
        qr_img.save(qr_path)
        conn = get_conn()
        conn.execute("UPDATE vip_cards SET qr_path = ? WHERE card_id = ?", (qr_path, card_id))
        conn.commit()
        conn.close()
    return send_from_directory('.', qr_path)


@app.route('/api/admin/reactions', methods=['GET'])
def admin_reactions():
    token = request.args.get('token') or request.headers.get('X-Admin-Token') or ''
    if not admin_ok(token):
        return jsonify({"message": "Unauthorized."}), 401
    conn = get_conn()
    rows = conn.execute("""SELECT target_type, target_id, reaction, COUNT(*)
        FROM reactions GROUP BY target_type, target_id, reaction""").fetchall()
    conn.commit(); conn.close()
    out = []
    for r in rows:
        out.append({"target_type": r[0], "target_id": r[1], "reaction": r[2], "count": r[3]})
    return jsonify(out), 200


@app.route('/api/admin/test-mode', methods=['POST'])
def admin_test_mode():
    token = request.args.get('token') or request.headers.get('X-Admin-Token') or ''
    if not admin_ok(token):
        return jsonify({"message": "Unauthorized."}), 401
    data = request.get_json(silent=True) or {}
    conn = get_conn()
    conn.execute("INSERT INTO admin_settings (key, value) VALUES ('test_mode', ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
               (str(1 if data.get('enabled') else 0),))
    conn.commit(); conn.close()
    return jsonify({"message": "Test mode updated."}), 200


@app.route('/api/admin/users', methods=['GET'])
def admin_users():
    token = request.args.get('token') or request.headers.get('X-Admin-Token') or ''
    if not admin_ok(token):
        return jsonify({"message": "Unauthorized."}), 401
    conn = get_conn()
    rows = conn.execute("SELECT username, nickname FROM users ORDER BY username").fetchall()
    login_counts = {}
    for r in conn.execute("SELECT username, COUNT(*) FROM login_log GROUP BY username"):
        login_counts[r[0]] = r[1]
    conn.close()
    return jsonify([{"username": r[0], "nickname": r[1], "logins": login_counts.get(r[0], 0)} for r in rows]), 200


@app.route('/api/admin/payment-methods', methods=['POST'])
def admin_payment_methods():
    token = request.args.get('token') or request.headers.get('X-Admin-Token') or ''
    if not admin_ok(token):
        return jsonify({"message": "Unauthorized."}), 401
    data = request.get_json(silent=True) or {}
    conn = get_conn()
    for method, enabled in (("paystack", data.get('paystack', True)),
                          ("cash", data.get('cash', True)),
                          ("transfer", data.get('transfer', True))):
        conn.execute("""INSERT INTO payment_settings (method, enabled) VALUES (?,?)
            ON CONFLICT(method) DO UPDATE SET enabled = excluded.enabled""",
            (method, 1 if enabled else 0))
    conn.commit(); conn.close()
    return jsonify({"message": "Payment methods updated."}), 200


SHARED_FILES_DIR = os.path.join("uploads", "shared_files")


@app.route('/api/admin/shared-files', methods=['POST'])
def upload_shared_file():
    token = request.args.get('token') or request.headers.get('X-Admin-Token') or ''
    if not admin_ok(token):
        return jsonify({"message": "Unauthorized."}), 401
    uploaded = request.files.get('file')
    if not uploaded or not uploaded.filename:
        return jsonify({"message": "No file selected."}), 400
    file_id = uuid.uuid4().hex
    os.makedirs(SHARED_FILES_DIR, exist_ok=True)
    name = f"{file_id}_{secure_filename(uploaded.filename) or 'file'}"
    uploaded.save(os.path.join(SHARED_FILES_DIR, name))
    conn = get_conn()
    conn.execute("""INSERT INTO shared_files (file_id, file_name, uploaded_by, uploaded_at)
        VALUES (?,?,?,?)""", (file_id, secure_filename(uploaded.filename), '', now_str()))
    conn.commit()
    conn.close()
    return jsonify({"message": "File uploaded."}), 200


@app.route('/api/admin/shared-files', methods=['GET'])
def list_shared_files():
    token = request.args.get('token') or request.headers.get('X-Admin-Token') or ''
    if not admin_ok(token):
        return jsonify({"message": "Unauthorized."}), 401
    conn = get_conn()
    rows = conn.execute("""SELECT id, file_id, file_name, uploaded_at FROM shared_files
        ORDER BY id DESC LIMIT 200""").fetchall()
    conn.close()
    return jsonify([{"id": r[0], "file_id": r[1], "file_name": r[2], "uploaded_at": r[3]} for r in rows]), 200


@app.route('/api/admin/shared-file/<file_id>', methods=['DELETE'])
def delete_shared_file(file_id):
    token = request.args.get('token') or request.headers.get('X-Admin-Token') or ''
    if not admin_ok(token):
        return jsonify({"message": "Unauthorized."}), 401
    if len(file_id) != 32:
        return jsonify({"message": "Invalid file id."}), 400
    conn = get_conn()
    conn.execute("DELETE FROM shared_files WHERE file_id = ?", (file_id,))
    conn.commit()
    conn.close()
    for f in os.listdir(SHARED_FILES_DIR):
        if f.startswith(file_id + "_"):
            os.remove(os.path.join(SHARED_FILES_DIR, f))
    return jsonify({"message": "File deleted."}), 200


@app.route('/api/shared-file/<file_id>', methods=['GET'])
def download_shared_file(file_id):
    token = request.args.get('token') or request.headers.get('X-Admin-Token') or ''
    if not admin_ok(token):
        return jsonify({"message": "Unauthorized."}), 401
    if len(file_id) != 32:
        return jsonify({"message": "Invalid file id."}), 400
    for f in os.listdir(SHARED_FILES_DIR):
        if f.startswith(file_id + "_"):
            return send_from_directory(SHARED_FILES_DIR, f, as_attachment=True)
    return jsonify({"message": "File not found."}), 404


@app.route('/api/transactions', methods=['GET'])
def get_transactions():
    username = (request.args.get('user') or '').strip().lower()
    conn = get_conn()
    rows = conn.execute("""SELECT id, job_type, total_price, status, production_status, timestamp
        FROM transactions WHERE username = ? ORDER BY id DESC""", (username,)).fetchall()
    conn.close()
    keys = ['id', 'job_type', 'total_price', 'status', 'production_status', 'timestamp']
    return jsonify([dict(zip(keys, r)) for r in rows]), 200


@app.route('/api/transaction/<int:txn_id>', methods=['GET'])
def get_transaction(txn_id):
    conn = get_conn()
    row = conn.execute("""SELECT id, username, job_type, actual_price, vip_money, total_price,
        status, production_status, timestamp FROM transactions WHERE id = ?""", (txn_id,)).fetchone()
    conn.close()
    if not row:
        return jsonify({"message": "Not found."}), 404
    keys = ['id', 'username', 'job_type', 'actual_price', 'vip_money', 'total_price',
            'status', 'production_status', 'timestamp']
    return jsonify(dict(zip(keys, row))), 200


@app.route('/api/my-cards', methods=['GET'])
def my_cards():
    username = (request.args.get('user') or '').strip().lower()
    conn = get_conn()
    card = conn.execute("""SELECT card_id, tier, valid_until, name, sex FROM vip_cards
        WHERE username = ? ORDER BY card_id DESC LIMIT 1""", (username,)).fetchone()
    sub = conn.execute("""SELECT sub_id, tag, valid_until FROM sub_cards
        WHERE username = ? ORDER BY registered_at DESC LIMIT 1""", (username,)).fetchone()
    conn.close()
    return jsonify({
        "vip": {"card_id": card[0], "tier": card[1], "valid_until": card[2],
                "name": card[3], "sex": card[4]} if card else None,
        "sub": {"sub_id": sub[0], "tag": sub[1], "valid_until": sub[2]} if sub else None,
    }), 200


@app.route('/api/my-sub', methods=['GET'])
def my_sub():
    username = (request.args.get('user') or '').strip().lower()
    conn = get_conn()
    row = conn.execute("SELECT sub_id, tag, valid_until FROM sub_cards WHERE username = ? ORDER BY registered_at DESC LIMIT 1",
                    (username,)).fetchone()
    if not row:
        return jsonify({"has_sub": False}), 200
    sub_id, tag, valid_until = row
    left = sub_uses_left(username)
    conn.close()
    return jsonify({"has_sub": True, "tag": tag, "valid_until": valid_until,
                   "uses_left": left}), 200


def build_card_slip_png(card_id, user, include_sub):
    from PIL import Image, ImageDraw, ImageFont
    conn = get_conn()
    card = conn.execute("SELECT card_id, username, name, sex, tier, valid_until FROM vip_cards WHERE card_id = ?",
                    (card_id,)).fetchone()
    sub = None
    if include_sub:
        sub = conn.execute("SELECT sub_id, tag FROM sub_cards WHERE username = ? ORDER BY registered_at DESC LIMIT 1",
                        (user,)).fetchone()
    conn.close()
    if not card:
        return None
    try:
        big = ImageFont.load_default(size=26)
        med = ImageFont.load_default(size=18)
        small = ImageFont.load_default(size=14)
    except TypeError:
        big = med = small = ImageFont.load_default()
    img = Image.new('RGB', (820, 1020), '#fdfdff')
    draw = ImageDraw.Draw(img)

    def text(x, y, s, font=med, fill='#222'):
        draw.text((x, y), s, font=font, fill=fill)

    text(30, 30, 'FodaKem VIP', font=big, fill='#6b46c1')
    text(30, 70, 'CARD & SUBSIDIARY SLIP', font=small, fill='#718096')

    sex_word = {'Male': 'Male', 'Female': 'Female'}.get(card[3] or '', '')
    sub_line = f"Sub Card: {'Yes' if sub else 'No'}"
    text(30, 130, f"Card ID      : PRY-STYLE {card_id}", font=small)
    text(30, 170, f"Holder Name   : {card[2] or '-'}")
    text(30, 205, f"Sex           : {sex_word or '-'}")
    text(30, 240, f"Phone         : -")
    text(30, 275, f"Plan          : {card[4]}")
    text(30, 310, f"Valid Until   : {card[5] or '-'}")
    text(30, 350, 'VIP CARD SECTION', font=big, fill='#6b46c1')
    text(30, 400, f"Card holder   : {card[2] or '-'}")
    text(30, 440, f"Registered as : {card_id}")
    if sub:
        text(30, 500, f"Sub Card ID   : {sub[0]}")
        text(30, 540, f"Sub Tag       : {sub[1]}")
        text(30, 580, 'Uses this week : 2 (resets every week)')
        text(30, 620, 'Valid while your VIP card is active')
    else:
        for y in (500, 540, 580, 620):
            text(30, y, '---------------------------------', font=small, fill='#999')
        text(30, 620, 'Sub Card: not purchased')
    return img


@app.route('/api/card-slip/<card_id>', methods=['GET'])
def serve_card_slip(card_id):
    raw_user = (request.args.get('user') or '').strip()
    include_sub = request.args.get('with_sub') in ('1', 'true', 'True')
    if not raw_user:
        return jsonify({"message": "Please sign in to download your card slip."}), 401
    conn = get_conn()
    # Accept either the username or the nickname
    urow = conn.execute("SELECT username FROM users WHERE username = ? OR nickname = ? COLLATE NOCASE",
                        (raw_user.lower(), raw_user)).fetchone()
    user = urow[0] if urow else raw_user.lower()
    card = conn.execute("SELECT username FROM vip_cards WHERE card_id = ?", (card_id,)).fetchone()
    if not card:
        conn.close()
        return jsonify({"message": "That card does not exist."}), 404
    if (card[0] or '').strip().lower() != user:
        conn.close()
        return jsonify({"message": "This card belongs to another customer."}), 403
    txn = conn.execute("""SELECT status FROM transactions WHERE username = ? AND job_type LIKE 'VIP Card%'
        ORDER BY id DESC LIMIT 1""", (user,)).fetchone()
    conn.close()
    if txn and 'Pending' in str(txn[0]):
        return jsonify({"message": "Your card payment is not confirmed yet. The admin must approve it before you can download the slip."}), 403
    img = build_card_slip_png(card_id, user, include_sub)
    if img is None:
        return jsonify({"message": "Cannot create the slip."}), 500
    out = io.BytesIO()
    img.save(out, format='PNG')
    out.seek(0)
    return Response(out.read(), mimetype='image/png',
                   headers={'Content-Disposition': 'attachment; filename="fodakem-slip.png"'})


@app.route('/')
def home():
    return send_from_directory('.', 'VLAND.html')


@app.route('/<path:filename>')
def serve_static(filename):
    if filename in STATIC_PAGES:
        return send_from_directory('.', filename)
    return jsonify({"message": "Not found"}), 404


init_db()
# Make sure every upload folder exists before serving
os.makedirs(JOB_FILES_DIR, exist_ok=True)
os.makedirs(ANNOUNCEMENTS_DIR, exist_ok=True)
os.makedirs(SHARED_FILES_DIR, exist_ok=True)

if __name__ == '__main__':
    debug_mode = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(host='0.0.0.0', port=5000, debug=debug_mode)


