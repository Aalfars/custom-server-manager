import time
import subprocess
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

from core.config import connected_agents, send_agent_rpc
from core.database import log_audit
from core.security import require_auth

router = APIRouter(prefix="/api/nodes", tags=["exec"])

class ExecRequest(BaseModel):
    command: str

@router.post("/{node_id}/exec")
async def exec_command(node_id: str, payload: ExecRequest, request: Request):
    require_auth(request)
    cmd = payload.command.strip()
    if not cmd:
        raise HTTPException(status_code=400, detail="Empty command")

    if node_id == "local-host":
        try:
            t0 = time.time()
            res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
            elapsed = round(time.time() - t0, 2)
            log_audit(node_id, "EXEC_COMMAND", cmd, "SUCCESS" if res.returncode == 0 else "FAILED")
            return {
                "success": res.returncode == 0,
                "stdout": res.stdout,
                "stderr": res.stderr,
                "exit_code": res.returncode,
                "elapsed": elapsed
            }
        except subprocess.TimeoutExpired:
            return {"success": False, "error": "Command timed out after 60s", "exit_code": -1}
        except Exception as e:
            return {"success": False, "error": str(e), "exit_code": -1}
    else:
        agent = connected_agents.get(node_id)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent is offline")
        return await send_agent_rpc(node_id, {"action": "exec", "command": cmd})
