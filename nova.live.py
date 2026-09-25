"""Nova Global Keys — Telegram Test Console + Vault Key Manager."""
from __future__ import annotations
import os, time, json, html, httpx, telebot
from telebot import types
from dotenv import load_dotenv

import db, dex, engine

load_dotenv()

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
BRIDGE_URL     = os.environ.get("BRIDGE_URL", "http://127.0.0.1:8001")
BRIDGE_TOKEN   = os.environ.get("BRIDGE_TOKEN", "")
JARVIS_URL     = os.environ.get("JARVIS_URL", "http://127.0.0.1:8000")
JARVIS_USER    = os.environ.get("JARVIS_USER", "owner1")
JARVIS_PASS    = os.environ.get("JARVIS_PASS", "password123")

BYBIT_CLIENT_ID    = os.environ.get("BYBIT_CLIENT_ID", "x9dmxAGkDDoa")
BYBIT_REDIRECT_URI = os.environ.get("BYBIT_REDIRECT_URI", "https://t.me/Novaglobalkeysbot")
BROKER_CODE        = os.environ.get("BROKER_CODE", "Kr000820")
DKHYR_ADDRESS      = "0x9991bE994829601F90328CCF9cee4D1A55ADae70"
# ── Telegram proxy (bypass ISP blocks) ───────────────────────
PROXY_URL = os.environ.get("TELEGRAM_PROXY", "").strip()
if PROXY_URL:
    from telebot import apihelper
    apihelper.proxy = {"https": PROXY_URL, "http": PROXY_URL}
    print(f"🌐 Telegram via proxy: {PROXY_URL}")
bot = telebot.TeleBot(TELEGRAM_TOKEN, parse_mode="HTML")
db.init()

_token_cache: dict[int, tuple[str, float]] = {}
_session: dict[int, dict] = {}


def h(x):  # HTML-escape dynamic content so Telegram doesn't choke
    return html.escape(str(x), quote=False)


def trunc(s, n=3800):
    return s if len(s) <= n else s[:n] + "…"


# ── tenant / auth ───────────────────────────────────────────────
def get_tenant(u):
    db.ensure_user(u.id, u.username or "")
    return f"tenant_{u.id}", f"org_{u.id}"


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
            t = r.json().get("access_token")
            if t:
                _token_cache[user_id] = (t, now + 3000)
                return t
    except Exception:
        pass
    return ""


# ── bridge calls ────────────────────────────────────────────────
def bridge_headers():
    return {"X-Bridge-Token": BRIDGE_TOKEN, "Content-Type": "application/json"}


def bridge_skill(skill, params, tenant_id, org_id, actor, confirm=False):
    body = {"skill_name": skill, "parameters": params,
            "tenant_id": tenant_id, "org_id": org_id, "actor": actor}
    if confirm:
        body["confirm"] = True
    try:
        r = httpx.post(f"{BRIDGE_URL}/skills/execute",
                       headers=bridge_headers(), json=body, timeout=15.0)
        if r.status_code >= 400:
            return {"error": f"HTTP {r.status_code}: {r.text[:250]}"}
        return r.json()
    except Exception as e:
        return {"error": str(e)}


def vault_store(tenant_id, api_key, api_secret):
    """Persist a tenant's keys in the encrypted vault."""
    try:
        r = httpx.post(f"{BRIDGE_URL}/v1/keys/store",
                       headers=bridge_headers(),
                       json={"tenant_id": tenant_id,
                             "api_key": api_key,
                             "api_secret": api_secret},
                       timeout=15.0)
        if r.status_code >= 400:
            return {"error": f"HTTP {r.status_code}: {r.text[:250]}"}
        return r.json()
    except Exception as e:
        return {"error": str(e)}


