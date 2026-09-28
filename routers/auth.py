from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from core.database import get_setting

router = APIRouter(prefix="/api/auth", tags=["auth"])

class LoginRequest(BaseModel):
    pin: str

@router.post("/login")
async def login(payload: LoginRequest, response: Response):
    valid_pin = get_setting("pin", "654321")
    if payload.pin == valid_pin:
        response.set_cookie(
            key="kokoro_auth",
            value=payload.pin,
            max_age=86400 * 30,  # 30 days
            httponly=True,
            samesite="lax"
        )
        return {"success": True, "message": "Autentikasi Berhasil"}
    return JSONResponse(status_code=401, content={"success": False, "message": "PIN Keamanan Salah!"})

@router.post("/logout")
async def logout(response: Response):
    response.delete_cookie("kokoro_auth")
    return {"success": True}
