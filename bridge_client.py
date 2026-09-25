import os
import httpx

BRIDGE_URL = os.getenv("BRIDGE_URL", "http://127.0.0.1:8001")
BRIDGE_TOKEN = os.getenv("BRIDGE_TOKEN", "be256d085577040c190fe42ff2f30d6739d9e6a2d32614e4fafb8976c5fab01")

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
