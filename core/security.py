from fastapi import Request, HTTPException
from core.database import get_setting

def is_authenticated(request: Request) -> bool:
    session_pin = request.cookies.get("kokoro_auth")
    valid_pin = get_setting("pin", "654321")
    return session_pin == valid_pin

def require_auth(request: Request):
    if not is_authenticated(request):
        raise HTTPException(status_code=401, detail="Unauthorized")

def get_client_ip(request: Request) -> str:
    if not request:
        return "-"
    # Check Cloudflare or reverse proxy headers first
    cf_ip = request.headers.get("cf-connecting-ip")
    if cf_ip:
        return cf_ip.strip()
    x_real_ip = request.headers.get("x-real-ip")
    if x_real_ip:
        return x_real_ip.strip()
    x_forwarded_for = request.headers.get("x-forwarded-for")
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()
    return request.client.host if request.client else "-"
