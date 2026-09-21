"""Nova Global Keys — Telegram bot entrypoint.

Wires together:
  db.py         user + API key storage (Fernet-encrypted at rest)
  exchanges.py  Bybit / Binance / OKX / KuCoin REST clients
  dex.py        DKHYR on Base Mainnet
  engine.py     intent parser (regex rules + local Ollama fallback)
"""
from __future__ import annotations

from __future__ import annotations

import os
import time
import telebot
from telebot import types
from dotenv import load_dotenv

import db
import dex
import engine
import exchanges

load_dotenv()

TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
ADMIN_ID = int(os.environ.get("ADMIN_TELEGRAM_ID", "0") or 0)
BYBIT_CLIENT_ID = os.environ.get("BYBIT_CLIENT_ID", "")
BYBIT_REDIRECT_URI = os.environ.get("BYBIT_REDIRECT_URI", "")

bot = telebot.TeleBot(TELEGRAM_TOKEN, parse_mode="Markdown")
db.init()


# ── helpers ─────────────────────────────────────────────────────
def _creds_or_reply(message, exchange: str):
    """Fetch stored creds for this user+exchange, or reply with how to connect."""
    tg_id = message.from_user.id
    creds = db.get_keys(tg_id, exchange)
    if creds:
        return creds
    if exchange == "bybit":
        bot.reply_to(message, "No Bybit connection yet. Run /connect to link your account.")
    else:
        bot.reply_to(
            message,
            f"No {exchange} keys on file. Add them with:\n"
            f"`/setkeys {exchange} <api_key> <api_secret>`",
        )
    return None


def _fmt_balance(exchange: str, result: dict) -> str:
    if not result.get("ok"):
        return f"❌ {exchange}: {result.get('error', 'unknown error')}"
    lines = [f"💰 *{exchange.capitalize()}*"]
    if result.get("equity"):
        lines.append(f"Equity: {result['equity']}")
    for coin, amt, usd in result.get("coins", []):
        tail = f" (~${usd})" if usd else ""
        lines.append(f"• {coin}: {amt}{tail}")
    return "\n".join(lines)


def _do_price(message, symbol: str, exchange: str):
    price = exchanges.ticker(exchange, symbol)
    if price is None:
        bot.reply_to(message, f"Couldn't fetch {symbol} on {exchange}.")
        return
    bot.reply_to(message, f"📊 *{symbol}* on {exchange}\n💵 ${price:,.4f}")


def _do_balance(message, exchange: str | None):
    tg_id = message.from_user.id
    exchanges_to_check = [exchange] if exchange else db.list_connected(tg_id)
    if not exchanges_to_check:
        bot.reply_to(message, "No exchanges connected yet. Try /connect (Bybit) or /setkeys.")
        return
    parts = []
    for ex in exchanges_to_check:
        creds = db.get_keys(tg_id, ex)
        if not creds:
            continue
        parts.append(_fmt_balance(ex, exchanges.balance(ex, creds)))
    bot.reply_to(message, "\n\n".join(parts) or "No balances found.")


def _do_trade(message, exchange: str, side: str, symbol: str, qty: float):
    creds = _creds_or_reply(message, exchange)
    if not creds:
        return
    result = exchanges.order(exchange, creds, symbol, side, qty)
    tg_id = message.from_user.id
    if "error" in result or result.get("retCode", 0) not in (0, None):
        err = result.get("error") or result.get("retMsg") or result
        db.log_trade(tg_id, exchange, symbol, side, qty, None, None, "failed")
        bot.reply_to(message, f"❌ Order failed: {err}")
        return
    order_id = (
        result.get("result", {}).get("orderId")
        or result.get("orderId")
        or result.get("data", {}).get("orderId")
        or "unknown"
    )
    db.log_trade(tg_id, exchange, symbol, side, qty, None, order_id, "submitted")
    bot.reply_to(message, f"✅ {side.capitalize()} {qty} {symbol} on {exchange}\nOrder ID: `{order_id}`")


# ── commands ────────────────────────────────────────────────────
@bot.message_handler(commands=["start", "help"])
def cmd_help(message):
    db.ensure_user(message.from_user.id, message.from_user.username or "")
    bot.reply_to(
        message,
        "✨ *Nova Global Keys* ✨\n\n"
        "📈 *Trading*\n"
        "/connect — Connect Bybit (OAuth, keys never touch this chat)\n"
        "/setkeys <exchange> <key> <secret> — Manual keys (bybit/binance/okx/kucoin)\n"
        "/price <SYMBOL> [exchange] — Live price\n"
        "/balance [exchange] — Your balance\n"
        "/trade <exchange> <buy|sell> <SYMBOL> <qty> — Market order\n\n"
        "🪙 *DKHYR (Base Mainnet)*\n"
        "/wallet <address> — On-chain DKHYR balance\n\n"
        "Or just type naturally: \"buy 50 usd of btc on bybit\", \"what's eth\", \"my balance\"",
    )


