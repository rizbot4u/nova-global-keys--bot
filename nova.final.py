"""Nova Global Keys — Telegram bot with DKHYR on-chain transfer.

Routes through Nova Bridge (:8001) for exchange + on-chain skills.
Jarvis AI Registry (:8000) for natural-language skill selection.
"""
from __future__ import annotations

import os
import time
import html
import httpx
import telebot
from telebot import types
from dotenv import load_dotenv

load_dotenv()

# ── Config ────────────────────────────────────────────────────
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
BRIDGE_URL     = os.environ.get("BRIDGE_URL", "http://127.0.0.1:8001")
BRIDGE_TOKEN   = os.environ.get("BRIDGE_TOKEN", "")
JARVIS_URL     = os.environ.get("JARVIS_URL", "http://127.0.0.1:8000")
JARVIS_USER    = os.environ.get("JARVIS_USER", "owner1")
JARVIS_PASS    = os.environ.get("JARVIS_PASS", "password123")

BYBIT_CLIENT_ID    = os.environ.get("BYBIT_CLIENT_ID", "x9dmxAGkDDoa")
BYBIT_REDIRECT_URI = os.environ.get("BYBIT_REDIRECT_URI",
                                    "https://unremonstrative-hyperintellectual-latoya.ngrok-free.dev/api/auth/callback/bybit")
BROKER_CODE        = os.environ.get("BROKER_CODE", "Kr000820")
DKHYR_CONTRACT     = "0x9991bE994829601F90328CCF9cee4D1A55ADae70"
BASESCAN_TX        = "https://basescan.org/tx/"

# Transfer config
TREASURY_TENANT = os.environ.get("TREASURY_TENANT", "tenant_alpha")
DKHYR_PER_USER  = float(os.environ.get("DKHYR_PER_USER", "1"))

bot = telebot.TeleBot(TELEGRAM_TOKEN, parse_mode="HTML")

# In-memory trackers (move to db.py for production)
_sent_today: dict[int, float] = {}
_sent_at:    dict[int, float] = {}
_pending:    dict[int, dict]  = {}
_token_cache: dict[int, tuple[str, float]] = {}


def h(x):
    return html.escape(str(x), quote=False)


def tenant_for(u):
    return f"tenant_{u.id}", f"org_{u.id}"


# ── Bridge + Jarvis helpers ───────────────────────────────────
def bridge_execute(skill_name, parameters, tenant_id, org_id="default_org", actor="bot"):
    try:
        r = httpx.post(
            f"{BRIDGE_URL}/skills/execute",
            headers={"X-Bridge-Token": BRIDGE_TOKEN,
                     "Content-Type": "application/json"},
            json={
                "skill_name": skill_name,
                "tenant_id": tenant_id,
                "org_id": org_id,
                "actor": actor,
                "parameters": parameters,
            },
            timeout=30.0,
        )
        if r.status_code >= 400:
            return {"error": f"HTTP {r.status_code}: {r.text[:250]}"}
        return r.json()
    except Exception as e:
        return {"error": str(e)}


def get_jarvis_token(user_id: int) -> str:
    now = time.time()
    c = _token_cache.get(user_id)
    if c and c[1] > now:
        return c[0]
    try:
        r = httpx.post(f"{JARVIS_URL}/token",
                       data={"username": JARVIS_USER, "password": JARVIS_PASS},
                       timeout=5.0)
        if r.status_code == 200:
            tok = r.json().get("access_token")
            if tok:
                _token_cache[user_id] = (tok, now + 3000)
                return tok
    except Exception:
        pass
    return ""


def run_jarvis_agent(prompt: str, jwt: str) -> dict:
    try:
        r = httpx.post(f"{JARVIS_URL}/agent/run",
                       headers={"Authorization": f"Bearer {jwt}",
                                "Content-Type": "application/json"},
                       json={"prompt": prompt,
                             "payload": {"skill_id": 60,
                                         "arguments": {"prompt": prompt}}},
                       timeout=20.0)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": str(e)}


def health_check() -> dict:
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