# ── menu ────────────────────────────────────────────────────────
@bot.message_handler(commands=["start", "help", "menu", "test"])
def cmd_menu(message):
    get_tenant(message.from_user)
    m = types.InlineKeyboardMarkup(row_width=2)
    m.add(types.InlineKeyboardButton("🩺 Stack Health", callback_data="act_health"),
          types.InlineKeyboardButton("🔑 Get JWT",      callback_data="act_token"))
    m.add(types.InlineKeyboardButton("🌉 Bridge Skills", callback_data="br_skills"),
          types.InlineKeyboardButton("📊 BTC Price",     callback_data="br_btc"))
    m.add(types.InlineKeyboardButton("✅ Jarvis Active", callback_data="jr_active"),
          types.InlineKeyboardButton("📋 Jarvis All",    callback_data="jr_all"))
    m.add(types.InlineKeyboardButton("🆕 Create Skill",  callback_data="jr_create"),
          types.InlineKeyboardButton("▶️ Execute Skill", callback_data="jr_exec"))
    m.add(types.InlineKeyboardButton("🤖 Run AI Agent",  callback_data="jr_agent"),
          types.InlineKeyboardButton("🗑️ Delete Skill",  callback_data="jr_delete"))
    m.add(types.InlineKeyboardButton("🏅 Brokerage Verify", callback_data="act_verify"),
          types.InlineKeyboardButton("💼 My Balances",      callback_data="act_bal"))
    m.add(types.InlineKeyboardButton("🔐 Vault Status",    callback_data="act_vault"))

    bot.reply_to(
        message,
        "🎛️ <b>Nova Stack — Live Test Console</b>\n\n"
        "• 🌉 <b>Bridge</b> calls Nova MCP (:8001)\n"
        "• 🧠 <b>Jarvis</b> calls AI Registry (:8000)\n"
        "• 🏅 <b>Brokerage</b> shows live Bybit verification\n"
        "• 💼 <b>Balances</b> reads via vault keys\n\n"
        "Store your own keys with:\n"
        "<code>/setkeys bybit API_KEY API_SECRET</code>",
        reply_markup=m,
    )


# ── /verify — brokerage proof ───────────────────────────────────
@bot.message_handler(commands=["verify"])
def cmd_verify(message):
    get_tenant(message.from_user)
    oauth_url = (f"https://www.bybit.com/en/oauth?client_id={BYBIT_CLIENT_ID}"
                 f"&redirect_uri={BYBIT_REDIRECT_URI}"
                 f"&response_type=code&scope=openapi")
    bot.reply_to(
        message,
        "🏅 <b>Nova Global Keys — Verified Brokerage</b>\n\n"
        f"<b>Bybit Broker Code:</b> <code>{h(BROKER_CODE)}</code>\n"
        f"<b>Tier:</b> 3 (Institutional)\n\n"
        "🔗 <b>Official links</b>\n"
        f"• <a href='https://www.bybit.com/en/verification/'>Bybit Verification</a>\n"
        f"• <a href='{h(oauth_url)}'>Connect Bybit via OAuth</a>\n"
        f"• <a href='https://basescan.org/token/{DKHYR_ADDRESS}'>DKHYR on Basescan</a>\n"
        f"• <a href='https://www.geckoterminal.com/base/pools/0xa3c44480ae67b44d4ee4796596942fadd5662606ef4a5daf37050e0048733c4d'>DKHYR / Uniswap V4 Pool</a>\n\n"
        "🔐 <b>Zero custody guarantee</b>\n"
        "• We never hold funds\n"
        "• Keys encrypted per-tenant (AES-256-GCM)\n"
        "• Bybit OAuth — keys stay at Bybit\n"
        "• Every action audit-logged",
        disable_web_page_preview=True,
    )


# ── /setkeys — store encrypted keys ─────────────────────────────
@bot.message_handler(commands=["setkeys"])
def cmd_setkeys(message):
    tenant_id, org_id = get_tenant(message.from_user)
    parts = message.text.split()
    if len(parts) != 4:
        bot.reply_to(message,
            "Usage: <code>/setkeys bybit API_KEY API_SECRET</code>\n\n"
            "Your message is auto-deleted. Keys are encrypted in your "
            "tenant vault and never shown again.")
        return
    _, exchange, api_key, api_secret = parts
    if exchange.lower() != "bybit":
        bot.reply_to(message, "Only <b>bybit</b> is supported right now.")
        return

    # Delete the message immediately
    try:
        bot.delete_message(message.chat.id, message.message_id)
    except Exception:
        pass

    # Store in vault via bridge
    result = vault_store(tenant_id, api_key, api_secret)
    if "error" in result:
        bot.send_message(message.chat.id,
            f"❌ Vault store failed: <code>{h(result['error'][:200])}</code>")
        return

    bot.send_message(message.chat.id,
        f"✅ <b>Keys encrypted in your vault</b>\n\n"
        f"• Tenant: <code>{h(tenant_id)}</code>\n"
        f"• Exchange: <code>bybit</code>\n"
        f"• Cipher: AES-256-GCM\n"
        f"• Derivation: PBKDF2 (100k iterations)\n\n"
        f"Run /balance to verify.")


