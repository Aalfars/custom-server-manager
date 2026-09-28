import os
import asyncio
import secrets
from typing import Dict, List
from fastapi import WebSocket, HTTPException

# Base Paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
STATIC_DIR = os.path.join(BASE_DIR, "static")
SCRIPTS_DIR = os.path.join(BASE_DIR, "scripts")
DB_PATH = os.path.join(DATA_DIR, "ops.db")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(TEMPLATES_DIR, exist_ok=True)
os.makedirs(STATIC_DIR, exist_ok=True)

# Connected Remote Agents Store
# node_id -> { "ws": WebSocket, "token": str, "last_seen": float, "telemetry": dict, "pending_requests": dict, "term_sessions": dict }
connected_agents: Dict[str, dict] = {}

# Active Browser subscribers for real-time telemetry WebSocket
telemetry_subscribers: List[WebSocket] = []

async def send_agent_rpc(node_id: str, payload: dict, timeout: float = 15.0) -> dict:
    """Helper to send JSON-RPC command to a connected satellite agent and await result."""
    agent = connected_agents.get(node_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent is offline")

    req_id = secrets.token_hex(8)
    payload["req_id"] = req_id

    loop = asyncio.get_event_loop()
    future = loop.create_future()
    agent["pending_requests"][req_id] = future

    try:
        await agent["ws"].send_json(payload)
    except Exception as e:
        agent["pending_requests"].pop(req_id, None)
        raise HTTPException(status_code=502, detail=f"Failed to communicate with agent: {str(e)}")

    try:
        res = await asyncio.wait_for(future, timeout=timeout)
        return res
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Agent request timed out")
    finally:
        agent["pending_requests"].pop(req_id, None)