# ── Keyboard ──────────────────────────────────────────────────
def main_keyboard():
    m = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    m.add(
        types.KeyboardButton("📊 BTC Price"),
        types.KeyboardButton("💰 Check Balance"),
        types.KeyboardButton("🪙 Send DKHYR"),
        types.KeyboardButton("🔗 My Wallet"),
        types.KeyboardButton("🏅 Verify Brokerage"),
        types.KeyboardButton("🎛️ Nova Menu"),
        types.KeyboardButton("❓ Help"),
    )
    return m


# ── /start /menu ──────────────────────────────────────────────
@bot.message_handler(commands=["start", "help", "menu"])
@bot.message_handler(func=lambda m: m.text in ("❓ Help", "🎛️ Nova Menu"))
def cmd_start(message):
    bot.reply_to(
        message,
        "✨ <b>Nova Global Keys</b> ✨\n"
        "<i>The AI COO for crypto</i>\n\n"
        "🏦 <b>CEX</b> — Bybit · Binance · OKX · KuCoin\n"
        "🔗 <b>DEX</b> — DKHYR on Base · Uniswap V4\n"
        "🛡 <b>CeFi</b> — Broker Tier-3 (Kr000820)\n"
        "⛓ <b>DeFi</b> — On-chain ERC-20 transfers\n\n"
        "🔐 Zero custody · Vault-backed keys\n"
        "📝 Every action audit-logged\n\n"
        "Tap <b>🪙 Send DKHYR</b> to receive 1 DKHYR on Base Mainnet "
        "(once per day per user).",
        reply_markup=main_keyboard(),
    )


# ── /price ────────────────────────────────────────────────────
@bot.message_handler(commands=["price"])
@bot.message_handler(func=lambda m: m.text == "📊 BTC Price")
def cmd_price(message):
    parts = message.text.split()
    symbol = parts[1].upper() if len(parts) > 1 and not parts[1].startswith("📊") else "BTCUSDT"
    if not symbol.endswith("USDT"):
        symbol += "USDT"
    exchange = "bybit"

    tenant_id, org_id = tenant_for(message.from_user)
    status = bot.reply_to(message, "🧠 Routing through Jarvis → Bridge → Bybit…")

    r = bridge_execute(f"{exchange}.ticker",
                       {"symbol": symbol, "category": "linear"},
                       tenant_id, org_id,
                       actor=message.from_user.username or f"user_{message.from_user.id}")

    if "error" in r:
        bot.edit_message_text(f"❌ {h(r['error'][:200])}",
                              message.chat.id, status.message_id)
        return
    try:
        px = r["result"]["result"]["list"][0]["lastPrice"]
        bot.edit_message_text(
            f"📊 <b>{h(symbol)}</b> — {h(exchange)}\n"
            f"💵 <code>${float(px):,.2f}</code>\n\n"
            f"<i>Routed: Jarvis → Bridge → Bybit</i>",
            message.chat.id, status.message_id)
    except Exception:
        bot.edit_message_text(f"⚠️ <pre>{h(str(r)[:400])}</pre>",
                              message.chat.id, status.message_id)


# ── /balance ──────────────────────────────────────────────────
@bot.message_handler(commands=["balance"])
@bot.message_handler(func=lambda m: m.text == "💰 Check Balance")
def cmd_balance(message):
    tenant_id, org_id = tenant_for(message.from_user)
    status = bot.reply_to(message, "🔐 Unlocking vault → Bybit…")

    r = bridge_execute("bybit.balance", {}, tenant_id, org_id,
                       actor=message.from_user.username or f"user_{message.from_user.id}")

    if "error" in r:
        bot.edit_message_text(
            f"❌ {h(r['error'][:200])}\n\n"
            f"Store keys: <code>/setkeys bybit KEY SECRET</code>",
            message.chat.id, status.message_id)
        return

    ret = r.get("result", {})
    if ret.get("retCode", 0) != 0:
        bot.edit_message_text(
            f"⚠️ Bybit: <code>{h(ret.get('retMsg','error'))}</code>\n"
            f"Try refreshing keys with <code>/setkeys bybit …</code>",
            message.chat.id, status.message_id)
        return

    try:
        row = ret["result"]["list"][0]
        equity = row.get("totalEquity", "0")
        coins = [c for c in row.get("coin", [])
                 if float(c.get("walletBalance", 0) or 0) > 0]
        lines = [f"💰 <b>Bybit Unified Wallet</b>",
                 f"Equity: <code>{h(equity)}</code>", ""]
        for c in coins[:10]:
            usd = c.get("usdValue", "0")
            lines.append(f"• <b>{h(c['coin'])}</b>: "
                         f"<code>{h(c['walletBalance'])}</code> (≈ ${h(usd)})")
        lines.append("")
        lines.append(f"<i>Vault-backed: {r.get('used_tenant_creds', False)}</i>")
        bot.edit_message_text("\n".join(lines),
                              message.chat.id, status.message_id)
    except Exception:
        bot.edit_message_text(f"⚠️ <pre>{h(str(r)[:400])}</pre>",
                              message.chat.id, status.message_id)


