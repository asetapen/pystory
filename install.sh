#!/usr/bin/env bash
set -euo pipefail

echo "Installing system dependencies..."
sudo apt-get update
sudo apt-get install -y cmake build-essential python3-dev

if ! command -v uv &>/dev/null; then
    echo "Installing uv..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
fi

echo "Installing pystory..."
uv sync

echo "Done. Run 'uv run pystory-enroll' to enroll your face, then 'uv run pystory' to start."
