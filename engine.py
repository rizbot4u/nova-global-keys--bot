"""Intent parser: robust extraction using entity lookup + LLM fallback."""
import os
import re
import json
import requests

LLM_URL = os.environ.get("LLM_URL", "http://127.0.0.1:8080")

# 1. Known dictionary maps to prevent false matches
KNOWN_EXCHANGES = ["okx", "bybit", "binance", "coinbase", "kraken", "kucoin"]
KNOWN_TOKENS = {
    "solana": "SOL", "sol": "SOL",
    "bitcoin": "BTC", "btc": "BTC",
    "ethereum": "ETH", "eth": "ETH",
    "cardano": "ADA", "ada": "ADA",
    "ripple": "XRP", "xrp": "XRP",
}

def _sym(raw_symbol: str) -> str:
    cleaned = raw_symbol.upper().strip()
    return cleaned if cleaned.endswith("USDT") else f"{cleaned}USDT"

def _extract_intent_fast(text: str) -> dict:
    t_lower = text.lower()
    
    # Extract action
    action = "price"
    if any(k in t_lower for k in ["buy", "long"]):
        action = "buy"
    elif any(k in t_lower for k in ["sell", "short"]):
        action = "sell"
    elif any(k in t_lower for k in ["balance", "my balance"]):
        action = "balance"

    # Extract exchange (match anywhere in sentence)
    found_exchange = "bybit"  # default
    for ex in KNOWN_EXCHANGES:
        if re.search(r'\b' + ex + r'\b', t_lower):
            found_exchange = ex
            break

    # Extract symbol (match mapped crypto name or explicit ticker)
    found_symbol = None
    for name, ticker in KNOWN_TOKENS.items():
        if re.search(r'\b' + name + r'\b', t_lower):
            found_symbol = _sym(ticker)
            break
            
    if not found_symbol:
        # Fallback regex for raw ticker patterns (e.g., SOLUSDT or 3-5 char tickers)
        raw_match = re.search(r'\b([a-zA-Z]{3,5})(usdt)?\b', text, re.I)
        if raw_match and raw_match.group(1).lower() not in ["what", "this", "from", "with", "that"]:
            found_symbol = _sym(raw_match.group(1))

    # Extract quantity if present
    qty = None
    qty_match = re.search(r'\$?([\d.]+)\s*(usd|dollars)?', t_lower)
    if qty_match and action in ["buy", "sell"]:
        try:
            qty = float(qty_match.group(1))
        except ValueError:
            pass

    if found_symbol or action == "balance":
        return {
            "action": action,
            "symbol": found_symbol,
            "exchange": found_exchange,
            "qty_usd": qty
        }
    
    return None

def parse(text: str) -> dict:
    """Fast entity rule match -> Fallback to optimized single-slot LLM."""
    result = _extract_intent_fast(text)
    if result:
        return result
    return _llm_parse(text)

def _llm_parse(text: str) -> dict:
    prompt = (
        "Extract intent from input. Output strictly valid JSON without explanation.\n"
        'JSON Schema: {"action": "price|buy|sell|balance", "symbol": "STRING", "exchange": "STRING", "qty_usd": float}\n'
        f'Input: "{text}"\nJSON:'
    )

    payload = {
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 48,
        "temperature": 0.0
    }

    try:
        r = requests.post(f"{LLM_URL}/v1/chat/completions", json=payload, timeout=120)
        content = r.json()["choices"][0]["message"]["content"].strip()
        match = re.search(r"\{.*\}", content, re.DOTALL)
        if match:
            parsed = json.loads(match.group(0))
            if parsed.get("symbol"):
                parsed["symbol"] = _sym(parsed["symbol"])
            return parsed
    except Exception:
        pass
    
    return {"action": "unknown"}
