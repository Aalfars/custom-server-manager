from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
from typing import Optional

from core.database import get_presets, create_preset, update_preset, delete_preset, log_audit
from core.security import require_auth

router = APIRouter(prefix="/api/presets", tags=["presets"])

class PresetPayload(BaseModel):
    name: str
    command: str
    description: Optional[str] = ""
    category: Optional[str] = "General"

@router.get("")
async def list_presets(request: Request):
    require_auth(request)
    return {"presets": get_presets()}

@router.post("")
async def add_preset(payload: PresetPayload, request: Request):
    require_auth(request)
    name = payload.name.strip()
    command = payload.command.strip()
    if not name or not command:
        raise HTTPException(status_code=400, detail="Name and Command are required")
    preset_id = create_preset(name, command, payload.description or "", payload.category or "General")
    log_audit("local-host", "CREATE_PRESET", f"Created command preset '{name}'", ip=request.client.host if request.client else "-")
    return {"success": True, "id": preset_id, "message": "Preset created successfully"}

@router.put("/{preset_id}")
async def edit_preset(preset_id: int, payload: PresetPayload, request: Request):
    require_auth(request)
    name = payload.name.strip()
    command = payload.command.strip()
    if not name or not command:
        raise HTTPException(status_code=400, detail="Name and Command are required")
    ok = update_preset(preset_id, name, command, payload.description or "", payload.category or "General")
    if not ok:
        raise HTTPException(status_code=404, detail="Preset not found")
    log_audit("local-host", "UPDATE_PRESET", f"Updated command preset '{name}'", ip=request.client.host if request.client else "-")
    return {"success": True, "message": "Preset updated"}

@router.delete("/{preset_id}")
async def remove_preset(preset_id: int, request: Request):
    require_auth(request)
    ok = delete_preset(preset_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Preset not found")
    log_audit("local-host", "DELETE_PRESET", f"Deleted command preset ID {preset_id}", ip=request.client.host if request.client else "-")
    return {"success": True, "message": "Preset deleted"}
