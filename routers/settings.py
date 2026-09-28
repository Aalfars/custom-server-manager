import os
from typing import Optional
from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from core.config import BASE_DIR
from core.database import get_db, get_setting, set_setting, log_audit
from core.security import require_auth

router = APIRouter(tags=["settings"])

class SettingsPayload(BaseModel):
    pin: Optional[str] = None
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    alert_cpu_threshold: Optional[str] = None
    alert_ram_threshold: Optional[str] = None
    alert_disk_threshold: Optional[str] = None

@router.get("/api/settings")
async def get_settings(request: Request):
    require_auth(request)
    return {
        "pin": get_setting("pin", "654321"),
        "telegram_bot_token": get_setting("telegram_bot_token", ""),
        "telegram_chat_id": get_setting("telegram_chat_id", ""),
        "alert_cpu_threshold": get_setting("alert_cpu_threshold", "90"),
        "alert_ram_threshold": get_setting("alert_ram_threshold", "90"),
        "alert_disk_threshold": get_setting("alert_disk_threshold", "90")
    }

@router.post("/api/settings")
async def update_settings(payload: SettingsPayload, request: Request):
    require_auth(request)
    if payload.pin and len(payload.pin.strip()) >= 4:
        set_setting("pin", payload.pin.strip())
    if payload.telegram_bot_token is not None:
        set_setting("telegram_bot_token", payload.telegram_bot_token.strip())
    if payload.telegram_chat_id is not None:
        set_setting("telegram_chat_id", payload.telegram_chat_id.strip())
    if payload.alert_cpu_threshold:
        set_setting("alert_cpu_threshold", payload.alert_cpu_threshold)
    if payload.alert_ram_threshold:
        set_setting("alert_ram_threshold", payload.alert_ram_threshold)
    if payload.alert_disk_threshold:
        set_setting("alert_disk_threshold", payload.alert_disk_threshold)

    log_audit("system", "UPDATE_SETTINGS", "Updated system settings / PIN")
    return {"success": True, "message": "Pengaturan berhasil disimpan"}

@router.get("/api/logs")
async def get_audit_logs(
    request: Request,
    limit: int = 100,
    action_filter: str = "ALL",
    search: str = ""
):
    require_auth(request)
    limit = min(max(10, limit), 200)
    db = get_db()
    
    query = "SELECT * FROM audit_logs"
    params = []
    conditions = []

    if action_filter and action_filter != "ALL":
        conditions.append("action LIKE ?")
        params.append(f"{action_filter}%")

    if search and search.strip():
        conditions.append("(detail LIKE ? OR action LIKE ? OR node_id LIKE ? OR ip LIKE ?)")
        s = f"%{search.strip()}%"
        params.extend([s, s, s, s])

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)

    rows = db.execute(query, params).fetchall()
    db.close()
    return {"logs": [dict(r) for r in rows]}

@router.delete("/api/logs")
async def delete_audit_logs(request: Request):
    require_auth(request)
    db = get_db()
    db.execute("DELETE FROM audit_logs")
    db.commit()
    db.close()
    return {"success": True, "message": "Seluruh audit log berhasil dibersihkan"}

@router.get("/install-agent.sh", response_class=PlainTextResponse)
async def serve_installer():
    script_path = os.path.join(BASE_DIR, "scripts", "install-agent.sh")
    if os.path.exists(script_path):
        with open(script_path, "r", encoding="utf-8") as f:
            return f.read()
    return "# Installer not configured yet"
