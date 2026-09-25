"""Intent parser: fast entity lookup -> optional LLM fallback (disabled by default).

Python 3.8+ compatible (no PEP 604 unions).
"""
import os
import re
import json
import requests

LLM_URL = os.environ.get("LLM_URL", "http://127.0.0.1:8080")
LLM_ENABLED = os.environ.get("LLM_ENABLED", "0") == "1"

KNOWN_EXCHANGES = ["okx", "bybit", "binance", "coinbase", "kraken", "kucoin"]

KNOWN_TOKENS = {
    "solana": "SOL", "sol": "SOL",
    "bitcoin": "BTC", "btc": "BTC",
    "ethereum": "ETH", "eth": "ETH",
    "cardano": "ADA", "ada": "ADA",
    "ripple": "XRP", "xrp": "XRP",
    "dogecoin": "DOGE", "doge": "DOGE",
    "polkadot": "DOT", "dot": "DOT",
    "chainlink": "LINK", "link": "LINK",
}

STOP_WORDS = {
    "what", "whats", "how", "doing", "is", "the", "a", "an",
    "this", "that", "from", "with", "me", "my",
    "price", "buy", "sell", "long", "short", "balance",
    "usd", "usdt", "dollars", "dollar", "worth", "value", "trading",
} | set(KNOWN_EXCHANGES) | set(KNOWN_TOKENS.keys())


def _sym(raw):
    """Normalize a symbol to XXXUSDT."""
    s = str(raw).upper().strip()
    if not s:
        return None
    return s if s.endswith("USDT") else s + "USDT"


def _extract_intent_fast(text):
    """Rule-based extraction. Returns dict or None if it can't decide."""
    t = text.lower()

    # ── action ─────────────────────────────────────────────
    action = None
    if re.search(r"\b(buy|long)\b", t):
        action = "buy"
    elif re.search(r"\b(sell|short)\b", t):
        action = "sell"
    elif "balance" in t:
        action = "balance"
    elif re.search(r"\b(help|commands?)\b", t):
        action = "help"
    elif re.search(r"\b(price|trading|worth|value|doing|what|whats|how)\b", t):
        action = "price"

    # ── exchange ───────────────────────────────────────────
    exchange = None
    for ex in KNOWN_EXCHANGES:
        if re.search(r"\b" + ex + r"\b", t):
            exchange = ex
            break

    # ── balance / help never carry a symbol ────────────────
    if action in ("balance", "help"):
        return {
            "action": action,
            "symbol": None,
            "exchange": exchange or "bybit",
            "qty_usd": None,
        }

    # ── symbol from known names ────────────────────────────
    symbol = None
    for name, ticker in KNOWN_TOKENS.items():
        if re.search(r"\b" + name + r"\b", t):
            symbol = _sym(ticker)
            break

    # ── fallback: raw ticker pattern, filtered ─────────────
    if not symbol and action in ("price", "buy", "sell"):
        for m in re.finditer(r"\b([A-Za-z]{2,6})(USDT)?\b", text):
            candidate = m.group(1).lower()
            if candidate not in STOP_WORDS:
                symbol = _sym(m.group(1))
                break

    # ── quantity ───────────────────────────────────────────
    qty = None
    if action in ("buy", "sell"):
        qm = re.search(r"\$?\s*([\d]+(?:\.\d+)?)\s*(?:usd|dollars?)?", t)
        if qm:
            try:
                qty = float(qm.group(1))
            except ValueError:
                qty = None

    # Can't act on price/buy/sell without a symbol
    if action in ("price", "buy", "sell") and symbol is None:
        return None

    if action is None:
        return None

    return {
        "action": action,
        "symbol": symbol,
        "exchange": exchange or "bybit",
        "qty_usd": qty,
    }


def parse(text):
    """Fast rules first, optional LLM fallback if enabled."""
    result = _extract_intent_fast(text)
    if result:
        return result
    if not LLM_ENABLED:
        return {"action": "unknown", "raw": text}
    return _llm_parse(text)


def _llm_parse(text):
    """Optional LLM fallback. Disabled unless LLM_ENABLED=1."""
    prompt = (
        "Extract intent. Output only JSON.\n"
        'Schema: {"action":"price|buy|sell|balance|unknown",'
        '"symbol":"STRING|null","exchange":"STRING|null","qty_usd":number|null}\n'
        'Input: "' + text + '"\nJSON:'
    )
    payload = {
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 64,
        "temperature": 0.0,
    }
    try:
        r = requests.post(LLM_URL + "/v1/chat/completions", json=payload, timeout=15)
        content = r.json()["choices"][0]["message"]["content"].strip()
        m = re.search(r"\{.*\}", content, re.DOTALL)
        if m:
            parsed = json.loads(m.group(0))
            if parsed.get("symbol"):
                parsed["symbol"] = _sym(parsed["symbol"])
            if parsed.get("action") == "balance":
                parsed["symbol"] = None
            return parsed
    except Exception as e:
        print("[engine] LLM fallback failed:", e)
    return {"action": "unknown", "raw": text}
