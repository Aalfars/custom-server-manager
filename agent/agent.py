#!/usr/bin/env python3
import os
import sys
import time
import json
import asyncio
import subprocess
import argparse
import pty
import fcntl
import termios
import struct
import select
from typing import Dict

try:
    import psutil
except ImportError:
    psutil = None

try:
    import websockets
except ImportError:
    print("[!] websockets library required. Install via: pip install websockets psutil")
    sys.exit(1)

parser = argparse.ArgumentParser(description="KOKORO // Lightweight Server Ops Agent")
parser.add_argument("--hub", required=True, help="Hub URL e.g. https://server.aranya.my.id")
parser.add_argument("--token", required=True, help="Node registration token")
parser.add_argument("--name", default="Remote Node", help="Node name")
args = parser.parse_args()

HUB_URL = args.hub.rstrip("/")
TOKEN = args.token
NODE_NAME = args.name

# Convert http(s) to ws(s)
if HUB_URL.startswith("https://"):
    WS_URL = "wss://" + HUB_URL[8:] + f"/ws/agent/{TOKEN}"
else:
    WS_URL = "ws://" + HUB_URL[7:] + f"/ws/agent/{TOKEN}"

active_terminal_sessions: Dict[str, dict] = {}

def get_system_telemetry() -> dict:
    now = time.time()
    
    # CPU & Load
    load_avg = [round(x, 2) for x in os.getloadavg()] if hasattr(os, "getloadavg") else [0, 0, 0]
    if psutil:
        cpu_pct = psutil.cpu_percent(interval=None)
        cpu_cores = psutil.cpu_count(logical=True)
        mem = psutil.virtual_memory()
        swap = psutil.swap_memory()
        disk = psutil.disk_usage('/')
        net = psutil.net_io_counters()

        mem_data = {
            "total_mb": round(mem.total / (1024 * 1024), 1),
            "used_mb": round(mem.used / (1024 * 1024), 1),
            "free_mb": round(mem.available / (1024 * 1024), 1),
            "percent": round(mem.percent, 1)
        }
        swap_data = {
            "total_mb": round(swap.total / (1024 * 1024), 1),
            "used_mb": round(swap.used / (1024 * 1024), 1),
            "percent": round(swap.percent, 1)
        }
        disk_data = {
            "total_gb": round(disk.total / (1024**3), 2),
            "used_gb": round(disk.used / (1024**3), 2),
            "free_gb": round(disk.free / (1024**3), 2),
            "percent": round(disk.percent, 1)
        }
        net_data = {
            "total_rx_mb": round(net.bytes_recv / (1024**2), 1),
            "total_tx_mb": round(net.bytes_sent / (1024**2), 1)
        }
    else:
        cpu_pct = 0.0
        cpu_cores = os.cpu_count() or 1
        mem_data = {"total_mb": 1024, "used_mb": 512, "free_mb": 512, "percent": 50.0}
        swap_data = {"total_mb": 0, "used_mb": 0, "percent": 0.0}
        disk_data = {"total_gb": 20, "used_gb": 10, "free_gb": 10, "percent": 50.0}
        net_data = {"total_rx_mb": 0, "total_tx_mb": 0}

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

    uptime_sec = 0
    try:
        with open("/proc/uptime", "r") as f:
            uptime_sec = int(float(f.readline().split()[0]))
    except Exception:
        pass

    return {
        "name": NODE_NAME,
        "os_info": os_name,
        "kernel": uname.release,
        "uptime": uptime_sec,
        "cpu": {
            "percent": round(cpu_pct, 1),
            "cores": cpu_cores,
            "load_avg": load_avg
        },
        "memory": mem_data,
        "swap": swap_data,
        "disk": disk_data,
        "network": net_data,
        "updated_at": int(now)
    }

