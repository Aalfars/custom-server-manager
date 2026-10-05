import os
import re
import shutil
import socket
import subprocess
from typing import List, Dict, Optional

def _parse_ss_listening() -> List[Dict]:
    """Parse ss -tulpn for listening ports on Linux."""
    cmd = "ss -tulpn"
    res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=5)
    if res.returncode != 0 or not res.stdout:
        return []
    
    ports = []
    lines = res.stdout.splitlines()
    for line in lines[1:]:  # skip header
        parts = line.split()
        if len(parts) < 5:
            continue
        proto = parts[0].lower()
        state = parts[1].upper() if len(parts) > 1 else ""
        
        # Local address is usually parts[4]
        local_raw = parts[4] if len(parts) > 4 else ""
        if not local_raw:
            continue
        
        # Extract IP & Port
        if ":" in local_raw:
            ip, port_str = local_raw.rsplit(":", 1)
        else:
            continue
        
        ip = ip.strip("[]")
        try:
            port = int(port_str)
        except ValueError:
            continue
            
        is_public = ip in ("0.0.0.0", "*", "::", "")
        
        # Extract process and PID
        proc_name = "-"
        pid = None
        if len(parts) >= 7:
            proc_raw = " ".join(parts[6:])
            # format: users:(("nginx",pid=123,fd=6))
            m = re.search(r'"([^"]+)",pid=(\d+)', proc_raw)
            if m:
                proc_name = m.group(1)
                pid = int(m.group(2))
        
        ports.append({
            "proto": proto,
            "port": port,
            "ip": ip or "0.0.0.0",
            "is_public": is_public,
            "state": state or "LISTEN",
            "process": proc_name,
            "pid": pid
        })
    return ports

def _parse_ss_connections() -> List[Dict]:
    """Parse ss -tan state established on Linux."""
    cmd = "ss -tan state established"
    res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=5)
    if res.returncode != 0 or not res.stdout:
        return []
    
    conns = []
    lines = res.stdout.splitlines()
    for line in lines[1:]:
        parts = line.split()
        if len(parts) < 4:
            continue
        local_raw = parts[2] if len(parts) > 2 else ""
        remote_raw = parts[3] if len(parts) > 3 else ""
        
        if ":" in remote_raw and ":" in local_raw:
            r_ip, r_port = remote_raw.rsplit(":", 1)
            l_ip, l_port = local_raw.rsplit(":", 1)
            r_ip = r_ip.strip("[]")
            l_ip = l_ip.strip("[]")
            
            # Skip localhost to localhost loopback noise
            if r_ip in ("127.0.0.1", "::1") and l_ip in ("127.0.0.1", "::1"):
                continue
                
            conns.append({
                "local_ip": l_ip,
                "local_port": l_port,
                "remote_ip": r_ip,
                "remote_port": r_port,
                "state": "ESTABLISHED"
            })
    return conns[:40]

def _parse_netstat_fallback() -> List[Dict]:
    """Fallback using netstat -ano."""
    try:
        cmd = "netstat -ano"
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=5)
        ports = []
        for line in res.stdout.splitlines():
            line = line.strip()
            if not line or "LISTENING" not in line.upper():
                continue
            parts = line.split()
            if len(parts) < 4:
                continue
            proto = parts[0].lower()
            local_addr = parts[1]
            pid = parts[-1] if parts[-1].isdigit() else "-"
            
            if ":" in local_addr:
                ip, port_str = local_addr.rsplit(":", 1)
                ip = ip.strip("[]")
                try:
                    port = int(port_str)
                except ValueError:
                    continue
                is_public = ip in ("0.0.0.0", "*", "::", "")
                ports.append({
                    "proto": proto,
                    "port": port,
                    "ip": ip or "0.0.0.0",
                    "is_public": is_public,
                    "state": "LISTEN",
                    "process": f"PID {pid}",
                    "pid": int(pid) if pid.isdigit() else None
                })
        return ports
    except Exception:
        return []