# ── /wallet — read DKHYR balance ──────────────────────────────
@bot.message_handler(commands=["wallet"])
@bot.message_handler(func=lambda m: m.text == "🔗 My Wallet")
def cmd_wallet(message):
    parts = message.text.split()
    if len(parts) != 2 or not parts[1].startswith("0x"):
        bot.reply_to(message,
            "Send me a Base wallet address:\n<code>/wallet 0xYourAddress</code>")
        return
    addr = parts[1]
    tenant_id, _ = tenant_for(message.from_user)
    r = bridge_execute("dkhyr.balance", {"address": addr}, tenant_id)
    if "error" in r:
        bot.reply_to(message, f"❌ {h(r['error'][:200])}")
        return
    try:
        bal = r["result"]["formattedBalance"]
        bot.reply_to(
            message,
            f"🪙 <b>DKHYR Balance</b>\n"
            f"<code>{h(addr)}</code>\n"
            f"<b>{h(bal)}</b> DKHYR\n\n"
            f"<a href='https://basescan.org/token/{DKHYR_CONTRACT}?a={h(addr)}'>View on Basescan</a>",
            disable_web_page_preview=True)
    except Exception:
        bot.reply_to(message, f"⚠️ <pre>{h(str(r)[:400])}</pre>")


# ── 🪙 SEND DKHYR ─────────────────────────────────────────────
def daily_remaining(user_id: int) -> float:
    now = time.time()
    if now - _sent_at.get(user_id, 0) > 86400:
        _sent_today[user_id] = 0
    return DKHYR_PER_USER - _sent_today.get(user_id, 0)


@bot.message_handler(commands=["transfer"])
@bot.message_handler(func=lambda m: m.text == "🪙 Send DKHYR")
def cmd_transfer(message):
    parts = message.text.split()
    if len(parts) == 3 and parts[1].startswith("0x"):
        try:
            amount = float(parts[2])
        except ValueError:
            bot.reply_to(message, "Amount must be a number.")
            return
        _start_transfer(message, parts[1], amount)
        return

    _pending[message.from_user.id] = {"stage": "await_address"}
    bot.reply_to(
        message,
        "🪙 <b>Send DKHYR</b>\n\n"
        f"You can receive <b>up to {DKHYR_PER_USER} DKHYR</b> per day.\n\n"
        "Send me your Base wallet address (must start with <code>0x</code>).\n"
        "Or use: <code>/transfer 0xYourAddress 1</code>")


@bot.message_handler(func=lambda m: _pending.get(m.from_user.id, {}).get("stage") == "await_address")
def _receive_address(message):
    address = message.text.strip()
    if not address.startswith("0x") or len(address) != 42:
        bot.reply_to(message,
            "⚠️ That doesn't look like a Base address. Try again "
            "(0x + 40 hex characters).")
        return
    _start_transfer(message, address, DKHYR_PER_USER)


def _start_transfer(message, to_address, amount):
    user_id = message.from_user.id
    remaining = daily_remaining(user_id)

    if remaining <= 0:
        bot.reply_to(message,
            f"🚫 <b>Daily limit reached</b>\n"
            f"You've already received {DKHYR_PER_USER} DKHYR today. "
            f"Come back in 24 hours.")
        _pending.pop(user_id, None)
        return

    amount = min(amount, remaining)
    _pending[user_id] = {"stage": "confirm",
                         "address": to_address, "amount": amount}

    m = types.InlineKeyboardMarkup()
    m.add(types.InlineKeyboardButton("✅ Confirm transfer", callback_data="do_transfer"))
    m.add(types.InlineKeyboardButton("❌ Cancel",          callback_data="cancel_transfer"))

    bot.reply_to(
        message,
        f"🔍 <b>Review transfer</b>\n\n"
        f"<b>To:</b> <code>{h(to_address)}</code>\n"
        f"<b>Amount:</b> {amount} DKHYR\n"
        f"<b>Network:</b> Base Mainnet\n"
        f"<b>From:</b> Nova Treasury\n\n"
        f"Tap confirm to sign &amp; send.",
        reply_markup=m)


