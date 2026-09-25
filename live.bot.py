"""Nova Global Keys — Telegram bot (Jarvis AI COO + Nova Bridge integrated).

Frontend that routes every user action through:
  - Nova MCP Bridge  (:8001) — vault, policy, audit
  - Jarvis Registry  (:8000) — AI skill selection via /agent/run
"""
from __future__ import annotations

import os
import time
import httpx
import telebot
from telebot import types
from dotenv import load_dotenv

import db
import dex
import engine

load_dotenv()

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
BRIDGE_URL     = os.environ.get("BRIDGE_URL", "http://127.0.0.1:8001")
BRIDGE_TOKEN   = os.environ.get("BRIDGE_TOKEN", "")   # move to .env!
JARVIS_URL     = os.environ.get("JARVIS_URL", "http://127.0.0.1:8000")
JARVIS_USER    = os.environ.get("JARVIS_USER", "owner1")
JARVIS_PASS    = os.environ.get("JARVIS_PASS", "password123")

ADMIN_ID          = int(os.environ.get("ADMIN_TELEGRAM_ID", "0") or 0)
BYBIT_CLIENT_ID   = os.environ.get("BYBIT_CLIENT_ID", "")
BYBIT_REDIRECT_URI = os.environ.get("BYBIT_REDIRECT_URI", "")

bot = telebot.TeleBot(TELEGRAM_TOKEN, parse_mode="Markdown")
db.init()

_token_cache: dict[int, tuple[str, float]] = {}


# ── tenant mapping ──────────────────────────────────────────────
def get_tenant(msg_user):
    """Deterministic per-user tenant. No schema change needed."""
    db.ensure_user(msg_user.id, msg_user.username or "")
    return f"tenant_{msg_user.id}", f"org_{msg_user.id}"


# ── Jarvis JWT ──────────────────────────────────────────────────
def get_jarvis_token(user_id: int) -> str:
    now = time.time()
    cached = _token_cache.get(user_id)
    if cached and cached[1] > now:
        return cached[0]
    try:
        r = httpx.post(
            f"{JARVIS_URL}/token",
            data={"username": JARVIS_USER, "password": JARVIS_PASS},
            timeout=5.0,
        )
        if r.status_code == 200:
            tok = r.json().get("access_token")
            if tok:
                _token_cache[user_id] = (tok, now + 3000)
                return tok
    except Exception:
        pass
    return ""


# ── Bridge call ─────────────────────────────────────────────────
def execute_bridge_skill(skill_name, parameters, tenant_id, org_id, actor) -> dict:
    headers = {"X-Bridge-Token": BRIDGE_TOKEN, "Content-Type": "application/json"}
    payload = {
        "skill_name": skill_name,
        "tenant_id": tenant_id,
        "org_id": org_id,
        "actor": actor,
        "parameters": parameters,
    }
    try:
        r = httpx.post(f"{BRIDGE_URL}/skills/execute", json=payload,
                       headers=headers, timeout=12.0)
        if r.status_code >= 400:
            return {"error": f"HTTP {r.status_code}: {r.text[:200]}"}
        return r.json()
    except Exception as e:
        return {"error": str(e)}


# ── Jarvis agent call ───────────────────────────────────────────
def run_jarvis_agent(prompt: str, jwt: str) -> dict:
    headers = {"Authorization": f"Bearer {jwt}", "Content-Type": "application/json"}
    try:
        r = httpx.post(f"{JARVIS_URL}/agent/run",
                       json={"prompt": prompt}, headers=headers, timeout=20.0)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": str(e)}


# ── health ──────────────────────────────────────────────────────
def _health() -> dict:
    out = {"bridge": False, "jarvis": False}
    try:
        out["bridge"] = httpx.get(f"{BRIDGE_URL}/", timeout=3).status_code == 200
    except Exception:
        pass
    try:
        out["jarvis"] = httpx.get(f"{JARVIS_URL}/", timeout=3).status_code == 200
    except Exception:
        pass
    return out


# ── commands ────────────────────────────────────────────────────
@bot.message_handler(commands=["start", "help"])
def cmd_help(message):
    get_tenant(message.from_user)
    bot.reply_to(
        message,
        "✨ *Nova Global Keys* ✨\n\n"
        "📈 *Trading (via Nova Bridge)*:\n"
        "/price <SYMBOL> [exchange] — Live price from vaulted creds\n"
        "/balance — Your account balance\n"
        "/trade <exchange> <buy|sell> <SYMBOL> <qty> — Market order\n"
        "/wallet <address> — DKHYR on Base Mainnet\n\n"
        "🤖 *Jarvis AI COO*:\n"
        "Just type naturally — *\"what's btc on bybit\"*, *\"my balance\"*\n\n"
        "🩺 /status — Live health of the stack",
    )


