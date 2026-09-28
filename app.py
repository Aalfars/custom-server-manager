import os
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse

from core.config import BASE_DIR, STATIC_DIR, TEMPLATES_DIR
from core.database import init_db
from core.security import is_authenticated
from routers import (
    auth_router,
    nodes_router,
    services_router,
    processes_router,
    files_router,
    exec_router,
    settings_router,
    websockets_router
)

# Initialize Database
init_db()

# Initialize FastAPI App
app = FastAPI(
    title="KOKORO // Multi-Node Server Ops",
    description="Modular Server Operations and Fleet Management Control Plane",
    docs_url=None,
    redoc_url=None
)

# Static & Templates setup
templates = Jinja2Templates(directory=TEMPLATES_DIR)
if os.path.exists(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Dashboard Root Route
@app.api_route("/", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request=request, name="index.html", context={
        "request": request,
        "is_auth": is_authenticated(request),
        "host_domain": "server.aranya.my.id"
    })

# Register Modular Routers
app.include_router(auth_router)
app.include_router(nodes_router)
app.include_router(services_router)
app.include_router(processes_router)
app.include_router(files_router)
app.include_router(exec_router)
app.include_router(settings_router)
app.include_router(websockets_router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=False)