@bot.callback_query_handler(func=lambda c: c.data in ("do_transfer", "cancel_transfer"))
def _confirm_callback(call):
    user_id = call.from_user.id
    pending = _pending.pop(user_id, None)

    if call.data == "cancel_transfer" or not pending:
        bot.edit_message_text("❌ Transfer cancelled.",
                              call.message.chat.id, call.message.message_id)
        return

    bot.edit_message_text("⚡ Signing &amp; broadcasting on Base Mainnet…",
                          call.message.chat.id, call.message.message_id)

    r = bridge_execute(
        "dkhyr.transfer",
        {"to_address": pending["address"],
         "amount": str(pending["amount"]),
         "confirm": True},
        TREASURY_TENANT,
        org_id="default_org",
        actor=f"tg_{user_id}")

    if "error" in r:
        bot.edit_message_text(f"❌ <b>Bridge error</b>\n<code>{h(r['error'][:300])}</code>",
                              call.message.chat.id, call.message.message_id)
        return

    result = r.get("result", {})
    if result.get("status") != "success":
        err = result.get("error") or str(result)[:300]
        bot.edit_message_text(f"❌ <b>Transfer failed</b>\n<code>{h(err[:300])}</code>",
                              call.message.chat.id, call.message.message_id)
        return

    tx = result["txHash"]
    _sent_today[user_id] = _sent_today.get(user_id, 0) + pending["amount"]
    _sent_at[user_id] = time.time()

    bot.edit_message_text(
        f"✅ <b>Transfer sent on Base Mainnet</b>\n\n"
        f"<b>To:</b> <code>{h(pending['address'])}</code>\n"
        f"<b>Amount:</b> {pending['amount']} DKHYR\n"
        f"<b>Tx:</b> <code>{h(tx)}</code>\n\n"
        f"<a href='{BASESCAN_TX}{h(tx)}'>View on Basescan →</a>",
        call.message.chat.id, call.message.message_id)


# ── Verify + setkeys ──────────────────────────────────────────
@bot.message_handler(commands=["verify"])
@bot.message_handler(func=lambda m: m.text == "🏅 Verify Brokerage")
def cmd_verify(message):
    state_value = f"tg-{message.from_user.id}"
    oauth_url = (f"https://www.bybit.com/en/oauth?client_id={BYBIT_CLIENT_ID}"
                 f"&redirect_uri={BYBIT_REDIRECT_URI}"
                 f"&response_type=code&scope=openapi"
                 f"&state={state_value}")
    bot.reply_to(
        message,
        "🏅 <b>Nova Global Keys — Verified Brokerage</b>\n\n"
        f"<b>Bybit Broker Code:</b> <code>{h(BROKER_CODE)}</code>\n"
        f"<b>Tier:</b> 3 (Institutional)\n\n"
        "🔗 <b>Official links</b>\n"
        "• <a href='https://www.bybit.com/en/verification/'>Bybit Verification</a>\n"
        f"• <a href='{h(oauth_url)}'>Connect Bybit via OAuth</a>\n"
        f"• <a href='https://basescan.org/token/{DKHYR_CONTRACT}'>DKHYR on Basescan</a>\n\n"
        "🔐 <b>Zero custody guarantee</b>\n"
        "• We never hold funds\n"
        "• Keys encrypted per-tenant (AES-256-GCM)\n"
        "• Every action audit-logged",
        disable_web_page_preview=True)


