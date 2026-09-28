import time
import secrets
import asyncio
import subprocess
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel

from core.config import connected_agents, send_agent_rpc
from core.database import get_db, log_audit, get_telemetry_history
from core.security import require_auth
from services.telemetry import get_local_telemetry

router = APIRouter(prefix="/api/nodes", tags=["nodes"])

class AddNodeRequest(BaseModel):
    name: str

class RenameNodeRequest(BaseModel):
    name: str

@router.get("")
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

@router.post("/register")
async def register_node(payload: AddNodeRequest, request: Request):
    require_auth(request)
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

@router.delete("/{node_id}")
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

@router.post("/{node_id}/rename")
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

@router.post("/{node_id}/reboot")
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

@router.post("/{node_id}/clean-cache")
async def clean_node_cache(node_id: str, request: Request):
    require_auth(request)
    log_audit(node_id, "CLEAN_CACHE", f"Drop pagecache dipicu untuk node {node_id}")
    if node_id == "local-host":
        try:
            virt_check = subprocess.run("systemd-detect-virt", shell=True, capture_output=True, text=True).stdout.strip()
            res = subprocess.run("sync && echo 3 > /proc/sys/vm/drop_caches", shell=True, capture_output=True, text=True, timeout=10)
            if res.returncode == 0:
                return {"success": True, "message": "Kernel RAM cache berhasil dibersihkan"}
            else:
                if "openvz" in virt_check or "lxc" in virt_check:
                    return {"success": True, "message": f"Sync selesai. Server ({virt_check}) berbagi memory cache kernel dengan hypervisor host."}
                return {"success": False, "message": f"Gagal: {res.stderr.strip()}"}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
    else:
        agent = connected_agents.get(node_id)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent is offline")
        res = await send_agent_rpc(node_id, {"action": "exec", "command": "systemd-detect-virt && (sync && echo 3 > /proc/sys/vm/drop_caches)"})
        if res.get("exit_code") == 0:
            return {"success": True, "message": "RAM Cache satellite berhasil dibersihkan"}
        else:
            virt_info = res.get("stdout", "").strip()
            stderr_info = res.get("stderr", "").strip()
            if "openvz" in virt_info or "lxc" in virt_info or "Permission denied" in stderr_info:
                return {"success": True, "message": f"Sync selesai. Satellite ({virt_info or 'Container'}) mengandalkan manajemen memory hypervisor host."}
            return {"success": False, "message": f"Gagal membersihkan cache: {stderr_info}"}

@router.get("/{node_id}/telemetry/history")
async def get_node_telemetry_history(node_id: str, request: Request, range: str = "1h"):
    require_auth(request)
    duration_map = {
        "1h": 3600,
        "6h": 21600,
        "24h": 86400
    }
    duration = duration_map.get(range, 3600)
    max_pts = 120 if range == "1h" else (180 if range == "6h" else 240)
    history = get_telemetry_history(node_id, duration_seconds=duration, max_points=max_pts)
    return {
        "node_id": node_id,
        "range": range,
        "points": history
    }
