import subprocess
from typing import List, Dict

HIGHLIGHT_SERVICES = ["mt5-trading", "mt5-dashboard", "cloudflared-tunnel", "nginx", "ssh", "cron", "kokoro-server"]

def get_systemd_services(highlight_list: List[str] = None) -> List[Dict]:
    highlights = highlight_list or HIGHLIGHT_SERVICES
    cmd = "systemctl list-units --type=service --all --no-pager --no-legend"
    res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=5)
    services = []

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

            is_key = any(h in unit_name for h in highlights)
            services.append({
                "name": unit_name,
                "load": load,
                "active": active,
                "sub": sub,
                "description": desc,
                "highlight": is_key
            })

    services.sort(key=lambda s: (not s["highlight"], s["name"]))
    return services[:100]

def execute_service_action(service: str, action: str) -> dict:
    if action not in ["start", "stop", "restart", "reload"]:
        raise ValueError("Invalid action")
    cmd = f"systemctl {action} {service}"
    subprocess.run(cmd, shell=True, check=True, timeout=15)
    return {"success": True, "message": f"Service {service} successfully {action}ed"}

def get_service_logs(service: str, lines: int = 50) -> List[str]:
    cmd = f"journalctl -u {service} -n {lines} --no-pager"
    res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=5)
    return res.stdout.splitlines()