@bot.message_handler(commands=["status"])
def cmd_status(message):
    h = _health()
    jwt = get_jarvis_token(message.from_user.id)
    skills_count = "?"
    if jwt:
        try:
            r = httpx.get(f"{JARVIS_URL}/skills/active",
                          headers={"Authorization": f"Bearer {jwt}"}, timeout=5)
            if r.status_code == 200:
                skills_count = len(r.json())
        except Exception:
            pass
    bot.reply_to(
        message,
        f"🏗️ *Nova Stack Health*\n\n"
        f"Jarvis Registry : {'✅' if h['jarvis'] else '❌'}\n"
        f"Nova Bridge     : {'✅' if h['bridge'] else '❌'}\n"
        f"Active skills   : `{skills_count}`\n\n"
        f"_Every action is tenant-isolated, vault-backed, and audited._",
    )


@bot.message_handler(commands=["connect"])
def cmd_connect(message):
    get_tenant(message.from_user)
    if not BYBIT_CLIENT_ID or not BYBIT_REDIRECT_URI:
        bot.reply_to(message, "Bybit OAuth is not configured on this environment.")
        return
    state = f"tg-{message.from_user.id}"
    url = (
        f"https://www.bybit.com/en/oauth?client_id={BYBIT_CLIENT_ID}"
        f"&redirect_uri={BYBIT_REDIRECT_URI}&response_type=code"
        f"&scope=openapi&state={state}"
    )
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔗 Connect Bybit Vault", url=url))
    bot.reply_to(
        message,
        "Tap below to securely link your account. Keys stay in your tenant vault.",
        reply_markup=markup,
    )


@bot.message_handler(commands=["price"])
def cmd_price(message):
    tenant_id, org_id = get_tenant(message.from_user)
    parts = message.text.split()
    if len(parts) < 2:
        bot.reply_to(message, "Usage: `/price BTC [exchange]`")
        return
    symbol   = engine._sym(parts[1])
    exchange = parts[2].lower() if len(parts) > 2 else "bybit"

    status = bot.reply_to(message, "🧠 *Routing through Jarvis → Nova Bridge…*")

    result = execute_bridge_skill(
        skill_name=f"{exchange}.ticker",
        parameters={"symbol": symbol, "category": "linear"},
        tenant_id=tenant_id,
        org_id=org_id,
        actor=message.from_user.username or f"user_{message.from_user.id}",
    )

    if "error" in result:
        bot.edit_message_text(
            f"❌ Bridge error: `{result['error'][:200]}`",
            message.chat.id, status.message_id,
        )
        return

    try:
        last = result["result"]["result"]["list"][0]["lastPrice"]
        bot.edit_message_text(
            f"📊 *{symbol}* on *{exchange}*\n"
            f"💵 ${float(last):,.2f}\n\n"
            f"_Routed: Jarvis → Bridge → {exchange.capitalize()}_",
            message.chat.id, status.message_id,
        )
    except Exception:
        bot.edit_message_text(
            f"📊 Raw response:\n`{str(result)[:300]}`",
            message.chat.id, status.message_id,
        )


@bot.message_handler(commands=["wallet"])
def cmd_wallet(message):
    get_tenant(message.from_user)
    parts = message.text.split()
    if len(parts) != 2:
        bot.reply_to(message, "Usage: `/wallet 0xYourAddress`")
        return
    if not dex.connected():
        bot.reply_to(message, "Base Mainnet RPC is offline.")
        return
    bal = dex.balance(parts[1])
    bot.reply_to(message, f"🪙 *DKHYR*\n`{parts[1]}`\n**{bal:,.2f} DKHYR**")


# ── natural language → Jarvis ───────────────────────────────────
@bot.message_handler(func=lambda m: True, content_types=["text"])
def natural_handler(message):
    get_tenant(message.from_user)
    user_id = message.from_user.id

    jwt = get_jarvis_token(user_id)
    if not jwt:
        bot.reply_to(message, "⚠️ Jarvis backend auth pending. Try again shortly.")
        return

    status = bot.reply_to(message, "🧠 *Jarvis is analyzing your intent…*")
    agent = run_jarvis_agent(message.text, jwt)

    if "error" in agent:
        # Fall back to regex engine
        intent = engine.parse(message.text)
        action = intent.get("action")
        if action == "price" and intent.get("symbol"):
            bot.edit_message_text(
                f"📊 Fallback price route needed for `{intent['symbol']}` — use /price",
                message.chat.id, status.message_id,
            )
        else:
            bot.edit_message_text(
                f"🤖 Jarvis notice: `{agent['error'][:200]}`",
                message.chat.id, status.message_id,
            )
        return

    exec_resp = agent.get("execution_response", {})
    skill     = exec_resp.get("skill", "unknown")
    result    = exec_resp.get("result", "")

    bot.edit_message_text(
        f"🧠 *Jarvis AI COO*\n"
        f"Selected: `{skill}`\n"
        f"Status: `{exec_resp.get('status', 'unknown')}`\n"
        f"Result: {result}\n\n"
        f"_Routed: Telegram → Jarvis → Bridge → Executed_",
        message.chat.id, status.message_id,
    )


if __name__ == "__main__":
    print("🚀 Nova Bridge & Jarvis-integrated bot active...")
    while True:
        try:
            bot.infinity_polling(timeout=30, long_polling_timeout=30)
        except Exception as e:
            print(f"Polling error: {e} — retrying in 5s")
            time.sleep(5)