async def handle_rpc(data: dict) -> dict:
    action = data.get("action")
    
    if action == "get_services":
        try:
            cmd = "systemctl list-units --type=service --all --no-pager --no-legend"
            res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=5)
            services = []
            highlight = ["nginx", "ssh", "cron", "docker", "mt5", "trading"]
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
                        "name": unit_name, "load": load, "active": active, "sub": sub,
                        "description": desc, "highlight": is_key
                    })
            services.sort(key=lambda s: (not s["highlight"], s["name"]))
            return {"services": services[:100]}
        except Exception as e:
            return {"error": str(e)}

    elif action == "service_action":
        service = data.get("service")
        op = data.get("op")
        if op in ["start", "stop", "restart", "reload"]:
            try:
                subprocess.run(f"systemctl {op} {service}", shell=True, check=True, timeout=15)
                return {"success": True, "message": f"Service {service} {op}ed successfully"}
            except Exception as e:
                return {"success": False, "error": str(e)}

    elif action == "service_logs":
        service = data.get("service")
        lines = data.get("lines", 50)
        try:
            res = subprocess.run(f"journalctl -u {service} -n {lines} --no-pager", shell=True, capture_output=True, text=True, timeout=5)
            return {"logs": res.stdout.splitlines()}
        except Exception as e:
            return {"error": str(e)}

    elif action == "get_processes":
        sort_by = data.get("sort_by", "cpu")
        procs = []
        if psutil:
            for p in psutil.process_iter(['pid', 'name', 'username', 'cpu_percent', 'memory_percent', 'status', 'cmdline']):
                try:
                    info = p.info
                    cmdline = " ".join(info['cmdline'] or [info['name']])
                    procs.append({
                        "pid": info['pid'], "name": info['name'], "user": info['username'],
                        "cpu": round(info['cpu_percent'] or 0, 1),
                        "memory": round(info['memory_percent'] or 0, 1),
                        "status": info['status'], "cmd": cmdline[:90]
                    })
                except Exception:
                    continue
            procs.sort(key=lambda x: x.get(sort_by, 0), reverse=True)
        return {"processes": procs[:30]}

    elif action == "kill_process":
        pid = data.get("pid")
        sig = data.get("signal", 15)
        try:
            os.kill(pid, sig)
            return {"success": True, "message": f"Killed PID {pid}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    elif action == "exec":
        cmd = data.get("command", "")
        try:
            t0 = time.time()
            res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
            return {
                "success": res.returncode == 0,
                "stdout": res.stdout,
                "stderr": res.stderr,
                "exit_code": res.returncode,
                "elapsed": round(time.time() - t0, 2)
            }
        except Exception as e:
            return {"success": False, "error": str(e), "exit_code": -1}

    elif action == "list_files":
        path = os.path.abspath(data.get("path", "/root"))
        try:
            entries = []
            with os.scandir(path) as it:
                for entry in it:
                    try:
                        st = entry.stat()
                        entries.append({
                            "name": entry.name, "path": entry.path, "is_dir": entry.is_dir(),
                            "size": st.st_size, "mtime": int(st.st_mtime), "mode": oct(st.st_mode)[-3:]
                        })
                    except Exception:
                        continue
            entries.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))
            return {"current_path": path, "entries": entries[:200]}
        except Exception as e:
            return {"error": str(e)}

    elif action == "file_content":
        path = os.path.abspath(data.get("path", ""))
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                return {"path": path, "content": f.read()}
        except Exception as e:
            return {"error": str(e)}

    elif action == "save_file":
        path = os.path.abspath(data.get("path", ""))
        content = data.get("content", "")
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            return {"success": True, "message": "File saved"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    return {"error": "Unknown action"}

async def run_agent():
    print(f"[*] Starting KOKORO Agent for '{NODE_NAME}'...")
    print(f"[*] Target Hub: {WS_URL}")

    while True:
        try:
            async with websockets.connect(WS_URL, ping_interval=20, ping_timeout=20) as ws:
                print(f"[+] Connected to Hub at {HUB_URL}!")

                async def telemetry_loop():
                    while True:
                        try:
                            telemetry = get_system_telemetry()
                            await ws.send(json.dumps({"type": "telemetry", "data": telemetry}))
                            await asyncio.sleep(2)
                        except Exception:
                            break

                t_task = asyncio.create_task(telemetry_loop())

                try:
                    while True:
                        raw_msg = await ws.recv()
                        data = json.loads(raw_msg)
                        action = data.get("action")

                        # PTY Terminal handler
                        if action == "open_terminal":
                            session_id = data.get("session_id")
                            master_fd, slave_fd = pty.openpty()
                            flags = fcntl.fcntl(master_fd, fcntl.F_GETFL)
                            fcntl.fcntl(master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
                            winsize = struct.pack("HHHH", 24, 80, 0, 0)
                            fcntl.ioctl(master_fd, termios.TIOCSWINSZ, winsize)

                            pid = os.fork()
                            if pid == 0:
                                os.close(master_fd)
                                os.setsid()
                                fcntl.ioctl(slave_fd, termios.TIOCSCTTY, 0)
                                os.dup2(slave_fd, 0)
                                os.dup2(slave_fd, 1)
                                os.dup2(slave_fd, 2)
                                os.close(slave_fd)
                                os.environ["TERM"] = "xterm-256color"
                                os.execlp("/bin/bash", "/bin/bash", "-l")
                                sys.exit(0)

                            os.close(slave_fd)
                            active_terminal_sessions[session_id] = {"fd": master_fd, "pid": pid}

                            async def pty_reader():
                                try:
                                    while session_id in active_terminal_sessions:
                                        await asyncio.sleep(0.02)
                                        r, _, _ = select.select([master_fd], [], [], 0)
                                        if r:
                                            chunk = os.read(master_fd, 4096)
                                            if not chunk:
                                                break
                                            await ws.send(json.dumps({
                                                "type": "term_output",
                                                "session_id": session_id,
                                                "data": chunk.decode("utf-8", errors="replace")
                                            }))
                                except Exception:
                                    pass

                            asyncio.create_task(pty_reader())

                        elif action == "term_input":
                            session_id = data.get("session_id")
                            inp = data.get("data", "")
                            sess = active_terminal_sessions.get(session_id)
                            if sess:
                                try:
                                    os.write(sess["fd"], inp.encode('utf-8'))
                                except Exception:
                                    pass

                        elif action == "close_terminal":
                            session_id = data.get("session_id")
                            sess = active_terminal_sessions.pop(session_id, None)
                            if sess:
                                try:
                                    os.close(sess["fd"])
                                    os.kill(sess["pid"], 9)
                                except Exception:
                                    pass

                        # Standard RPC handler
                        elif "req_id" in data:
                            req_id = data.get("req_id")
                            result = await handle_rpc(data)
                            await ws.send(json.dumps({
                                "type": "rpc_response",
                                "req_id": req_id,
                                "result": result
                            }))
                finally:
                    t_task.cancel()

        except Exception as e:
            print(f"[!] Connection lost: {e}. Reconnecting in 5 seconds...")
            await asyncio.sleep(5)

if __name__ == "__main__":
    try:
        asyncio.run(run_agent())
    except KeyboardInterrupt:
        print("\n[*] Agent stopped.")
