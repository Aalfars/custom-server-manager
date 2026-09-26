# Kokoro // Multi-Node Server Ops

> **Minimalist, Monad-Editorial Inspired Multi-Node Server Management & Telemetry Hub**

Kokoro is a lightweight, responsive server operations and remote node management dashboard crafted with an editorial Monad aesthetic (warm parchment palette, ABC Diatype Mono typography, and dark mode support).

Featuring **Elaina** (the Wandering Witch) as the operator mascot, Kokoro delivers real-time telemetry, full reverse-terminal access (even for NAT instances behind firewalls), service & process controls, and file management across multiple remote Linux nodes.

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
  - **Interactive Terminal**: Real-time bidirectional PTY shell via `xterm.js` over WebSocket.
  - **System Services (systemd)**: Start, stop, restart, reload, and view live logs (`journalctl`).
  - **Process Explorer**: View running processes, sort by CPU/RAM usage, and kill stuck processes (`SIGTERM` / `SIGKILL`).
  - **Quick Script Runner**: Run bash commands directly with stdout/stderr capture and execution timing.
  - **Remote File Manager**: Browse directories, view files, and edit server configs remotely.
  - **System Power Actions**: Clean RAM cache (`sync && drop_caches` with OpenVZ/LXC/KVM container awareness) and Remote Reboot.
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

## 🚀 Quick Start

### 1. Requirements

- Python 3.10+
- Linux (Ubuntu, Debian, CentOS, AlmaLinux, Alpine, etc.)

### 2. Hub Installation

```bash
git clone git@github.com:ahmadmct/server-manager.git
cd server-manager

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run server
uvicorn app:app --host 0.0.0.0 --port 8000
```

### 3. Satellite Node Agent Deployment (1-Line Install)

From the Kokoro Web UI, click **"+ Tambah Server Baru"** to generate a unique registration token and 1-line curl command:

```bash
curl -sSL https://<YOUR_HUB_DOMAIN>/install-agent.sh | bash -s -- --hub https://<YOUR_HUB_DOMAIN> --token <NODE_TOKEN> --name "My Satellite Node"
```

The installer configures `kokoro-agent.service` via `systemd` to automatically connect and stay alive on boot.

---

## 🔒 Security

- Single-PIN authentication protection for dashboard access.
- Secure token-based WebSocket handshake for satellite nodes.
- Full audit logging for commands, service actions, and file edits.

---

## 📜 License

MIT License © 2026 ahmadmct
