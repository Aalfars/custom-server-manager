from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from core.config import connected_agents, send_agent_rpc
from core.database import log_audit
from core.security import require_auth
from services.systemd import get_systemd_services, execute_service_action, get_service_logs

router = APIRouter(prefix="/api/nodes", tags=["services"])

class ServiceActionRequest(BaseModel):
    service_name: str
    action: str  # start, stop, restart, reload

@router.get("/{node_id}/services")
async def list_services(node_id: str, request: Request):
    require_auth(request)
    if node_id == "local-host":
        try:
            services = get_systemd_services()
            return {"services": services}
        except Exception as e:
            return JSONResponse(status_code=500, content={"error": str(e)})
    else:
        agent = connected_agents.get(node_id)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent is offline")
        try:
            resp = await send_agent_rpc(node_id, {"action": "get_services"})
            return resp
        except Exception as e:
            return JSONResponse(status_code=500, content={"error": str(e)})

@router.post("/{node_id}/service-action")
async def service_action(node_id: str, payload: ServiceActionRequest, request: Request):
    require_auth(request)
    action = payload.action
    service = payload.service_name
    if action not in ["start", "stop", "restart", "reload"]:
        raise HTTPException(status_code=400, detail="Invalid action")

    if node_id == "local-host":
        try:
            res = execute_service_action(service, action)
            log_audit(node_id, "SERVICE_ACTION", f"{action} service {service}")
            return res
        except Exception as e:
            return JSONResponse(status_code=500, content={"success": False, "error": f"Failed to {action} {service}: {str(e)}"})
    else:
        agent = connected_agents.get(node_id)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent is offline")
        resp = await send_agent_rpc(node_id, {"action": "service_action", "service": service, "op": action})
        log_audit(node_id, "REMOTE_SERVICE_ACTION", f"{action} service {service}")
        return resp

@router.get("/{node_id}/service-logs")
async def service_logs(node_id: str, service: str, lines: int = 50, request: Request = None):
    require_auth(request)
    if node_id == "local-host":
        try:
            logs = get_service_logs(service, lines)
            return {"logs": logs}
        except Exception as e:
            return {"error": str(e)}
    else:
        agent = connected_agents.get(node_id)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent is offline")
        return await send_agent_rpc(node_id, {"action": "service_logs", "service": service, "lines": lines})
