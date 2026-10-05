from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Optional

from core.config import connected_agents, send_agent_rpc
from core.database import log_audit
from core.security import require_auth
from services.cron import (
    get_crontab_jobs,
    add_crontab_job,
    toggle_crontab_job,
    delete_crontab_job,
    run_crontab_job_now
)

router = APIRouter(prefix="/api/nodes", tags=["cron"])

class AddCronPayload(BaseModel):
    schedule: str
    command: str
    comment: Optional[str] = ""

class ToggleCronPayload(BaseModel):
    job_id: int
    enable: bool

class RunCronPayload(BaseModel):
    command: str

@router.get("/{node_id}/cron")
async def list_cron_jobs(node_id: str, request: Request):
    require_auth(request)
    if node_id == "local-host":
        try:
            jobs = get_crontab_jobs()
            return {"jobs": jobs}
        except Exception as e:
            return JSONResponse(status_code=500, content={"error": str(e)})
    else:
        agent = connected_agents.get(node_id)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent is offline")
        return await send_agent_rpc(node_id, {"action": "get_cron_jobs"})

@router.post("/{node_id}/cron")
async def create_cron_job(node_id: str, payload: AddCronPayload, request: Request):
    require_auth(request)
    if node_id == "local-host":
        try:
            res = add_crontab_job(payload.schedule, payload.command, payload.comment or "")
            log_audit(node_id, "ADD_CRON", f"Added cron {payload.schedule} {payload.command[:80]}", ip=request.client.host if request.client else "-")
            return res
        except Exception as e:
            return JSONResponse(status_code=400, content={"success": False, "error": str(e)})
    else:
        agent = connected_agents.get(node_id)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent is offline")
        res = await send_agent_rpc(node_id, {
            "action": "add_cron_job",
            "schedule": payload.schedule,
            "command": payload.command,
            "comment": payload.comment or ""
        })
        log_audit(node_id, "REMOTE_ADD_CRON", f"Added cron {payload.schedule} {payload.command[:80]}", ip=request.client.host if request.client else "-")
        return res

@router.post("/{node_id}/cron/toggle")
async def toggle_cron(node_id: str, payload: ToggleCronPayload, request: Request):
    require_auth(request)
    if node_id == "local-host":
        try:
            res = toggle_crontab_job(payload.job_id, payload.enable)
            log_audit(node_id, "TOGGLE_CRON", f"Toggled cron ID {payload.job_id} to {'ENABLED' if payload.enable else 'DISABLED'}", ip=request.client.host if request.client else "-")
            return res
        except Exception as e:
            return JSONResponse(status_code=400, content={"success": False, "error": str(e)})
    else:
        agent = connected_agents.get(node_id)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent is offline")
        res = await send_agent_rpc(node_id, {
            "action": "toggle_cron_job",
            "job_id": payload.job_id,
            "enable": payload.enable
        })
        log_audit(node_id, "REMOTE_TOGGLE_CRON", f"Toggled cron ID {payload.job_id} to {'ENABLED' if payload.enable else 'DISABLED'}", ip=request.client.host if request.client else "-")
        return res

@router.delete("/{node_id}/cron/{job_id}")
async def remove_cron(node_id: str, job_id: int, request: Request):
    require_auth(request)
    if node_id == "local-host":
        try:
            res = delete_crontab_job(job_id)
            log_audit(node_id, "DELETE_CRON", f"Deleted cron job ID {job_id}", ip=request.client.host if request.client else "-")
            return res
        except Exception as e:
            return JSONResponse(status_code=400, content={"success": False, "error": str(e)})
    else:
        agent = connected_agents.get(node_id)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent is offline")
        res = await send_agent_rpc(node_id, {
            "action": "delete_cron_job",
            "job_id": job_id
        })
        log_audit(node_id, "REMOTE_DELETE_CRON", f"Deleted cron job ID {job_id}", ip=request.client.host if request.client else "-")
        return res

@router.post("/{node_id}/cron/run")
async def run_cron_now(node_id: str, payload: RunCronPayload, request: Request):
    require_auth(request)
    cmd = payload.command.strip()
    if not cmd:
        raise HTTPException(status_code=400, detail="Empty command")
    if node_id == "local-host":
        try:
            res = run_crontab_job_now(cmd)
            log_audit(node_id, "RUN_CRON_NOW", f"Ran cron test {cmd[:80]}", ip=request.client.host if request.client else "-")
            return res
        except Exception as e:
            return JSONResponse(status_code=500, content={"success": False, "error": str(e)})
    else:
        agent = connected_agents.get(node_id)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent is offline")
        res = await send_agent_rpc(node_id, {
            "action": "run_cron_now",
            "command": cmd
        })
        log_audit(node_id, "REMOTE_RUN_CRON_NOW", f"Ran cron test {cmd[:80]}", ip=request.client.host if request.client else "-")
        return res
