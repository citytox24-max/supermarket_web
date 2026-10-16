# Supermarket POS (web version) — pentest target

Flask + SQLite rewrite of the desktop app, built as a quick live target.

## Run locally
    pip install -r requirements.txt
    python app.py
Open http://localhost:5000

Seeded accounts:
- admin / admin123  (role: admin)
- cashier / cashier123  (role: cashier)

## Fastest way to get a link today (no account/signup)
From this folder, with the app running locally on port 5000:
    npx localtunnel --port 5000
or, if you have ngrok installed:
    ngrok http 5000
Either prints a public https:// URL you can send your friend immediately.
Close the tunnel (Ctrl+C) when the test is done.

## A persistent link (survives your laptop sleeping)
Push this folder to a GitHub repo, then deploy on Render.com (free tier):
1. render.com -> New -> Web Service -> connect the repo
2. Build command: pip install -r requirements.txt
3. Start command: gunicorn app:app
Render gives you a permanent https://*.onrender.com URL.
(Vercel/Netlify/GitHub Pages won't work here — they don't run persistent
Python/Flask processes with a database; Render/Railway/Fly.io do.)

## Known residual risk (left in on purpose for the test)
POST /mpesa/callback accepts and applies a payment status update with no
request authentication — mirroring how Safaricom's real Daraja callback
works. A tester should be able to forge a "PAID" status for a
checkout_request_id without ever paying.
