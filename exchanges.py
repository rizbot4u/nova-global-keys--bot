"""Unified signing + requests for Bybit, Binance, OKX, KuCoin."""
import time
import json
import hmac
import base64
import hashlib
from datetime import datetime
from urllib.parse import urlencode
import requests

SUPPORTED = ("bybit", "binance", "okx", "kucoin")

def _bybit_sign(secret, ts, key, recv, payload):
    return hmac.new(secret.encode(), (ts + key + recv + payload).encode(),
                    hashlib.sha256).hexdigest()


def bybit_get(creds, path, params=None):
    params = params or {}
    ts, recv = str(int(time.time() * 1000)), "5000"
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    sig = _bybit_sign(creds["secret"], ts, creds["key"], recv, qs)
    return requests.get(f"https://api.bybit.com{path}?{qs}",
        headers={"X-BAPI-API-KEY": creds["key"], "X-BAPI-TIMESTAMP": ts,
                 "X-BAPI-SIGN": sig, "X-BAPI-RECV-WINDOW": recv},
        timeout=15).json()


def bybit_post(creds, path, body):
    ts, recv = str(int(time.time() * 1000)), "5000"
    js = json.dumps(body, separators=(",", ":"))
    sig = _bybit_sign(creds["secret"], ts, creds["key"], recv, js)
    return requests.post(f"https://api.bybit.com{path}",
        headers={"X-BAPI-API-KEY": creds["key"], "X-BAPI-TIMESTAMP": ts,
                 "X-BAPI-SIGN": sig, "X-BAPI-RECV-WINDOW": recv,
                 "Content-Type": "application/json"},
        data=js, timeout=15).json()

def _binance_sign(secret, payload):
    return hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()


def binance_get(creds, path, params=None):
    params = params or {}
    params["timestamp"] = int(time.time() * 1000)
    params["recvWindow"] = 5000
    qs = urlencode(params)
    sig = _binance_sign(creds["secret"], qs)
    return requests.get(f"https://api.binance.com{path}?{qs}&signature={sig}",
        headers={"X-MBX-APIKEY": creds["key"]}, timeout=15).json()


def binance_post(creds, path, body):
    body["timestamp"] = int(time.time() * 1000)
    body["recvWindow"] = 5000
    qs = urlencode(body)
    sig = _binance_sign(creds["secret"], qs)
    return requests.post(f"https://api.binance.com{path}?{qs}&signature={sig}",
        headers={"X-MBX-APIKEY": creds["key"]}, timeout=15).json()

def _okx_sign(secret, ts, method, path, body):
    return base64.b64encode(hmac.new(secret.encode(),
        f"{ts}{method}{path}{body}".encode(), hashlib.sha256).digest()).decode()


def okx_request(creds, method, path, body_dict=None):
    ts = datetime.utcnow().isoformat(timespec="milliseconds") + "Z"
    body = json.dumps(body_dict, separators=(",", ":")) if body_dict else ""
    headers = {"OK-ACCESS-KEY": creds["key"],
               "OK-ACCESS-SIGN": _okx_sign(creds["secret"], ts, method, path, body),
               "OK-ACCESS-TIMESTAMP": ts,
               "OK-ACCESS-PASSPHRASE": creds["passphrase"],
               "Content-Type": "application/json"}
    url = f"https://www.okx.com{path}"
    if method == "GET":
        return requests.get(url, headers=headers, timeout=15).json()
    return requests.post(url, headers=headers, data=body, timeout=15).json()

def _kc_sign(secret, ts, method, path, body):
    return base64.b64encode(hmac.new(secret.encode(),
        f"{ts}{method}{path}{body}".encode(), hashlib.sha256).digest()).decode()


def _kc_pass(secret, passphrase):
    return base64.b64encode(hmac.new(secret.encode(),
        passphrase.encode(), hashlib.sha256).digest()).decode()


def kucoin_request(creds, method, path, body_dict=None):
    ts = str(int(time.time() * 1000))
    body = json.dumps(body_dict, separators=(",", ":")) if body_dict else ""
    headers = {"KC-API-KEY": creds["key"],
               "KC-API-SIGN": _kc_sign(creds["secret"], ts, method, path, body),
               "KC-API-TIMESTAMP": ts,
               "KC-API-PASSPHRASE": _kc_pass(creds["secret"], creds["passphrase"]),
               "KC-API-KEY-VERSION": "2",
               "Content-Type": "application/json"}
    url = f"https://api.kucoin.com{path}"
    if method == "GET":
        return requests.get(url, headers=headers, timeout=15).json()
    return requests.post(url, headers=headers, data=body, timeout=15).json()

