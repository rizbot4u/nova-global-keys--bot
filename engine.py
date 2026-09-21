"""Intent parser: fast entity lookup -> optional LLM fallback (disabled by default)."""
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

def _sym(raw: str) -> str:
    s = raw.upper().strip()
    return s if s.endswith("USDT") else f"{s}USDT"

def _extract_intent_fast(text: str) -> dict | None:
    t = text.lower()

    action = None
    if any(k in t for k in ["buy", "long"]):
        action = "buy"
    elif any(k in t for k in ["sell", "short"]):
        action = "sell"
    elif "balance" in t:
        action = "balance"
    elif any(k in t for k in ["price", "what", "how much", "trading"]):
        action = "price"

    exchange = None
    for ex in KNOWN_EXCHANGES:
        if re.search(rf"\b{ex}\b", t):
            exchange = ex
            break

    # Balance / help never have a symbol
    if action == "balance":
        return {"action": "balance", "symbol": None,
                "exchange": exchange or "bybit", "qty_usd": None}

    symbol = None
    for name, ticker in KNOWN_TOKENS.items():
        if re.search(rf"\b{name}\b", t):
            symbol = _sym(ticker)
            break

    # Only look for raw ticker if action requires a symbol
    if not symbol and action in ("price", "buy", "sell"):
        m = re.search(r"\b([A-Z]{3,5})(USDT)?\b", text)
        if m:
            symbol = _sym(m.group(1))

    if action is None:
        return None

    qty = None
    if action in ("buy", "sell"):
        m = re.search(r"\$?([\d.]+)\s*(?:usd|dollars)?", t)
        if m:
            try:
                qty = float(m.group(1))
            except ValueError:
                pass

    if symbol is None and action in ("price", "buy", "sell"):
        return None  # can't act without a symbol -> fall through

    return {"action": action, "symbol": symbol,
            "exchange": exchange or "bybit", "qty_usd": qty}

def parse(text: str) -> dict:
    result = _extract_intent_fast(text)
    if result:
        return result
    if not LLM_ENABLED:
        return {"action": "unknown", "raw": text}
    return _llm_parse(text)

def _llm_parse(text: str) -> dict:
    prompt = (
        "Extract intent. Output only JSON.\n"
        'Schema: {"action":"price|buy|sell|balance","symbol":"STRING|null","exchange":"STRING|null","qty_usd":number|null}\n'
        f'Input: "{text}"\nJSON:'
    )
    payload = {"messages": [{"role": "user", "content": prompt}],
               "max_tokens": 48, "temperature": 0.0}
    try:
        r = requests.post(f"{LLM_URL}/v1/chat/completions",
                          json=payload, timeout=10)
        content = r.json()["choices"][0]["message"]["content"].strip()
        m = re.search(r"\{.*\}", content, re.DOTALL)
        if m:
            parsed = json.loads(m.group(0))
            if parsed.get("symbol"):
                parsed["symbol"] = _sym(parsed["symbol"])
            return parsed
    except Exception:
        pass
    return {"action": "unknown"}

# alias used elsewhere
_sym = _sym
