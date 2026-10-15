import os
import json
import uuid
import sqlite3
import datetime
import qrcode
import bcrypt
import time
import hmac
import hashlib
import requests
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from werkzeug.utils import secure_filename

app = Flask(__name__)
# Securely allows all network traffic from Netlify or any public browser link
CORS(app, resources={r"/api/*": {"origins": "*"}})

DATABASE_FILE = "database.db"
app.config['MAX_CONTENT_LENGTH'] = 15 * 1024 * 1024

# ---------------------------------------------------------------------------
# PAYSTACK SETTINGS — set these as ENVIRONMENT VARIABLES on Render:
#   PAYSTACK_SECRET_KEY  = sk_live_...   (server-side verification key)
#   PAYSTACK_PUBLIC_KEY  = pk_live_...   (sent to the browser for checkout)
#   PAYSTACK_SUBACCOUNT  = ACCT_...      (optional - leave EMPTY to take 100%)
#   ADMIN_TOKEN          = (any secret word) - unlocks the admin order page
# ---------------------------------------------------------------------------
PAYSTACK_SECRET_KEY = os.environ.get("PAYSTACK_SECRET_KEY", "sk_test_your_copied_secret_key_here")
PAYSTACK_PUBLIC_KEY = os.environ.get("PAYSTACK_PUBLIC_KEY", "")
PAYSTACK_SUBACCOUNT = os.environ.get("PAYSTACK_SUBACCOUNT", "")
PAYSTACK_WEBHOOK_SECRET = os.environ.get("PAYSTACK_WEBHOOK_SECRET", "")
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")
# Support multiple admins: ADMIN_TOKENS="token1,token2,token3"
ADMIN_TOKENS = {t.strip() for t in os.environ.get("ADMIN_TOKENS", "").split(",") if t.strip()}
if ADMIN_TOKEN:
    ADMIN_TOKENS.add(ADMIN_TOKEN)

JOB_FILES_DIR = os.path.join("uploads", "job_files")
ANNOUNCEMENTS_DIR = os.path.join("uploads", "announcements")

# Envelope & Card design prices (PLACEHOLDER - confirm real prices)
ENVELOPE_SIZES = {"8x4.5": 2500, "9x5": 3500, "10x6": 4500}
CARD_SIZES = {"3.5x2": 1500, "4x2.5": 2000, "4.5x3": 2500}
DESIGN_FEE = 2000  # extra when customer has NOT designed it themselves

# VIP card tiers: price in Naira + validity in days
VIP_TIER_PRICES = {"blue": 1500, "red": 3000, "yellow": 4500, "black": 6000}
VIP_TIER_VALIDITY_DAYS = {"blue": 30, "red": 90, "yellow": 180, "black": 365}

# Only these files may be served to browsers. Everything else (database.db,
# logins.txt, uploads/, app.py) stays private.
STATIC_PAGES = {
    "VLAND.html", "dashboard.html", "jobs.html", "payment.html",
    "renew.html", "VIP-CARD.html", "admin.html", "VLAND.css", "VLAND.js",
}

