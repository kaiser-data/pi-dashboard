#!/usr/bin/env bash
# install.sh — Pi Dashboard installer
# Installs a minimal system monitor accessible via browser
set -euo pipefail

PORT="${PORT:-19999}"
TAILSCALE_PORT="${TAILSCALE_PORT:-8443}"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
ok()  { echo -e "${GREEN}✓${NC} $*"; }
die() { echo -e "${RED}✗ $*${NC}"; exit 1; }

[[ $EUID -ne 0 ]] && die "Run with sudo: sudo bash install.sh"

echo -e "\n🖥  Pi Dashboard — installing...\n"

# Create data directory
mkdir -p /var/lib/pi-dashboard
chown pi:pi /var/lib/pi-dashboard
ok "Data directory: /var/lib/pi-dashboard"

# Install server script
cp "$(dirname "$0")/server.py" /usr/local/bin/pi-dashboard.py
chmod +x /usr/local/bin/pi-dashboard.py
ok "Server installed: /usr/local/bin/pi-dashboard.py"

# Create systemd service
cat > /etc/systemd/system/pi-dashboard.service << EOF
[Unit]
Description=Pi Minimal Dashboard
After=network.target

[Service]
Type=simple
User=pi
ExecStart=/usr/bin/python3 /usr/local/bin/pi-dashboard.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now pi-dashboard
ok "Service enabled and started"

# Tailscale Serve (optional)
if command -v tailscale &>/dev/null; then
    tailscale serve --bg --yes --https="${TAILSCALE_PORT}" "${PORT}" 2>/dev/null && \
        ok "Tailscale Serve: https://$(tailscale status --json | python3 -c 'import json,sys; print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))'):${TAILSCALE_PORT}" || \
        echo -e "${YELLOW}!${NC} Tailscale Serve skipped (run manually if needed)"
fi

echo ""
echo -e "${GREEN}Done!${NC} Open in your browser:"
echo "  Local:     http://$(hostname -I | awk '{print $1}'):${PORT}"
echo "  Tailscale: https://$(hostname).ts.net:${TAILSCALE_PORT}  (if Tailscale active)"
echo ""
echo "Data persists in /var/lib/pi-dashboard/history.jsonl"
