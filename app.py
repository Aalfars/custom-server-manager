import os
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse

import time
import asyncio
from core.config import BASE_DIR, STATIC_DIR, TEMPLATES_DIR, connected_agents
from core.database import init_db, record_telemetry_history, cleanup_old_telemetry_history
from core.security import is_authenticated
from services.telemetry import get_local_telemetry
from routers import (
    auth_router,
    nodes_router,
    services_router,
    processes_router,
    files_router,
    exec_router,
    settings_router,
    websockets_router,
    presets_router,
    cron_router,
    network_router,
    logs_router
)

# Initialize Database
init_db()

async def background_telemetry_recorder():
    last_cleanup = 0
    while True:
        try:
            # 1. Record local host
            local = get_local_telemetry()
            record_telemetry_history(
                node_id="local-host",
                cpu_percent=local["cpu"]["percent"],
                ram_percent=local["memory"]["percent"],
                disk_percent=local["disk"]["percent"],
                rx_kbps=local["network"]["rx_kbps"],
                tx_kbps=local["network"]["tx_kbps"]
            )

            # 2. Record remote connected nodes
            now = time.time()
            for n_id, ag in list(connected_agents.items()):
                if now - ag.get("last_seen", 0) < 15:
                    t = ag.get("telemetry", {})
                    if t:
                        record_telemetry_history(
                            node_id=n_id,
                            cpu_percent=t.get("cpu", {}).get("percent", 0.0),
                            ram_percent=t.get("memory", {}).get("percent", 0.0),
                            disk_percent=t.get("disk", {}).get("percent", 0.0),
                            rx_kbps=t.get("network", {}).get("rx_kbps", 0.0),
                            tx_kbps=t.get("network", {}).get("tx_kbps", 0.0)
                        )

            # 3. Cleanup every 1 hour
            if now - last_cleanup > 3600:
                cleanup_old_telemetry_history(86400)
                last_cleanup = now
        except Exception:
            pass

        await asyncio.sleep(20)

# Initialize FastAPI App
app = FastAPI(
    title="KOKORO // Multi-Node Server Ops",
    description="Modular Server Operations and Fleet Management Control Plane",
    docs_url=None,
    redoc_url=None
)

@app.on_event("startup")
async def on_startup():
    asyncio.create_task(background_telemetry_recorder())

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
app.include_router(presets_router)
app.include_router(cron_router)
app.include_router(network_router)
app.include_router(logs_router)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=False)
