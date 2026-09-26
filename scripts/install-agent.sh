#!/bin/bash
set -e

# ==============================================================================
# KOKORO // UNIVERSAL NODE AGENT INSTALLER
# ==============================================================================

echo "=================================================================="
echo "  KOKORO // MULTI-NODE INFRASTRUCTURE AGENT INSTALLER"
echo "=================================================================="

HUB_URL=""
TOKEN=""
NODE_NAME="Remote-Node"

while [[ "$#" -gt 0 ]]; do
    case $1 in
        --hub) HUB_URL="$2"; shift ;;
        --token) TOKEN="$2"; shift ;;
        --name) NODE_NAME="$2"; shift ;;
        *) echo "Unknown parameter passed: $1"; exit 1 ;;
    esac
    shift
done

if [ -z "$HUB_URL" ] || [ -z "$TOKEN" ]; then
    echo "[!] Error: Missing required arguments."
    echo "Usage: curl -sSL https://server.aranya.my.id/install-agent.sh | bash -s -- --hub <HUB_URL> --token <TOKEN> [--name <NODE_NAME>]"
    exit 1
fi

echo "[*] Target Hub: $HUB_URL"
echo "[*] Node Name:  $NODE_NAME"
echo "[*] Registering Node Token: ${TOKEN:0:8}..."

# Check Python 3
if ! command -v python3 >/dev/null 2>&1; then
    echo "[*] Installing Python 3..."
    if command -v apt-get >/dev/null 2>&1; then
        apt-get update -qq && apt-get install -y -qq python3 python3-pip
    elif command -v yum >/dev/null 2>&1; then
        yum install -y python3 python3-pip
    elif command -v apk >/dev/null 2>&1; then
        apk add python3 py3-pip
    fi
fi

# Ensure websockets and psutil
echo "[*] Ensuring required python packages (websockets, psutil)..."
python3 -m pip install --quiet --no-cache-dir websockets psutil 2>/dev/null || pip3 install --quiet --no-cache-dir websockets psutil 2>/dev/null || true

# Prepare directory
INSTALL_DIR="/opt/kokoro-agent"
mkdir -p "$INSTALL_DIR"

# Download agent.py from hub
echo "[*] Fetching agent binary script from Hub..."
curl -sSL "${HUB_URL}/static/agent/agent.py" -o "${INSTALL_DIR}/agent.py" || \
curl -sSL "https://server.aranya.my.id/static/agent/agent.py" -o "${INSTALL_DIR}/agent.py"

chmod +x "${INSTALL_DIR}/agent.py"

# Create systemd service
SERVICE_FILE="/etc/systemd/system/kokoro-agent.service"
cat << EOF > "$SERVICE_FILE"
[Unit]
Description=KOKORO Multi-Node Server Ops Agent
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=${INSTALL_DIR}
ExecStart=/usr/bin/python3 ${INSTALL_DIR}/agent.py --hub "${HUB_URL}" --token "${TOKEN}" --name "${NODE_NAME}"
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable kokoro-agent.service
systemctl restart kokoro-agent.service

echo ""
echo "=================================================================="
echo "  [+] KOKORO AGENT INSTALLED & RUNNING SUCCESSFULLY!"
echo "  [+] Service: systemctl status kokoro-agent"
echo "  [+] Node is now connected to ${HUB_URL}"
echo "=================================================================="
