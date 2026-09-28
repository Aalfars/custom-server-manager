from fastapi import Request, HTTPException
from core.database import get_setting

def is_authenticated(request: Request) -> bool:
    session_pin = request.cookies.get("kokoro_auth")
    valid_pin = get_setting("pin", "654321")
    return session_pin == valid_pin

def require_auth(request: Request):
    if not is_authenticated(request):
        raise HTTPException(status_code=401, detail="Unauthorized")
