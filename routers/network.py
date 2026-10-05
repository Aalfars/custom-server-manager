from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional, Any

from core.config import connected_agents, send_agent_rpc
from core.database import log_audit
from core.security import require_auth
from services.network import (
    get_listening_ports,
    get_active_connections,
    get_ufw_status,
    execute_ufw_action
)

router = APIRouter(prefix="/api/nodes", tags=["network"])

class UfwActionPayload(BaseModel):
    action: str  # enable, disable, allow, deny, delete
    port: Optional[str] = ""
    from_ip: Optional[str] = ""
    proto: Optional[str] = "tcp"
    rule_num: Optional[int] = None

@router.get("/{node_id}/network")
async def get_network_overview(node_id: str, request: Request):
    require_auth(request)
    if node_id == "local-host":
        try:
            ports = get_listening_ports()
            conns = get_active_connections()
            ufw = get_ufw_status()
            return {
                "ports": ports,
                "connections": conns,
                "ufw": ufw
            }
        except Exception as e:
            return JSONResponse(status_code=500, content={"error": str(e)})
    else:
        agent = connected_agents.get(node_id)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent is offline")
        return await send_agent_rpc(node_id, {"action": "get_network_info"})

@router.post("/{node_id}/network/ufw/action")
async def ufw_action(node_id: str, payload: UfwActionPayload, request: Request):
    require_auth(request)
    action = payload.action.lower()
    
    if node_id == "local-host":
        try:
            res = execute_ufw_action(
                action=action,
                port=payload.port,
                from_ip=payload.from_ip,
                proto=payload.proto,
                rule_num=payload.rule_num
            )
            detail = f"{action.upper()} port={payload.port} ip={payload.from_ip} rule={payload.rule_num}"
            log_audit(node_id, "UFW_ACTION", detail, ip=request.client.host if request.client else "-")
            return res
        except Exception as e:
            return JSONResponse(status_code=400, content={"success": False, "error": str(e)})
    else:
        agent = connected_agents.get(node_id)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent is offline")
        res = await send_agent_rpc(node_id, {
            "action": "ufw_action",
            "op": action,
            "port": payload.port,
            "from_ip": payload.from_ip,
            "proto": payload.proto,
            "rule_num": payload.rule_num
        })
        detail = f"{action.upper()} port={payload.port} ip={payload.from_ip} rule={payload.rule_num}"
        log_audit(node_id, "REMOTE_UFW_ACTION", detail, ip=request.client.host if request.client else "-")
        return res
