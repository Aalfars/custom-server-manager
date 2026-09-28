# Kokoro // Multi-Node Server Ops

> **Minimalist, Monad-Editorial Inspired Multi-Node Server Management & Telemetry Hub**

Kokoro is a lightweight, responsive server operations and remote node management dashboard crafted with an editorial Monad aesthetic (warm parchment palette, ABC Diatype Mono typography, and dark mode support).

Featuring **Elaina** (the Wandering Witch) as the operator mascot, Kokoro delivers real-time telemetry, full reverse-terminal access (even for NAT instances behind firewalls), service & process controls, and complete file management (browse, edit, upload, download, extract) across multiple remote Linux nodes.

---

## ✨ Features

- **Multi-Node Architecture**:
  - **Hub Controller**: Central dashboard & API gateway.
  - **Satellite Agent**: Lightweight daemon running on edge / NAT VPS instances with zero port forwarding required (reverse WebSocket connection).
- **Isolated Server Flow**:
  - Server Selection screen with quick health & hardware metrics.
  - Dedicated dashboard workspace per server with real-time stats (CPU, RAM, Disk, Load Average, Uptime).
  - Customizable server display names.
  - One-click node deletion & unlinking.
- **Full Remote Operations**:
  - **Interactive Terminal**: Real-time bidirectional PTY shell via `xterm.js` over WebSocket with auto process lifecycle cleanup.
  - **System Services (systemd)**: Start, stop, restart, reload, and view live logs (`journalctl`).
  - **Process Explorer**: View running processes, sort by CPU/RAM usage, and kill stuck processes (`SIGTERM` / `SIGKILL`).
  - **Quick Script Runner**: Run bash commands directly with stdout/stderr capture and execution timing.
  - **Enhanced Remote File Manager**:
    - Directory navigation and permissions inspector.
    - View and live-edit configuration files (with automatic `.bak` backup creation).
    - **File Upload**: Direct file uploading to any server directory with progress tracking.
    - **File Download**: 1-click download of server files to local client.
    - **Archive Extraction**: In-place extraction supporting `.zip`, `.tar.gz`, `.tgz`, `.tar.bz2`, `.tar.xz`, `.tar`, `.rar`, and `.7z`.
  - **System Power Actions**: Clean RAM cache (`sync && drop_caches` with OpenVZ/LXC/KVM container awareness) and Remote Reboot.
- **Modular Codebase**:
  - Clean separation into `core/` (config, DB, auth), `services/` (telemetry, systemd, process, terminal, file_manager), and `routers/` (FastAPI APIRouter).
- **Aesthetic UI & UX**:
  - Monad warm parchment light theme (`#f6f3f1`) & sleek dark mode (`#121214`).
  - Smooth anime operator branding with dynamic day/night mascot transitions.
  - Ultra-clean responsive design optimized for desktop and mobile devices.
  - PIN security authentication lock.

---

## 🏗️ Architecture

```
+-------------------------------------------------------------+
|                     KOKORO HUB CONTROLLER                   |
|                   (FastAPI + Jinja2 + xterm.js)             |
|                    https://server.aranya.my.id              |
+------------------------------+------------------------------+
                               ^
                               | Reverse WSS Tunnel
                               v
+-------------------------------------------------------------+
|                     SATELLITE NODE(S)                       |
|               (kokoro-agent / Python Daemon)                |
|             NAT VPS / KVM / OpenVZ Behind Firewall          |
+-------------------------------------------------------------+
```

---

## 📂 Modular Codebase Layout

```
server-manager/
├── app.py                      # Main application entry point & router mounting
├── core/
│   ├── config.py               # Paths, agent connection registry, RPC dispatcher
│   ├── database.py             # SQLite DB helpers, settings, audit logging
│   └── security.py             # PIN authentication & cookie verification
├── services/
│   ├── telemetry.py            # Local hardware telemetry & delta I/O tracker
│   ├── systemd.py              # Systemd unit controller & log viewer
│   ├── process.py              # Process manager & signal killer
│   ├── terminal.py             # PTY bash terminal spawner with leak-proof cleanup
│   └── file_manager.py         # File read/write, upload, download, and archive extraction
├── routers/
│   ├── auth.py                 # PIN login and logout
│   ├── nodes.py                # Server registration, deletion, rename, reboot, clean-cache
│   ├── services.py             # Systemd service actions and logs
│   ├── processes.py            # Process listing and termination
│   ├── files.py                # File listing, editing, upload, download, extract
│   ├── exec_cmd.py             # Ad-hoc bash script execution
│   ├── settings.py             # Platform settings and audit logs
│   └── websockets.py           # Real-time telemetry, web terminal, and agent WS hub
├── agent/
│   └── agent.py                # Satellite node agent daemon
├── templates/
│   └── index.html              # Responsive Monad UI with Elaina operator
├── static/
│   └── agent/agent.py          # Public agent installer target
└── scripts/
    └── install-agent.sh        # 1-line agent installer
```

---

## 🚀 Quick Start

### 1. Requirements

- Python 3.10+
- Linux (Ubuntu, Debian, CentOS, AlmaLinux, Alpine, etc.)

### 2. Hub Installation

```bash
git clone https://github.com/Aalfars/custom-server-manager.git
cd custom-server-manager

# Install dependencies
pip install -r requirements.txt

# Run server
uvicorn app:app --host 0.0.0.0 --port 8000
```

### 3. Satellite Node Agent Deployment (1-Line Install)

From the Kokoro Web UI, click **"+ Link Node ▸"** to generate a unique registration token and 1-line curl command:

```bash
curl -sSL https://<YOUR_HUB_DOMAIN>/install-agent.sh | bash -s -- --hub https://<YOUR_HUB_DOMAIN> --token <NODE_TOKEN> --name "My Satellite Node"
```

The installer configures `kokoro-agent.service` via `systemd` to automatically connect and stay alive on boot.

---

## 🔒 Security

- Single-PIN authentication protection for dashboard access.
- Secure token-based WebSocket handshake for satellite nodes.
- Full audit logging for commands, service actions, and file operations.

---

## 📜 License

MIT License © 2026 Aalfars
