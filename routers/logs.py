from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse

from core.config import connected_agents, send_agent_rpc
from core.security import require_auth
from services.log_tailer import get_available_log_targets

router = APIRouter(prefix="/api/nodes", tags=["logs"])

@router.get("/{node_id}/logs/targets")
async def list_log_targets(node_id: str, request: Request):
    require_auth(request)
    if node_id == "local-host":
        try:
            targets = get_available_log_targets()
            return {"targets": targets}
        except Exception as e:
            return JSONResponse(status_code=500, content={"error": str(e)})
    else:
        agent = connected_agents.get(node_id)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent is offline")
        return await send_agent_rpc(node_id, {"action": "get_log_targets"})