# ── /balance — read from vault ──────────────────────────────────
@bot.message_handler(commands=["balance"])
def cmd_balance(message):
    tenant_id, org_id = get_tenant(message.from_user)
    actor = message.from_user.username or f"user_{message.from_user.id}"

    status = bot.reply_to(message, "🔐 Unlocking vault → Bybit…")
    result = bridge_skill("bybit.balance", {}, tenant_id, org_id, actor)

    if "error" in result:
        bot.edit_message_text(
            f"❌ <code>{h(result['error'][:250])}</code>\n\n"
            f"Tip: store keys first with <code>/setkeys bybit …</code>",
            message.chat.id, status.message_id)
        return

    try:
        data = result["result"]["result"]
        # Bybit V5 wallet-balance format
        rows = data.get("list", [{}])[0]
        equity = rows.get("totalEquity", "0")
        coins = rows.get("coin", [])
        lines = [f"💰 <b>Bybit Unified Wallet</b>",
                 f"<b>Equity:</b> <code>{h(equity)}</code>", ""]
        for c in coins[:10]:
            if float(c.get("walletBalance", 0)) > 0:
                lines.append(
                    f"• <b>{h(c['coin'])}</b>: "
                    f"<code>{h(c.get('walletBalance','0'))}</code>"
                    f" (≈ ${h(c.get('usdValue','0'))})")
        used_vault = result.get("used_tenant_creds", False)
        lines.append("")
        lines.append(f"<i>Vault-backed: {used_vault} • Tenant: {h(tenant_id)}</i>")
        bot.edit_message_text("\n".join(lines),
                              message.chat.id, status.message_id)
    except Exception as e:
        bot.edit_message_text(
            f"⚠️ Unparsed response:\n<pre>{h(str(result)[:500])}</pre>",
            message.chat.id, status.message_id)


# ── /wallet — DKHYR balance ─────────────────────────────────────
@bot.message_handler(commands=["wallet"])
def cmd_wallet(message):
    parts = message.text.split()
    addr = parts[1] if len(parts) > 1 else "0xA4eE963F223C193261d8545e4c4681ED3837af25"
    if not dex.connected():
        bot.reply_to(message, "Base Mainnet RPC offline.")
        return
    bal = dex.balance(addr)
    bot.reply_to(
        message,
        f"🪙 <b>DKHYR — Base Mainnet</b>\n\n"
        f"<b>Wallet:</b> <code>{h(addr)}</code>\n"
        f"<b>Balance:</b> <code>{bal:,.2f} DKHYR</code>\n\n"
        f"🔗 <a href='https://basescan.org/token/{DKHYR_ADDRESS}?a={h(addr)}'>View on Basescan</a>",
        disable_web_page_preview=True)


