import os
import glob
import shutil
import asyncio
from typing import List, Dict

COMMON_LOG_PATHS = [
    {"name": "System Syslog", "path": "/var/log/syslog"},
    {"name": "SSH & Auth Log", "path": "/var/log/auth.log"},
    {"name": "Nginx Access Log", "path": "/var/log/nginx/access.log"},
    {"name": "Nginx Error Log", "path": "/var/log/nginx/error.log"},
    {"name": "System Messages", "path": "/var/log/messages"},
    {"name": "Daemon Log", "path": "/var/log/daemon.log"},
    {"name": "UFW Firewall Log", "path": "/var/log/ufw.log"},
    {"name": "Kokoro Hub Ops Log", "path": "/root/server-manager/ops.log"},
    {"name": "Kokoro Hub Service Log", "path": "/root/server-manager/app.log"}
]

def get_available_log_targets() -> List[Dict]:
    targets = []
    
    # 1. Check predefined common log paths
    for item in COMMON_LOG_PATHS:
        p = item["path"]
        if os.path.exists(p) and os.path.isfile(p):
            try:
                size = os.path.getsize(p)
                targets.append({
                    "name": item["name"],
                    "path": p,
                    "size_mb": round(size / (1024 * 1024), 2),
                    "exists": True
                })
            except Exception:
                continue

    # 2. Check any other *.log files in /var/log
    if os.path.exists("/var/log"):
        try:
            for f in glob.glob("/var/log/*.log"):
                if not any(t["path"] == f for t in targets):
                    targets.append({
                        "name": os.path.basename(f),
                        "path": f,
                        "size_mb": round(os.path.getsize(f) / (1024 * 1024), 2),
                        "exists": True
                    })
        except Exception:
            pass

    # Fallback for Windows local dev
    if not targets:
        targets = [
            {"name": "System Syslog (Simulated)", "path": "/var/log/syslog", "size_mb": 1.2, "exists": True},
            {"name": "SSH Auth Log (Simulated)", "path": "/var/log/auth.log", "size_mb": 0.5, "exists": True},
            {"name": "Nginx Access Log (Simulated)", "path": "/var/log/nginx/access.log", "size_mb": 4.1, "exists": True},
            {"name": "Kokoro Service Log", "path": os.path.abspath("app.py"), "size_mb": 0.1, "exists": True}
        ]

    return targets

async def stream_local_log(path: str, lines: int, callback):
    """Streams tail output of a local file to an async callback."""
    if not os.path.exists(path):
        await callback(f"[!] File log tidak ditemukan: {path}\n")
        return

    # Check if tail CLI is available
    if shutil.which("tail"):
        cmd = f"tail -n {lines} -F '{path}'"
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT
        )
        try:
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                await callback(line.decode("utf-8", errors="replace"))
        except asyncio.CancelledError:
            proc.terminate()
            try:
                await proc.wait()
            except Exception:
                pass
            raise
    else:
        # Fallback file polling reader for Windows
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                content = f.readlines()
                for l in content[-lines:]:
                    await callback(l)
                
                f.seek(0, os.SEEK_END)
                while True:
                    await asyncio.sleep(0.5)
                    new_line = f.readline()
                    if new_line:
                        await callback(new_line)
        except asyncio.CancelledError:
            raise
