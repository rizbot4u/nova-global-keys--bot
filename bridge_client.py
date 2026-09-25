import os
import httpx

BRIDGE_URL = os.getenv("BRIDGE_URL", "http://127.0.0.1:8001")
BRIDGE_TOKEN = os.getenv("BRIDGE_TOKEN")
if not BRIDGE_TOKEN:
    raise RuntimeError("BRIDGE_TOKEN env var is required")
def execute_skill(skill_name: str, tenant_id: str, org_id: str, actor: str, parameters: dict):
    """Executes a skill securely through the Nova MCP Bridge."""
    headers = {
        "X-Bridge-Token": BRIDGE_TOKEN,
        "Content-Type": "application/json"
    }
    payload = {
        "skill_name": skill_name,
        "tenant_id": tenant_id,
        "org_id": org_id,
        "actor": actor,
        "parameters": parameters
    }
    
    try:
        response = httpx.post(f"{BRIDGE_URL}/skills/execute", json=payload, headers=headers, timeout=10.0)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        return {"error": str(e)}