# ── button handler ──────────────────────────────────────────────
@bot.callback_query_handler(func=lambda c: True)
def on_button(call):
    u = call.from_user
    tenant_id, org_id = get_tenant(u)
    actor = u.username or f"user_{u.id}"
    chat_id = call.message.chat.id
    data = call.data
    bot.answer_callback_query(call.id)

    try:
        if data == "act_health":
            b = httpx.get(f"{BRIDGE_URL}/", timeout=3).json()
            j = httpx.get(f"{JARVIS_URL}/", timeout=3).json()
            bot.send_message(chat_id,
                f"🏗️ <b>Stack Health</b>\n\n"
                f"<b>Bridge:</b> <code>{h(b.get('version', '?'))}</code>\n"
                f"<b>Vault:</b> <code>{h(b.get('vault', '?'))}</code>\n"
                f"<b>Jarvis:</b> <code>{h(j.get('message', '?'))}</code>")

        elif data == "act_token":
            jwt = get_jarvis_token(u.id)
            bot.send_message(chat_id,
                f"🔑 <b>JWT acquired</b>\n<code>{h(jwt[:60])}…</code>\n\n"
                f"<i>Valid ~50 min • Tenant: {h(tenant_id)}</i>")

        elif data == "act_verify":
            cmd_verify(call.message)

        elif data == "act_vault":
            bot.send_message(chat_id,
                f"🔐 <b>Your Vault</b>\n\n"
                f"• Tenant: <code>{h(tenant_id)}</code>\n"
                f"• Org: <code>{h(org_id)}</code>\n"
                f"• Cipher: AES-256-GCM (PBKDF2 100k)\n\n"
                f"Store keys: <code>/setkeys bybit KEY SECRET</code>\n"
                f"Read balances: /balance\n"
                f"<i>Keys never leave the bridge in plaintext.</i>")

        elif data == "act_bal":
            cmd_balance(call.message)

        elif data == "br_skills":
            r = httpx.get(f"{BRIDGE_URL}/skills/list", timeout=5).json()
            lines = ["🌉 <b>Bridge skills</b>", ""]
            for s in r.get("skills", []):
                lines.append(f"• <code>{h(s['name'])}</code> — {h(s.get('target',''))}")
            bot.send_message(chat_id, "\n".join(lines))

        elif data == "br_btc":
            bot.send_message(chat_id, "🧠 Routing <b>Jarvis → Bridge → Bybit</b>…")
            r = bridge_skill("bybit.ticker",
                             {"symbol": "BTCUSDT", "category": "linear"},
                             tenant_id, org_id, actor)
            if "error" in r:
                bot.send_message(chat_id, f"❌ <code>{h(r['error'][:300])}</code>")
            else:
                px = r["result"]["result"]["list"][0]["lastPrice"]
                bot.send_message(chat_id,
                    f"📊 <b>BTCUSDT</b> — Bybit\n"
                    f"💵 <code>${float(px):,.2f}</code>\n\n"
                    f"<i>Tenant: {h(tenant_id)} • Vault: {r.get('used_tenant_creds', False)}</i>")

        elif data == "jr_active":
            jwt = get_jarvis_token(u.id)
            r = httpx.get(f"{JARVIS_URL}/skills/active",
                          headers={"Authorization": f"Bearer {jwt}"}, timeout=5).json()
            preview = "\n".join(f"• #{s['id']} {h(s['name'])}" for s in r[:10])
            bot.send_message(chat_id,
                f"✅ <b>{len(r)} active skills</b>\n{preview}")

        elif data == "jr_all":
            jwt = get_jarvis_token(u.id)
            r = httpx.get(f"{JARVIS_URL}/skills",
                          headers={"Authorization": f"Bearer {jwt}"}, timeout=5).json()
            lines = [f"📋 <b>{len(r)} total skills</b>", ""]
            for s in r[:25]:
                lines.append(f"• #{s['id']} {h(s['name'])} <code>{h(s['status'])}</code>")
            bot.send_message(chat_id, "\n".join(lines))

        elif data == "jr_create":
            jwt = get_jarvis_token(u.id)
            r1 = httpx.post(f"{JARVIS_URL}/skills",
                            headers={"Authorization": f"Bearer {jwt}"},
                            json={"name": f"Demo-{int(time.time())}",
                                  "description": "Live demo"},
                            timeout=10).json()
            skill_id = r1["id"]
            cfg = json.dumps({"parameters_schema": {
                "type": "object",
                "properties": {"note": {"type": "string"}},
                "required": ["note"]}})
            r2 = httpx.post(f"{JARVIS_URL}/skills/{skill_id}/versions",
                            headers={"Authorization": f"Bearer {jwt}"},
                            json={"configuration": cfg, "created_by": actor},
                            timeout=10).json()
            ver_id = r2["id"]
            httpx.post(f"{JARVIS_URL}/skills/{skill_id}/activate?version_id={ver_id}",
                       headers={"Authorization": f"Bearer {jwt}"}, timeout=10)
            _session[u.id] = {"skill_id": skill_id, "version_id": ver_id}
            bot.send_message(chat_id,
                f"🆕 <b>Skill created & activated</b>\n\n"
                f"Skill: <code>{skill_id}</code>\n"
                f"Version: <code>{ver_id}</code>")

        elif data == "jr_exec":
            s = _session.get(u.id)
            if not s:
                bot.send_message(chat_id, "⚠️ Tap 🆕 Create Skill first.")
                return
            jwt = get_jarvis_token(u.id)
            r = httpx.post(f"{JARVIS_URL}/skills/{s['skill_id']}/execute",
                           headers={"Authorization": f"Bearer {jwt}",
                                    "Content-Type": "application/json"},
                           json={"note": f"exec at {time.strftime('%H:%M:%S')}"},
                           timeout=10).json()
            bot.send_message(chat_id,
                f"▶️ <b>Executed</b>\n<pre>{h(json.dumps(r, indent=2)[:1500])}</pre>")

        elif data == "jr_agent":
            jwt = get_jarvis_token(u.id)
            body = {"prompt": "Approve invoice #12345",
                    "payload": {"skill_id": 60,
                                "arguments": {"invoice_id": 12345, "amount": 250.0}}}
            r = httpx.post(f"{JARVIS_URL}/agent/run",
                           headers={"Authorization": f"Bearer {jwt}",
                                    "Content-Type": "application/json"},
                           json=body, timeout=20)
            if r.status_code != 200:
                bot.send_message(chat_id, f"❌ HTTP {r.status_code}")
            else:
                bot.send_message(chat_id,
                    f"🤖 <b>Jarvis AI COO</b>\n"
                    f"<pre>{h(json.dumps(r.json(), indent=2)[:2000])}</pre>")

        elif data == "jr_delete":
            s = _session.get(u.id)
            if not s:
                bot.send_message(chat_id, "⚠️ No test skill to delete.")
                return
            jwt = get_jarvis_token(u.id)
            r = httpx.delete(f"{JARVIS_URL}/skills/{s['skill_id']}",
                             headers={"Authorization": f"Bearer {jwt}"}, timeout=10)
            bot.send_message(chat_id,
                f"🗑️ Deleted skill <code>{s['skill_id']}</code> → {r.status_code}")
            _session.pop(u.id, None)

        else:
            bot.send_message(chat_id, f"Unknown action: <code>{h(data)}</code>")

    except Exception as e:
        bot.send_message(chat_id, f"❌ <code>{h(str(e)[:300])}</code>")


