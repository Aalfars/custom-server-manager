from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from core.database import get_setting, log_audit
from core.security import get_client_ip

router = APIRouter(prefix="/api/auth", tags=["auth"])

class LoginRequest(BaseModel):
    pin: str

@router.post("/login")
async def login(payload: LoginRequest, request: Request, response: Response):
    ip = get_client_ip(request)
    valid_pin = get_setting("pin", "654321")
    if payload.pin == valid_pin:
        response.set_cookie(
            key="kokoro_auth",
            value=payload.pin,
            max_age=86400 * 30,  # 30 days
            httponly=True,
            samesite="lax"
        )
        log_audit("system", "AUTH_LOGIN", "Login berhasil ke Kokoro Control Plane", "SUCCESS", ip)
        return {"success": True, "message": "Autentikasi Berhasil"}
    
    log_audit("system", "AUTH_LOGIN", "Percobaan login gagal (PIN salah)", "FAILED", ip)
    return JSONResponse(status_code=401, content={"success": False, "message": "PIN Keamanan Salah!"})

@router.post("/logout")
async def logout(request: Request, response: Response):
    ip = get_client_ip(request)
    response.delete_cookie("kokoro_auth")
    log_audit("system", "AUTH_LOGOUT", "Sesi logout", "SUCCESS", ip)
    return {"success": True}
