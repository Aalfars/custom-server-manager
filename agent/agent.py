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
active_log_tail_sessions: Dict[str, dict] = {}

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
                if len(parts) >= 4:
                    unit_name = parts[0]
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

    elif action == "save_binary":
        path = os.path.abspath(data.get("path", ""))
        b64 = data.get("data_b64", "")
        try:
            import base64
            raw = base64.b64decode(b64)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as f:
                f.write(raw)
            return {"success": True, "message": f"File {os.path.basename(path)} saved ({len(raw)} bytes)", "path": path}
        except Exception as e:
            return {"success": False, "error": str(e)}

    elif action == "read_binary":
        path = os.path.abspath(data.get("path", ""))
        try:
            import base64
            with open(path, "rb") as f:
                raw = f.read()
            return {"success": True, "data_b64": base64.b64encode(raw).decode("ascii"), "filename": os.path.basename(path)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    elif action == "file_extract":
        src = os.path.abspath(data.get("path", ""))
        dest = os.path.abspath(data.get("destination")) if data.get("destination") else os.path.dirname(src)
        try:
            os.makedirs(dest, exist_ok=True)
            lower_src = src.lower()
            if lower_src.endswith(".zip"):
                cmd = f"unzip -o -q '{src}' -d '{dest}'"
            elif lower_src.endswith((".tar.gz", ".tgz")):
                cmd = f"tar -xzf '{src}' -C '{dest}'"
            elif lower_src.endswith((".tar.bz2", ".tbz2")):
                cmd = f"tar -xjf '{src}' -C '{dest}'"
            elif lower_src.endswith((".tar.xz", ".txz")):
                cmd = f"tar -xJf '{src}' -C '{dest}'"
            elif lower_src.endswith(".tar"):
                cmd = f"tar -xf '{src}' -C '{dest}'"
            elif lower_src.endswith(".rar"):
                cmd = f"unrar x -o+ -inul '{src}' '{dest}/'"
            elif lower_src.endswith(".7z"):
                cmd = f"7z x -y -o'{dest}' '{src}'"
            elif lower_src.endswith(".gz"):
                import shutil
                target_in_dest = os.path.join(dest, os.path.basename(src))
                if os.path.abspath(target_in_dest) != src:
                    shutil.copy2(src, target_in_dest)
                cmd = f"gunzip -f -k '{target_in_dest}'"
            elif lower_src.endswith(".bz2"):
                import shutil
                target_in_dest = os.path.join(dest, os.path.basename(src))
                if os.path.abspath(target_in_dest) != src:
                    shutil.copy2(src, target_in_dest)
                cmd = f"bunzip2 -f -k '{target_in_dest}'"
            elif lower_src.endswith(".xz"):
                import shutil
                target_in_dest = os.path.join(dest, os.path.basename(src))
                if os.path.abspath(target_in_dest) != src:
                    shutil.copy2(src, target_in_dest)
                cmd = f"unxz -f -k '{target_in_dest}'"
            else:
                return {"success": False, "error": "Unsupported archive format"}
            res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=120)
            return {
                "success": res.returncode == 0,
                "message": f"Extracted to {dest}" if res.returncode == 0 else (res.stderr.strip() or "Extract failed"),
                "destination": dest
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    elif action == "file_compress":
        import zipfile
        import tarfile
        base_dir = data.get("directory", "/root")
        items = data.get("items", [])
        archive_name = os.path.basename(data.get("archive_name", "archive.zip").strip())
        fmt = data.get("format", "zip").lower()
        if not items:
            return {"success": False, "error": "No items to compress"}
        try:
            if fmt in ("tar.gz", "tgz", "tar"):
                if not archive_name.endswith((".tar.gz", ".tgz")):
                    archive_name += ".tar.gz"
                out_path = os.path.join(base_dir, archive_name)
                with tarfile.open(out_path, "w:gz") as tar:
                    for it in items:
                        it_name = os.path.basename(it)
                        full = os.path.join(base_dir, it_name)
                        if os.path.exists(full) and os.path.abspath(full) != os.path.abspath(out_path):
                            tar.add(full, arcname=it_name)
            else:
                if not archive_name.endswith(".zip"):
                    archive_name += ".zip"
                out_path = os.path.join(base_dir, archive_name)
                with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zipf:
                    for it in items:
                        it_name = os.path.basename(it)
                        full = os.path.join(base_dir, it_name)
                        if not os.path.exists(full) or os.path.abspath(full) == os.path.abspath(out_path):
                            continue
                        if os.path.isdir(full):
                            for root, _, files in os.walk(full):
                                for f in files:
                                    fp = os.path.join(root, f)
                                    if os.path.abspath(fp) == os.path.abspath(out_path):
                                        continue
                                    zipf.write(fp, os.path.relpath(fp, base_dir))
                        else:
                            zipf.write(full, it_name)
            return {
                "success": True,
                "message": f"Arsip {archive_name} berhasil dibuat",
                "archive_name": archive_name,
                "size": os.path.getsize(out_path)
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

    elif action == "get_cron_jobs":
        try:
            res = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=5)
            raw = res.stdout if res.returncode == 0 else ""
            lines = raw.splitlines()
            jobs = []
            last_comment = ""
            for idx, line in enumerate(lines):
                t = line.strip()
                if not t:
                    last_comment = ""
                    continue
                if t.startswith("#") and not t.startswith("# DISABLED_BY_KOKORO: "):
                    last_comment = t.lstrip("#").strip()
                    continue
                enabled = True
                active_line = t
                if t.startswith("# DISABLED_BY_KOKORO: "):
                    enabled = False
                    active_line = t[len("# DISABLED_BY_KOKORO: "):].strip()
                parts = active_line.split(maxsplit=5)
                if len(parts) >= 6:
                    sched = " ".join(parts[:5])
                    cmd = parts[5]
                    jobs.append({
                        "id": idx,
                        "schedule": sched,
                        "schedule_human": sched,
                        "command": cmd,
                        "comment": last_comment,
                        "enabled": enabled,
                        "raw": line
                    })
                    last_comment = ""
            return {"jobs": jobs}
        except Exception as e:
            return {"error": str(e)}

    elif action == "add_cron_job":
        try:
            sched = data.get("schedule", "").strip()
            cmd = data.get("command", "").strip()
            comment = data.get("comment", "").strip()
            if not sched or not cmd:
                return {"success": False, "error": "Jadwal dan Perintah harus diisi"}
            res = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=5)
            raw = res.stdout if res.returncode == 0 else ""
            entry = f"# {comment}\n{sched} {cmd}\n" if comment else f"{sched} {cmd}\n"
            new_content = raw.rstrip() + "\n" + entry
            subprocess.run(["crontab", "-"], input=new_content, text=True, check=True, timeout=5)
            return {"success": True, "message": "Cron job berhasil ditambahkan"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    elif action == "toggle_cron_job":
        try:
            job_id = int(data.get("job_id", -1))
            enable = bool(data.get("enable", True))
            res = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=5)
            lines = res.stdout.splitlines() if res.returncode == 0 else []
            if job_id < 0 or job_id >= len(lines):
                return {"success": False, "error": "Job ID tidak valid"}
            line = lines[job_id].strip()
            prefix = "# DISABLED_BY_KOKORO: "
            if enable and line.startswith(prefix):
                lines[job_id] = line[len(prefix):].strip()
            elif not enable and not line.startswith(prefix) and not line.startswith("#"):
                lines[job_id] = prefix + line
            subprocess.run(["crontab", "-"], input="\n".join(lines) + "\n", text=True, check=True, timeout=5)
            return {"success": True, "message": f"Cron job {'diaktifkan' if enable else 'dinonaktifkan'}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    elif action == "delete_cron_job":
        try:
            job_id = int(data.get("job_id", -1))
            res = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=5)
            lines = res.stdout.splitlines() if res.returncode == 0 else []
            if job_id < 0 or job_id >= len(lines):
                return {"success": False, "error": "Job ID tidak valid"}
            del lines[job_id]
            if job_id > 0 and lines[job_id - 1].strip().startswith("#") and not lines[job_id - 1].strip().startswith("# DISABLED_BY_KOKORO: "):
                del lines[job_id - 1]
            subprocess.run(["crontab", "-"], input="\n".join(lines) + "\n", text=True, check=True, timeout=5)
            return {"success": True, "message": "Cron job berhasil dihapus"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    elif action == "run_cron_now":
        try:
            cmd = data.get("command", "")
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

    elif action == "get_network_info":
        try:
            import re
            # Ports
            ports = []
            res_ports = subprocess.run("ss -tulpn", shell=True, capture_output=True, text=True, timeout=5)
            if res_ports.returncode == 0:
                for line in res_ports.stdout.splitlines()[1:]:
                    parts = line.split()
                    if len(parts) >= 5:
                        proto = parts[0].lower()
                        state = parts[1].upper()
                        local_raw = parts[4]
                        if ":" in local_raw:
                            ip, p_str = local_raw.rsplit(":", 1)
                            ip = ip.strip("[]")
                            if p_str.isdigit():
                                port = int(p_str)
                                is_pub = ip in ("0.0.0.0", "*", "::", "")
                                proc_name = "-"
                                pid = None
                                if len(parts) >= 7:
                                    m = re.search(r'"([^"]+)",pid=(\d+)', " ".join(parts[6:]))
                                    if m:
                                        proc_name = m.group(1)
                                        pid = int(m.group(2))
                                ports.append({
                                    "proto": proto, "port": port, "ip": ip or "0.0.0.0",
                                    "is_public": is_pub, "state": state, "process": proc_name, "pid": pid
                                })
            seen = set()
            unique_ports = []
            for p in ports:
                k = (p["proto"], p["port"], p["ip"])
                if k not in seen:
                    seen.add(k)
                    unique_ports.append(p)
            unique_ports.sort(key=lambda x: (not x["is_public"], x["port"]))

            # Connections
            conns = []
            res_c = subprocess.run("ss -tan state established", shell=True, capture_output=True, text=True, timeout=5)
            if res_c.returncode == 0:
                for line in res_c.stdout.splitlines()[1:]:
                    parts = line.split()
                    if len(parts) >= 4:
                        l_raw, r_raw = parts[2], parts[3]
                        if ":" in r_raw and ":" in l_raw:
                            r_ip, r_p = r_raw.rsplit(":", 1)
                            l_ip, l_p = l_raw.rsplit(":", 1)
                            if r_ip not in ("127.0.0.1", "::1"):
                                conns.append({
                                    "local_ip": l_ip.strip("[]"), "local_port": l_p,
                                    "remote_ip": r_ip.strip("[]"), "remote_port": r_p,
                                    "state": "ESTABLISHED"
                                })

            # UFW
            ufw_data = {"installed": False, "active": False, "rules": []}
            import shutil
            if shutil.which("ufw"):
                res_u = subprocess.run("ufw status numbered", shell=True, capture_output=True, text=True, timeout=5)
                out = res_u.stdout or ""
                ufw_data["installed"] = True
                ufw_data["active"] = "Status: active" in out
                for line in out.splitlines():
                    m = re.match(r'\[\s*(\d+)\]\s+(.*?)\s+(ALLOW IN|DENY IN|ALLOW|DENY|REJECT)\s+(.*)', line)
                    if m:
                        ufw_data["rules"].append({
                            "num": int(m.group(1)),
                            "to": m.group(2).strip(),
                            "action": m.group(3).strip(),
                            "from": m.group(4).strip()
                        })

            return {"ports": unique_ports, "connections": conns[:40], "ufw": ufw_data}
        except Exception as e:
            return {"error": str(e)}

    elif action == "ufw_action":
        op = data.get("op", "").lower()
        port = str(data.get("port", "")).strip()
        from_ip = str(data.get("from_ip", "")).strip()
        proto = str(data.get("proto", "")).strip()
        rule_num = data.get("rule_num")
        try:
            if op == "enable": cmd = "ufw --force enable"
            elif op == "disable": cmd = "ufw disable"
            elif op == "allow":
                target = f"{port}/{proto}" if proto and proto != "both" else port
                cmd = f"ufw allow from {from_ip} to any port {port}" if from_ip and from_ip != "any" else f"ufw allow {target}"
            elif op == "deny":
                target = f"{port}/{proto}" if proto and proto != "both" else port
                cmd = f"ufw deny from {from_ip} to any port {port}" if from_ip and from_ip != "any" else f"ufw deny {target}"
            elif op == "delete":
                cmd = f"ufw --force delete {rule_num}"
            else:
                return {"success": False, "error": f"Aksi UFW {op} tidak valid"}
            res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
            return {"success": res.returncode == 0, "message": res.stdout.strip() or res.stderr.strip()}
        except Exception as e:
            return {"success": False, "error": str(e)}

    elif action == "get_log_targets":
        try:
            import glob
            targets = []
            common = [
                {"name": "System Syslog", "path": "/var/log/syslog"},
                {"name": "SSH & Auth Log", "path": "/var/log/auth.log"},
                {"name": "Nginx Access Log", "path": "/var/log/nginx/access.log"},
                {"name": "Nginx Error Log", "path": "/var/log/nginx/error.log"},
                {"name": "System Messages", "path": "/var/log/messages"},
                {"name": "Daemon Log", "path": "/var/log/daemon.log"},
                {"name": "UFW Firewall Log", "path": "/var/log/ufw.log"}
            ]
            for item in common:
                p = item["path"]
                if os.path.exists(p) and os.path.isfile(p):
                    targets.append({
                        "name": item["name"],
                        "path": p,
                        "size_mb": round(os.path.getsize(p) / (1024 * 1024), 2),
                        "exists": True
                    })
            if os.path.exists("/var/log"):
                for f in glob.glob("/var/log/*.log"):
                    if not any(t["path"] == f for t in targets):
                        targets.append({
                            "name": os.path.basename(f),
                            "path": f,
                            "size_mb": round(os.path.getsize(f) / (1024 * 1024), 2),
                            "exists": True
                        })
            return {"targets": targets}
        except Exception as e:
            return {"error": str(e)}

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

                        # Live Log Streaming Tailer
                        elif action == "open_log_tail":
                            tail_id = data.get("tail_id")
                            path = data.get("path")
                            lines = data.get("lines", 50)

                            async def tail_runner():
                                try:
                                    proc = await asyncio.create_subprocess_shell(
                                        f"tail -n {lines} -F '{path}'",
                                        stdout=asyncio.subprocess.PIPE,
                                        stderr=asyncio.subprocess.STDOUT
                                    )
                                    active_log_tail_sessions[tail_id] = proc
                                    while True:
                                        line = await proc.stdout.readline()
                                        if not line:
                                            break
                                        await ws.send(json.dumps({
                                            "type": "log_stream",
                                            "tail_id": tail_id,
                                            "data": line.decode("utf-8", errors="replace")
                                        }))
                                except asyncio.CancelledError:
                                    if tail_id in active_log_tail_sessions:
                                        p = active_log_tail_sessions.pop(tail_id, None)
                                        if p:
                                            try: p.terminate()
                                            except Exception: pass
                                except Exception:
                                    pass

                            t = asyncio.create_task(tail_runner())
                            active_log_tail_sessions[tail_id + "_task"] = t

                        elif action == "close_log_tail":
                            tail_id = data.get("tail_id")
                            t = active_log_tail_sessions.pop(tail_id + "_task", None)
                            if t and not t.done():
                                t.cancel()
                            p = active_log_tail_sessions.pop(tail_id, None)
                            if p:
                                try: p.terminate()
                                except Exception: pass

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
