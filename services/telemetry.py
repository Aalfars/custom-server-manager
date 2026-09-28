import os
import time
import psutil
from core.database import get_node_name

# Network previous values for delta speed computation
_prev_net_io = psutil.net_io_counters()
_prev_net_time = time.time()

def get_local_telemetry() -> dict:
    global _prev_net_io, _prev_net_time
    now = time.time()
    dt = max(0.1, now - _prev_net_time)

    # CPU
    cpu_percent = psutil.cpu_percent(interval=None)
    cpu_count = psutil.cpu_count(logical=True)
    load_avg = [round(x, 2) for x in os.getloadavg()] if hasattr(os, "getloadavg") else [0.0, 0.0, 0.0]

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
    uname = os.uname() if hasattr(os, "uname") else None
    os_name = f"{uname.sysname} {uname.release} ({uname.machine})" if uname else "Linux Host"
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
        "name": get_node_name("local-host", "MT5 Trading Server"),
        "status": "online",
        "is_local": True,
        "os_info": os_name,
        "kernel": uname.release if uname else "",
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
