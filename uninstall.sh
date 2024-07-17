#!/usr/bin/env bash
# Uninstall the pystory service
set -eo pipefail

sudo -v

PYSTORY_SERVICE_NAME="pystory.service"

SUDO_PYSTORY_SERVICE_PATH="/etc/systemd/system"
USER_PYSTORY_SERVICE_PATH="${HOME}/.config/systemd/user"

# Stop and disable the service
sudo systemctl stop "${PYSTORY_SERVICE_NAME}" &> /dev/null || true
sudo systemctl disable "${PYSTORY_SERVICE_NAME}" &> /dev/null || true
systemctl --user stop "${PYSTORY_SERVICE_NAME}" &> /dev/null || true
systemctl --user disable "${PYSTORY_SERVICE_NAME}" &> /dev/null || true

# Remove the service file
sudo rm "${SUDO_PYSTORY_SERVICE_PATH}/${PYSTORY_SERVICE_NAME}" &> /dev/null || true
rm "${USER_PYSTORY_SERVICE_PATH}/${PYSTORY_SERVICE_NAME}" &> /dev/null || true

# Reload the daemon
sudo systemctl daemon-reload
systemctl --user daemon-reload
