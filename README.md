# FGURL VIP

Flask backend + static frontend for the FGURL VIP portal (registration, login,
VIP card generation with QR codes, and Paystack payment verification).

## Setup

```bash
pip install -r requirements.txt
python app.py
```

Open **http://127.0.0.1:5000** in your browser.

## Environment variables

Set these on Render (service → Environment) or locally before running:

| Variable | Value | Purpose |
|---|---|---|
| `PAYSTACK_SECRET_KEY` | `sk_live_...` (or `sk_test_...` locally) | Server-side payment verification |
| `PAYSTACK_PUBLIC_KEY` | `pk_live_...` (or `pk_test_...` locally) | Browser checkout key |
| `PAYSTACK_SUBACCOUNT` | `ACCT_...` (optional) | Revenue split — leave EMPTY to take 100% |
| `ADMIN_TOKEN` | any secret word | Unlocks `/admin.html` order monitor |

Get them from: Paystack Dashboard → Settings → API Keys & Webhooks.

## Admin order monitor

Open `/admin.html`, enter your `ADMIN_TOKEN`, and you'll see every
payment and VIP card in real time (auto-refreshes every 15s).

## VIP tiers

| Tier | Price | Validity |
|---|---|---|
| Blue | ₦1,500 | 30 days |
| Red | ₦3,000 | 90 days |
| Yellow | ₦4,500 | 180 days |
| Black | ₦6,000 | 365 days |

## Deploy to Render

1. Push this repo to GitHub.
2. Render → New Web Service → connect the repo.
3. Build command: `pip install -r requirements.txt`
4. Start command: `gunicorn --bind 0.0.0.0:$PORT app:app`
5. Add the environment variables above.

## Notes

- SQLite (`database.db`) is ephemeral on Render — it resets on every deploy.
  Switch to Render Postgres for persistent data.
- `/api/vip-checkout` and `/api/checkout-live` verify every payment
  directly with Paystack and recompute prices server-side.
- Keep the admin token secret.
