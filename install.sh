#!/usr/bin/env bash
# Install the pystory service
set -eo pipefail

# figure out where this file is located even if it is being run from another location
# or as a symlink
SOURCE="${BASH_SOURCE[0]}"
while [ -h "$SOURCE" ]; do # resolve $SOURCE until the file is no longer a symlink
  DIR="$( cd -P "$( dirname "$SOURCE" )" >/dev/null && pwd )"
  SOURCE="$(readlink "$SOURCE")"
  [[ $SOURCE != /* ]] && SOURCE="$DIR/$SOURCE" # if $SOURCE was a relative symlink, we need to resolve it relative to the path where the symlink file was located
done
THIS_DIR="$( cd -P "$( dirname "$SOURCE" )" >/dev/null && pwd )"

PYSTORY_USE_SUDO=1
PYSTORY_SERVICE_NAME="pystory.service"

if [ $PYSTORY_USE_SUDO -eq 1 ]; then
  sudo -v
fi

if [ $PYSTORY_USE_SUDO -eq 1 ]; then
  PYSTORY_SERVICE_PATH="/etc/systemd/system"
  sudo cp "${THIS_DIR}/sys/${PYSTORY_SERVICE_NAME}" "${PYSTORY_SERVICE_PATH}"

  sudo systemctl daemon-reload
  sudo systemctl enable "${PYSTORY_SERVICE_NAME}"
  sudo systemctl start "${PYSTORY_SERVICE_NAME}"
else
  PYSTORY_SERVICE_PATH="${HOME}/.config/systemd/user"
  mkdir -p "${PYSTORY_SERVICE_PATH}"
  cp "${THIS_DIR}/sys/${PYSTORY_SERVICE_NAME}""${PYSTORY_SERVICE_PATH}"

  # If we are not root, then we need to enable linger and reload the user daemon
  loginctl enable-linger "${USER}"
  systemctl --user daemon-reload
  systemctl --user enable "${PYSTORY_SERVICE_NAME}"
  systemctl --user start "${PYSTORY_SERVICE_NAME}"
fi
