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
        status TEXT
    )
    """)
    # Default settings
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('pin', '654321')")
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('telegram_bot_token', '')")
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('telegram_chat_id', '')")
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('alert_cpu_threshold', '90')")
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('alert_ram_threshold', '90')")
    c.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('alert_disk_threshold', '90')")

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

def log_audit(node_id: str, action: str, detail: str, status: str = "SUCCESS"):
    try:
        db = get_db()
        db.execute("""
        INSERT INTO audit_logs (timestamp, node_id, action, detail, status)
        VALUES (?, ?, ?, ?, ?)
        """, (int(time.time()), node_id, action, detail[:500], status))
        db.commit()
        db.close()
    except Exception:
        pass

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
