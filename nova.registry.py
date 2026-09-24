"""Nova Global Keys — Layman Test Console.
Every Bridge and Jarvis endpoint is exposed as a Telegram button.
"""
from __future__ import annotations
import os
import time
import json
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
BRIDGE_TOKEN   = os.environ.get("BRIDGE_TOKEN", "")
JARVIS_URL     = os.environ.get("JARVIS_URL", "http://127.0.0.1:8000")
JARVIS_USER    = os.environ.get("JARVIS_USER", "owner1")
JARVIS_PASS    = os.environ.get("JARVIS_PASS", "password123")

BYBIT_CLIENT_ID    = os.environ.get("BYBIT_CLIENT_ID", "")
BYBIT_REDIRECT_URI = os.environ.get("BYBIT_REDIRECT_URI", "")

bot = telebot.TeleBot(TELEGRAM_TOKEN, parse_mode="Markdown")
db.init()

_token_cache: dict[int, tuple[str, float]] = {}
_session: dict[int, dict] = {}   # per-user test session state


# ── helpers ─────────────────────────────────────────────────────
def get_tenant(u):
    db.ensure_user(u.id, u.username or "")
    return f"tenant_{u.id}", f"org_{u.id}"


def get_jarvis_token(user_id: int) -> str:
    now = time.time()
    cached = _token_cache.get(user_id)
    if cached and cached[1] > now:
        return cached[0]
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


def jget(path, jwt):
    return httpx.get(f"{JARVIS_URL}{path}",
                     headers={"Authorization": f"Bearer {jwt}"}, timeout=10)


def jpost(path, jwt, body=None):
    return httpx.post(f"{JARVIS_URL}{path}",
                      headers={"Authorization": f"Bearer {jwt}",
                               "Content-Type": "application/json"},
                      json=body or {}, timeout=15)


def bridge_call(skill_name, parameters, tenant_id, org_id, actor):
    try:
        r = httpx.post(f"{BRIDGE_URL}/skills/execute",
                       headers={"X-Bridge-Token": BRIDGE_TOKEN,
                                "Content-Type": "application/json"},
                       json={"skill_name": skill_name, "parameters": parameters,
                             "tenant_id": tenant_id, "org_id": org_id, "actor": actor},
                       timeout=15.0)
        if r.status_code >= 400:
            return {"error": f"HTTP {r.status_code}: {r.text[:200]}"}
        return r.json()
    except Exception as e:
        return {"error": str(e)}


def _send(msg_chat_id, text):
    bot.send_message(msg_chat_id, text[:3900])


