from routers.auth import router as auth_router
from routers.nodes import router as nodes_router
from routers.services import router as services_router
from routers.processes import router as processes_router
from routers.files import router as files_router
from routers.exec_cmd import router as exec_router
from routers.settings import router as settings_router
from routers.websockets import router as websockets_router
from routers.presets import router as presets_router
from routers.cron import router as cron_router
from routers.network import router as network_router
from routers.logs import router as logs_router

__all__ = [
    "auth_router",
    "nodes_router",
    "services_router",
    "processes_router",
    "files_router",
    "exec_router",
    "settings_router",
    "websockets_router",
    "presets_router",
    "cron_router",
    "network_router",
    "logs_router"
]

