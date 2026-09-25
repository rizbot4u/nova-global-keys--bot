#!/usr/bin/env python3
"""Test the local llama-server: direct chat, JSON extraction, and Jarvis pipeline."""
import os
import sys
import json
import requests

LLM_URL = os.environ.get("LLM_URL", "http://127.0.0.1:8080")
JARVIS_URL = os.environ.get("JARVIS_URL", "http://127.0.0.1:8000")
NOVA_URL = os.environ.get("NOVA_URL", "http://127.0.0.1:8001")
BRIDGE_SECRET = os.environ.get("BRIDGE_SECRET", "")
JARVIS_USER = os.environ.get("JARVIS_USER", "owner1")
JARVIS_PASS = os.environ.get("JARVIS_PASS", "password123")
TENANT_ID = os.environ.get("TENANT_ID", "tenant_alpha")


def section(title):
    print()
    print("=" * 60)
    print("  " + title)
    print("=" * 60)


def test_llm_alive():
    section("1 · LLM alive")
    try:
        r = requests.post(
            f"{LLM_URL}/v1/chat/completions",
            json={
                "messages": [{"role": "user", "content": "Reply with OK."}],
                "max_tokens": 5,
                "temperature": 0,
            },
            timeout=60,
        )
        r.raise_for_status()
        data = r.json()
        msg = data["choices"][0]["message"]["content"].strip()
        tps = data.get("timings", {}).get("predicted_per_second", 0)
        print(f"  ✅ Response: {msg!r}")
        print(f"  ⚡ Speed:    {tps:.2f} tok/s")
        return True
    except Exception as e:
        print(f"  ❌ {e}")
        return False


def test_llm_json():
    section("2 · LLM JSON extraction")
    prompt = (
        "Extract intent from this message. Return ONLY valid JSON with keys "
        "action, symbol, exchange, qty_usd.\n"
        'Example: "buy 50 of ETH on bybit" -> '
        '{"action":"buy","symbol":"ETHUSDT","exchange":"bybit","qty_usd":50}\n'
        'Input: "what is solana trading for on okx"\nJSON:'
    )
    try:
        r = requests.post(
            f"{LLM_URL}/v1/chat/completions",
            json={
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 64,
                "temperature": 0,
            },
            timeout=120,
        )
        r.raise_for_status()
        raw = r.json()["choices"][0]["message"]["content"].strip()
        print(f"  Raw output: {raw!r}")
        import re
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            parsed = json.loads(m.group(0))
            print(f"  ✅ Parsed:   {parsed}")
        else:
            print("  ⚠️  No JSON found in output")
    except Exception as e:
        print(f"  ❌ {e}")


def test_jarvis_login():
    section("3 · Jarvis login")
    try:
        r = requests.post(
            f"{JARVIS_URL}/token",
            data={"username": JARVIS_USER, "password": JARVIS_PASS},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=10,
        )
        r.raise_for_status()
        tok = r.json()["access_token"]
        print(f"  ✅ Token: {tok[:40]}...")
        return tok
    except Exception as e:
        print(f"  ❌ {e}")
        return None


def test_nova_direct(token):
    section("4 · Nova direct (X-Bridge-Token)")
    if not BRIDGE_SECRET:
        print("  ⚠️  BRIDGE_SECRET not set — export it from ~/nova_mcp/.env")
        return
    try:
        r = requests.post(
            f"{NOVA_URL}/skills/execute",
            headers={"X-Bridge-Token": BRIDGE_SECRET, "Content-Type": "application/json"},
            json={
                "skill_name": "bybit.ticker",
                "tenant_id": TENANT_ID,
                "parameters": {"symbol": "BTCUSDT", "category": "linear"},
            },
            timeout=30,
        )
        r.raise_for_status()
        d = r.json()
        price = d["result"]["result"]["list"][0]["lastPrice"]
        used = d.get("used_tenant_creds")
        print(f"  ✅ BTC = {price}  (tenant={TENANT_ID}, used_tenant_creds={used})")
    except Exception as e:
        print(f"  ❌ {e}")


def test_jarvis_to_nova(token):
    section("5 · Jarvis → Nova (full pipeline)")
    try:
        r = requests.post(
            f"{JARVIS_URL}/skills/1/execute",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"symbol": "BTCUSDT", "category": "linear", "tenant_id": TENANT_ID},
            timeout=30,
        )
        r.raise_for_status()
        d = r.json()
        inner = d["result"]
        price = inner["result"]["result"]["list"][0]["lastPrice"]
        print(f"  ✅ Skill:       {d['skill']}")
        print(f"  ✅ Status:      {d['status']}")
        print(f"  ✅ BTC =        {price}")
        print(f"  ✅ Executed by: {d['executed_by']}  org={d['organization_id']}")
        print(f"  ✅ Tenant used: {inner['tenant_id']}  (used_tenant_creds={inner['used_tenant_creds']})")
    except Exception as e:
        print(f"  ❌ {e}")


def main():
    print("Nova LLM / Pipeline Test")
    print(f"  LLM_URL:    {LLM_URL}")
    print(f"  JARVIS_URL: {JARVIS_URL}")
    print(f"  NOVA_URL:   {NOVA_URL}")
    print(f"  TENANT:     {TENANT_ID}")

    if not test_llm_alive():
        print("\n⚠️  LLM not reachable — start llama-server first:")
        print("   cd ~/llama.cpp && ./build/bin/llama-server -m ~/llama3.2-1b.gguf \\")
        print("     --host 127.0.0.1 --port 8080 -c 1024 -np 1")
        sys.exit(1)

    test_llm_json()

    token = test_jarvis_login()
    if token:
        test_nova_direct(token)
        test_jarvis_to_nova(token)

    print()
    print("=" * 60)
    print("  Done")
    print("=" * 60)


if __name__ == "__main__":
    main()