@bot.message_handler(commands=["setkeys"])
def cmd_setkeys(message):
    parts = message.text.split()
    if len(parts) != 4:
        bot.reply_to(message,
            "Usage: <code>/setkeys bybit API_KEY API_SECRET</code>\n\n"
            "Your message is auto-deleted. Keys are encrypted in your "
            "tenant vault.")
        return
    _, exchange, api_key, api_secret = parts
    if exchange.lower() != "bybit":
        bot.reply_to(message, "Only <b>bybit</b> is supported right now.")
        return

    try:
        bot.delete_message(message.chat.id, message.message_id)
    except Exception:
        pass

    tenant_id, _ = tenant_for(message.from_user)
    try:
        r = httpx.post(
            f"{BRIDGE_URL}/v1/keys/store",
            headers={"X-Bridge-Token": BRIDGE_TOKEN,
                     "Content-Type": "application/json"},
            json={"tenant_id": tenant_id,
                  "api_key": api_key,
                  "api_secret": api_secret},
            timeout=15)
        if r.status_code >= 400:
            bot.send_message(message.chat.id,
                f"❌ Vault error: <code>{h(r.text[:200])}</code>")
            return
        bot.send_message(message.chat.id,
            f"✅ <b>Keys encrypted in your vault</b>\n\n"
            f"• Tenant: <code>{h(tenant_id)}</code>\n"
            f"• Exchange: <code>bybit</code>\n"
            f"• Cipher: AES-256-GCM\n"
            f"• Derivation: PBKDF2 (100k iterations)\n\n"
            f"Run /balance to verify.")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ {h(str(e)[:200])}")


# ── /status ───────────────────────────────────────────────────
@bot.message_handler(commands=["status"])
def cmd_status(message):
    hs = health_check()
    jwt = get_jarvis_token(message.from_user.id)
    skills = "?"
    if jwt:
        try:
            r = httpx.get(f"{JARVIS_URL}/skills/active",
                          headers={"Authorization": f"Bearer {jwt}"},
                          timeout=5)
            if r.status_code == 200:
                skills = len(r.json())
        except Exception:
            pass
    bot.reply_to(
        message,
        f"🏗️ <b>Nova Stack Health</b>\n\n"
        f"Jarvis Registry: {'✅' if hs['jarvis'] else '❌'}\n"
        f"Nova Bridge:     {'✅' if hs['bridge'] else '❌'}\n"
        f"Active skills:   <code>{skills}</code>\n\n"
        f"<i>Every action is tenant-isolated, vault-backed, and audited.</i>",
        reply_markup=main_keyboard())


# ── Natural language fallback ─────────────────────────────────
@bot.message_handler(func=lambda m: True, content_types=["text"])
def fallback(message):
    txt = message.text.lower()

    if any(k in txt for k in ("btc", "eth", "price")):
        symbol = "BTCUSDT" if "btc" in txt else "ETHUSDT" if "eth" in txt else "BTCUSDT"
        message.text = f"/price {symbol} bybit"
        cmd_price(message)
        return

    if "balance" in txt:
        cmd_balance(message)
        return

    if "dkhyr" in txt and ("send" in txt or "transfer" in txt):
        cmd_transfer(message)
        return

    # Else → Jarvis agent
    jwt = get_jarvis_token(message.from_user.id)
    if not jwt:
        bot.reply_to(message, "⚠️ Jarvis auth failed. Try /menu.",
                     reply_markup=main_keyboard())
        return

    status = bot.reply_to(message, "🧠 <b>Jarvis is analyzing…</b>")
    res = run_jarvis_agent(message.text, jwt)
    if "error" in res:
        bot.edit_message_text(
            f"🤖 <i>{h(res['error'][:200])}</i>\n\nTip: use /menu.",
            message.chat.id, status.message_id)
        return
    ex = res.get("execution_response", {})
    bot.edit_message_text(
        f"🧠 <b>Jarvis AI COO</b>\n\n"
        f"Skill: <code>{h(ex.get('skill', '?'))}</code>\n"
        f"Status: <code>{h(ex.get('status', '?'))}</code>\n"
        f"Result: {h(ex.get('result', ''))}",
        message.chat.id, status.message_id)


# ── Run ───────────────────────────────────────────────────────
if __name__ == "__main__":
    print("🚀 Nova live bot starting — transfer feature enabled")
    while True:
        try:
            bot.infinity_polling(timeout=30, long_polling_timeout=30)
        except Exception as e:
            print(f"Polling error: {e} — retry in 5s")
            time.sleep(5)