# ── main menu ───────────────────────────────────────────────────
@bot.message_handler(commands=["start", "help", "menu", "test"])
def cmd_menu(message):
    get_tenant(message.from_user)
    m = types.InlineKeyboardMarkup(row_width=2)

    m.add(types.InlineKeyboardButton("🩺 Stack Health", callback_data="act_health"),
          types.InlineKeyboardButton("🔑 Get JWT", callback_data="act_token"))

    m.add(types.InlineKeyboardButton("🌉 Bridge Skills", callback_data="br_skills"),
          types.InlineKeyboardButton("📊 BTC via Bridge", callback_data="br_btc"))

    m.add(types.InlineKeyboardButton("✅ Jarvis Active", callback_data="jr_active"),
          types.InlineKeyboardButton("📋 Jarvis All", callback_data="jr_all"))

    m.add(types.InlineKeyboardButton("🆕 Create Test Skill", callback_data="jr_create"),
          types.InlineKeyboardButton("▶️ Execute Test Skill", callback_data="jr_exec"))

    m.add(types.InlineKeyboardButton("🤖 Run AI Agent", callback_data="jr_agent"),
          types.InlineKeyboardButton("🗑️ Delete Test Skill", callback_data="jr_delete"))

    m.add(types.InlineKeyboardButton("💼 Wallet DKHYR", callback_data="act_wallet"))

    bot.reply_to(
        message,
        "🎛️ *Nova Stack — Live Test Console*\n\n"
        "Tap any button to exercise a real endpoint:\n"
        "• *Bridge* buttons call Nova MCP (`:8001`)\n"
        "• *Jarvis* buttons call AI Registry (`:8000`)\n\n"
        "Every action is tenant-isolated and audit-logged.",
        reply_markup=m,
    )


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
        # ---------- STACK HEALTH ----------
        if data == "act_health":
            b = httpx.get(f"{BRIDGE_URL}/", timeout=3).json()
            j = httpx.get(f"{JARVIS_URL}/", timeout=3).json()
            _send(chat_id,
                f"🏗️ *Stack Health*\n\n"
                f"*Bridge (:8001)*\n`{json.dumps(b)[:200]}`\n\n"
                f"*Jarvis (:8000)*\n`{json.dumps(j)[:200]}`")

        # ---------- JWT ----------
        elif data == "act_token":
            jwt = get_jarvis_token(u.id)
            if not jwt:
                _send(chat_id, "❌ Could not get JWT from Jarvis.")
            else:
                _send(chat_id,
                    f"🔑 *JWT acquired*\n`{jwt[:60]}…`\n\n"
                    f"_Cached for 50 min. Tenant: `{tenant_id}`_")

        # ---------- BRIDGE /skills/list ----------
        elif data == "br_skills":
            r = httpx.get(f"{BRIDGE_URL}/skills/list", timeout=5)
            try:
                payload = r.json()
            except Exception:
                payload = r.text
            _send(chat_id, f"🌉 *Bridge skills*\n```\n{json.dumps(payload, indent=2)[:3000]}\n```")

        # ---------- BRIDGE bybit.ticker ----------
        elif data == "br_btc":
            _send(chat_id, "🧠 Routing through *Jarvis → Bridge → Bybit*…")
            r = bridge_call("bybit.ticker",
                            {"symbol": "BTCUSDT", "category": "linear"},
                            tenant_id, org_id, actor)
            if "error" in r:
                _send(chat_id, f"❌ `{r['error'][:300]}`")
            else:
                px = r["result"]["result"]["list"][0]["lastPrice"]
                _send(chat_id,
                    f"📊 *BTCUSDT* — Bybit\n💵 ${float(px):,.2f}\n\n"
                    f"_Tenant: `{tenant_id}`_\n"
                    f"_Vault-backed: `{r.get('has_tenant_creds', 'false')}`_")

        # ---------- JARVIS /skills/active ----------
        elif data == "jr_active":
            jwt = get_jarvis_token(u.id)
            r = jget("/skills/active", jwt)
            rows = r.json()
            preview = "\n".join(f"• #{s['id']} {s['name']}" for s in rows[:10])
            _send(chat_id,
                f"✅ *{len(rows)} active skills*\n{preview}\n\n"
                f"_Org: {rows[0]['organization_id'] if rows else '—'}_")

        # ---------- JARVIS /skills (all) ----------
        elif data == "jr_all":
            jwt = get_jarvis_token(u.id)
            r = jget("/skills", jwt)
            rows = r.json()
            _send(chat_id,
                f"📋 *{len(rows)} total skills in your org*\n"
                + "\n".join(f"• #{s['id']} {s['name']} `{s['status']}`" for s in rows[:20]))

        # ---------- JARVIS create + version + activate ----------
        elif data == "jr_create":
            jwt = get_jarvis_token(u.id)
            # 1. Create skill
            r1 = jpost("/skills", jwt, {"name": f"Demo-{int(time.time())}",
                                         "description": "Live demo skill"})
            skill = r1.json()
            skill_id = skill["id"]
            # 2. Add version
            cfg = json.dumps({"parameters_schema": {
                "type": "object",
                "properties": {"note": {"type": "string"}},
                "required": ["note"]
            }})
            r2 = jpost(f"/skills/{skill_id}/versions", jwt,
                       {"configuration": cfg, "created_by": actor})
            ver_id = r2.json()["id"]
            # 3. Activate
            r3 = jpost(f"/skills/{skill_id}/activate?version_id={ver_id}", jwt)
            # Save in session for execute/delete
            _session[u.id] = {"skill_id": skill_id, "version_id": ver_id}
            _send(chat_id,
                f"🆕 *Skill created & activated*\n\n"
                f"Skill ID: `{skill_id}`\n"
                f"Version: `{ver_id}`\n"
                f"Status: `active`\n\n"
                f"Now tap *▶️ Execute Test Skill*.")

        # ---------- JARVIS execute ----------
        elif data == "jr_exec":
            s = _session.get(u.id)
            if not s:
                _send(chat_id, "⚠️ Tap *🆕 Create Test Skill* first.")
                return
            jwt = get_jarvis_token(u.id)
            r = jpost(f"/skills/{s['skill_id']}/execute", jwt,
                      {"note": f"executed at {time.strftime('%H:%M:%S')}"})
            _send(chat_id,
                f"▶️ *Skill executed*\n```\n{json.dumps(r.json(), indent=2)[:2000]}\n```")

        # ---------- JARVIS /agent/run ----------
        elif data == "jr_agent":
            jwt = get_jarvis_token(u.id)
            body = {
                "prompt": "Approve invoice #12345",
                "payload": {"skill_id": 60, "arguments": {"invoice_id": 12345, "amount": 250.0}}
            }
            r = jpost("/agent/run", jwt, body)
            if r.status_code != 200:
                _send(chat_id, f"❌ HTTP {r.status_code}\n`{r.text[:300]}`")
            else:
                _send(chat_id,
                    f"🤖 *Jarvis AI COO*\n"
                    f"```\n{json.dumps(r.json(), indent=2)[:2500]}\n```")

        # ---------- JARVIS delete ----------
        elif data == "jr_delete":
            s = _session.get(u.id)
            if not s:
                _send(chat_id, "⚠️ No test skill to delete.")
                return
            jwt = get_jarvis_token(u.id)
            r = httpx.delete(f"{JARVIS_URL}/skills/{s['skill_id']}",
                             headers={"Authorization": f"Bearer {jwt}"}, timeout=10)
            _send(chat_id,
                f"🗑️ Delete skill `{s['skill_id']}` → HTTP `{r.status_code}`")
            _session.pop(u.id, None)

        # ---------- WALLET ----------
        elif data == "act_wallet":
            addr = "0xA4eE963F223C193261d8545e4c4681ED3837af25"
            bal = dex.balance(addr) if dex.connected() else 0
            _send(chat_id, f"💼 *DKHYR wallet*\n`{addr}`\n{bal:,.2f} DKHYR")

        else:
            _send(chat_id, f"Unknown action: `{data}`")

    except Exception as e:
        _send(chat_id, f"❌ Error: `{str(e)[:300]}`")


