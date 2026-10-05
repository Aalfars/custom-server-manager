import os
import re
import time
import shutil
import subprocess
from typing import List, Dict

DISABLED_PREFIX = "# DISABLED_BY_KOKORO: "

def describe_cron_schedule(sched: str) -> str:
    sched = sched.strip()
    parts = sched.split()
    if len(parts) != 5:
        return f"Kustom ({sched})"
    
    m, h, dom, mon, dow = parts
    
    if sched == "* * * * *":
        return "Setiap menit"
    elif sched == "*/2 * * * *":
        return "Setiap 2 menit"
    elif sched == "*/5 * * * *":
        return "Setiap 5 menit"
    elif sched == "*/10 * * * *":
        return "Setiap 10 menit"
    elif sched == "*/15 * * * *":
        return "Setiap 15 menit"
    elif sched == "*/30 * * * *":
        return "Setiap 30 menit"
    elif sched == "0 * * * *":
        return "Setiap jam (menit 00)"
    elif sched == "0 */2 * * *":
        return "Setiap 2 jam"
    elif sched == "0 */6 * * *":
        return "Setiap 6 jam"
    elif sched == "0 */12 * * *":
        return "Setiap 12 jam"
    elif sched == "0 0 * * *":
        return "Setiap hari tengah malam (00:00)"
    elif sched == "0 12 * * *":
        return "Setiap hari siang (12:00)"
    elif sched == "0 0 * * 0" or sched == "0 0 * * 7":
        return "Setiap Minggu (00:00)"
    elif sched == "0 0 1 * *":
        return "Setiap tanggal 1 awal bulan (00:00)"
    elif dom == "*" and mon == "*" and dow == "*":
        if re.match(r"^\d+$", m) and re.match(r"^\d+$", h):
            return f"Setiap hari jam {h.zfill(2)}:{m.zfill(2)}"
    
    return f"Ekspresi: {sched}"

def _get_raw_crontab() -> str:
    if not shutil.which("crontab"):
        # Local development fallback
        mock_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "mock_crontab.txt")
        if os.path.exists(mock_file):
            with open(mock_file, "r", encoding="utf-8") as f:
                return f.read()
        return "# Crontab dev mock\n0 0 * * * /root/backup.sh\n# DISABLED_BY_KOKORO: */15 * * * * /usr/bin/python3 /root/bot.py\n"

    try:
        res = subprocess.run(["crontab", "-l"], capture_output=True, text=True, timeout=5)
        if res.returncode == 0:
            return res.stdout
        return ""
    except Exception:
        return ""

def _save_raw_crontab(content: str):
    content = content.strip() + "\n"
    if not shutil.which("crontab"):
        mock_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "mock_crontab.txt")
        os.makedirs(os.path.dirname(mock_file), exist_ok=True)
        with open(mock_file, "w", encoding="utf-8") as f:
            f.write(content)
        return

    res = subprocess.run(["crontab", "-"], input=content, text=True, capture_output=True, timeout=5)
    if res.returncode != 0:
        raise RuntimeError(f"Gagal menyimpan crontab: {res.stderr.strip() or 'Unknown error'}")

def get_crontab_jobs() -> List[Dict]:
    raw = _get_raw_crontab()
    lines = raw.splitlines()
    jobs = []
    
    last_comment = ""
    for idx, line in enumerate(lines):
        trimmed = line.strip()
        if not trimmed:
            last_comment = ""
            continue
        
        # Check if line is a regular comment
        if trimmed.startswith("#") and not trimmed.startswith(DISABLED_PREFIX):
            last_comment = trimmed.lstrip("#").strip()
            continue
        
        enabled = True
        active_line = trimmed
        if trimmed.startswith(DISABLED_PREFIX):
            enabled = False
            active_line = trimmed[len(DISABLED_PREFIX):].strip()
        
        parts = active_line.split(maxsplit=5)
        if len(parts) >= 6:
            schedule = " ".join(parts[:5])
            command = parts[5]
            jobs.append({
                "id": idx,
                "schedule": schedule,
                "schedule_human": describe_cron_schedule(schedule),
                "command": command,
                "comment": last_comment,
                "enabled": enabled,
                "raw": line
            })
            last_comment = ""
    
    return jobs

def add_crontab_job(schedule: str, command: str, comment: str = "") -> dict:
    schedule = schedule.strip()
    command = command.strip()
    comment = comment.strip()
    
    parts = schedule.split()
    if len(parts) != 5:
        raise ValueError("Format cron tidak valid! Harus terdiri dari 5 bagian (menit jam hari bulan hari_dalam_minggu).")
    if not command:
        raise ValueError("Perintah (command) tidak boleh kosong.")
        
    raw = _get_raw_crontab()
    new_entry = ""
    if comment:
        new_entry += f"# {comment}\n"
    new_entry += f"{schedule} {command}\n"
    
    new_content = raw.rstrip() + "\n" + new_entry
    _save_raw_crontab(new_content)
    return {"success": True, "message": "Cron job berhasil ditambahkan."}

def toggle_crontab_job(job_id: int, enable: bool) -> dict:
    raw = _get_raw_crontab()
    lines = raw.splitlines()
    if job_id < 0 or job_id >= len(lines):
        raise IndexError("ID Cron job tidak ditemukan.")
    
    line = lines[job_id].strip()
    if enable:
        if line.startswith(DISABLED_PREFIX):
            lines[job_id] = line[len(DISABLED_PREFIX):].strip()
    else:
        if not line.startswith(DISABLED_PREFIX) and not line.startswith("#"):
            lines[job_id] = DISABLED_PREFIX + line
            
    _save_raw_crontab("\n".join(lines))
    return {"success": True, "message": f"Cron job berhasil {'diaktifkan' if enable else 'dinonaktifkan'}."}

def delete_crontab_job(job_id: int) -> dict:
    raw = _get_raw_crontab()
    lines = raw.splitlines()
    if job_id < 0 or job_id >= len(lines):
        raise IndexError("ID Cron job tidak ditemukan.")
    
    # If previous line is a comment associated with this job, delete it too
    del lines[job_id]
    if job_id > 0 and lines[job_id - 1].strip().startswith("#") and not lines[job_id - 1].strip().startswith(DISABLED_PREFIX):
        del lines[job_id - 1]
        
    _save_raw_crontab("\n".join(lines))
    return {"success": True, "message": "Cron job berhasil dihapus."}

def run_crontab_job_now(command: str) -> dict:
    t0 = time.time()
    try:
        res = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=60)
        return {
            "success": res.returncode == 0,
            "stdout": res.stdout,
            "stderr": res.stderr,
            "exit_code": res.returncode,
            "elapsed": round(time.time() - t0, 2)
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Eksekusi melebihi batas waktu (timeout 60 detik).", "exit_code": -1}
    except Exception as e:
        return {"success": False, "error": str(e), "exit_code": -1}