@bot.message_handler(commands=["connect"])
def cmd_connect(message):
    db.ensure_user(message.from_user.id, message.from_user.username or "")
    if not BYBIT_CLIENT_ID or not BYBIT_REDIRECT_URI:
        bot.reply_to(message, "Bybit OAuth isn't configured on this bot yet.")
        return
    state = f"tg-{message.from_user.id}"
    url = (
        "https://www.bybit.com/en/oauth"
        f"?client_id={BYBIT_CLIENT_ID}"
        f"&redirect_uri={BYBIT_REDIRECT_URI}"
        f"&response_type=code&scope=openapi&state={state}"
    )
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔗 Connect Bybit", url=url))
    bot.reply_to(message, "Tap below to authorize — your API keys stay with Bybit, never with us.", reply_markup=markup)


@bot.message_handler(commands=["setkeys"])
def cmd_setkeys(message):
    parts = message.text.split()
    if len(parts) not in (4, 5):
        bot.reply_to(message, "Usage: `/setkeys <exchange> <api_key> <api_secret> [passphrase]`")
        return
    _, exchange, key, secret, *rest = parts
    exchange = exchange.lower()
    if exchange not in exchanges.SUPPORTED:
        bot.reply_to(message, f"Unsupported exchange. Choose from: {', '.join(exchanges.SUPPORTED)}")
        return
    passphrase = rest[0] if rest else None
    db.ensure_user(message.from_user.id, message.from_user.username or "")
    db.save_keys(message.from_user.id, exchange, key, secret, passphrase)
    try:
        bot.delete_message(message.chat.id, message.message_id)
    except Exception:
        pass
    bot.send_message(message.chat.id, f"✅ {exchange.capitalize()} keys saved (and your message deleted for safety).")


@bot.message_handler(commands=["price"])
def cmd_price(message):
    parts = message.text.split()
    if len(parts) < 2:
        bot.reply_to(message, "Usage: `/price BTC [exchange]`")
        return
    symbol = engine._sym(parts[1])
    exchange = parts[2].lower() if len(parts) > 2 else "bybit"
    _do_price(message, symbol, exchange)


@bot.message_handler(commands=["balance"])
def cmd_balance(message):
    parts = message.text.split()
    exchange = parts[1].lower() if len(parts) > 1 else None
    _do_balance(message, exchange)


@bot.message_handler(commands=["trade"])
def cmd_trade(message):
    parts = message.text.split()
    if len(parts) != 5:
        bot.reply_to(message, "Usage: `/trade <exchange> <buy|sell> <SYMBOL> <qty>`")
        return
    _, exchange, side, symbol, qty = parts
    if exchange.lower() not in exchanges.SUPPORTED or side.lower() not in ("buy", "sell"):
        bot.reply_to(message, "Bad exchange or side. Example: `/trade bybit buy BTCUSDT 0.001`")
        return
    try:
        qty_f = float(qty)
    except ValueError:
        bot.reply_to(message, "Quantity must be a number.")
        return
    _do_trade(message, exchange.lower(), side.lower(), engine._sym(symbol), qty_f)


@bot.message_handler(commands=["wallet"])
def cmd_wallet(message):
    parts = message.text.split()
    if len(parts) != 2:
        bot.reply_to(message, "Usage: `/wallet 0xYourAddress`")
        return
    if not dex.connected():
        bot.reply_to(message, "Base Mainnet RPC isn't reachable right now.")
        return
    bal = dex.balance(parts[1])
    bot.reply_to(message, f"🪙 *DKHYR balance*\n`{parts[1]}`\n{bal:,.2f} DKHYR")


# ── natural language fallback ──────────────────────────────────
@bot.message_handler(func=lambda m: True, content_types=["text"])
def nl_fallback(message):
    db.ensure_user(message.from_user.id, message.from_user.username or "")
    intent = engine.parse(message.text)
    action = intent.get("action")

    if action == "price" and intent.get("symbol"):
        _do_price(message, intent["symbol"], intent.get("exchange") or "bybit")
    elif action == "balance":
        _do_balance(message, intent.get("exchange"))
    elif action == "buy" and intent.get("symbol") and intent.get("qty_usd"):
        price = exchanges.ticker(intent.get("exchange", "bybit"), intent["symbol"])
        if not price:
            bot.reply_to(message, "Couldn't price that symbol.")
            return
        qty = round(intent["qty_usd"] / price, 6)
        _do_trade(message, intent.get("exchange", "bybit"), "buy", intent["symbol"], qty)
    elif action == "sell" and intent.get("symbol"):
        bot.reply_to(
            message,
            f"To sell, tell me a quantity: `/trade {intent.get('exchange','bybit')} sell "
            f"{intent['symbol']} <qty>`",
        )
    elif action == "help":
        cmd_help(message)
    else:
        bot.reply_to(message, "Not sure what you mean — try /help for commands.")


if __name__ == "__main__":
    print("Nova Global Keys bot starting...")
    while True:
        try:
            bot.infinity_polling(timeout=30, long_polling_timeout=30)
        except Exception as e:
            print(f"Polling error: {e} — retrying in 5s")
            time.sleep(5)
