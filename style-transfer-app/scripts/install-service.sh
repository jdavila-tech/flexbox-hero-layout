#!/usr/bin/env bash
# Installs StyleShift as a systemd service: runs in the background,
# survives closing SSH, and starts automatically on boot.
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_USER="${SUDO_USER:-$USER}"
NODE_BIN="$(command -v node || true)"

if [ -z "$NODE_BIN" ]; then
  echo "Node.js not found. Install Node 20+ first." >&2
  exit 1
fi
NODE_MAJOR="$("$NODE_BIN" -p 'process.versions.node.split(".")[0]')"
if [ "$NODE_MAJOR" -lt 20 ]; then
  echo "Node $NODE_MAJOR found, but StyleShift needs Node 20 or newer." >&2
  exit 1
fi

cd "$APP_DIR"
[ -d node_modules ] || sudo -u "$RUN_USER" npm install --omit=dev
[ -f .env ] || sudo -u "$RUN_USER" cp .env.example .env
# Turn HTTPS on by default (needed for the live camera on phones)
grep -q '^HTTPS=' .env || echo 'HTTPS=true' >> .env

sudo tee /etc/systemd/system/styleshift.service >/dev/null <<UNIT
[Unit]
Description=StyleShift web app
After=network-online.target
Wants=network-online.target

[Service]
User=$RUN_USER
WorkingDirectory=$APP_DIR
ExecStart=$NODE_BIN server.js
Restart=always
RestartSec=3
Environment=NODE_ENV=production

[Install]
WantedBy=multi-user.target
UNIT

sudo systemctl daemon-reload
sudo systemctl enable --now styleshift
sudo systemctl restart styleshift
sleep 3
echo
sudo journalctl -u styleshift -n 15 --no-pager -o cat
echo
echo "Done. Useful commands:"
echo "  sudo systemctl status styleshift     # is it running?"
echo "  sudo journalctl -u styleshift -f     # live logs"
echo "  sudo systemctl restart styleshift    # restart after changes"
