"""Bybit OAuth callback receiver. Runs as a small Flask app."""
import os
import sqlite3
import requests
from flask import Flask, request
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__)

DB_PATH = os.path.expanduser(os.environ.get("NOVA_DB", "./nova.db"))
CLIENT_ID = os.environ["BYBIT_CLIENT_ID"]
CLIENT_SECRET = os.environ["BYBIT_CLIENT_SECRET"]
TOKEN_URL = "https://api2.bybit.com/oauth/v1/public/access_token"
OPENAPI_URL = "https://api2.bybit.com/oauth/v1/resource/restrict/openapi"


def db():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


@app.route("/api/auth/callback/bybit")
def callback():
    code = request.args.get("code")
    state = request.args.get("state")  # format: tg-<telegram_id>
    error = request.args.get("error")

    if error or not code or not state:
        return f"❌ Authorization failed: {error or 'missing code'}", 400

    r = requests.post(TOKEN_URL, data={
        "grant_type": "authorization_code",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "code": code,
    }, timeout=15)
    body = r.json()
    if "access_token" not in body:
        return f"❌ Token exchange failed: {body}", 400

    access = body["access_token"]
    r2 = requests.get(OPENAPI_URL,
                      headers={"Authorization": f"Bearer {access}"},
                      timeout=15).json()
    if r2.get("ret_code") != 0:
        return f"❌ Could not fetch API key: {r2}", 400

    api_key = r2["result"]["api_key"]
    api_secret = r2["result"]["api_secret"]

    tg_id = int(state.replace("tg-", "")) if state.startswith("tg-") else None
    if tg_id:
        with db() as c:
            c.execute("""
                INSERT INTO api_keys (telegram_id, exchange, api_key, api_secret)
                VALUES (?, 'bybit', ?, ?)
                ON CONFLICT(telegram_id, exchange) DO UPDATE SET
                    api_key=excluded.api_key, api_secret=excluded.api_secret
            """, (tg_id, api_key, api_secret))

    return "<h2>✅ Bybit connected</h2><p>Return to Telegram.</p>", 200


@app.route("/")
def health():
    return {"service": "nova-oauth-callback", "status": "ok"}


if __name__ == "__main__":
    port = int(os.environ.get("OAUTH_PORT", "9876"))
    app.run(host="0.0.0.0", port=port)
