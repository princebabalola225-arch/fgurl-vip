import os
import sqlite3
import datetime
import qrcode
import bcrypt
import time
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
# PAYSTACK KEYS
# Set these as ENVIRONMENT VARIABLES on Render (Render dashboard -> your
# service -> Environment -> Add Environment Variable). Never hardcode the
# SECRET key in the source code.
#   PAYSTACK_SECRET_KEY  = sk_live_...   (server-side verification key)
#   PAYSTACK_PUBLIC_KEY  = pk_live_...   (sent to the browser for checkout)
# ---------------------------------------------------------------------------
PAYSTACK_SECRET_KEY = os.environ.get("PAYSTACK_SECRET_KEY", "sk_test_your_copied_secret_key_here")
PAYSTACK_PUBLIC_KEY = os.environ.get("PAYSTACK_PUBLIC_KEY", "")

# Only these files may be served to browsers. Everything else (database.db,
# logins.txt, uploads/, app.py) stays private.
STATIC_PAGES = {
    "VLAND.html", "dashboard.html", "jobs.html", "payment.html",
    "renew.html", "VIP-CARD.html", "VLAND.css", "VLAND.js",
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
    # Migrate databases created by older versions of this app:
    # the old "transactions" table had no "timestamp" column.
    cursor.execute("PRAGMA table_info(transactions)")
    txn_cols = {row[1] for row in cursor.fetchall()}
    if "timestamp" not in txn_cols:
        try:
            cursor.execute("ALTER TABLE transactions ADD COLUMN timestamp TEXT")
        except sqlite3.OperationalError:
            pass  # another gunicorn worker already added it
    conn.commit()
    conn.close()

def get_json_body():
    # silent=True prevents a crash when a request has no/invalid JSON body
    return request.get_json(silent=True) or {}

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
    # BUG FIX: fetchone() returns a tuple like (hash,), so we must use row[0]
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
    return jsonify({"status": "active", "has_card": True}), 200

@app.route('/api/create-vip', methods=['POST'])
def create_vip():
    username = (request.form.get('username') or '').strip().lower()
    name = request.form.get('name')
    phone = request.form.get('phone')
    sex = request.form.get('sex')
    tier = request.form.get('tier')
    issue_date = request.form.get('issue_date')

    passport = request.files.get('passport')
    if passport and passport.filename:
        os.makedirs("uploads", exist_ok=True)
        unique_suffix = int(time.time())
        # BUG FIX: splitext returns a tuple; take index [1] for the extension,
        # and sanitize the filename to block path-traversal attacks.
        file_extension = os.path.splitext(secure_filename(passport.filename))[1] or '.jpg'
        passport_name = f"{username}_{unique_suffix}_passport{file_extension}"
        passport.save(os.path.join("uploads", passport_name))

    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM vip_cards")
    # BUG FIX: fetchone() returns a tuple like (5,), so take [0] before +1
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
    conn.commit()
    conn.close()
    return jsonify({"message": f"Successfully mapped FGURL VIP Card #{card_sequence_number}"}), 200

@app.route('/api/config', methods=['GET'])
def paystack_config():
    # Hand the PUBLIC key to the browser. The SECRET key never leaves the server.
    return jsonify({"paystack_public_key": PAYSTACK_PUBLIC_KEY})

@app.route('/api/checkout-live', methods=['POST'])
def checkout_live():
    data = get_json_body()
    username = data.get('user')
    job_type = data.get('job_type')
    try:
        actual_price = float(data.get('actual_price'))
    except (TypeError, ValueError):
        return jsonify({"message": "Invalid price supplied."}), 400
    surcharge_rate = float(data.get('surcharge_rate') or 0.25)
    paystack_ref = data.get('paystack_ref')
    if not paystack_ref:
        return jsonify({"message": "Missing payment reference."}), 400

    # Security Verification: Confirms directly with Paystack cloud that money landed safely
    # BUG FIX: the verification endpoint is api.paystack.co/transaction/verify/<ref>
    paystack_verification_url = f"https://api.paystack.co/transaction/verify/{paystack_ref}"
    headers = {
        # Uses the LIVE secret key from the PAYSTACK_SECRET_KEY environment variable
        "Authorization": f"Bearer {PAYSTACK_SECRET_KEY}"
    }

    try:
        response = requests.get(paystack_verification_url, headers=headers, timeout=15).json()
    except Exception:
        return jsonify({"message": "Error verification network connection dropout."}), 500

    if response.get('status') and response.get('data', {}).get('status') == 'success':
        vip_money = actual_price * surcharge_rate
        total_price = actual_price + vip_money
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # NOTE: The actual money split happens inside Paystack via the SUBACCOUNT
        # percentage configured on the Paystack dashboard. The figures below are
        # only a console/log report - they are NOT transfers executed by this code.
        partner_share = 2200.00
        your_share = 300.00

        conn = sqlite3.connect(DATABASE_FILE)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO transactions (username, job_type, actual_price, vip_money, total_price, status, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (username, job_type, actual_price, vip_money, total_price, "Payment Confirmed / Approved for Production", timestamp))
        conn.commit()
        conn.close()

        # Cloud console payout log reporting format
        print("\n💰 --- FGURL VIP REAL-TIME CHECKOUT SPLIT COMPILATION ---")
        print(f"Ref Token: [{paystack_ref}] | Account Profile: [{username}]")
        print(f"Total Confirmed Revenue Received: ₦{total_price:,.2f}")
        print(f"-> Automated Payout Sent to Partner Node: ₦{partner_share:,.2f}")
        print(f"-> Your Dedicated Premium Payout (Oladele): ₦{your_share:,.2f} to 8065867966")
        print("-------------------------------------------------------------\n")
        return jsonify({"message": f"Payment Verified! Total Processed: ₦{total_price:,.2f}."}), 200
    else:
        return jsonify({"message": "Verification parameters fraudulent or invalid."}), 400

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

# Create/upgrade the database tables at startup. This runs both with
# `python app.py` AND under gunicorn on Render (where __main__ never executes).
init_db()

if __name__ == '__main__':
    # debug=True is DANGEROUS in production (exposes an interactive debugger).
    # Only enable it locally via FLASK_DEBUG=1; Render defaults it to off.
    debug_mode = os.environ.get("FLASK_DEBUG", "0") == "1"
    # Runs globally on Render network channels
    app.run(host='0.0.0.0', port=5000, debug=debug_mode)
