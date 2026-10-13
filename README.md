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

| Variable | Value | Where |
|---|---|---|
| `PAYSTACK_SECRET_KEY` | your `sk_live_...` (or `sk_test_...` locally) | Render → Environment / local shell |
| `PAYSTACK_PUBLIC_KEY` | your `pk_live_...` (or `pk_test_...` locally) | Render → Environment / local shell |

Get them from: Paystack Dashboard → Settings → API Keys & Webhooks.

## Deploy to Render

1. Push this repo to GitHub.
2. Render → New Web Service → connect the repo.
3. Build command: `pip install -r requirements.txt`
4. Start command: `gunicorn app:app`
5. Add the two environment variables above.

## Notes

- SQLite (`database.db`) is ephemeral on Render — it resets on every deploy.
  Switch to Render Postgres for persistent data.
- `/api/create-vip` and `/api/transactions` currently have no authentication.
  Add login checks before public launch.