def get_listening_ports() -> List[Dict]:
    ports = _parse_ss_listening()
    if not ports:
        ports = _parse_netstat_fallback()
    
    # Sort by port number
    # Remove duplicate (proto, port, ip)
    seen = set()
    unique_ports = []
    for p in ports:
        key = (p["proto"], p["port"], p["ip"])
        if key not in seen:
            seen.add(key)
            unique_ports.append(p)
            
    unique_ports.sort(key=lambda x: (not x["is_public"], x["port"]))
    return unique_ports

def get_active_connections() -> List[Dict]:
    conns = _parse_ss_connections()
    return conns

def get_ufw_status() -> Dict:
    if not shutil.which("ufw"):
        return {
            "installed": False,
            "active": False,
            "rules": []
        }
    
    try:
        res = subprocess.run(["ufw", "status", "numbered"], capture_output=True, text=True, timeout=5)
        stdout = res.stdout or ""
        is_active = "Status: active" in stdout
        rules = []
        
        # Parse numbered rules: [ 1] 22/tcp ALLOW IN Anywhere
        for line in stdout.splitlines():
            m = re.match(r'\[\s*(\d+)\]\s+(.*?)\s+(ALLOW IN|DENY IN|ALLOW|DENY|REJECT)\s+(.*)', line)
            if m:
                num = int(m.group(1))
                to_target = m.group(2).strip()
                action = m.group(3).strip()
                from_source = m.group(4).strip()
                rules.append({
                    "num": num,
                    "to": to_target,
                    "action": action,
                    "from": from_source
                })
                
        return {
            "installed": True,
            "active": is_active,
            "rules": rules
        }
    except Exception as e:
        return {
            "installed": True,
            "active": False,
            "error": str(e),
            "rules": []
        }

def execute_ufw_action(action: str, **kwargs) -> Dict:
    if not shutil.which("ufw"):
        raise RuntimeError("UFW (Uncomplicated Firewall) tidak terinstall di node ini.")
    
    action = action.lower()
    if action == "enable":
        res = subprocess.run("ufw --force enable", shell=True, capture_output=True, text=True, timeout=10)
    elif action == "disable":
        res = subprocess.run("ufw disable", shell=True, capture_output=True, text=True, timeout=10)
    elif action == "allow":
        port = str(kwargs.get("port", "")).strip()
        from_ip = str(kwargs.get("from_ip", "")).strip()
        proto = str(kwargs.get("proto", "")).strip()
        
        if not port:
            raise ValueError("Port harus diisi")
            
        target = f"{port}/{proto}" if proto and proto != "both" else port
        if from_ip and from_ip != "any":
            cmd = f"ufw allow from {from_ip} to any port {port}"
        else:
            cmd = f"ufw allow {target}"
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
    elif action == "deny":
        port = str(kwargs.get("port", "")).strip()
        from_ip = str(kwargs.get("from_ip", "")).strip()
        proto = str(kwargs.get("proto", "")).strip()
        
        if from_ip and from_ip != "any" and not port:
            cmd = f"ufw insert 1 deny from {from_ip} to any"
        elif port:
            target = f"{port}/{proto}" if proto and proto != "both" else port
            if from_ip and from_ip != "any":
                cmd = f"ufw deny from {from_ip} to any port {port}"
            else:
                cmd = f"ufw deny {target}"
        else:
            raise ValueError("Port atau IP harus diisi untuk memblokir")
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
    elif action == "delete":
        rule_num = kwargs.get("rule_num")
        if not rule_num:
            raise ValueError("Nomor rule harus diisi")
        res = subprocess.run(f"ufw --force delete {rule_num}", shell=True, capture_output=True, text=True, timeout=10)
    else:
        raise ValueError(f"Aksi UFW tidak dikenal: {action}")
        
    if res.returncode != 0:
        raise RuntimeError(res.stderr.strip() or res.stdout.strip() or "UFW action failed")
        
    return {
        "success": True,
        "message": res.stdout.strip() or f"Aksi UFW {action} berhasil dilakukan."
    }