# ── free text → Jarvis ──────────────────────────────────────────
@bot.message_handler(func=lambda m: True, content_types=["text"])
def nl_handler(message):
    get_tenant(message.from_user)
    jwt = get_jarvis_token(message.from_user.id)
    if not jwt:
        bot.reply_to(message, "⚠️ Jarvis auth failed. Try /menu.")
        return

    status = bot.reply_to(message, "🧠 *Jarvis is analyzing…*")
    body = {"prompt": message.text,
            "payload": {"skill_id": 60, "arguments": {"prompt": message.text}}}
    r = jpost("/agent/run", jwt, body)

    if r.status_code != 200:
        bot.edit_message_text(
            f"🤖 Jarvis HTTP {r.status_code}\n`{r.text[:300]}`\n\n"
            f"_Tip: use /menu for one-tap testing._",
            message.chat.id, status.message_id)
        return

    res = r.json()
    ex = res.get("execution_response", {})
    bot.edit_message_text(
        f"🧠 *Jarvis AI COO*\n"
        f"Skill: `{ex.get('skill', '?')}`\n"
        f"Status: `{ex.get('status', '?')}`\n"
        f"Result: {ex.get('result', '')}\n\n"
        f"_Pipeline: Telegram → Jarvis → Bridge_",
        message.chat.id, status.message_id)


if __name__ == "__main__":
    print("🚀 Nova Test Console active...")
    while True:
        try:
            bot.infinity_polling(timeout=30, long_polling_timeout=30)
        except Exception as e:
            print(f"Polling error: {e} — retry in 5s")
            time.sleep(5)