# ── natural language → Jarvis ──────────────────────────────────
@bot.message_handler(func=lambda m: True, content_types=["text"])
def nl_handler(message):
    get_tenant(message.from_user)
    jwt = get_jarvis_token(message.from_user.id)
    if not jwt:
        bot.reply_to(message, "⚠️ Jarvis auth failed. Try /menu.")
        return

    status = bot.reply_to(message, "🧠 <b>Jarvis is analyzing…</b>")
    r = httpx.post(f"{JARVIS_URL}/agent/run",
                   headers={"Authorization": f"Bearer {jwt}",
                            "Content-Type": "application/json"},
                   json={"prompt": message.text,
                         "payload": {"skill_id": 60,
                                     "arguments": {"prompt": message.text}}},
                   timeout=20)
    if r.status_code != 200:
        bot.edit_message_text(
            f"🤖 Jarvis HTTP {r.status_code}\n"
            f"<i>Tip: use /menu for buttons.</i>",
            message.chat.id, status.message_id)
        return
    res = r.json()
    ex = res.get("execution_response", {})
    bot.edit_message_text(
        f"🧠 <b>Jarvis AI COO</b>\n\n"
        f"<b>Skill:</b> <code>{h(ex.get('skill', '?'))}</code>\n"
        f"<b>Status:</b> <code>{h(ex.get('status', '?'))}</code>\n"
        f"<b>Result:</b> {h(ex.get('result', ''))}\n\n"
        f"<i>Telegram → Jarvis → Bridge</i>",
        message.chat.id, status.message_id)


if __name__ == "__main__":
    print("🚀 Nova Test Console + Vault Manager active…")
    while True:
        try:
            bot.infinity_polling(timeout=30, long_polling_timeout=30)
        except Exception as e:
            print(f"Polling error: {e} — retry in 5s")
            time.sleep(5)
