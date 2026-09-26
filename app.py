import os
import sys
import time
import json
import asyncio
import sqlite3
import subprocess
import pty
import fcntl
import termios
import struct
import select
from typing import Dict, List, Optional
from datetime import datetime

import psutil
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, Response, HTTPException, Depends
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

# Initialize Paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
STATIC_DIR = os.path.join(BASE_DIR, "static")
DB_PATH = os.path.join(DATA_DIR, "ops.db")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(TEMPLATES_DIR, exist_ok=True)
os.makedirs(STATIC_DIR, exist_ok=True)

# Database Setup
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
    CREATE TABLE IF NOT EXISTS nodes (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        token TEXT UNIQUE NOT NULL,
        ip TEXT,
        os_info TEXT,
        is_local INTEGER DEFAULT 0,
        created_at INTEGER
    )
    """)
    c.execute("""
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT
    )
    """)
    c.execute("""
    CREATE TABLE IF NOT EXISTS audit_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp INTEGER,
        node_id TEXT,
        action TEXT,
        detail TEXT,
        status TEXT
    )
    """)
    # Default settings
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('pin', '654321')")
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('telegram_bot_token', '')")
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('telegram_chat_id', '')")
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('alert_cpu_threshold', '90')")
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('alert_ram_threshold', '90')")
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('alert_disk_threshold', '90')")

    # Ensure Local Node is registered
    c.execute("SELECT id FROM nodes WHERE is_local = 1")
    if not c.fetchone():
        c.execute("""
        INSERT INTO nodes (id, name, token, ip, os_info, is_local, created_at)
        VALUES ('local-host', 'NODE-01 // TOKYO-NAT (HOST)', 'local-master-token', '127.0.0.1', 'Linux Host', 1, ?)
        """, (int(time.time()),))

    conn.commit()
    conn.close()

init_db()

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def get_setting(key: str, default: str = "") -> str:
    db = get_db()
    row = db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    db.close()
    return row["value"] if row else default

def set_setting(key: str, value: str):
    db = get_db()
    db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
    db.commit()
    db.close()

def log_audit(node_id: str, action: str, detail: str, status: str = "SUCCESS"):
    try:
        db = get_db()
        db.execute("""
        INSERT INTO audit_logs (timestamp, node_id, action, detail, status)
        VALUES (?, ?, ?, ?, ?)
        """, (int(time.time()), node_id, action, detail[:500], status))
        db.commit()
        db.close()
    except Exception:
        pass

# FastAPI App
app = FastAPI(title="KOKORO // Multi-Node Server Ops", docs_url=None, redoc_url=None)
templates = Jinja2Templates(directory=TEMPLATES_DIR)
if os.path.exists(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Remote Agents Store
# node_id -> { "ws": WebSocket, "token": str, "last_seen": float, "telemetry": dict, "pending_requests": dict }
connected_agents: Dict[str, dict] = {}
# Browser subscribers for live telemetry
telemetry_subscribers: List[WebSocket] = []

# Network previous values for delta speed computation
_prev_net_io = psutil.net_io_counters()
_prev_net_time = time.time()

def get_node_name(node_id: str, default: str = "") -> str:
    try:
        db = get_db()
        row = db.execute("SELECT name FROM nodes WHERE id = ?", (node_id,)).fetchone()
        db.close()
        if row and row["name"]:
            return row["name"]
    except Exception:
        pass
    return default

def get_local_telemetry() -> dict:
    global _prev_net_io, _prev_net_time
    now = time.time()
    dt = max(0.1, now - _prev_net_time)

    # CPU
    cpu_percent = psutil.cpu_percent(interval=None)
    cpu_count = psutil.cpu_count(logical=True)
    load_avg = [round(x, 2) for x in os.getloadavg()]

    # Memory
    mem = psutil.virtual_memory()
    swap = psutil.swap_memory()

    # Disk
    disk = psutil.disk_usage('/')

    # Net I/O speed
    net_now = psutil.net_io_counters()
    rx_speed = (net_now.bytes_recv - _prev_net_io.bytes_recv) / dt
    tx_speed = (net_now.bytes_sent - _prev_net_io.bytes_sent) / dt
    _prev_net_io = net_now
    _prev_net_time = now

    # OS Info
    uname = os.uname()
    os_name = f"{uname.sysname} {uname.release} ({uname.machine})"
    try:
        if os.path.exists("/etc/os-release"):
            with open("/etc/os-release") as f:
                for line in f:
                    if line.startswith("PRETTY_NAME="):
                        os_name = line.strip().split("=")[1].replace('"', '')
                        break
    except Exception:
        pass

    # Uptime
    boot_time = psutil.boot_time()
    uptime_sec = int(now - boot_time)

    return {
        "node_id": "local-host",
        "name": get_node_name("local-host", "NODE-01 // TOKYO-NAT (HOST)"),
        "status": "online",
        "is_local": True,
        "os_info": os_name,
        "kernel": uname.release,
        "uptime": uptime_sec,
        "cpu": {
            "percent": round(cpu_percent, 1),
            "cores": cpu_count,
            "load_avg": load_avg
        },
        "memory": {
            "total_mb": round(mem.total / (1024 * 1024), 1),
            "used_mb": round(mem.used / (1024 * 1024), 1),
            "free_mb": round(mem.available / (1024 * 1024), 1),
            "percent": round(mem.percent, 1)
        },
        "swap": {
            "total_mb": round(swap.total / (1024 * 1024), 1),
            "used_mb": round(swap.used / (1024 * 1024), 1),
            "percent": round(swap.percent, 1)
        },
        "disk": {
            "total_gb": round(disk.total / (1024**3), 2),
            "used_gb": round(disk.used / (1024**3), 2),
            "free_gb": round(disk.free / (1024**3), 2),
            "percent": round(disk.percent, 1)
        },
        "network": {
            "rx_kbps": round(rx_speed / 1024, 1),
            "tx_kbps": round(tx_speed / 1024, 1),
            "total_rx_mb": round(net_now.bytes_recv / (1024**2), 1),
            "total_tx_mb": round(net_now.bytes_sent / (1024**2), 1)
        },
        "updated_at": int(now)
    }

# Session Authentication
def is_authenticated(request: Request) -> bool:
    session_pin = request.cookies.get("kokoro_auth")
    valid_pin = get_setting("pin", "654321")
    return session_pin == valid_pin

def require_auth(request: Request):
    if not is_authenticated(request):
        raise HTTPException(status_code=401, detail="Unauthorized")

# ----------------- HTTP Routes -----------------

@app.api_route("/", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request=request, name="index.html", context={
        "request": request,
        "is_auth": is_authenticated(request),
        "host_domain": "server.aranya.my.id"
    })

@app.post("/api/auth/login")
async def login(request: Request, response: Response):
    data = await request.json()
    pin = data.get("pin", "")
    valid_pin = get_setting("pin", "654321")
    if pin == valid_pin:
        response.set_cookie(
            key="kokoro_auth",
            value=pin,
            max_age=86400 * 30, # 30 days
            httponly=True,
            samesite="lax"
        )
        return {"success": True, "message": "Autentikasi Berhasil"}
    return JSONResponse(status_code=401, content={"success": False, "message": "PIN Keamanan Salah!"})

@app.post("/api/auth/logout")
async def logout(response: Response):
    response.delete_cookie("kokoro_auth")
    return {"success": True}

# Node Telemetry & List
@app.get("/api/nodes")
async def list_nodes(request: Request):
    require_auth(request)
    db = get_db()
    rows = db.execute("SELECT * FROM nodes ORDER BY is_local DESC, created_at ASC").fetchall()
    db.close()

    result = []
    local_data = get_local_telemetry()

    for row in rows:
        n_id = row["id"]
        node_name = row["name"]
        if row["is_local"]:
            item = dict(local_data)
            item["name"] = node_name
            result.append(item)
        else:
            agent = connected_agents.get(n_id)
            if agent and (time.time() - agent.get("last_seen", 0) < 10):
                telemetry = dict(agent.get("telemetry", {}))
                telemetry["node_id"] = n_id
                telemetry["name"] = node_name
                telemetry["status"] = "online"
                telemetry["is_local"] = False
                result.append(telemetry)
            else:
                result.append({
                    "node_id": n_id,
                    "name": row["name"],
                    "status": "offline",
                    "is_local": False,
                    "os_info": row["os_info"] or "Unknown OS",
                    "uptime": 0,
                    "cpu": {"percent": 0, "cores": 1, "load_avg": [0, 0, 0]},
                    "memory": {"total_mb": 0, "used_mb": 0, "free_mb": 0, "percent": 0},
                    "disk": {"total_gb": 0, "used_gb": 0, "free_gb": 0, "percent": 0},
                    "network": {"rx_kbps": 0, "tx_kbps": 0},
                    "updated_at": 0
                })

    return {"nodes": result}

# Register / Add Node
class AddNodeRequest(BaseModel):
    name: str

@app.post("/api/nodes/register")
async def register_node(payload: AddNodeRequest, request: Request):
    require_auth(request)
    import secrets
    token = "node_" + secrets.token_hex(16)
    node_id = "node-" + secrets.token_hex(4)
    now = int(time.time())

    db = get_db()
    db.execute("""
    INSERT INTO nodes (id, name, token, is_local, created_at)
    VALUES (?, ?, ?, 0, ?)
    """, (node_id, payload.name.strip(), token, now))
    db.commit()
    db.close()

    log_audit("system", "REGISTER_NODE", f"Node '{payload.name}' dibuat dengan ID {node_id}")

    install_cmd = f"curl -sSL https://server.aranya.my.id/install-agent.sh | bash -s -- --hub https://server.aranya.my.id --token {token} --name \"{payload.name}\""

    return {
        "success": True,
        "node_id": node_id,
        "token": token,
        "install_command": install_cmd
    }

@app.delete("/api/nodes/{node_id}")
async def delete_node(node_id: str, request: Request):
    require_auth(request)
    if node_id == "local-host":
        raise HTTPException(status_code=400, detail="Cannot delete Host node")

    db = get_db()
    db.execute("DELETE FROM nodes WHERE id = ?", (node_id,))
    db.commit()
    db.close()

    if node_id in connected_agents:
        try:
            await connected_agents[node_id]["ws"].close()
        except Exception:
            pass
        connected_agents.pop(node_id, None)

    log_audit(node_id, "DELETE_NODE", f"Node {node_id} dihapus")
    return {"success": True}

class RenameNodeRequest(BaseModel):
    name: str

@app.post("/api/nodes/{node_id}/rename")
async def rename_node(node_id: str, payload: RenameNodeRequest, request: Request):
    require_auth(request)
    new_name = payload.name.strip()
    if not new_name:
        raise HTTPException(status_code=400, detail="Nama server tidak boleh kosong")

    db = get_db()
    node = db.execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone()
    if not node:
        db.close()
        raise HTTPException(status_code=404, detail="Server node tidak ditemukan")

    db.execute("UPDATE nodes SET name = ? WHERE id = ?", (new_name, node_id))
    db.commit()
    db.close()

    if node_id in connected_agents:
        connected_agents[node_id]["name"] = new_name

    log_audit(node_id, "RENAME_NODE", f"Node diubah namanya menjadi '{new_name}'")
    return {"success": True, "message": "Nama server berhasil diperbarui", "name": new_name}

# System Services Management
@app.get("/api/nodes/{node_id}/services")
async def get_services(node_id: str, request: Request):
    require_auth(request)
    if node_id == "local-host":
        # Local systemctl query
        try:
            cmd = "systemctl list-units --type=service --all --no-pager --no-legend"
            res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=5)
            services = []
            
            # Key services to track
            highlight = ["mt5-trading", "mt5-dashboard", "cloudflared-tunnel", "nginx", "ssh", "cron", "kokoro-server"]
            
            for line in res.stdout.splitlines():
                parts = line.strip().split()
                if not parts:
                    continue
                if parts[0] in ("●", "*", "x", "!") and len(parts) >= 5:
                    parts = parts[1:]
                if len(parts) >= 4:
                    unit_name = parts[0]
                    if not (unit_name.endswith(".service") or unit_name.endswith(".timer") or unit_name.endswith(".socket")):
                        continue
                    load = parts[1]
                    active = parts[2]
                    sub = parts[3]
                    desc = " ".join(parts[4:]) if len(parts) > 4 else ""
                    
                    is_key = any(h in unit_name for h in highlight)
                    services.append({
                        "name": unit_name,
                        "load": load,
                        "active": active,
                        "sub": sub,
                        "description": desc,
                        "highlight": is_key
                    })
            # Sort highlights first
            services.sort(key=lambda s: (not s["highlight"], s["name"]))
            return {"services": services[:100]}
        except Exception as e:
            return JSONResponse(status_code=500, content={"error": str(e)})
    else:
        # Remote agent query via WebSocket RPC
        agent = connected_agents.get(node_id)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent is offline")
        try:
            resp = await send_agent_rpc(node_id, {"action": "get_services"})
            return resp
        except Exception as e:
            return JSONResponse(status_code=500, content={"error": str(e)})

class ServiceActionRequest(BaseModel):
    service_name: str
    action: str # start, stop, restart, reload

@app.post("/api/nodes/{node_id}/service-action")
async def service_action(node_id: str, payload: ServiceActionRequest, request: Request):
    require_auth(request)
    action = payload.action
    service = payload.service_name
    if action not in ["start", "stop", "restart", "reload"]:
        raise HTTPException(status_code=400, detail="Invalid action")

    if node_id == "local-host":
        try:
            cmd = f"systemctl {action} {service}"
            subprocess.run(cmd, shell=True, check=True, timeout=15)
            log_audit(node_id, "SERVICE_ACTION", f"{action} service {service}")
            return {"success": True, "message": f"Service {service} successfully {action}ed"}
        except subprocess.CalledProcessError as e:
            return JSONResponse(status_code=500, content={"success": False, "error": f"Failed to {action} {service}"})
    else:
        agent = connected_agents.get(node_id)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent is offline")
        resp = await send_agent_rpc(node_id, {"action": "service_action", "service": service, "op": action})
        log_audit(node_id, "REMOTE_SERVICE_ACTION", f"{action} service {service}")
        return resp

# Service Log Viewer (journalctl)
@app.get("/api/nodes/{node_id}/service-logs")
async def service_logs(node_id: str, service: str, lines: int = 50, request: Request = None):
    require_auth(request)
    if node_id == "local-host":
        try:
            cmd = f"journalctl -u {service} -n {lines} --no-pager"
            res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=5)
            return {"logs": res.stdout.splitlines()}
        except Exception as e:
            return {"error": str(e)}
    else:
        agent = connected_agents.get(node_id)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent is offline")
        return await send_agent_rpc(node_id, {"action": "service_logs", "service": service, "lines": lines})

# Process Manager
@app.get("/api/nodes/{node_id}/processes")
async def get_processes(node_id: str, sort_by: str = "cpu", request: Request = None):
    require_auth(request)
    if node_id == "local-host":
        procs = []
        for p in psutil.process_iter(['pid', 'name', 'username', 'cpu_percent', 'memory_percent', 'status', 'cmdline']):
            try:
                info = p.info
                cmdline = " ".join(info['cmdline'] or [info['name']])
                procs.append({
                    "pid": info['pid'],
                    "name": info['name'],
                    "user": info['username'],
                    "cpu": round(info['cpu_percent'] or 0, 1),
                    "memory": round(info['memory_percent'] or 0, 1),
                    "status": info['status'],
                    "cmd": cmdline[:90]
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        if sort_by == "memory":
            procs.sort(key=lambda x: x["memory"], reverse=True)
        else:
            procs.sort(key=lambda x: x["cpu"], reverse=True)

        return {"processes": procs[:30]}
    else:
        agent = connected_agents.get(node_id)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent is offline")
        return await send_agent_rpc(node_id, {"action": "get_processes", "sort_by": sort_by})

class KillProcessRequest(BaseModel):
    pid: int
    signal: int = 15 # default SIGTERM (15) or SIGKILL (9)

@app.post("/api/nodes/{node_id}/kill-process")
async def kill_process(node_id: str, payload: KillProcessRequest, request: Request):
    require_auth(request)
    if node_id == "local-host":
        try:
            os.kill(payload.pid, payload.signal)
            log_audit(node_id, "KILL_PROCESS", f"Killed PID {payload.pid} with signal {payload.signal}")
            return {"success": True, "message": f"PID {payload.pid} terminated"}
        except Exception as e:
            return JSONResponse(status_code=500, content={"success": False, "error": str(e)})
    else:
        agent = connected_agents.get(node_id)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent is offline")
        return await send_agent_rpc(node_id, {"action": "kill_process", "pid": payload.pid, "signal": payload.signal})

# Execute Shell Command (Batch & Quick Script Runner)
class ExecRequest(BaseModel):
    command: str

@app.post("/api/nodes/{node_id}/exec")
async def exec_command(node_id: str, payload: ExecRequest, request: Request):
    require_auth(request)
    cmd = payload.command.strip()
    if not cmd:
        raise HTTPException(status_code=400, detail="Empty command")

    if node_id == "local-host":
        try:
            t0 = time.time()
            res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
            elapsed = round(time.time() - t0, 2)
            log_audit(node_id, "EXEC_COMMAND", cmd, "SUCCESS" if res.returncode == 0 else "FAILED")
            return {
                "success": res.returncode == 0,
                "stdout": res.stdout,
                "stderr": res.stderr,
                "exit_code": res.returncode,
                "elapsed": elapsed
            }
        except subprocess.TimeoutExpired:
            return {"success": False, "error": "Command timed out after 60s", "exit_code": -1}
        except Exception as e:
            return {"success": False, "error": str(e), "exit_code": -1}
    else:
        agent = connected_agents.get(node_id)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent is offline")
        return await send_agent_rpc(node_id, {"action": "exec", "command": cmd})

# System Power & Maintenance Actions
@app.post("/api/nodes/{node_id}/reboot")
async def reboot_node(node_id: str, request: Request):
    require_auth(request)
    log_audit(node_id, "SYSTEM_REBOOT", f"Reboot dipicu untuk node {node_id}")
    if node_id == "local-host":
        try:
            subprocess.Popen("sleep 1 && systemctl reboot", shell=True)
            return {"success": True, "message": "Host server sedang reboot..."}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    else:
        agent = connected_agents.get(node_id)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent is offline")
        try:
            await send_agent_rpc(node_id, {"action": "exec", "command": "sleep 1 && systemctl reboot &"}, timeout=5.0)
            return {"success": True, "message": "Satellite server sedang reboot..."}
        except asyncio.TimeoutError:
            return {"success": True, "message": "Perintah reboot terkirim."}
        except Exception as e:
            return {"success": True, "message": f"Perintah reboot dikirim: {str(e)}"}

@app.post("/api/nodes/{node_id}/clean-cache")
async def clean_node_cache(node_id: str, request: Request):
    require_auth(request)
    log_audit(node_id, "CLEAN_CACHE", f"Drop pagecache dipicu untuk node {node_id}")
    cmd = "sync && echo 3 > /proc/sys/vm/drop_caches"
    if node_id == "local-host":
        try:
            res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
            return {"success": res.returncode == 0, "message": "Kernel RAM cache berhasil dibersihkan"}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    else:
        agent = connected_agents.get(node_id)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent is offline")
        res = await send_agent_rpc(node_id, {"action": "exec", "command": cmd})
        return {"success": res.get("success", False), "message": "RAM Cache satellite berhasil dibersihkan", "detail": res}

# File Manager / Config Editor
@app.get("/api/nodes/{node_id}/files")
async def list_files(node_id: str, path: str = "/root", request: Request = None):
    require_auth(request)
    if node_id == "local-host":
        try:
            target = os.path.abspath(path)
            if not os.path.exists(target):
                raise HTTPException(status_code=404, detail="Path not found")
            entries = []
            with os.scandir(target) as it:
                for entry in it:
                    try:
                        st = entry.stat()
                        entries.append({
                            "name": entry.name,
                            "path": entry.path,
                            "is_dir": entry.is_dir(),
                            "size": st.st_size,
                            "mtime": int(st.st_mtime),
                            "mode": oct(st.st_mode)[-3:]
                        })
                    except Exception:
                        continue
            entries.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))
            return {"current_path": target, "entries": entries[:200]}
        except Exception as e:
            return JSONResponse(status_code=500, content={"error": str(e)})
    else:
        agent = connected_agents.get(node_id)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent is offline")
        return await send_agent_rpc(node_id, {"action": "list_files", "path": path})

@app.get("/api/nodes/{node_id}/file-content")
async def file_content(node_id: str, path: str, request: Request):
    require_auth(request)
    if node_id == "local-host":
        try:
            target = os.path.abspath(path)
            if not os.path.isfile(target):
                raise HTTPException(status_code=404, detail="File not found")
            if os.path.getsize(target) > 2 * 1024 * 1024:
                raise HTTPException(status_code=400, detail="File too large to open via web (>2MB)")
            with open(target, "r", encoding="utf-8", errors="replace") as f:
                content = f.read()
            return {"path": target, "content": content}
        except Exception as e:
            return JSONResponse(status_code=500, content={"error": str(e)})
    else:
        agent = connected_agents.get(node_id)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent is offline")
        return await send_agent_rpc(node_id, {"action": "file_content", "path": path})

class SaveFileRequest(BaseModel):
    path: str
    content: str

@app.post("/api/nodes/{node_id}/file-save")
async def save_file(node_id: str, payload: SaveFileRequest, request: Request):
    require_auth(request)
    if node_id == "local-host":
        try:
            target = os.path.abspath(payload.path)
            # Backup original first
            if os.path.exists(target):
                try:
                    with open(target + ".bak", "w", encoding="utf-8") as bf:
                        with open(target, "r", encoding="utf-8") as orig:
                            bf.write(orig.read())
                except Exception:
                    pass
            with open(target, "w", encoding="utf-8") as f:
                f.write(payload.content)
            log_audit(node_id, "SAVE_FILE", f"Edited {target}")
            return {"success": True, "message": f"File {os.path.basename(target)} saved successfully"}
        except Exception as e:
            return JSONResponse(status_code=500, content={"success": False, "error": str(e)})
    else:
        agent = connected_agents.get(node_id)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent is offline")
        return await send_agent_rpc(node_id, {"action": "save_file", "path": payload.path, "content": payload.content})

# Audit Logs
@app.get("/api/logs")
async def get_audit_logs(request: Request):
    require_auth(request)
    db = get_db()
    rows = db.execute("SELECT * FROM audit_logs ORDER BY id DESC LIMIT 50").fetchall()
    db.close()
    return {"logs": [dict(r) for r in rows]}

# Settings
@app.get("/api/settings")
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

class SettingsPayload(BaseModel):
    pin: Optional[str] = None
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    alert_cpu_threshold: Optional[str] = None
    alert_ram_threshold: Optional[str] = None
    alert_disk_threshold: Optional[str] = None

@app.post("/api/settings")
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

# Public Agent Installer Script
@app.get("/install-agent.sh", response_class=PlainTextResponse)
async def serve_installer():
    script_path = os.path.join(BASE_DIR, "scripts", "install-agent.sh")
    if os.path.exists(script_path):
        with open(script_path, "r", encoding="utf-8") as f:
            return f.read()
    return "# Installer not configured yet"

# ----------------- WebSockets -----------------

# Telemetry broadcast to admin browser
@app.websocket("/ws/telemetry")
async def ws_telemetry(websocket: WebSocket):
    await websocket.accept()
    telemetry_subscribers.append(websocket)
    try:
        while True:
            await asyncio.sleep(2)
            try:
                db = get_db()
                node_map = {r["id"]: r["name"] for r in db.execute("SELECT id, name FROM nodes").fetchall()}
                db.close()
            except Exception:
                node_map = {}

            local_telemetry = get_local_telemetry()
            if "local-host" in node_map:
                local_telemetry["name"] = node_map["local-host"]
            
            # Combine all node telemetry
            all_nodes = [local_telemetry]
            now = time.time()
            for n_id, ag in list(connected_agents.items()):
                if now - ag.get("last_seen", 0) < 10:
                    t = dict(ag.get("telemetry", {}))
                    t["node_id"] = n_id
                    t["name"] = node_map.get(n_id, ag.get("name", t.get("name", n_id)))
                    t["status"] = "online"
                    t["is_local"] = False
                    all_nodes.append(t)

            await websocket.send_json({"type": "telemetry", "nodes": all_nodes})
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        if websocket in telemetry_subscribers:
            telemetry_subscribers.remove(websocket)

# Interactive Web Terminal (PTY)
@app.websocket("/ws/terminal/{node_id}")
async def ws_terminal(websocket: WebSocket, node_id: str):
    await websocket.accept()

    if node_id == "local-host":
        # Spawn local interactive PTY bash process
        master_fd, slave_fd = pty.openpty()

        # Set non-blocking
        flags = fcntl.fcntl(master_fd, fcntl.F_GETFL)
        fcntl.fcntl(master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

        # Default size 80x24
        winsize = struct.pack("HHHH", 24, 80, 0, 0)
        fcntl.ioctl(master_fd, termios.TIOCSWINSZ, winsize)

        pid = os.fork()
        if pid == 0:
            # Child process
            os.close(master_fd)
            os.setsid()
            fcntl.ioctl(slave_fd, termios.TIOCSCTTY, 0)
            os.dup2(slave_fd, 0)
            os.dup2(slave_fd, 1)
            os.dup2(slave_fd, 2)
            os.close(slave_fd)
            os.environ["TERM"] = "xterm-256color"
            os.environ["LANG"] = "en_US.UTF-8"
            os.environ["LC_ALL"] = "en_US.UTF-8"
            os.execlp("/bin/bash", "/bin/bash", "-l")
            sys.exit(0)

        os.close(slave_fd)

        async def read_from_pty():
            loop = asyncio.get_event_loop()
            try:
                while True:
                    await asyncio.sleep(0.02)
                    r, _, _ = select.select([master_fd], [], [], 0)
                    if r:
                        try:
                            data = os.read(master_fd, 4096)
                            if not data:
                                break
                            await websocket.send_bytes(data)
                        except (BlockingIOError, OSError):
                            pass
            except (WebSocketDisconnect, Exception):
                pass

        async def write_to_pty():
            try:
                while True:
                    msg = await websocket.receive()
                    if "text" in msg:
                        data = msg["text"]
                        try:
                            # Check resize message format: {"resize": [cols, rows]}
                            js = json.loads(data)
                            if "resize" in js:
                                cols, rows = js["resize"]
                                winsize = struct.pack("HHHH", rows, cols, 0, 0)
                                fcntl.ioctl(master_fd, termios.TIOCSWINSZ, winsize)
                                continue
                        except Exception:
                            pass
                        os.write(master_fd, data.encode('utf-8'))
                    elif "bytes" in msg:
                        os.write(master_fd, msg["bytes"])
            except (WebSocketDisconnect, Exception):
                pass

        reader_task = asyncio.create_task(read_from_pty())
        writer_task = asyncio.create_task(write_to_pty())

        try:
            await asyncio.gather(reader_task, writer_task)
        finally:
            try:
                os.close(master_fd)
                os.kill(pid, 9)
                os.waitpid(pid, 0)
            except Exception:
                pass
    else:
        # Tunnel terminal to remote agent
        agent = connected_agents.get(node_id)
        if not agent:
            await websocket.send_text("\r\n[!] Agent is offline. Cannot open terminal session.\r\n")
            await websocket.close()
            return

        session_id = f"term_{int(time.time()*1000)}"
        agent_ws = agent["ws"]

        # Tell agent to open terminal
        await agent_ws.send_json({"action": "open_terminal", "session_id": session_id})

        # Relay loop
        async def browser_to_agent():
            try:
                while True:
                    msg = await websocket.receive()
                    if "text" in msg:
                        await agent_ws.send_json({"action": "term_input", "session_id": session_id, "data": msg["text"]})
                    elif "bytes" in msg:
                        await agent_ws.send_bytes(msg["bytes"])
            except Exception:
                pass

        # Handled in agent message router
        agent["term_sessions"] = agent.get("term_sessions", {})
        agent["term_sessions"][session_id] = websocket

        try:
            await browser_to_agent()
        finally:
            agent["term_sessions"].pop(session_id, None)
            try:
                await agent_ws.send_json({"action": "close_terminal", "session_id": session_id})
            except Exception:
                pass

# Agent WebSocket Connection
@app.websocket("/ws/agent/{token}")
async def ws_agent_connect(websocket: WebSocket, token: str):
    db = get_db()
    node = db.execute("SELECT * FROM nodes WHERE token = ?", (token,)).fetchone()
    db.close()

    if not node:
        await websocket.close(code=4001, reason="Invalid Node Token")
        return

    node_id = node["id"]
    await websocket.accept()

    agent_entry = {
        "ws": websocket,
        "token": token,
        "last_seen": time.time(),
        "telemetry": {},
        "pending_requests": {},
        "term_sessions": {}
    }
    connected_agents[node_id] = agent_entry
    log_audit(node_id, "AGENT_CONNECTED", f"Agent for node '{node['name']}' connected")

    try:
        while True:
            msg = await websocket.receive()
            if "text" in msg:
                data = json.loads(msg["text"])
                msg_type = data.get("type")

                if msg_type == "telemetry":
                    agent_entry["telemetry"] = data.get("data", {})
                    agent_entry["last_seen"] = time.time()
                elif msg_type == "rpc_response":
                    req_id = data.get("req_id")
                    if req_id in agent_entry["pending_requests"]:
                        agent_entry["pending_requests"][req_id].set_result(data.get("result"))
                elif msg_type == "term_output":
                    session_id = data.get("session_id")
                    target_ws = agent_entry.get("term_sessions", {}).get(session_id)
                    if target_ws:
                        raw = data.get("data", "")
                        await target_ws.send_text(raw)
            elif "bytes" in msg:
                pass
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        connected_agents.pop(node_id, None)
        log_audit(node_id, "AGENT_DISCONNECTED", f"Agent '{node['name']}' disconnected")

# Helper to send RPC to agent and await response
async def send_agent_rpc(node_id: str, payload: dict, timeout: float = 15.0) -> dict:
    agent = connected_agents.get(node_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent is offline")

    import secrets
    req_id = secrets.token_hex(8)
    payload["req_id"] = req_id

    loop = asyncio.get_event_loop()
    future = loop.create_future()
    agent["pending_requests"][req_id] = future

    await agent["ws"].send_json(payload)
    try:
        res = await asyncio.wait_for(future, timeout=timeout)
        return res
    finally:
        agent["pending_requests"].pop(req_id, None)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=False)