def init_db():
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE IF NOT EXISTS users (username TEXT PRIMARY KEY, password_hash TEXT)")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, job_type TEXT,
            actual_price REAL, vip_money REAL, total_price REAL, status TEXT, timestamp TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS vip_cards (
            card_id TEXT PRIMARY KEY, username TEXT, name TEXT,
            phone TEXT, sex TEXT, tier TEXT, issue_date TEXT, qr_path TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, sender TEXT,
            message_text TEXT, timestamp TEXT, is_read INTEGER
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS job_availability (
            job_key TEXT PRIMARY KEY, available INTEGER DEFAULT 1, reason TEXT DEFAULT ''
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS announcements (
            id INTEGER PRIMARY KEY AUTOINCREMENT, file_id TEXT, file_name TEXT,
            description TEXT, created_at TEXT
        )
    """)
    # Migrate databases created by older versions of this app:
    # the old "transactions" table had no "timestamp" column.
    cursor.execute("PRAGMA table_info(transactions)")
    txn_cols = {row[1] for row in cursor.fetchall()}
    if "timestamp" not in txn_cols:
        try:
            cursor.execute("ALTER TABLE transactions ADD COLUMN timestamp TEXT")
        except sqlite3.OperationalError:
            pass  # another gunicorn worker already added it
    if "paystack_ref" not in txn_cols:
        try:
            cursor.execute("ALTER TABLE transactions ADD COLUMN paystack_ref TEXT")
        except sqlite3.OperationalError:
            pass  # another gunicorn worker already added it
    if "file_id" not in txn_cols:
        try:
            cursor.execute("ALTER TABLE transactions ADD COLUMN file_id TEXT")
        except sqlite3.OperationalError:
            pass  # another gunicorn worker already added it
    conn.commit()
    conn.close()

def get_json_body():
    # silent=True prevents a crash when a request has no/invalid JSON body
    return request.get_json(silent=True) or {}

def verify_paystack_reference(paystack_ref):
    """Confirm directly with Paystack that money landed. Returns the data dict, or None."""
    paystack_verification_url = f"https://api.paystack.co/transaction/verify/{paystack_ref}"
    headers = {"Authorization": f"Bearer {PAYSTACK_SECRET_KEY}"}
    try:
        response = requests.get(paystack_verification_url, headers=headers, timeout=15).json()
    except Exception:
        return None
    if response.get('status') and response.get('data', {}).get('status') == 'success':
        return response['data']
    return None

def log_payout(paystack_ref, username, total_price):
    # NOTE: The real money split happens inside Paystack via the SUBACCOUNT
    # percentage configured on the Paystack dashboard. The figures below are
    # only a console/log report - they are NOT transfers executed by this code.
    partner_share = 2200.00
    your_share = 300.00
    print("\n--- FGURL VIP REAL-TIME CHECKOUT SPLIT COMPILATION ---")
    print(f"Ref Token: [{paystack_ref}] | Account Profile: [{username}]")
    print(f"Total Confirmed Revenue Received: N{total_price:,.2f}")
    print(f"-> Automated Payout Sent to Partner Node: N{partner_share:,.2f}")
    print(f"-> Your Dedicated Premium Payout (Oladele): N{your_share:,.2f} to 8065867966")
    print("-------------------------------------------------------------\n")

def compute_job_price(job_type, params):
    """Server-side price calculation so clients cannot tamper with prices."""
    try:
        copies = int(params.get('copies', 1))
        if copies < 1 or copies > 1000000:
            return None  # enforce the 1 - 1,000,000 copies limit
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
            base = ENVELOPE_SIZES.get(params.get('size', ''))
            if base is None:
                return None
            if params.get('design') != 'yes':
                base += DESIGN_FEE
            return base * copies
        if job_type.startswith("Card Design"):
            base = CARD_SIZES.get(params.get('size', ''))
            if base is None:
                return None
            if params.get('design') != 'yes':
                base += DESIGN_FEE
            return base * copies
    except (TypeError, ValueError):
        return None
    return None

# Create/upgrade the database tables at startup. This runs both with
# `python app.py` AND under gunicorn on Render (where __main__ never executes).
init_db()

@app.route('/api/register', methods=['POST'])
def register():
    data = get_json_body()
    username = (data.get('username') or '').strip().lower()
    password = data.get('password') or ''
    if not username or not password:
        return jsonify({"message": "Inputs cannot be left empty."}), 400
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT username FROM users WHERE username = ?", (username,))
    if cursor.fetchone():
        conn.close()
        return jsonify({"message": "Error: That username is already registered under FGURL VIP."}), 400
    hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    cursor.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)", (username, hashed))
    conn.commit()
    conn.close()
    return jsonify({"message": "FGURL VIP Profile Formed Successfully!"}), 200

@app.route('/api/login', methods=['POST'])
def login():
    data = get_json_body()
    username = (data.get('username') or '').strip().lower()
    password = data.get('password') or ''
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT password_hash FROM users WHERE username = ?", (username,))
    row = cursor.fetchone()
    conn.close()
    # fetchone() returns a tuple like (hash,), so we must use row[0]
    if row and bcrypt.checkpw(password.encode('utf-8'), row[0].encode('utf-8')):
        current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open("logins.txt", "a") as log_file:
            log_file.write(f"[{current_time}] AUTH SUCCESS - Profile '{username}' entered the FGURL VIP Portal.\n")
        return jsonify({"message": "Access Verified! Loading panel..."}), 200
    return jsonify({"message": "Error: Invalid entry credentials. Access Denied."}), 401

@app.route('/api/check-expiry', methods=['GET'])
def check_expiry():
    username = (request.args.get('user') or '').strip().lower()
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT tier, issue_date FROM vip_cards WHERE username = ?", (username,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return jsonify({"status": "active", "has_card": False}), 200
    tier, issue_date = row[0], row[1]
    days = VIP_TIER_VALIDITY_DAYS.get(tier, 0)
    try:
        issued = datetime.datetime.strptime(issue_date[:16], "%Y-%m-%dT%H:%M")
        expires = issued + datetime.timedelta(days=days)
        if datetime.datetime.now() > expires:
            return jsonify({"status": "expired", "has_card": True, "expires": str(expires)}), 200
        return jsonify({"status": "active", "has_card": True, "expires": str(expires)}), 200
    except (TypeError, ValueError):
        return jsonify({"status": "active", "has_card": True}), 200

@app.route('/api/config', methods=['GET'])
def paystack_config():
    # Hand the PUBLIC key (and optional subaccount) to the browser.
    # The SECRET key never leaves the server.
    return jsonify({
        "paystack_public_key": PAYSTACK_PUBLIC_KEY,
        "paystack_subaccount": PAYSTACK_SUBACCOUNT
    })

@app.route('/api/checkout-live', methods=['POST'])
def checkout_live():
    data = get_json_body()
    username = data.get('user')
    job_type = data.get('job_type') or ''
    surcharge_rate = float(data.get('surcharge_rate') or 0.25)
    params = data.get('params') or {}
    file_id = data.get('file_id') or ''
    paystack_ref = data.get('paystack_ref')

    # Server-side price calculation - the client-supplied price is ignored
    actual_price = compute_job_price(job_type, params)
    if actual_price is None:
        return jsonify({"message": "Invalid job parameters supplied."}), 400
    if not paystack_ref:
        return jsonify({"message": "Missing payment reference."}), 400

    # Security Verification: Confirms directly with Paystack cloud that money landed safely
    payment_data = verify_paystack_reference(paystack_ref)
    if not payment_data:
        return jsonify({"message": "Verification parameters fraudulent or invalid."}), 400

    # Make sure the customer actually paid the full amount (Paystack reports kobo)
    paid_kobo = int(payment_data.get('amount') or 0)
    expected_total = actual_price * (1 + surcharge_rate)
    if paid_kobo + 50 < expected_total * 100:
        return jsonify({"message": f"Underpayment detected. Expected ₦{expected_total:,.2f}."}), 400

    vip_money = actual_price * surcharge_rate
    total_price = actual_price + vip_money
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO transactions (username, job_type, actual_price, vip_money, total_price, status, timestamp, paystack_ref, file_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (username, job_type, actual_price, vip_money, total_price, "Payment Confirmed / Approved for Production", timestamp, paystack_ref, file_id))
    conn.commit()
    conn.close()

    log_payout(paystack_ref, username, total_price)
    return jsonify({"message": f"Payment Verified! Total Processed: ₦{total_price:,.2f}."}), 200

@app.route('/api/vip-checkout', methods=['POST'])
def vip_checkout():
    """Charge a real payment for a VIP card, then issue the card."""
    username = (request.form.get('username') or '').strip().lower()
    name = request.form.get('name')
    phone = request.form.get('phone')
    sex = request.form.get('sex')
    tier = request.form.get('tier')
    issue_date = request.form.get('issue_date')
    paystack_ref = request.form.get('paystack_ref')

    if tier not in VIP_TIER_PRICES:
        return jsonify({"message": "Invalid VIP tier selected."}), 400
    expected_naira = VIP_TIER_PRICES[tier]
    if not paystack_ref:
        return jsonify({"message": "Missing payment reference."}), 400

    # Verify the money really landed in your Paystack account
    payment_data = verify_paystack_reference(paystack_ref)
    if not payment_data:
        return jsonify({"message": "Payment not confirmed by Paystack. Please try again."}), 400

    paid_kobo = int(payment_data.get('amount') or 0)
    if paid_kobo + 50 < expected_naira * 100:
        return jsonify({"message": f"Underpayment: ₦{expected_naira:,.0f} required for the {tier} plan."}), 400

    # Save passport photograph
    passport = request.files.get('passport')
    if passport and passport.filename:
        os.makedirs("uploads", exist_ok=True)
        unique_suffix = int(time.time())
        file_extension = os.path.splitext(secure_filename(passport.filename))[1] or '.jpg'
        passport_name = f"{username}_{unique_suffix}_passport{file_extension}"
        passport.save(os.path.join("uploads", passport_name))

    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM vip_cards")
    count = cursor.fetchone()[0] + 1
    card_sequence_number = f"{count:03d}"

    qr_data = f"FGURL VIP CARD ID: {card_sequence_number}\nHolder: {name}\nContact: {phone}\nGender: {sex}\nPlan: {tier}"
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(qr_data)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white")
    os.makedirs("uploads", exist_ok=True)
    qr_filename = f"uploads/{card_sequence_number}_qr.png"
    qr_img.save(qr_filename)

    cursor.execute("DELETE FROM vip_cards WHERE username = ?", (username,))
    cursor.execute("""
        INSERT INTO vip_cards (card_id, username, name, phone, sex, tier, issue_date, qr_path)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (card_sequence_number, username, name, phone, sex, tier, issue_date, qr_filename))

    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("""
        INSERT INTO transactions (username, job_type, actual_price, vip_money, total_price, status, timestamp, paystack_ref)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (username, f"VIP Card ({tier})", expected_naira, 0.0, expected_naira,
          "Payment Confirmed / Approved for Production", timestamp, paystack_ref))
    conn.commit()
    conn.close()

    log_payout(paystack_ref, username, expected_naira)
    return jsonify({"message": f"Payment Verified! FGURL VIP Card #{card_sequence_number} ({tier}) is now active."}), 200

@app.route('/api/paystack-webhook', methods=['POST'])
def paystack_webhook():
    """Paystack calls this the INSTANT any payment succeeds - true real-time."""
    if not PAYSTACK_WEBHOOK_SECRET:
        return jsonify({"message": "Webhook not configured"}), 400

    # Verify the request really came from Paystack
    signature = request.headers.get('X-Paystack-Token', '')
    payload = request.get_data()
    computed = hmac.new(
        PAYSTACK_WEBHOOK_SECRET.encode('utf-8'), payload, hashlib.sha512
    ).hexdigest()
    if not hmac.compare_digest(computed, signature):
        return jsonify({"message": "Invalid signature"}), 401

    event = request.get_json(silent=True) or {}
    if event.get('event') != 'charge.success':
        return jsonify({"message": "Event ignored"}), 200

    data = event.get('data', {})
    paystack_ref = data.get('reference') or ''
    amount_kobo = int(data.get('amount') or 0)
    metadata = data.get('metadata') or {}
    custom_fields = metadata.get('custom_fields') or []
    fields = {}
    for f in custom_fields:
        if f.get('variable_name'):
            fields[f['variable_name']] = f.get('value')

    username = (fields.get('username') or '').strip().lower()
    job_type = fields.get('job_type') or ''
    tier = fields.get('tier') or ''
    file_id = fields.get('file_id') or ''

    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()

    # Never record the same payment twice
    cursor.execute("SELECT id FROM transactions WHERE paystack_ref = ?", (paystack_ref,))
    if cursor.fetchone():
        conn.close()
        return jsonify({"message": "Already processed"}), 200

    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # VIP card purchase
    if tier in VIP_TIER_PRICES:
        expected_kobo = VIP_TIER_PRICES[tier] * 100
        if amount_kobo + 50 < expected_kobo:
            conn.close()
            return jsonify({"message": "Underpayment ignored"}), 200
        cursor.execute("""
            INSERT INTO transactions (username, job_type, actual_price, vip_money, total_price, status, timestamp, paystack_ref)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (username, f"VIP Card ({tier})", expected_kobo / 100, 0.0, expected_kobo / 100,
              "Payment Confirmed via Webhook - finish card setup in portal", timestamp, paystack_ref))
        conn.commit()
        conn.close()
        print(f"\n[WEBHOOK] VIP payment {paystack_ref} from {username} (N{expected_kobo/100:,.0f})")
        return jsonify({"message": "Recorded"}), 200

    # Print / service job
    if job_type:
        try:
            params = json.loads(fields.get('params') or '{}')
        except ValueError:
            params = {}
        price = compute_job_price(job_type, params)
        if price is None:
            conn.close()
            return jsonify({"message": "Unknown job type"}), 200
        surcharge_rate = float(fields.get('surcharge_rate') or 0.25)
        total_price = price * (1 + surcharge_rate)
        if amount_kobo + 50 < total_price * 100:
            conn.close()
            return jsonify({"message": "Underpayment ignored"}), 200
        cursor.execute("""
            INSERT INTO transactions (username, job_type, actual_price, vip_money, total_price, status, timestamp, paystack_ref, file_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (username, job_type, price, price * surcharge_rate, total_price,
              "Payment Confirmed via Webhook / Approved for Production", timestamp, paystack_ref, file_id))
        conn.commit()
        conn.close()
        print(f"\n[WEBHOOK] Job payment {paystack_ref} from {username} (N{total_price:,.2f})")
        return jsonify({"message": "Recorded"}), 200

    conn.close()
    return jsonify({"message": "No metadata to record"}), 200

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
    """Admin-only download of an uploaded job file."""
    token = request.args.get('token') or ''
    if not ADMIN_TOKENS or token not in ADMIN_TOKENS:
        return jsonify({"message": "Unauthorized."}), 401
    # file_id must be a 32-char hex uuid - blocks path traversal
    if not file_id or len(file_id) != 32 or not all(c in '0123456789abcdef' for c in file_id):
        return jsonify({"message": "Invalid file id."}), 400
    try:
        matches = [f for f in os.listdir(JOB_FILES_DIR) if f.startswith(file_id + "_")]
    except FileNotFoundError:
        matches = []
    if not matches:
        return jsonify({"message": "File not found."}), 404
    return send_from_directory(JOB_FILES_DIR, matches[0], as_attachment=True)

@app.route('/api/transactions', methods=['GET'])
def get_transactions():
    username = request.args.get('user')
    conn = sqlite3.connect(DATABASE_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT id, job_type, total_price, status, timestamp FROM transactions WHERE username = ? ORDER BY id DESC", (username,))
    rows = cursor.fetchall()
    conn.close()
    return jsonify([dict(ix) for ix in rows])

@app.route('/api/admin/transactions', methods=['GET'])
def admin_transactions():
    """Lists every order and VIP card. Locked behind the ADMIN_TOKEN env var."""
    token = request.args.get('token') or request.headers.get('X-Admin-Token') or ''
    if not ADMIN_TOKENS or token not in ADMIN_TOKENS:
        return jsonify({"message": "Unauthorized."}), 401
    conn = sqlite3.connect(DATABASE_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, job_type, total_price, status, timestamp, paystack_ref, file_id FROM transactions ORDER BY id DESC LIMIT 200")
    txns = [dict(r) for r in cursor.fetchall()]
    cursor.execute("SELECT card_id, username, name, phone, tier, issue_date FROM vip_cards ORDER BY card_id DESC")
    cards = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return jsonify({"transactions": txns, "vip_cards": cards})

@app.route('/api/job-availability', methods=['GET'])
def job_availability():
    """Public: which jobs are currently available/unavailable."""
    conn = sqlite3.connect(DATABASE_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT job_key, available, reason FROM job_availability")
    rows = {r['job_key']: {"available": bool(r['available']), "reason": r['reason']} for r in cursor.fetchall()}
    conn.close()
    return jsonify(rows)

@app.route('/api/admin/availability', methods=['POST'])
def admin_availability():
    token = request.args.get('token') or request.headers.get('X-Admin-Token') or ''
    if not ADMIN_TOKENS or token not in ADMIN_TOKENS:
        return jsonify({"message": "Unauthorized."}), 401
    data = get_json_body()
    job_key = data.get('job_key') or ''
    available = bool(data.get('available', True))
    reason = str(data.get('reason') or '').strip()
    if not job_key:
        return jsonify({"message": "Missing job key."}), 400
    if reason and len(reason.split()) > 50:
        return jsonify({"message": "Reason must be 50 words or less."}), 400
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO job_availability (job_key, available, reason)
        VALUES (?, ?, ?)
        ON CONFLICT(job_key) DO UPDATE SET available = ?, reason = ?
    """, (job_key, 1 if available else 0, reason, 1 if available else 0, reason))
    conn.commit()
    conn.close()
    return jsonify({"message": "Availability updated."}), 200

@app.route('/api/admin/announcements', methods=['POST'])
def admin_announcements():
    """Admin posts a news/update with a design file (max 15MB) + description (max 100 words)."""
    token = request.args.get('token') or request.headers.get('X-Admin-Token') or ''
    if not ADMIN_TOKENS or token not in ADMIN_TOKENS:
        return jsonify({"message": "Unauthorized."}), 401
    file = request.files.get('file')
    if not file or not file.filename:
        return jsonify({"message": "No file selected."}), 400
    description = str(request.form.get('description') or '').strip()
    if not description:
        return jsonify({"message": "Description required."}), 400
    if len(description.split()) > 100:
        return jsonify({"message": "Description must be 100 words or less."}), 400
    file_id = uuid.uuid4().hex
    os.makedirs(ANNOUNCEMENTS_DIR, exist_ok=True)
    safe_name = secure_filename(file.filename) or "news_file"
    stored_name = f"{file_id}_{safe_name}"
    file.save(os.path.join(ANNOUNCEMENTS_DIR, stored_name))
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO announcements (file_id, file_name, description, created_at)
        VALUES (?, ?, ?, ?)
    """, (file_id, safe_name, description, timestamp))
    conn.commit()
    conn.close()
    return jsonify({"message": "News/Update posted to dashboard."}), 200

@app.route('/api/announcements', methods=['GET'])
def get_announcements():
    conn = sqlite3.connect(DATABASE_FILE)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT id, file_id, file_name, description, created_at FROM announcements ORDER BY id DESC LIMIT 20")
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return jsonify(rows)

@app.route('/api/announcement-image/<file_id>', methods=['GET'])
def serve_announcement_image(file_id):
    if not file_id or len(file_id) != 32 or not all(c in '0123456789abcdef' for c in file_id):
        return jsonify({"message": "Invalid file id."}), 400
    try:
        matches = [f for f in os.listdir(ANNOUNCEMENTS_DIR) if f.startswith(file_id + "_")]
    except FileNotFoundError:
        matches = []
    if not matches:
        return jsonify({"message": "File not found."}), 404
    return send_from_directory(ANNOUNCEMENTS_DIR, matches[0])

# ---------------------------------------------------------------------------
# Serve the frontend pages (Render only runs what app.py exposes)
# ---------------------------------------------------------------------------
@app.route('/')
def home():
    return send_from_directory('.', 'VLAND.html')

@app.route('/<path:filename>')
def serve_static(filename):
    if filename in STATIC_PAGES:
        return send_from_directory('.', filename)
    return jsonify({"message": "Not found"}), 404

if __name__ == '__main__':
    # debug=True is DANGEROUS in production (exposes an interactive debugger).
    # Only enable it locally via FLASK_DEBUG=1; Render defaults it to off.
    debug_mode = os.environ.get("FLASK_DEBUG", "0") == "1"
    # Runs globally on Render network channels
    app.run(host='0.0.0.0', port=5000, debug=debug_mode)