def ticker(exchange, symbol):
    try:
        if exchange == "bybit":
            r = requests.get("https://api.bybit.com/v5/market/tickers",
                             params={"category": "spot", "symbol": symbol}, timeout=8).json()
            if r.get("retCode") == 0 and r["result"]["list"]:
                return float(r["result"]["list"][0]["lastPrice"])
        elif exchange == "binance":
            r = requests.get("https://api.binance.com/api/v3/ticker/price",
                             params={"symbol": symbol}, timeout=8).json()
            return float(r["price"])
        elif exchange == "okx":
            r = requests.get("https://www.okx.com/api/v5/market/ticker",
                             params={"instId": symbol.replace("USDT", "-USDT")}, timeout=8).json()
            if r.get("code") == "0" and r["data"]:
                return float(r["data"][0]["last"])
        elif exchange == "kucoin":
            r = requests.get("https://api.kucoin.com/api/v1/market/orderbook/level1",
                             params={"symbol": symbol.replace("USDT", "-USDT")}, timeout=8).json()
            if r.get("code") == "200000":
                return float(r["data"]["price"])
    except Exception:
        pass
    return None


def balance(exchange, creds):
    try:
        if exchange == "bybit":
            r = bybit_get(creds, "/v5/account/wallet-balance", {"accountType": "UNIFIED"})
            if r.get("retCode") != 0:
                return {"ok": False, "error": r.get("retMsg")}
            a = (r["result"]["list"] or [{}])[0]
            coins = [c for c in a.get("coin", []) if float(c.get("usdValue", 0) or 0) > 0.01]
            return {"ok": True, "equity": a.get("totalEquity"),
                    "coins": [(c["coin"], c.get("walletBalance"), c.get("usdValue")) for c in coins[:8]]}
        elif exchange == "binance":
            r = binance_get(creds, "/api/v3/account")
            if "balances" not in r:
                return {"ok": False, "error": r.get("msg", "auth failed")}
            coins = [(b["asset"], b["free"], None) for b in r["balances"] if float(b["free"]) > 0]
            return {"ok": True, "equity": None, "coins": coins[:8]}
        elif exchange == "okx":
            r = okx_request(creds, "GET", "/api/v5/account/balance")
            if r.get("code") != "0":
                return {"ok": False, "error": r.get("msg")}
            a = (r.get("data") or [{}])[0]
            return {"ok": True, "equity": a.get("totalEq"), "coins": []}
        elif exchange == "kucoin":
            r = kucoin_request(creds, "GET", "/api/v1/accounts")
            if r.get("code") != "200000":
                return {"ok": False, "error": r.get("msg")}
            coins = [(x["currency"], x["balance"], None) for x in r["data"] if float(x["balance"]) > 0]
            return {"ok": True, "equity": None, "coins": coins[:8]}
    except Exception as e:
        return {"ok": False, "error": str(e)}
    return {"ok": False, "error": "unknown exchange"}


def order(exchange, creds, symbol, side, qty):
    try:
        if exchange == "bybit":
            return bybit_post(creds, "/v5/order/create",
                {"category": "spot", "symbol": symbol,
                 "side": side.capitalize(), "orderType": "Market", "qty": str(qty)})
        elif exchange == "binance":
            return binance_post(creds, "/api/v3/order",
                {"symbol": symbol, "side": side.upper(),
                 "type": "MARKET", "quantity": qty})
        elif exchange == "okx":
            return okx_request(creds, "POST", "/api/v5/trade/order",
                {"instId": symbol.replace("USDT", "-USDT"), "tdMode": "cash",
                 "side": side.lower(), "ordType": "market", "sz": str(qty)})
        elif exchange == "kucoin":
            return kucoin_request(creds, "POST", "/api/v1/orders",
                {"clientOid": str(int(time.time() * 1000)), "side": side.lower(),
                 "symbol": symbol.replace("USDT", "-USDT"),
                 "type": "market", "size": str(qty)})
    except Exception as e:
        return {"error": str(e)}
    return {"error": "unknown exchange"}
