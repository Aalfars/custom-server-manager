import time
import sqlite3
from typing import Optional
from core.config import DB_PATH

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
        status TEXT,
        ip TEXT DEFAULT '-'
    )
    """)
    # Add ip column to audit_logs if older schema exists
    try:
        c.execute("ALTER TABLE audit_logs ADD COLUMN ip TEXT DEFAULT '-'")
    except Exception:
        pass

    c.execute("""
    CREATE TABLE IF NOT EXISTS telemetry_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp INTEGER,
        node_id TEXT,
        cpu_percent REAL,
        ram_percent REAL,
        disk_percent REAL,
        rx_kbps REAL,
        tx_kbps REAL
    )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_telemetry_history ON telemetry_history(node_id, timestamp)")
    # Default settings
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('pin', '654321')")
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('telegram_bot_token', '')")
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('telegram_chat_id', '')")
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('alert_cpu_threshold', '90')")
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('alert_ram_threshold', '90')")
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('alert_disk_threshold', '90')")

    c.execute("""
    CREATE TABLE IF NOT EXISTS command_presets (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        command TEXT NOT NULL,
        description TEXT DEFAULT '',
        category TEXT DEFAULT 'General',
        created_at INTEGER
    )
    """)

    # Seed Default Command Presets if empty
    c.execute("SELECT COUNT(*) FROM command_presets")
    if c.fetchone()[0] == 0:
        now_ts = int(time.time())
        presets = [
            ("Disk & Inode Overview", "df -h; echo '--- INODES ---'; df -i; echo '--- TOP DIRECTORIES ---'; du -sh /* 2>/dev/null | sort -hr | head -n 10", "Cek penggunaan kapasitas disk dan ukuran folder terbesar", "System", now_ts),
            ("Top Resource Processes", "uptime; echo '--- TOP CPU ---'; ps aux --sort=-%cpu | head -n 8; echo '--- TOP RAM ---'; ps aux --sort=-%mem | head -n 8", "Lihat proses yang paling memakan CPU dan memori", "System", now_ts),
            ("Clean RAM Cache & Swap", "sync; echo 3 > /proc/sys/vm/drop_caches; swapoff -a && swapon -a; free -m", "Kosongkan buffer RAM dan swap untuk meringankan server", "Maintenance", now_ts),
            ("Check Failed Services", "systemctl --failed --no-pager; echo '--- CRITICAL LOGS ---'; journalctl -p 3 -xb -n 15 --no-pager", "Periksa semua service yang gagal berjalan dan error log", "System", now_ts),
            ("Listening Ports & Sockets", "ss -tulpn; echo '--- ESTABLISHED ---'; ss -tan state established", "Lihat port yang terbuka dan koneksi aktif", "Network", now_ts),
            ("Git Pull & Restart App", "cd /root/server-manager && git pull && systemctl restart kokoro-server", "Tarik pembaruan dari Git dan reload service manager", "App", now_ts)
        ]
        c.executemany("INSERT INTO command_presets (name, command, description, category, created_at) VALUES (?, ?, ?, ?, ?)", presets)

    # Ensure Local Node is registered
    c.execute("SELECT id FROM nodes WHERE is_local = 1")
    if not c.fetchone():
        c.execute("""
        INSERT INTO nodes (id, name, token, ip, os_info, is_local, created_at)
        VALUES ('local-host', 'MT5 Trading Server', 'local-master-token', '127.0.0.1', 'Linux Host', 1, ?)
        """, (int(time.time()),))

    conn.commit()
    conn.close()

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

def log_audit(node_id: str, action: str, detail: str, status: str = "SUCCESS", ip: str = "-"):
    try:
        db = get_db()
        db.execute("""
        INSERT INTO audit_logs (timestamp, node_id, action, detail, status, ip)
        VALUES (?, ?, ?, ?, ?, ?)
        """, (int(time.time()), node_id, action, detail[:500], status, ip[:64]))
        db.commit()
        db.close()
    except Exception:
        pass

def record_telemetry_history(node_id: str, cpu_percent: float, ram_percent: float, disk_percent: float, rx_kbps: float, tx_kbps: float):
    try:
        db = get_db()
        db.execute("""
        INSERT INTO telemetry_history (timestamp, node_id, cpu_percent, ram_percent, disk_percent, rx_kbps, tx_kbps)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (int(time.time()), node_id, round(cpu_percent, 1), round(ram_percent, 1), round(disk_percent, 1), round(rx_kbps, 1), round(tx_kbps, 1)))
        db.commit()
        db.close()
    except Exception:
        pass

def cleanup_old_telemetry_history(max_age_seconds: int = 86400):
    try:
        cutoff = int(time.time()) - max_age_seconds
        db = get_db()
        db.execute("DELETE FROM telemetry_history WHERE timestamp < ?", (cutoff,))
        db.commit()
        db.close()
    except Exception:
        pass

def get_telemetry_history(node_id: str, duration_seconds: int = 3600, max_points: int = 120):
    try:
        start_time = int(time.time()) - duration_seconds
        db = get_db()
        rows = db.execute("""
        SELECT timestamp, cpu_percent, ram_percent, disk_percent, rx_kbps, tx_kbps
        FROM telemetry_history
        WHERE node_id = ? AND timestamp >= ?
        ORDER BY timestamp ASC
        """, (node_id, start_time)).fetchall()
        db.close()

        total = len(rows)
        if total <= max_points or total == 0:
            return [dict(r) for r in rows]

        # Downsample evenly to max_points
        step = total / max_points
        sampled = []
        for i in range(max_points):
            idx = int(i * step)
            sampled.append(dict(rows[idx]))
        return sampled
    except Exception:
        return []

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

def get_presets():
    try:
        db = get_db()
        rows = db.execute("SELECT * FROM command_presets ORDER BY category ASC, id ASC").fetchall()
        db.close()
        return [dict(r) for r in rows]
    except Exception:
        return []

def create_preset(name: str, command: str, description: str = "", category: str = "General") -> int:
    db = get_db()
    c = db.cursor()
    c.execute("""
    INSERT INTO command_presets (name, command, description, category, created_at)
    VALUES (?, ?, ?, ?, ?)
    """, (name, command, description, category, int(time.time())))
    preset_id = c.lastrowid
    db.commit()
    db.close()
    return preset_id

def update_preset(preset_id: int, name: str, command: str, description: str = "", category: str = "General") -> bool:
    db = get_db()
    c = db.cursor()
    c.execute("""
    UPDATE command_presets
    SET name = ?, command = ?, description = ?, category = ?
    WHERE id = ?
    """, (name, command, description, category, preset_id))
    affected = c.rowcount
    db.commit()
    db.close()
    return affected > 0

def delete_preset(preset_id: int) -> bool:
    db = get_db()
    c = db.cursor()
    c.execute("DELETE FROM command_presets WHERE id = ?", (preset_id,))
    affected = c.rowcount
    db.commit()
    db.close()
    return affected > 0

