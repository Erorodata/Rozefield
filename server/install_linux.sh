#!/bin/sh
# Installs Rozefield Server as a service that starts when the device boots (systemd: Debian, Ubuntu, Raspberry Pi OS).
#   sudo ./install_linux.sh            install and start
#   sudo ./install_linux.sh --remove   stop and remove the service (the server folder is not touched)
# Manage it with:  sudo systemctl status|restart|stop rozefield      Log: journalctl -u rozefield -f
set -e
DIR=$(cd "$(dirname "$0")" && pwd)
UNIT=/etc/systemd/system/rozefield.service
if [ "$(id -u)" != 0 ]; then echo "Run with sudo."; exit 1; fi
if [ "$1" = "--remove" ]; then
  systemctl disable --now rozefield 2>/dev/null || true
  rm -f "$UNIT"; systemctl daemon-reload; echo "Removed the rozefield service."; exit 0
fi
USER_NAME=${SUDO_USER:-root}
command -v python3 >/dev/null || { echo "Install Python 3 first:  sudo apt install python3 python3-pip"; exit 1; }
sudo -u "$USER_NAME" python3 -c "import google.protobuf, cramjam" 2>/dev/null || \
  sudo -u "$USER_NAME" python3 -m pip install --user -q "protobuf>=4.25" "cramjam>=2.8" 2>/dev/null || \
  sudo -u "$USER_NAME" python3 -m pip install --user --break-system-packages -q "protobuf>=4.25" "cramjam>=2.8"
chmod +x "$DIR/start_server.sh"
cat > "$UNIT" <<EOF
[Unit]
Description=Rozefield Server
After=network-online.target
Wants=network-online.target

[Service]
User=$USER_NAME
WorkingDirectory=$DIR
ExecStart=$DIR/start_server.sh
Restart=always
RestartSec=5
# ports 80 (address lookup) and 18881/11001 without running as root
AmbientCapabilities=CAP_NET_BIND_SERVICE
StandardInput=null

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now rozefield
echo "Rozefield Server is running and starts on boot."
echo "Set the control-panel password:  $DIR/start_server.sh --set-admin-password <password>"
echo "Open TCP 80, 18881 and 11001 in the firewall (VPS: in the provider's firewall too)."
