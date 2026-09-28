import os
import psutil
from typing import List, Dict

def get_system_processes(sort_by: str = "cpu", limit: int = 30) -> List[Dict]:
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

    return procs[:limit]

def kill_system_process(pid: int, signal: int = 15) -> dict:
    os.kill(pid, signal)
    return {"success": True, "message": f"PID {pid} terminated"}
