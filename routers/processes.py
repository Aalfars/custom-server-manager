from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from core.config import connected_agents, send_agent_rpc
from core.database import log_audit
from core.security import require_auth
from services.process import get_system_processes, kill_system_process

router = APIRouter(prefix="/api/nodes", tags=["processes"])

class KillProcessRequest(BaseModel):
    pid: int
    signal: int = 15  # default SIGTERM (15) or SIGKILL (9)

@router.get("/{node_id}/processes")
async def list_processes(node_id: str, sort_by: str = "cpu", request: Request = None):
    require_auth(request)
    if node_id == "local-host":
        procs = get_system_processes(sort_by=sort_by, limit=30)
        return {"processes": procs}
    else:
        agent = connected_agents.get(node_id)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent is offline")
        return await send_agent_rpc(node_id, {"action": "get_processes", "sort_by": sort_by})

@router.post("/{node_id}/kill-process")
async def kill_process(node_id: str, payload: KillProcessRequest, request: Request):
    require_auth(request)
    if node_id == "local-host":
        try:
            res = kill_system_process(payload.pid, payload.signal)
            log_audit(node_id, "KILL_PROCESS", f"Killed PID {payload.pid} with signal {payload.signal}")
            return res
        except Exception as e:
            return JSONResponse(status_code=500, content={"success": False, "error": str(e)})
    else:
        agent = connected_agents.get(node_id)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent is offline")
        return await send_agent_rpc(node_id, {"action": "kill_process", "pid": payload.pid, "signal": payload.signal})
