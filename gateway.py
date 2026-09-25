import os
import json
import httpx
from fastapi import FastAPI, HTTPException, Depends, Header
from pydantic import BaseModel

app = FastAPI(title="Nova API Gateway")

JARVIS_URL = os.environ.get("JARVIS_URL", "http://127.0.0.1:8000")
NOVA_URL = os.environ.get("NOVA_BRIDGE_URL", "http://127.0.0.1:8001")
LLM_URL = os.environ.get("LLM_URL", "http://127.0.0.1:8080")
BRIDGE_TOKEN = os.environ.get("BRIDGE_SECRET", "5ea976fdc87bd216e784ad0e16e6768b7f8a98ef7f1ca961d9036753525f9320")

VALID_CATEGORIES = {"linear", "spot"}
VALID_ACTIONS = {"buy", "sell", "price", "balance", "help"}

class TokenRequest(BaseModel):
    username: str
    password: str

@app.post("/v1/auth/token")
async def issue_token(body: TokenRequest):
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{JARVIS_URL}/token",
            data={"username": body.username, "password": body.password},
        )
    if r.status_code != 200:
        raise HTTPException(status_code=r.status_code, detail="auth failed")
    return r.json()

async def _require_user(authorization: str = Header(...)) -> str:
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{JARVIS_URL}/skills/active",
            headers={"Authorization": authorization},
        )
    if r.status_code != 200:
        raise HTTPException(status_code=401, detail="invalid or expired token")
    return authorization

class ChatRequest(BaseModel):
    message: str
    tenant_id: str

def _normalize_intent(raw: dict) -> dict:
    action = raw.get("action")
    if action not in VALID_ACTIONS:
        action = "unknown"

    category = raw.get("category", "linear")
    if category not in VALID_CATEGORIES:
        category = "linear"

    symbol = raw.get("symbol")
    if symbol and not str(symbol).upper().endswith("USDT"):
        symbol = str(symbol).upper() + "USDT"

    return {
        "action": action,
        "symbol": symbol,
        "category": category,
        "qty_usd": raw.get("qty_usd"),
    }

async def _llm_parse(message: str) -> dict:
    schema = (
        "You are an intent parser for a crypto trading bot.\n"
        "Return ONLY a JSON object with these exact fields:\n"
        '{"action": "buy|sell|price|balance|help|unknown", "symbol": "<TICKER> or null", "category": "linear" or "spot", "qty_usd": <number or null>}'
    )
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(
            f"{LLM_URL}/v1/chat/completions",
            json={
                "messages": [
                    {"role": "system", "content": schema},
                    {"role": "user", "content": message},
                ],
                "response_format": {"type": "json_object"},
                "temperature": 0.0,
                "max_tokens": 60,
            },
        )
    content = r.json()["choices"][0]["message"]["content"]
    try:
        return _normalize_intent(json.loads(content))
    except (json.JSONDecodeError, KeyError):
        return {"action": "unknown", "symbol": None, "category": "linear", "qty_usd": None}

@app.post("/v1/chat")
async def chat(body: ChatRequest, auth: str = Depends(_require_user)):
    intent = await _llm_parse(body.message)

    if intent["action"] == "unknown":
        return {"reply": "Not sure what you mean — try asking about a price or balance."}

    if intent["action"] == "price" and intent["symbol"]:
        async with httpx.AsyncClient() as client:
            r = await client.post(
                f"{NOVA_URL}/skills/execute",
                headers={"X-Bridge-Token": BRIDGE_TOKEN},
                json={
                    "skill_name": "bybit.ticker",
                    "tenant_id": body.tenant_id,
                    "parameters": {"symbol": intent["symbol"], "category": intent["category"]},
                },
            )
        if r.status_code != 200:
            raise HTTPException(status_code=r.status_code, detail=r.text)
        data = r.json()
        price = data["result"]["result"]["list"][0]["lastPrice"]
        return {"reply": f"{intent['symbol']} = ${price}", "intent": intent}

    return {"reply": f"Got intent: {intent}, but that action isn't wired up yet.", "intent": intent}

@app.get("/")
async def health():
    return {"service": "nova-api-gateway", "status": "ok"}
