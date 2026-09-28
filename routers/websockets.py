import time
import json
import asyncio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from core.config import connected_agents, telemetry_subscribers
from core.database import get_db, log_audit
from services.telemetry import get_local_telemetry
from services.terminal import handle_local_terminal, handle_remote_terminal

router = APIRouter(tags=["websockets"])

@router.websocket("/ws/telemetry")
async def ws_telemetry(websocket: WebSocket):
    await websocket.accept()
    telemetry_subscribers.append(websocket)
    try:
        while True:
            await asyncio.sleep(2)
            try:
                db = get_db()
                node_map = {r["id"]: r["name"] for r in db.execute("SELECT id, name FROM nodes").fetchall()}
                db.close()
            except Exception:
                node_map = {}

            local_telemetry = get_local_telemetry()
            if "local-host" in node_map:
                local_telemetry["name"] = node_map["local-host"]

            # Combine all node telemetry
            all_nodes = [local_telemetry]
            now = time.time()
            for n_id, ag in list(connected_agents.items()):
                if now - ag.get("last_seen", 0) < 10:
                    t = dict(ag.get("telemetry", {}))
                    t["node_id"] = n_id
                    t["name"] = node_map.get(n_id, ag.get("name", t.get("name", n_id)))
                    t["status"] = "online"
                    t["is_local"] = False
                    all_nodes.append(t)

            await websocket.send_json({"type": "telemetry", "nodes": all_nodes})
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        if websocket in telemetry_subscribers:
            telemetry_subscribers.remove(websocket)

@router.websocket("/ws/terminal/{node_id}")
async def ws_terminal(websocket: WebSocket, node_id: str):
    await websocket.accept()
    if node_id == "local-host":
        await handle_local_terminal(websocket)
    else:
        await handle_remote_terminal(websocket, node_id)

@router.websocket("/ws/agent/{token}")
async def ws_agent_connect(websocket: WebSocket, token: str):
    db = get_db()
    node = db.execute("SELECT * FROM nodes WHERE token = ?", (token,)).fetchone()
    db.close()

    if not node:
        await websocket.close(code=4001, reason="Invalid Node Token")
        return

    node_id = node["id"]
    await websocket.accept()

    agent_entry = {
        "ws": websocket,
        "token": token,
        "name": node["name"],
        "last_seen": time.time(),
        "telemetry": {},
        "pending_requests": {},
        "term_sessions": {}
    }
    connected_agents[node_id] = agent_entry
    log_audit(node_id, "AGENT_CONNECTED", f"Agent for node '{node['name']}' connected")

    try:
        while True:
            msg = await websocket.receive()
            if "text" in msg:
                data = json.loads(msg["text"])
                msg_type = data.get("type")

                if msg_type == "telemetry":
                    agent_entry["telemetry"] = data.get("data", {})
                    agent_entry["last_seen"] = time.time()
                elif msg_type == "rpc_response":
                    req_id = data.get("req_id")
                    if req_id in agent_entry["pending_requests"]:
                        agent_entry["pending_requests"][req_id].set_result(data.get("result"))
                elif msg_type == "term_output":
                    session_id = data.get("session_id")
                    target_ws = agent_entry.get("term_sessions", {}).get(session_id)
                    if target_ws:
                        raw = data.get("data", "")
                        await target_ws.send_text(raw)
            elif "bytes" in msg:
                pass
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        connected_agents.pop(node_id, None)
        log_audit(node_id, "AGENT_DISCONNECTED", f"Agent '{node['name']}' disconnected")
